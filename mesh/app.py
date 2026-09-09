"""The main window: menus, actions, and the wiring between panels and viewport.

Every mutating action snapshots the document first, mutates, then syncs.
Keeping that order uniform is what makes undo trustworthy.
"""

import sys
from pathlib import Path

import numpy as np
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
)
from PySide6.QtCore import Qt

from mesh import ops
from mesh.gizmo import Gizmo
from mesh.io_formats import (
    EXPORT_EXTS,
    IMPORT_EXTS,
    ExportError,
    MeshImportError,
    export_scene,
    import_meshes,
    load_project,
    save_project,
)
from mesh.panels import Inspector, ShapeShelf
from mesh.printcheck import check
from mesh.scene import Document, new_primitive, transform_with_euler
from mesh.viewport import Viewport


class MeshWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("mesh")
        self.resize(1400, 900)
        self.document = Document()

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.viewport.set_scene(self.document.scene)
        self.viewport.picked.connect(self._on_picked)

        self.gizmo = Gizmo(self.viewport, self)
        self.gizmo.changing.connect(lambda: self.document.snapshot("move"))
        self.gizmo.changed.connect(lambda _id: self.sync(keep_gizmo=True))

        self.shelf = ShapeShelf(self)
        self.shelf.primitive_requested.connect(self.add_primitive)
        self._dock("Shapes", self.shelf, Qt.LeftDockWidgetArea)

        self.inspector = Inspector(self)
        self.inspector.edited.connect(self._on_edited)
        self._dock("Details", self.inspector, Qt.RightDockWidgetArea)

        self._build_menus()
        self.statusBar().showMessage("Add a shape to get started.")

    def _dock(self, title, widget, area) -> None:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)

    def _act(self, menu, text, shortcut, handler) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(handler)
        menu.addAction(action)
        self.addAction(action)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._act(file_menu, "&Open Project", "Ctrl+O", self.do_open)
        self._act(file_menu, "&Save Project", "Ctrl+S", self.do_save)
        file_menu.addSeparator()
        self._act(file_menu, "&Add a Model File", None, self.do_import)
        self._act(file_menu, "&Save for Printing", "Ctrl+E", self.do_export)
        file_menu.addSeparator()
        self._act(file_menu, "&Quit", "Ctrl+Q", self.close)

        edit = self.menuBar().addMenu("&Edit")
        self._act(edit, "&Undo", "Ctrl+Z", self.do_undo)
        self._act(edit, "&Redo", "Ctrl+Shift+Z", self.do_redo)
        edit.addSeparator()
        self._act(edit, "&Duplicate", "Ctrl+D", self.do_duplicate)
        self._act(edit, "De&lete", "Delete", self.do_delete)
        self._act(edit, "Select &All", "Ctrl+A", self.do_select_all)

        shape = self.menuBar().addMenu("&Shape")
        self._act(shape, "&Group", "Ctrl+G", self.do_group)
        self._act(shape, "&Ungroup", "Ctrl+Shift+G", self.do_ungroup)
        self._act(shape, "Make &Hole / Solid", "H", self.do_toggle_hole)
        shape.addSeparator()
        for axis in ("x", "y", "z"):
            self._act(shape, f"Mirror along {axis.upper()}", None,
                      lambda _c=False, a=axis: self.do_mirror(a))
        shape.addSeparator()
        for axis in ("x", "y", "z"):
            for mode in ("min", "center", "max"):
                self._act(shape, f"Align {axis.upper()} {mode}", None,
                          lambda _c=False, a=axis, m=mode: self.do_align(a, m))

        view = self.menuBar().addMenu("&View")
        self._act(view, "&Home", "Home", lambda: self.viewport.view_preset("home"))
        self._act(view, "&Front", "1", lambda: self.viewport.view_preset("front"))
        self._act(view, "&Right", "3", lambda: self.viewport.view_preset("right"))
        self._act(view, "&Top", "7", lambda: self.viewport.view_preset("top"))
        self._act(view, "&Zoom to Selection", "F", self.viewport.frame_selection)

    # --- helpers -------------------------------------------------------

    def sync(self, keep_gizmo: bool = False) -> None:
        self.viewport.set_scene(self.document.scene)
        self.viewport.refresh()
        chosen = self.document.scene.selected()
        self.inspector.show_shape(chosen[0] if len(chosen) == 1 else None)
        if not keep_gizmo:
            self.gizmo.attach(chosen[0] if len(chosen) == 1 else None)
        self.gizmo.snap_mm = self.document.scene.snap_mm
        self.update_status()

    def update_status(self) -> None:
        self.statusBar().showMessage(check(self.document.scene).message)

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # --- actions -------------------------------------------------------

    def add_primitive(self, kind: str) -> None:
        self.document.snapshot("add")
        shape = new_primitive(kind)
        self.document.scene.add(shape)
        self.document.scene.select([shape.id])
        self.sync()

    def do_undo(self) -> None:
        if self.document.undo():
            self.sync()

    def do_redo(self) -> None:
        if self.document.redo():
            self.sync()

    def do_select_all(self) -> None:
        self.document.scene.select([s.id for s in self.document.scene.shapes])
        self.sync()

    def do_delete(self) -> None:
        if not self.document.scene.selection:
            return
        self.document.snapshot("delete")
        self.document.scene.remove(list(self.document.scene.selection))
        self.sync()

    def do_duplicate(self) -> None:
        chosen = self.document.scene.selected()
        if not chosen:
            return
        self.document.snapshot("duplicate")
        clones = [ops.duplicate(s) for s in chosen]
        for clone in clones:
            self.document.scene.add(clone)
        self.document.scene.select([c.id for c in clones])
        self.sync()

    def do_toggle_hole(self) -> None:
        chosen = self.document.scene.selected()
        if not chosen:
            return
        self.document.snapshot("hole")
        target = not chosen[0].is_hole
        for shape in chosen:
            shape.is_hole = target
        self.sync()

    def do_group(self) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) < 1:
            return
        try:
            group = ops.make_group(chosen)
        except ops.NothingToCombineError as exc:
            self._warn("Cannot group", str(exc))
            return
        self.document.snapshot("group")
        self.document.scene.remove([s.id for s in chosen])
        self.document.scene.add(group)
        self.document.scene.select([group.id])
        self.sync()

    def do_ungroup(self) -> None:
        chosen = [s for s in self.document.scene.selected() if s.kind == "group"]
        if not chosen:
            return
        self.document.snapshot("ungroup")
        restored = []
        for group in chosen:
            children = ops.ungroup(group)
            self.document.scene.remove([group.id])
            for child in children:
                self.document.scene.add(child)
            restored.extend(children)
        self.document.scene.select([s.id for s in restored])
        self.sync()

    def do_mirror(self, axis: str) -> None:
        chosen = self.document.scene.selected()
        if not chosen:
            return
        self.document.snapshot("mirror")
        for shape in chosen:
            ops.mirror(shape, axis)
        self.sync()

    def do_align(self, axis: str, mode: str) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) < 2:
            return
        self.document.snapshot("align")
        ops.align(chosen, axis, mode)
        self.sync()

    # --- signals -------------------------------------------------------

    def _on_picked(self, shape_id: str, additive: bool) -> None:
        scene = self.document.scene
        if not shape_id:
            scene.select([] if not additive else scene.selection)
        elif additive:
            selection = list(scene.selection)
            selection.remove(shape_id) if shape_id in selection else selection.append(shape_id)
            scene.select(selection)
        else:
            scene.select([shape_id])
        self.sync()

    def _on_edited(self, shape_id: str, field: str, value) -> None:
        try:
            shape = self.document.scene.get(shape_id)
        except KeyError:
            return

        self.document.snapshot("edit")
        if field == "is_hole":
            shape.is_hole = bool(value)
        elif field in ("x", "y", "z"):
            axis = "xyz".index(field)
            shape.transform = np.asarray(shape.transform, dtype=np.float64).copy()
            shape.transform[axis, 3] = float(value)
        elif field in ("rx", "ry", "rz"):
            # Rotation is authoritative in the transform, not in params:
            # shape_geometry() never reads rotation from params, so writing
            # a typed angle there would silently do nothing. Read the
            # shape's current angles, replace the one that changed, and
            # rebuild the transform around it — position and scale are
            # preserved by transform_with_euler.
            from mesh.scene import euler_from_transform

            transform = np.asarray(shape.transform, dtype=np.float64)
            rx, ry, rz = euler_from_transform(transform)
            angles = {"rx": rx, "ry": ry, "rz": rz}
            angles[field] = float(value)
            shape.transform = transform_with_euler(
                transform, angles["rx"], angles["ry"], angles["rz"]
            )
        else:
            shape.params[field] = float(value)
        self.sync()

    # --- files ---------------------------------------------------------

    def export_to(self, path) -> None:
        export_scene(self.document.scene, path)

    def save_to(self, path) -> None:
        save_project(self.document.scene, path)

    def open_from(self, path) -> None:
        self.document = Document(load_project(path))
        self.sync()

    def do_export(self) -> None:
        pattern = "Printable models (" + " ".join(f"*{e}" for e in EXPORT_EXTS) + ")"
        path, _ = QFileDialog.getSaveFileName(self, "Save for Printing", "part.stl", pattern)
        if not path:
            return
        try:
            self.export_to(path)
        except ExportError as exc:
            self._warn("Cannot save", str(exc))
            return
        self.statusBar().showMessage(f"Saved {Path(path).name}")

    def do_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "part.mesh", "mesh project (*.mesh)")
        if path:
            self.save_to(path)
            self.statusBar().showMessage(f"Saved {Path(path).name}")

    def do_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "mesh project (*.mesh)")
        if not path:
            return
        try:
            self.open_from(path)
        except ExportError as exc:
            self._warn("Cannot open", str(exc))

    def do_import(self) -> None:
        pattern = "3D models (" + " ".join(f"*{e}" for e in IMPORT_EXTS) + ")"
        path, _ = QFileDialog.getOpenFileName(self, "Add a Model File", "", pattern)
        if not path:
            return
        try:
            shapes = import_meshes(path)
        except MeshImportError as exc:
            self._warn("Cannot open", str(exc))
            return

        self.document.snapshot("import")
        for shape in shapes:
            self.document.scene.add(shape)
        self.document.scene.select([s.id for s in shapes])
        self.sync()


