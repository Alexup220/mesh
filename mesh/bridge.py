"""The thin layer between the QML front end and the window's logic.

QML never touches the scene directly. It reads plain lists and maps from
the Bridge (the commands, the parts in the scene, the selected part's
numbers, the undo history, the status line) and calls back into it with
keys and values. Every change still goes through the same MeshWindow
methods and QActions the rest of the app uses, so snapshot, mutate, sync
and every refusal message behave exactly as they always have.
"""

from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QEventLoop, QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QColorDialog

from mesh import panels, themes, ui_catalog
from mesh.scene import new_primitive
from mesh.shapes import PRIMITIVES, REFERENCES, is_reference

ASSETS = Path(__file__).resolve().parent / "assets"
ICON_DIR = ASSETS / "icons"
THUMBNAIL_DIR = ASSETS / "thumbnails"

# The two colours icons are drawn in, swapped for the theme's text and
# highlight colours when an icon is shown (see IconProvider).
ICON_INK = "#333333"
ICON_ACCENT = "#2f7fd8"

INSERT_MIME = "application/x-mesh-insert"


class IconProvider(QQuickImageProvider):
    """image://icon/<name>/<ink>/<accent>: an icon from mesh/assets/icons,
    redrawn in the theme's colours (given without the "#")."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: dict[tuple, QImage] = {}

    def requestImage(self, request: str, size, requested_size) -> QImage:
        name, _, rest = request.partition("/")
        ink, _, accent = rest.partition("/")
        width = requested_size.width() if requested_size.width() > 0 else 24
        height = requested_size.height() if requested_size.height() > 0 else width
        key = (name, ink, accent, width, height)
        image = self._cache.get(key)
        if image is None:
            image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            path = ICON_DIR / f"{name}.svg"
            if path.exists():
                text = path.read_text()
                if ink:
                    text = text.replace(ICON_INK, f"#{ink}")
                if accent:
                    text = text.replace(ICON_ACCENT, f"#{accent}")
                renderer = QSvgRenderer(text.encode())
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
            self._cache[key] = image
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image


def _shortcut_text(action: QAction) -> str:
    return action.shortcut().toString()


def _plain(text: str) -> str:
    return text.replace("&", "")


class FormSession(QObject):
    """One question asked through the QML form window (FormDialog.qml):
    the same fields panels.run_form takes, and the typed values back."""

    finished = Signal()

    def __init__(self, title: str, fields, note: str | None, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._note = note or ""
        self._specs = list(fields)
        self.result: dict | None = None
        self.done = False

    @Property(str, constant=True)
    def title(self) -> str:
        return self._title

    @Property(str, constant=True)
    def note(self) -> str:
        return self._note

    @Property("QVariantList", constant=True)
    def fields(self) -> list:
        out = []
        for key, label, default, options in self._specs:
            options = options or {}
            row = {"key": key, "label": label, "value": default, "choices": []}
            if isinstance(default, bool):
                row["kind"] = "check"
            elif isinstance(default, int):
                row.update(kind="whole", min=int(options.get("min", 0)), max=int(options.get("max", 1000)))
            elif isinstance(default, float):
                row.update(kind="number", min=float(options.get("min", 0.0)),
                           max=float(options.get("max", 10000.0)),
                           decimals=int(options.get("decimals", 2)), step=float(options.get("step", 1.0)))
            elif "choices" in options:
                row["kind"] = "choice"
                row["choices"] = [{"value": v, "label": t} for v, t in options["choices"]]
            else:
                row["kind"] = "text"
            out.append(row)
        return out

    def values_from(self, typed: dict) -> dict:
        """The answer as panels.run_form gives it: each field's own type,
        numbers held inside their range, unknown choices at the default."""
        out = {}
        for key, _label, default, options in self._specs:
            options = options or {}
            value = typed.get(key, default)
            if isinstance(default, bool):
                out[key] = bool(value)
            elif isinstance(default, (int, float)):
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    number = float(default)
                if isinstance(default, int):
                    low, high = int(options.get("min", 0)), int(options.get("max", 1000))
                    out[key] = int(min(max(round(number), low), high))
                else:
                    low, high = float(options.get("min", 0.0)), float(options.get("max", 10000.0))
                    out[key] = round(min(max(number, low), high), int(options.get("decimals", 2)))
            elif "choices" in options:
                allowed = [v for v, _t in options["choices"]]
                out[key] = value if value in allowed else default
            else:
                out[key] = str(value)
        return out

    @Slot("QVariantMap")
    def accept(self, typed) -> None:
        if self.done:
            return
        self.result = self.values_from(dict(typed))
        self.done = True
        self.finished.emit()

    @Slot()
    def reject(self) -> None:
        if self.done:
            return
        self.result = None
        self.done = True
        self.finished.emit()


class Bridge(QObject):
    """What QML sees of the window. See the module docstring."""

    commandsChanged = Signal()
    menusChanged = Signal()
    sceneChanged = Signal()
    propertiesChanged = Signal()
    historyChanged = Signal()
    statusChanged = Signal()
    modeChanged = Signal()
    themeChanged = Signal()
    expertChanged = Signal()

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.actions: dict[str, QAction] = {}
        # The QActions whose changes already refresh the commands.
        self._watched: set[int] = set()
        self._menus: list = []
        self._ribbon: list = []
        self._expert = bool(window.settings.expert_mode)
        self._commands: dict = {}
        self._outliner: list = []
        self._properties: list = []
        self._selected_name = ""
        self._history: list = []
        self._status = ""
        self._warning = False
        self._theme_name = themes.DEFAULT_THEME
        self._tokens = dict(themes.BUILTIN[themes.DEFAULT_THEME])
        self._preview: dict | None = None
        # Coalesces the burst of QAction.changed signals one Expert mode
        # switch sends into one refresh of the menus and commands.
        self._commands_timer = QTimer(self)
        self._commands_timer.setSingleShot(True)
        self._commands_timer.setInterval(0)
        self._commands_timer.timeout.connect(self.refresh_commands)
        window.statusBar().messageChanged.connect(self._on_message)

    # --- commands and menus ---------------------------------------------------

    def collect_actions(self) -> None:
        """Name every menu item by its key and remember its menus' shape.
        Call again whenever menu items are added."""
        self.actions = {}
        self._menu_tree = []
        for top in self.window.menuBar().actions():
            menu = top.menu()
            if menu is None:
                continue
            path = [_plain(top.text())]
            self._menu_tree.append((top, path, self._walk(menu, path)))
        for action in list(self.actions.values()) + [t for t, _p, _e in self._menu_tree]:
            if id(action) not in self._watched:
                action.changed.connect(self._commands_timer.start)
                self._watched.add(id(action))
        self.refresh_commands()

    def _walk(self, menu, path) -> list:
        entries = []
        for action in menu.actions():
            if action.isSeparator():
                entries.append(("separator",))
            elif action.menu() is not None:
                sub_path = path + [_plain(action.text())]
                entries.append(("menu", action, self._walk(action.menu(), sub_path)))
            else:
                key = ui_catalog.command_key(path, action.text())
                self.actions[key] = action
                entries.append(("action", key))
        return entries

    def _entries_model(self, entries) -> list:
        out = []
        for entry in entries:
            if entry[0] == "separator":
                if out and out[-1]["type"] != "separator":
                    out.append({"type": "separator"})
            elif entry[0] == "menu":
                sub = self._entries_model(entry[2])
                if entry[1].isVisible() and sub:
                    out.append({"type": "menu", "title": _plain(entry[1].text()), "entries": sub})
            elif self.actions[entry[1]].isVisible():
                out.append({"type": "action", "key": entry[1]})
        while out and out[-1]["type"] == "separator":
            out.pop()
        return out

    @Slot()
    def refresh_commands(self) -> None:
        commands = {}
        for key, action in self.actions.items():
            commands[key] = {
                "key": key,
                "label": _plain(action.text()).replace("...", "…"),
                "tip": self._tip(action),
                "shortcut": _shortcut_text(action),
                "enabled": action.isEnabled() and action.isVisible(),
                "visible": action.isVisible(),
                "checkable": action.isCheckable(),
                "checked": action.isChecked(),
                "icon": ui_catalog.icon_for(key) or "",
            }
        menus = [
            {"title": path[0], "entries": self._entries_model(entries)}
            for top, path, entries in self._menu_tree
            if top.isVisible()
        ]
        # Only what really changed is sent on: every panel rebuilt from
        # these is redrawn when they are.
        if commands != self._commands:
            self._commands = commands
            self.commandsChanged.emit()
        if menus != self._menus:
            self._menus = menus
            self._ribbon = self._build_ribbon()
            self.menusChanged.emit()
        expert = bool(self.window.settings.expert_mode)
        if expert != self._expert:
            self._expert = expert
            self.expertChanged.emit()

    @staticmethod
    def _tip(action: QAction) -> str:
        """The command's own explanation, if it has one (Qt otherwise makes
        a tooltip from the menu text, which says nothing new)."""
        tip = action.toolTip()
        if tip.replace("...", "").strip() == _plain(action.text()).replace("...", "").strip():
            tip = ""
        return tip or action.statusTip()

    @Property("QVariantMap", notify=commandsChanged)
    def commands(self) -> dict:
        return self._commands

    @Property("QVariantList", notify=menusChanged)
    def menus(self) -> list:
        return self._menus

    @Property("QVariantList", notify=menusChanged)
    def ribbon(self) -> list:
        return self._ribbon

    def _build_ribbon(self) -> list:
        """The ribbon's tabs, holding only the commands that are showing."""
        tabs = []
        for title, _expert_only, groups in ui_catalog.RIBBON:
            shown_groups = []
            for group_title, items in groups:
                shown = []
                for item in items:
                    if isinstance(item, tuple):
                        entries = self._prefixed(item[3])
                        if entries:
                            shown.append({"type": "menu", "label": item[1], "icon": item[2],
                                          "entries": entries})
                    elif item in self._commands and self._commands[item]["visible"]:
                        shown.append({"type": "action", "key": item})
                if shown:
                    shown_groups.append({"title": group_title, "items": shown})
            if shown_groups:
                tabs.append({"title": title, "groups": shown_groups})
        return tabs

    def _prefixed(self, prefix: str) -> list:
        """A drop-down's entries: the menu items whose keys start with
        `prefix`, kept in their menus' shape (hardware sizes stay grouped)."""
        def keep(entries):
            out = []
            for entry in entries:
                if entry["type"] == "action" and entry["key"].startswith(prefix):
                    out.append(entry)
                elif entry["type"] == "menu":
                    sub = keep(entry["entries"])
                    if sub:
                        out.append({**entry, "entries": sub})
            return out

        found = []
        for menu in self._menus:
            found += keep(menu["entries"])
        return found

    @Property("QVariantList", notify=commandsChanged)
    def palette(self) -> list:
        return [k for k in ui_catalog.PALETTE if k in self._commands and self._commands[k]["visible"]]

    @Slot(str)
    def trigger(self, key: str) -> None:
        action = self.actions.get(key)
        if action is None or not (action.isEnabled() and action.isVisible()):
            return
        action.trigger()

    @Property(bool, notify=expertChanged)
    def expertMode(self) -> bool:
        return self._expert

    # --- the Insert panel ----------------------------------------------------

    @Property("QVariantList", constant=True)
    def insertItems(self) -> list:
        return [
            {**item, "thumbnailUrl": (THUMBNAIL_DIR / f"{item['thumbnail']}.svg").as_uri()}
            for item in ui_catalog.insert_items()
        ]

    @Property(str, constant=True)
    def insertMime(self) -> str:
        return INSERT_MIME

    def new_insert_shape(self, key: str):
        """The new shape an Insert thumbnail adds, or None for the ones that
        run a command instead (they ask for numbers first)."""
        kind, _, name = key.partition(":")
        if kind == "shape" and name in PRIMITIVES:
            return new_primitive(name)
        if kind == "hardware":
            for item_key, _label, primitive, params in ui_catalog.hardware_inserts():
                if item_key == key:
                    from mesh import hardware

                    shape = new_primitive(primitive, name=hardware.preset_name(primitive, params))
                    shape.params.update(params)
                    shape.is_hole = True
                    shape.fit = hardware.DEFAULT_FIT[primitive]
                    return shape
        return None

    @Slot(str)
    def insert(self, key: str) -> None:
        self.insert_at(key, None)

    def insert_at(self, key: str, point) -> None:
        """Add the thumbnail's shape (one undo step), centred on the
        workplane `point` (x, y) if given."""
        kind, _, name = key.partition(":")
        if kind == "command":
            self.trigger(name)
            return
        shape = self.new_insert_shape(key)
        if shape is None:
            return
        if point is not None and not (self.window.tool == "place" and self.window._place_target):
            transform = np.asarray(shape.transform, dtype=np.float64).copy()
            transform[0, 3], transform[1, 3] = float(point[0]), float(point[1])
            shape.transform = transform
        self.window.add_shape(shape)

    # --- the scene outliner ------------------------------------------------------

    def refresh_scene(self) -> None:
        scene = self.window.document.scene
        selected = set(scene.selection)
        rows = []
        for shape in scene.shapes:
            primitive = shape.params.get("primitive") if shape.kind == "primitive" else None
            if primitive in PRIMITIVES:
                kind = PRIMITIVES[primitive]["label"]
            elif primitive in REFERENCES:
                kind = REFERENCES[primitive]["label"]
            elif shape.kind == "group":
                kind = "Group"
            else:
                kind = "Model file"
            rows.append({
                "id": shape.id,
                "name": shape.name,
                "kind": kind,
                "hole": bool(shape.is_hole),
                "guide": is_reference(shape),
                "color": shape.color,
                "selected": shape.id in selected,
                "component": getattr(shape, "component", "") or "",
            })
        self._outliner = rows
        self.sceneChanged.emit()

    @Property("QVariantList", notify=sceneChanged)
    def outliner(self) -> list:
        return self._outliner

    @Slot(str, bool)
    def select(self, shape_id: str, additive: bool) -> None:
        self.window._on_picked(shape_id, additive)

    # --- the properties panel ------------------------------------------------------

    def refresh_properties(self) -> None:
        """The selected part's numbers, read from the window's own
        inspector (kept hidden), so the fields shown, their ranges and
        their values are exactly the ones the inspector would show."""
        inspector = self.window.inspector
        shape = inspector._shape
        rows = []
        if shape is not None:
            layout = inspector._layout
            shown = lambda field: layout.isRowVisible(inspector._rows[field])  # noqa: E731
            for field in panels.POSITION_FIELDS:
                rows.append(self._number_row(field, "Position"))
            for field in panels.SIZE_FIELDS:
                if shown(field):
                    rows.append(self._number_row(field, "Size"))
            for field in panels.CHOICE_FIELDS:
                if shown(field):
                    combo = inspector.choice_boxes[field]
                    rows.append({
                        "field": field, "section": "Size", "kind": "choice",
                        "label": panels.FIELD_LABELS[field], "value": combo.currentData(),
                        "choices": [{"value": combo.itemData(i), "label": combo.itemText(i)}
                                    for i in range(combo.count())],
                    })
            for field in panels.TEXT_FIELDS:
                if shown(field):
                    rows.append({"field": field, "section": "Size", "kind": "text",
                                 "label": panels.FIELD_LABELS[field],
                                 "value": inspector.text_boxes[field].text()})
            for field in panels.ROTATION_FIELDS:
                rows.append(self._number_row(field, "Turn"))
            rows.append({"field": "color", "section": "Look", "kind": "color",
                         "label": panels.FIELD_LABELS["color"], "value": inspector.field_value("color")})
            if layout.isRowVisible(inspector._hole_row):
                rows.append({"field": "is_hole", "section": "Look", "kind": "check",
                             "label": inspector.hole_box.text(), "value": inspector.hole_box.isChecked()})
            if layout.isRowVisible(inspector._fit_row):
                box = inspector.fit_box
                rows.append({
                    "field": "fit", "section": "Look", "kind": "choice", "label": panels.FIELD_LABELS["fit"],
                    "value": box.currentData(),
                    "choices": [{"value": box.itemData(i), "label": box.itemText(i)} for i in range(box.count())],
                })
        self._properties = rows
        self._selected_name = shape.name if shape is not None else ""
        self.propertiesChanged.emit()

    def _number_row(self, field: str, section: str) -> dict:
        box = self.window.inspector.fields[field]
        return {
            "field": field, "section": section, "kind": "number",
            "label": panels.FIELD_LABELS[field], "value": box.value(),
            "min": box.minimum(), "max": box.maximum(), "decimals": box.decimals(),
            "step": box.singleStep(), "tip": box.toolTip(),
        }

    @Property("QVariantList", notify=propertiesChanged)
    def properties(self) -> list:
        return self._properties

    @Property(str, notify=propertiesChanged)
    def selectedName(self) -> str:
        return self._selected_name

    @Property(int, notify=sceneChanged)
    def selectedCount(self) -> int:
        return sum(1 for row in self._outliner if row["selected"])

    @Slot(str, "QVariant")
    def setField(self, field: str, value) -> None:
        """Type `value` into the inspector's own control for `field`, so the
        edit takes exactly the inspector's path (its checks, its undo step,
        its coalescing)."""
        inspector = self.window.inspector
        if inspector._shape is None:
            return
        if field in inspector.fields:
            try:
                inspector.fields[field].setValue(float(value))
            except (TypeError, ValueError):
                pass
        elif field in inspector.choice_boxes or field == "fit":
            combo = inspector.fit_box if field == "fit" else inspector.choice_boxes[field]
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        elif field in inspector.text_boxes:
            line = inspector.text_boxes[field]
            line.setText(str(value))
            inspector._emit_text(field, line)
        elif field == "is_hole":
            inspector.hole_box.setChecked(bool(value))
        elif field == "color":
            color = themes.clean_color(value)
            if color is not None and color != inspector.field_value("color"):
                inspector._set_color_swatch(color)
                inspector._emit("color", color)
        # A refused edit puts the inspector back; show what it shows now.
        self.refresh_properties()

    @Slot()
    def pickColor(self) -> None:
        self.window.inspector._pick_color()
        self.refresh_properties()

    # --- undo history --------------------------------------------------------

    def refresh_history(self) -> None:
        document = self.window.document
        done = [self._step_label(label) for label in document.undo_labels]
        undone = [self._step_label(label) for label in reversed(document.redo_labels)]
        rows = [{"label": "Start", "state": "done" if done else "current"}]
        rows += [{"label": label, "state": "done"} for label in done]
        if done:
            rows[-1]["state"] = "current"
        rows += [{"label": label, "state": "undone"} for label in undone]
        self._history = rows
        self.historyChanged.emit()

    @staticmethod
    def _step_label(label: str) -> str:
        return (label or "change").capitalize()

    @Property("QVariantList", notify=historyChanged)
    def history(self) -> list:
        return self._history

    @Slot(int)
    def undoTo(self, index: int) -> None:
        """Undo or redo until the history shows step `index` (0 is Start)
        as the current one."""
        document = self.window.document
        current = len(document.undo_labels)
        steps = index - current
        moved = False
        while steps < 0 and document.undo():
            steps += 1
            moved = True
        while steps > 0 and document.redo():
            steps -= 1
            moved = True
        if moved:
            self.window._clear_tool()
            self.window.sync()

    # --- the status line and mode --------------------------------------------------

    def _on_message(self, message: str) -> None:
        self._status = message
        self._warning = bool(self.window.statusBar().styleSheet())
        self.statusChanged.emit()

    def set_warning(self, warning: bool) -> None:
        if warning != self._warning:
            self._warning = warning
            self.statusChanged.emit()

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=statusChanged)
    def statusWarning(self) -> bool:
        return self._warning

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        tool = self.window.tool
        if tool is None:
            return "Select"
        return tool.replace("_", " ").capitalize()

    @Property(bool, notify=modeChanged)
    def toolActive(self) -> bool:
        return self.window.tool is not None

    def refresh_mode(self) -> None:
        self.modeChanged.emit()

    # --- themes ----------------------------------------------------------------

    @Property("QVariantList", notify=themeChanged)
    def themeNames(self) -> list:
        return list(themes.all_themes(self.window.themes_dir))

    @Property(str, notify=themeChanged)
    def themeName(self) -> str:
        return self._theme_name

    @Property("QVariantMap", notify=themeChanged)
    def tokens(self) -> dict:
        return dict(self._preview or self._tokens)

    @Property("QVariantList", constant=True)
    def tokenNames(self) -> list:
        return [{"token": t, "label": themes.TOKEN_LABELS[t]} for t in themes.TOKENS]

    @Slot(str, result="QVariantMap")
    def themeTokens(self, name: str) -> dict:
        return dict(themes.all_themes(self.window.themes_dir).get(name, self._tokens))

    @Slot(str)
    def setTheme(self, name: str) -> None:
        self.window.apply_theme(name)

    def show_theme(self, name: str, tokens: dict) -> None:
        self._theme_name = name
        self._tokens = dict(tokens)
        self._preview = None
        self.themeChanged.emit()

    @Slot("QVariantMap")
    def previewTheme(self, tokens) -> None:
        colors = themes.clean_colors(dict(tokens))
        if colors is None:
            return
        self._preview = colors
        self.window.paint_theme(colors)
        self.themeChanged.emit()

    @Slot()
    def endPreview(self) -> None:
        if self._preview is not None:
            self._preview = None
            self.window.paint_theme(self._tokens)
            self.themeChanged.emit()

    @Slot(str, "QVariantMap", result=str)
    def saveTheme(self, name: str, tokens) -> str:
        """Save a custom theme and switch to it. Returns "" when saved, or
        what is wrong, in plain words."""
        try:
            themes.save_custom(name, dict(tokens), self.window.themes_dir)
        except themes.ThemeError as exc:
            return str(exc)
        self._preview = None
        self.window.refresh_theme_menu()
        self.window.apply_theme(name.strip())
        return ""

    @Slot(str, result=str)
    def chooseColor(self, current: str) -> str:
        """Ask for a colour (the system's colour chooser); the current one
        back if the user cancels."""
        chosen = QColorDialog.getColor(QColor(current), self.window, "Choose a colour")
        return chosen.name(QColor.HexRgb).lower() if chosen.isValid() else current

    # --- everything at once ---------------------------------------------------

    def refresh(self) -> None:
        self.refresh_scene()
        self.refresh_properties()
        self.refresh_history()
        self.refresh_mode()


def run_form_in(view_opener, title: str, fields, note: str | None = None) -> dict | None:
    """Ask `fields` in a QML form window and wait for the answer, like
    panels.run_form. `view_opener(session)` shows the window and returns it."""
    session = FormSession(title, fields, note)
    loop = QEventLoop()
    session.finished.connect(loop.quit)
    view = view_opener(session)
    view.visibleChanged.connect(lambda visible: None if visible else session.reject())
    if not session.done:
        loop.exec()
    view.close()
    view.deleteLater()
    return session.result
