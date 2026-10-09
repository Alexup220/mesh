"""The main window with its Qt Quick (QML) front end.

The 3D view stays the VTK widget it has always been: VTK draws through
X11 directly and has no Qt Quick item for Python, so it cannot live inside
a QML scene. Everything around it is QML: the menu bar and ribbon along the
top, the tool palette and Insert panel on the left, the scene outliner,
properties and history on the right, and the status bar along the bottom.
Each panel is a QQuickWidget in a dockable panel, all sharing one QML
engine, so they share one Theme and one Bridge (mesh/bridge.py).

QmlWindow is MeshWindow with that front end put in front of it. Every menu
item, shortcut, action and dialog of MeshWindow is still there (its own
menu bar, docks and toolbar are only taken out of sight), so all the
window's behaviour, and everything the tests check about it, is unchanged.
"""

import base64
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDockWidget, QSizePolicy, QToolBar, QVBoxLayout, QWidget
from shiboken6 import isValid

from mesh import themes
from mesh.app import MeshWindow
from mesh.bridge import INSERT_MIME, Bridge, IconProvider, run_form_in
from mesh.theme import stylesheet_for

# Draw Qt Quick in software, not OpenGL. VTK makes its own OpenGL context
# current behind Qt's back each time it renders, so on a real screen Qt
# Quick's OpenGL drawing landed in the 3D view (a solid panel colour there)
# and the panels themselves stayed empty. The panels are flat 2D, which
# the software renderer draws fine. Must run before any Qt Quick window.
QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)

QML_DIR = Path(__file__).resolve().parent / "qml"
MODULE_DIR = QML_DIR / "Mesh"

# The dockable panels: (object name, title, QML file, area, height).
PANELS = (
    ("tools", "Tools", "ToolPalette.qml", Qt.LeftDockWidgetArea),
    ("insert", "Insert", "InsertPanel.qml", Qt.LeftDockWidgetArea),
    ("scene", "Scene", "Outliner.qml", Qt.RightDockWidgetArea),
    ("history", "History", "HistoryPanel.qml", Qt.RightDockWidgetArea),
    ("properties", "Properties", "Properties.qml", Qt.RightDockWidgetArea),
)