def run(argv: list[str] | None = None) -> int:
    import os

    from mesh.theme import apply_theme

    # VTK's Linux OpenGL backend (vtkXOpenGLRenderWindow) is X11-only: the
    # viewport widget hands it a native window id via winId()/SetWindowInfo,
    # and vtkXOpenGLRenderWindow treats that id as a real X11 Window. Under
    # Qt's native "wayland" platform plugin that id is not an X11 Window at
    # all, and VTK's very first XChangeWindowAttributes call on it dies with
    # "X Error: BadWindow (invalid Window parameter)" -- confirmed by
    # reproducing the crash directly. Running through XWayland (the "xcb"
    # platform plugin) gives widgets real X11 window ids, which is what lets
    # VTK create a working GL context and resize the render surface as the
    # widget resizes.
    #
    # A plain setdefault() is not enough: many Wayland desktops (this one
    # included) export QT_QPA_PLATFORM=wayland;xcb, which is already
    # "set" -- Qt takes the first platform in that list that connects
    # successfully, which is wayland, so the xcb fallback never triggers
    # and VTK still crashes. So this overrides that default, while still
    # leaving a single explicit platform choice (e.g. "offscreen" for a
    # headless/scripted run) alone. It must happen before QApplication
    # exists.
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform in ("", "wayland") or ";" in platform:
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    app = QApplication(argv or sys.argv)
    apply_theme(app)
    window = MeshWindow()
    window.show()
    window.viewport.start()
    return app.exec()