class _DropFilter(QObject):
    """Lets an Insert thumbnail be dragged onto the 3D view: the shape
    lands where it is dropped on the workplane."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (QEvent.DragEnter, QEvent.DragMove) and event.mimeData().hasFormat(INSERT_MIME):
            event.acceptProposedAction()
            return True
        if kind == QEvent.Drop and event.mimeData().hasFormat(INSERT_MIME):
            key = bytes(event.mimeData().data(INSERT_MIME)).decode()
            position = event.position()
            point = self.window.viewport.workplane_point(position.x(), position.y())
            event.acceptProposedAction()
            self.window.bridge.insert_at(key, point)
            return True
        return False


class QmlWindow(MeshWindow):
    def __init__(self, settings=None, themes_dir=None, welcome: bool | None = None) -> None:
        super().__init__(settings)
        # Where custom themes are saved; tests pass a temporary folder.
        self.themes_dir = Path(themes_dir) if themes_dir is not None else themes.themes_dir()
        self.qml_warnings: list[str] = []
        self.views: list = []

        self.engine = QQmlEngine(self)
        self.engine.addImportPath(str(QML_DIR))
        self.engine.addImageProvider("icon", IconProvider())
        self.engine.warnings.connect(self._on_qml_warnings)
        self.bridge = Bridge(self)
        self.engine.rootContext().setContextProperty("bridge", self.bridge)

        self._hide_classic_front()
        self._add_view_menu_items()
        self.bridge.collect_actions()

        self.ribbon = self._quick("Ribbon.qml")
        self.ribbon.setFixedHeight(162)
        top = QToolBar("Ribbon", self)
        top.setObjectName("ribbon")
        top.setMovable(False)
        top.setFloatable(False)
        top.addWidget(self.ribbon)
        self.addToolBar(Qt.TopToolBarArea, top)
        self.ribbon_bar = top

        self.status_view = self._quick("StatusBar.qml")
        self.status_view.setFixedHeight(30)
        bottom = QToolBar("Status", self)
        bottom.setObjectName("status")
        bottom.setMovable(False)
        bottom.setFloatable(False)
        bottom.addWidget(self.status_view)
        self.addToolBar(Qt.BottomToolBarArea, bottom)
        self.status_bar_view = bottom

        # The 3D view, with the mode strip (current tool, Expert mode) above it.
        viewport = self.takeCentralWidget()
        centre = QWidget(self)
        column = QVBoxLayout(centre)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.mode_view = self._quick("ModeBar.qml")
        self.mode_view.setFixedHeight(30)
        column.addWidget(self.mode_view)
        column.addWidget(viewport, 1)
        self.setCentralWidget(centre)
        self._drop_filter = _DropFilter(self)
        self.viewport._widget.setAcceptDrops(True)
        self.viewport._widget.installEventFilter(self._drop_filter)

        self.docks: dict[str, QDockWidget] = {}
        for name, title, source, area in PANELS:
            dock = QDockWidget(title, self)
            dock.setObjectName(name)
            dock.setWidget(self._quick(source))
            self.addDockWidget(area, dock)
            self.docks[name] = dock
        self.tabifyDockWidget(self.docks["scene"], self.docks["history"])
        self.docks["scene"].raise_()
        self.resizeDocks([self.docks["tools"], self.docks["insert"]], [300, 420], Qt.Vertical)
        self.resizeDocks([self.docks["scene"], self.docks["properties"]], [260, 520], Qt.Vertical)
        self.resizeDocks([self.docks["tools"], self.docks["scene"]], [230, 290], Qt.Horizontal)
        self._add_panel_menu()

        name = self.settings.theme if self.settings.theme in self._themes() else themes.DEFAULT_THEME
        self.apply_theme(name, save=False)
        self._restore_layout()
        self.bridge.refresh()
        self.bridge.set_warning(bool(self.statusBar().styleSheet()))

        # The welcome screen: on the very first start (nothing saved yet),
        # unless the caller says otherwise.
        if welcome is None:
            welcome = self.settings.path is not None and not self.settings.layout
        if welcome:
            QTimer.singleShot(0, self.show_welcome)

    # --- building --------------------------------------------------------

    def _hide_classic_front(self) -> None:
        """Take the widget menu bar, docks and toolbar out of sight. They
        stay alive: their actions, shortcuts and the hidden inspector are
        what the QML front end drives."""
        self.menuBar().setVisible(False)
        # Held here: once out of the layout, Python owns them, and letting
        # go of them would delete the inspector with its dock.
        self._classic_docks = self.findChildren(QDockWidget)
        self._classic_bars = self.findChildren(QToolBar)
        for dock in self._classic_docks:
            self.removeDockWidget(dock)
            dock.hide()
        for bar in self._classic_bars:
            self.removeToolBar(bar)
            bar.hide()
        self.statusBar().setVisible(False)

    def _add_view_menu_items(self) -> None:
        view = self.view_menu
        view.addSeparator()
        self.act_search = self._act(view, "Search Commands...", "Ctrl+K", self.show_command_palette)
        self.theme_menu = view.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self.refresh_theme_menu(collect=False)
        self._act(view, "Theme Editor...", None, self.show_theme_editor)
        self._act(view, "Welcome Screen", None, self.show_welcome)

    def _add_panel_menu(self) -> None:
        panels_menu = self.view_menu.addMenu("Panels")
        for dock in self.docks.values():
            action = dock.toggleViewAction()
            panels_menu.addAction(action)
        self.bridge.collect_actions()

    def refresh_theme_menu(self, collect: bool = True) -> None:
        """One checkable item per theme, built-in and saved."""
        for action in self.theme_menu.actions():
            self.theme_menu.removeAction(action)
            self._theme_group.removeAction(action)
            self.removeAction(action)
            action.deleteLater()
        for name in self._themes():
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(name == getattr(self, "_theme_name", None))
            action.triggered.connect(lambda _c=False, n=name: self.apply_theme(n))
            self._theme_group.addAction(action)
            self.theme_menu.addAction(action)
        if collect:
            self.bridge.collect_actions()

    def _quick(self, source: str) -> QQuickWidget:
        widget = QQuickWidget(self.engine, self)
        widget.setResizeMode(QQuickWidget.SizeRootObjectToView)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        widget.setSource(QUrl.fromLocalFile(str(MODULE_DIR / source)))
        for error in widget.errors():
            self.qml_warnings.append(error.toString())
        return widget

    def _on_qml_warnings(self, warnings) -> None:
        for warning in warnings:
            self.qml_warnings.append(warning.toString())
            print(f"QML: {warning.toString()}")

    def open_view(self, source: str, properties: dict, title: str, modal: bool = False,
                  size=(480, 360)) -> QQuickView:
        """A separate QML window (a dialog) over the main window, sharing
        the engine, so it shares the theme and the bridge."""
        view = QQuickView(self.engine, None)
        view.setTitle(title)
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.setInitialProperties(properties)
        view.setSource(QUrl.fromLocalFile(str(MODULE_DIR / source)))
        for error in view.errors():
            self.qml_warnings.append(error.toString())
        view.resize(*size)
        handle = self.windowHandle()
        if handle is not None:
            view.setTransientParent(handle)
            centre = self.geometry().center()
            view.setPosition(centre.x() - size[0] // 2, centre.y() - size[1] // 2)
        if modal:
            view.setModality(Qt.ApplicationModal)
        view.setFlags(Qt.Dialog)
        # Closed windows go with deleteLater, never by dropping them here:
        # this often runs inside a closed window's own key or click handler
        # (Ctrl+K closes the search, then runs Theme Editor...), and
        # deleting a window during its own QML handler makes Qt abort.
        # Their entries stay until Qt has deleted them.
        for old in self.views:
            if isValid(old) and not old.isVisible():
                old.deleteLater()
        self.views = [v for v in self.views if isValid(v)] + [view]
        view.show()
        view.requestActivate()
        return view

    # --- dialogs -----------------------------------------------------------

    def ask_form(self, title: str, fields, note: str | None = None) -> dict | None:
        """Forms (Hollow out, Split, ...) asked of this window are QML
        windows too; see panels.run_form."""
        rows = len(list(fields))
        height = 150 + 44 * rows + (70 if note else 0)
        return run_form_in(
            lambda session: self.open_view("FormDialog.qml", {"session": session}, title,
                                           modal=True, size=(460, height)),
            title, fields, note,
        )

    def show_command_palette(self) -> None:
        # A plain dialog that stays open until a command runs or Escape is
        # pressed. It used to close as soon as it lost focus, but with focus
        # following the mouse (Hyprland's default) that happened the moment
        # the mouse moved, so it never seemed to open.
        self.open_view("CommandPalette.qml", {}, "Search commands", size=(560, 420))

    def show_theme_editor(self) -> None:
        self.open_view("ThemeEditor.qml", {"startTheme": self.bridge.themeName}, "Theme editor",
                       modal=True, size=(520, 560))

    def show_welcome(self) -> None:
        self.open_view("Welcome.qml", {}, "Welcome to mesh", modal=True, size=(620, 460))

    # --- themes --------------------------------------------------------------

    def _themes(self) -> dict:
        return themes.all_themes(self.themes_dir)

    def apply_theme(self, name: str, save: bool = True) -> None:
        """Switch the whole window to the theme `name`, live, and remember
        it for next time."""
        available = self._themes()
        if name not in available:
            return
        self._theme_name = name
        tokens = available[name]
        self.paint_theme(tokens)
        self.bridge.show_theme(name, tokens)
        for action in self.theme_menu.actions():
            action.setChecked(action.text() == name)
        if save and self.settings.theme != name:
            self.settings.theme = name
            self.settings.save()

    def paint_theme(self, tokens: dict) -> None:
        """Put `tokens` on screen: the QML Theme, the remaining widgets
        (dock titles, message boxes, the sketch window), and the 3D view."""
        theme = self.engine.singletonInstance("Mesh", "Theme")
        if theme is not None:
            theme.setProperty("tokens", dict(tokens))
        # On this window only (its dialogs and message boxes inherit it):
        # an application-wide style sheet would restyle every widget in
        # the program each time the theme changes.
        self.setStyleSheet(stylesheet_for(tokens))
        self.viewport.set_colors(tokens["viewport"], tokens["grid"], tokens["selection"])

    # --- layout ----------------------------------------------------------------

    def _restore_layout(self) -> None:
        saved = self.settings.layout
        if not saved or "|" not in saved:
            return
        geometry, _, state = saved.partition("|")
        try:
            self.restoreGeometry(base64.b64decode(geometry))
            self.restoreState(base64.b64decode(state))
        except ValueError:
            return

    def layout_text(self) -> str:
        geometry = base64.b64encode(bytes(self.saveGeometry())).decode()
        state = base64.b64encode(bytes(self.saveState())).decode()
        return f"{geometry}|{state}"

    def closeEvent(self, event) -> None:
        self.settings.layout = self.layout_text()
        self.settings.save()
        for view in self.views:
            if isValid(view):
                view.close()
        super().closeEvent(event)

    # --- keeping the front end up to date --------------------------------------

    def sync(self, keep_gizmo: bool = False) -> None:
        super().sync(keep_gizmo)
        if hasattr(self, "bridge"):
            self.bridge.refresh()

    def update_status(self) -> None:
        super().update_status()
        self.bridge.set_warning(bool(self.statusBar().styleSheet()))

    def start_tool(self, tool: str) -> None:
        super().start_tool(tool)
        self.bridge.refresh_mode()

    def _clear_tool(self) -> None:
        super()._clear_tool()
        if hasattr(self, "bridge"):
            self.bridge.refresh_mode()


def make_qml_window() -> QmlWindow:
    """The app's window with the QML front end and this computer's saved
    preferences."""
    from mesh.settings import Settings, default_path

    return QmlWindow(Settings.load(default_path()))
