"""The main window: menus, actions, and the wiring between panels and viewport.

Every mutating action snapshots the document first, mutates, then syncs.
Keeping that order uniform is what makes undo trustworthy.
"""

import copy
import sys
from pathlib import Path

import numpy as np
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
)
from PySide6.QtCore import QTimer, Qt

from mesh import builders, create, expert, hardware, ops, panels
from mesh.expert_actions import ExpertActions
from mesh.gizmo import Gizmo
from mesh.io_formats import (
    EXPORT_EXTS,
    IMPORT_EXTS,
    MeshImportError,
    ProjectError,
    export_scene,
    import_meshes,
    load_project,
    save_project,
    suggest_unit_scale,
)
from mesh.panels import Inspector, ShapeShelf
from mesh.printcheck import check
from mesh.scene import MAX_FIT_CLEARANCE, Document, new_primitive, transform_with_euler
from mesh.settings import Settings, default_path
from mesh.shapes import is_reference, shape_geometry
from mesh.text import has_letters
from mesh.viewport import Viewport


class MeshWindow(ExpertActions, QMainWindow):
    EDIT_COALESCE_MS = 400

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("mesh")
        self.resize(1400, 900)
        self.document = Document()
        # Preferences of this computer, such as Expert mode. A window built
        # without them (as in the tests) starts from the defaults and saves
        # nothing; run() passes the user's own.
        self.settings = settings if settings is not None else Settings()

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.viewport.set_scene(self.document.scene)
        self.viewport.picked.connect(self._on_picked)
        self.viewport.surface_picked.connect(self._on_surface_picked)
        # Which click-on-a-part tool is active: None, "lay_flat", "place"
        # or "measure". See start_tool / stop_tool.
        self.tool: str | None = None
        # Where "Place on face" will put the next added shape:
        # (world point, face direction), or None until a face is clicked.
        self._place_target = None
        # The Measure tool's clicked points (0, 1 or 2 world points).
        self._measure_points: list = []

        self.gizmo = Gizmo(self.viewport, self)
        self.gizmo.changing.connect(lambda: self.document.snapshot("move"))
        self.gizmo.changed.connect(lambda _id: self.sync(keep_gizmo=True))

        self.shelf = ShapeShelf(self)
        self.shelf.primitive_requested.connect(self.add_primitive)
        self._dock("Shapes", self.shelf, Qt.LeftDockWidgetArea)

        self.inspector = Inspector(self)
        self.inspector.edited.connect(self._on_edited)
        self._dock("Details", self.inspector, Qt.RightDockWidgetArea)

        # Coalescing for inspector edits: a spinbox fires valueChanged on
        # every keystroke, and naively snapshotting/syncing on each one
        # made one deliberate edit (e.g. typing "125") cost three
        # snapshots, three full-scene viewport rebuilds, and three
        # printcheck evaluations -- and three undo entries, so a single
        # Ctrl+Z only undid the last keystroke. _on_edited now applies the
        # mutation immediately (so the data model, and any test calling it
        # directly, stays correct-by-construction) but takes exactly one
        # snapshot per burst and defers the expensive sync() until typing
        # has paused for EDIT_COALESCE_MS.
        self._edit_active = False
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(self.EDIT_COALESCE_MS)
        self._edit_timer.timeout.connect(self._finish_edit)

        self._build_menus()
        self._build_expert_menus()
        self._build_bottom_bar()
        self.statusBar().showMessage("Add a shape to get started.")
        self._apply_expert_mode()

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
        self.act_undo = self._act(edit, "&Undo", "Ctrl+Z", self.do_undo)
        self.act_redo = self._act(edit, "&Redo", "Ctrl+Shift+Z", self.do_redo)
        self.act_stop_tool = self._act(edit, "Stop Current Tool", "Esc", self.stop_tool)
        edit.addSeparator()
        self.act_duplicate = self._act(edit, "&Duplicate", "Ctrl+D", self.do_duplicate)
        self.act_delete = self._act(edit, "De&lete", "Delete", self.do_delete)
        self._act(edit, "Select &All", "Ctrl+A", self.do_select_all)

        shape = self.menuBar().addMenu("&Shape")
        self.act_group = self._act(shape, "&Group", "Ctrl+G", self.do_group)
        self.act_ungroup = self._act(shape, "&Ungroup", "Ctrl+Shift+G", self.do_ungroup)
        self._act(shape, "Make &Hole / Solid", "H", self.do_toggle_hole)
        self._act(shape, "Fit clearances...", None, self.do_edit_fit_clearances)
        shape.addSeparator()
        self.act_lay_flat = self._act(shape, "&Lay Flat on a Face", "L", self.start_lay_flat)
        self.act_place = self._act(shape, "&Place Next Shape on a Face", "P", self.toggle_place_on_face)
        self.act_place.setCheckable(True)
        shape.addSeparator()
        self._act(shape, "Hollow &Out...", None, self.do_hollow)
        self._act(shape, "S&plit Part...", None, self.do_split)
        shape.addSeparator()
        self._act(shape, "Repeat in a &Row...", None, self.do_repeat_row)
        self._act(shape, "Repeat in a &Circle...", None, self.do_repeat_circle)
        shape.addSeparator()
        self._act(shape, "Box with &Lid...", None, self.do_box_with_lid)
        self._act(shape, "Add &Text...", "T", self.do_add_text)
        shape.addSeparator()
        # Explicit Union/Subtract/Intersect: the secondary route to
        # ops.boolean, for a user who wants the operator directly instead
        # of the Solid/Hole flag that Group teaches as the primary path.
        for op, label in ops.BOOLEAN_LABELS.items():
            self._act(shape, label, None, lambda _c=False, o=op: self.do_boolean(o))
        shape.addSeparator()
        for axis in ("x", "y", "z"):
            self._act(shape, f"Mirror along {axis.upper()}", None,
                      lambda _c=False, a=axis: self.do_mirror(a))
        shape.addSeparator()
        for axis in ("x", "y", "z"):
            for mode in ("min", "center", "max"):
                self._act(shape, f"Align {axis.upper()} {mode}", None,
                          lambda _c=False, a=axis, m=mode: self.do_align(a, m))

        holes = self.menuBar().addMenu("Add hard&ware hole")
        self.hardware_menu = holes
        for submenu_label, items in hardware.menu_presets():
            submenu = holes.addMenu(submenu_label)
            for label, primitive, params in items:
                self._act(submenu, label, None,
                          lambda _c=False, k=primitive, p=params: self.add_hardware(k, dict(p)))

        tools = self.menuBar().addMenu("&Tools")
        self.act_measure = self._act(tools, "&Measure", "M", self.toggle_measure)
        self.act_measure.setCheckable(True)
        tools.addSeparator()
        self.act_expert = self._act(tools, "&Expert Mode", None, self.set_expert_mode)
        self.act_expert.setCheckable(True)
        self.act_expert.setStatusTip(self.EXPERT_TIP)

        view = self.menuBar().addMenu("&View")
        self.view_menu = view
        self.act_view_home = self._act(view, "&Home", "Home", lambda: self.viewport.view_preset("home"))
        self.act_view_front = self._act(view, "&Front", "1", lambda: self.viewport.view_preset("front"))
        self.act_view_right = self._act(view, "&Right", "3", lambda: self.viewport.view_preset("right"))
        self.act_view_top = self._act(view, "&Top", "7", lambda: self.viewport.view_preset("top"))
        self._act(view, "&Zoom to Selection", "F", self.viewport.frame_selection)

    def _build_expert_menus(self) -> None:
        """One menu item per tool in mesh.expert.TOOLS, under the expert
        menus (placed before View). They are shown or hidden only by
        _apply_expert_mode."""
        self.expert_menus = {}
        self.expert_actions = {}
        for key, title in expert.MENUS:
            menu = QMenu(title, self)
            self.menuBar().insertMenu(self.view_menu.menuAction(), menu)
            menu.setToolTipsVisible(True)
            self.expert_menus[key] = menu
            for tool in expert.tools_in(key):
                action = self._act(menu, tool.label, tool.shortcut, getattr(self, tool.handler))
                action.setToolTip(tool.tip)
                action.setStatusTip(tool.tip)
                self.expert_actions[tool.key] = action
        # Shown in the status bar while Expert mode is on.
        self.expert_badge = QLabel("Expert mode", self)
        self.statusBar().addPermanentWidget(self.expert_badge)

    EXPERT_TIP = "Show the extra modeling tools for experienced users. Turn off to hide them again."
    EXPERT_NOT_SAVED = "Expert mode changed, but it could not be saved for next time."

    def set_expert_mode(self, on: bool) -> None:
        """Show or hide every expert tool, and remember the choice.

        A preference, not an edit: no undo step, and the scene is left
        exactly as it is, so nothing made with an expert tool is lost or
        changed when the mode goes off."""
        self.settings.expert_mode = bool(on)
        saved = self.settings.save()
        if not on and self.tool in self.EXPERT_CLICK_TOOLS:
            self.stop_tool()
        if not on:
            self._end_inspecting()
        self._apply_expert_mode()
        if self.settings.path is not None and not saved:
            self.statusBar().showMessage(self.EXPERT_NOT_SAVED)

    def _apply_expert_mode(self) -> None:
        on = self.settings.expert_mode
        self.act_expert.blockSignals(True)
        self.act_expert.setChecked(on)
        self.act_expert.blockSignals(False)
        for action in self.expert_actions.values():
            # Hidden and disabled, so a hidden tool's shortcut does nothing.
            action.setVisible(on)
            action.setEnabled(on)
        for menu in self.expert_menus.values():
            menu.menuAction().setVisible(on and bool(menu.actions()))
        self.expert_badge.setVisible(on)

    def _build_bottom_bar(self) -> None:
        """A visible bottom bar for the actions and camera presets the
        spec calls "mandatory, not decorative": a beginner lost in 3D
        will not go looking in the View menu for Home. Every button here
        reuses the same QAction created in _build_menus, so there is
        exactly one place each action's logic lives -- the toolbar just
        gives it a second, more visible entry point.
        """
        bar = QToolBar("Actions", self)
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)

        for action in (
            self.act_undo, self.act_redo, self.act_group, self.act_ungroup,
            self.act_duplicate, self.act_delete,
        ):
            bar.addAction(action)

        bar.addSeparator()

        for action in (
            self.act_view_home, self.act_view_top,
            self.act_view_front, self.act_view_right,
        ):
            bar.addAction(action)

        self.addToolBar(Qt.BottomToolBarArea, bar)

    # --- helpers -------------------------------------------------------

    def sync(self, keep_gizmo: bool = False) -> None:
        self.viewport.set_scene(self.document.scene)
        self.viewport.refresh()
        chosen = self.document.scene.selected()
        self.inspector.show_shape(chosen[0] if len(chosen) == 1 else None)
        if not keep_gizmo:
            # While a click tool waits, the drag handles stay away, or they
            # would catch the click meant for the part.
            self.gizmo.attach(chosen[0] if len(chosen) == 1 and self.tool is None else None)
        self.gizmo.snap_mm = self.document.scene.snap_mm
        self.update_status()
        if self.tool is not None:
            self.statusBar().setStyleSheet("")
            self.statusBar().showMessage(self._tool_prompt())

    # Warm coral, readable on the dark theme's status bar background
    # (#1b1e22 -- see mesh/theme.py) without being alarm-red.
    STATUS_WARNING_COLOR = "#ff6b6b"

    def update_status(self) -> None:
        report = check(self.document.scene, revision=self.document.revision)
        bar = self.statusBar()
        bar.showMessage(report.message)
        if not report.empty and (not report.fits or not report.watertight):
            bar.setStyleSheet(f"QStatusBar {{ color: {self.STATUS_WARNING_COLOR}; }}")
        else:
            bar.setStyleSheet("")

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # --- actions -------------------------------------------------------

    def add_primitive(self, kind: str) -> None:
        self.add_shape(new_primitive(kind))

    def add_shape(self, shape) -> None:
        """Add one new shape as one undo step and select it. Every "add"
        (shelf, hardware holes, text) comes through here."""
        if self.tool == "place" and self._place_target is not None:
            point, direction = self._place_target
            # The new shape isn't in the scene yet, so placing it first
            # changes nothing if it fails.
            ops.place_on_face(shape, point, direction)
            # One placement, then back to landing on the workplane.
            self._clear_tool()
        self.document.snapshot("add")
        self.document.scene.add(shape)
        self.document.scene.select([shape.id])
        self.sync()

    def add_hardware(self, primitive: str, params: dict) -> None:
        """Add a ready-made hardware Hole (see mesh/hardware.py)."""
        shape = new_primitive(primitive, name=hardware.preset_name(primitive, params))
        shape.params.update(params)
        shape.is_hole = True
        shape.fit = hardware.DEFAULT_FIT[primitive]
        self.add_shape(shape)

    def do_undo(self) -> None:
        if self.document.undo():
            # A clicked face or point belongs to the scene as it was.
            self._clear_tool()
            self.sync()

    def do_redo(self) -> None:
        if self.document.redo():
            self._clear_tool()
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
        # A guide (a sketch) is never printed, so it is never a hole.
        chosen = [s for s in self.document.scene.selected() if not is_reference(s)]
        if not chosen:
            return
        target = not chosen[0].is_hole
        trials = [copy.copy(s) for s in chosen]
        for trial in trials:
            trial.is_hole = target
        if not self._fits_build(trials, "Cannot make a hole"):
            return
        self.document.snapshot("hole")
        for shape in chosen:
            shape.is_hole = target
        self.sync()

    def _fits_build(self, shapes, title: str, clearances: dict | None = None) -> bool:
        """Whether every Hole made from a sketch among `shapes` can be made
        at its fit (with `clearances`, or the scene's). If not, say why."""
        problem = create.fit_refusal(
            shapes, self.document.scene.fit_clearances if clearances is None else clearances
        )
        if problem is not None:
            self._warn(title, problem)
        return problem is None

    GUIDES_ONLY = "Sketches are guides, not parts, so there is nothing to combine. Select parts too."

    def _parts_chosen(self):
        """The selected shapes to combine: guides (sketches) are left out
        and stay where they are. None, and a message, if only guides are."""
        selected = self.document.scene.selected()
        chosen = [s for s in selected if not is_reference(s)]
        if selected and not chosen:
            self.statusBar().showMessage(self.GUIDES_ONLY)
            return None
        return chosen

    def do_group(self) -> None:
        chosen = self._parts_chosen()
        if not chosen:
            return
        try:
            group = ops.make_group(chosen, clearances=self.document.scene.fit_clearances)
        except ops.NothingToCombineError as exc:
            self._warn("Cannot group", str(exc))
            return
        self.document.snapshot("group")
        self.document.scene.remove([s.id for s in chosen])
        self.document.scene.add(group)
        self.document.scene.select([group.id])
        self.sync()

    def do_boolean(self, op: str) -> None:
        """The explicit Join / Cut Out / Keep Overlap menu items: the
        secondary route to ops.boolean for a user who wants the operator
        directly rather than the Solid/Hole flag. Solid/Hole + Group stays
        the primary path."""
        chosen = self._parts_chosen()
        if not chosen:
            return
        try:
            group = ops.make_boolean_group(
                chosen, op, clearances=self.document.scene.fit_clearances
            )
        except ops.NothingToCombineError as exc:
            self._warn("Cannot combine", str(exc))
            return
        self.document.snapshot(op)
        self.document.scene.remove([s.id for s in chosen])
        self.document.scene.add(group)
        self.document.scene.select([group.id])
        self.sync()

    def do_ungroup(self) -> None:
        chosen = [s for s in self.document.scene.selected() if s.kind == "group"]
        if not chosen:
            return
        unpacked = [(group, ops.ungroup(group)) for group in chosen]
        # The fits may have changed since the group was made.
        if not self._fits_build([c for _g, children in unpacked for c in children], "Cannot ungroup"):
            return
        self.document.snapshot("ungroup")
        restored = []
        for group, children in unpacked:
            self.document.scene.remove([group.id])
            for child in children:
                self.document.scene.add(child)
            restored.extend(children)
        self.document.scene.select([s.id for s in restored])
        self.sync()

    def set_fit_clearances(self, values: dict) -> bool:
        """Change how much room Press / Snug / Loose fits add (mm per side).

        One undo step. Returns False (and changes nothing, adds no undo
        step) if a value is not a sensible clearance.
        """
        current = self.document.scene.fit_clearances
        cleaned = {}
        for key in current:
            value = float(values.get(key, current[key]))
            if not 0.0 <= value <= MAX_FIT_CLEARANCE:
                self._warn(
                    "Cannot change fits",
                    f"A fit's clearance must be between 0 and {MAX_FIT_CLEARANCE:g} mm.",
                )
                return False
            cleaned[key] = value
        if cleaned == current:
            return False
        if not self._fits_build(self.document.scene.shapes, "Cannot change fits", cleaned):
            return False
        self.document.snapshot("fit clearances")
        self.document.scene.fit_clearances = cleaned
        self.sync()
        return True

    def do_edit_fit_clearances(self) -> None:
        values = panels.ask_fit_clearances(self, self.document.scene.fit_clearances)
        if values is not None:
            self.set_fit_clearances(values)

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

    def _one_selected(self, what: str):
        chosen = self.document.scene.selected()
        if len(chosen) != 1:
            self.statusBar().showMessage(f"Select one part to {what}.")
            return None
        return chosen[0]

    def _replace_with(self, label: str, old, new_shapes) -> None:
        """One undo step: swap `old` for the shapes a tool built."""
        self.document.snapshot(label)
        self.document.scene.remove([old.id])
        for shape in new_shapes:
            self.document.scene.add(shape)
        self.document.scene.select([s.id for s in new_shapes])
        self.sync()

    def _attempt(self, title: str, build):
        """Run a tool that might refuse. On refusal, say why and return None
        -- before any snapshot, so a failure leaves no undo step behind."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return build()
        except (builders.BuildError, ops.NothingToCombineError) as exc:
            error = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        self._warn(title, error)
        return None

    def hollow_selected(self, wall: float, open_top: bool = False, drain: float = 0.0) -> bool:
        shape = self._one_selected("hollow out")
        if shape is None:
            return False
        scene = self.document.scene
        group = self._attempt(
            "Cannot hollow out",
            lambda: builders.hollow(shape, wall, open_top, drain, scene.fit_clearances),
        )
        if group is None:
            return False
        self._replace_with("hollow out", shape, [group])
        return True

    def do_hollow(self) -> None:
        shape = self._one_selected("hollow out")
        if shape is None:
            return
        values = panels.ask_hollow(self, exact=builders.hollows_exactly(shape))
        if values is not None:
            self.hollow_selected(values["wall"], values.get("open_top", False), values["drain"])

    def split_selected(
        self, axis: str, distance: float, pegs: bool = False, peg_diameter: float = 4.0
    ) -> bool:
        """Cut the selected part `distance` mm in from its bottom (axis "z"),
        left ("x") or front ("y") edge. One undo step on success."""
        shape = self._one_selected("split")
        if shape is None:
            return False
        scene = self.document.scene
        low = shape_geometry(shape, scene.fit_clearances).bounds[0]["xyz".index(axis)]
        halves = self._attempt(
            "Cannot split",
            lambda: builders.split(
                shape, axis, low + float(distance), pegs, peg_diameter, scene.fit_clearances
            ),
        )
        if halves is None:
            return False
        self._replace_with("split", shape, list(halves))
        return True

    def do_split(self) -> None:
        shape = self._one_selected("split")
        if shape is None:
            return
        tm = shape_geometry(shape, self.document.scene.fit_clearances)
        values = panels.ask_split(self, tuple(float(v) for v in tm.bounds[1] - tm.bounds[0]))
        if values is not None:
            self.split_selected(
                values["axis"], values["distance"], values["pegs"], values["peg_diameter"]
            )

    def _add_copies(self, label: str, shape, copies, new_transform=None) -> None:
        """One undo step for a whole pattern."""
        self.document.snapshot(label)
        if new_transform is not None:
            shape.transform = new_transform
        for clone in copies:
            self.document.scene.add(clone)
        self.document.scene.select([shape.id] + [c.id for c in copies])
        self.sync()

    def repeat_row_selected(self, count: int, spacing: float, axis: str = "x") -> bool:
        shape = self._one_selected("repeat")
        if shape is None:
            return False
        copies = self._attempt(
            "Cannot repeat", lambda: builders.repeat_row(shape, count, spacing, axis)
        )
        if copies is None:
            return False
        self._add_copies("repeat in a row", shape, copies)
        return True

    def repeat_circle_selected(self, count: int, radius: float, centre, angle: float = 360.0) -> bool:
        shape = self._one_selected("repeat")
        if shape is None:
            return False
        result = self._attempt(
            "Cannot repeat",
            lambda: builders.repeat_circle(shape, count, radius, centre, angle),
        )
        if result is None:
            return False
        transform, copies = result
        self._add_copies("repeat in a circle", shape, copies, transform)
        return True

    def do_repeat_row(self) -> None:
        if self._one_selected("repeat") is None:
            return
        values = panels.ask_repeat_row(self)
        if values is not None:
            self.repeat_row_selected(values["count"], values["spacing"], values["axis"])

    def do_repeat_circle(self) -> None:
        shape = self._one_selected("repeat")
        if shape is None:
            return
        centre = shape_geometry(shape).bounds.mean(axis=0)
        values = panels.ask_repeat_circle(self, (float(centre[0]), float(centre[1])))
        if values is not None:
            self.repeat_circle_selected(
                values["count"], values["radius"],
                (values["centre_x"], values["centre_y"]), values["angle"],
            )

    def make_box_with_lid(self, width, depth, height, wall, lid_height, fit="snug") -> bool:
        """Add a box and its lid as one undo step."""
        scene = self.document.scene
        parts = self._attempt(
            "Cannot make the box",
            lambda: builders.box_with_lid(
                width, depth, height, wall, lid_height, fit, scene.fit_clearances
            ),
        )
        if parts is None:
            return False
        self.document.snapshot("box with lid")
        for part in parts:
            scene.add(part)
        scene.select([p.id for p in parts])
        self.sync()
        return True

    def add_text(self, text: str, letter_height: float = 10.0, depth: float = 2.0,
                 engraved: bool = False) -> bool:
        """Raised text is a solid; engraved text is a Hole. One undo step."""
        if not has_letters(text):
            self._warn("Cannot add text", "Type some text first.")
            return False
        shape = new_primitive("text", name=f"Text: {text}")
        shape.params.update(text=text, letter_height=float(letter_height), depth=float(depth))
        shape.is_hole = bool(engraved)
        self.add_shape(shape)
        return True

    def do_add_text(self) -> None:
        values = panels.ask_text(self)
        if values is not None:
            self.add_text(values["text"], values["letter_height"], values["depth"],
                          values["style"] == "engraved")

    def do_box_with_lid(self) -> None:
        values = panels.ask_box_with_lid(self)
        if values is not None:
            self.make_box_with_lid(**values)

    # --- click-on-a-part tools -----------------------------------------

    TOOL_PROMPTS = {
        "lay_flat": "Click the face of a part that should rest on the workplane. Esc cancels.",
        "place": "Click a face of a part. The next shape you add will sit on it. Esc cancels.",
        "place_ready": "Now add a shape. It will sit on the face you clicked. Esc cancels.",
        "measure": "Click the first point on a part. Esc or Measure again to stop.",
        "measure_second": "Now click the second point.",
        **ExpertActions.EXPERT_TOOL_PROMPTS,
    }

    def start_tool(self, tool: str) -> None:
        """Wait for a click on a part. The gizmo is put away meanwhile so a
        click on the selected part reaches the part, not the drag handles."""
        self._clear_tool()
        self.tool = tool
        self.viewport.set_pick_mode(tool)
        self.gizmo.attach(None)
        self.statusBar().setStyleSheet("")
        self.statusBar().showMessage(self.TOOL_PROMPTS[tool])

    def _clear_tool(self) -> None:
        self.tool = None
        self._place_target = None
        self._measure_points = []
        self.viewport.set_pick_mode(None)
        self.viewport.clear_measure_line()
        for action in (self.act_place, self.act_measure):
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)

    def _tool_prompt(self) -> str:
        if self.tool == "place" and self._place_target is not None:
            return self.TOOL_PROMPTS["place_ready"]
        if self.tool == "measure" and len(self._measure_points) == 1:
            return self.TOOL_PROMPTS["measure_second"]
        return self._construct_prompt() or self.TOOL_PROMPTS[self.tool]

    def stop_tool(self) -> None:
        if self.tool is None:
            return
        self._clear_tool()
        self.sync()

    def toggle_place_on_face(self, checked: bool = True) -> None:
        if not checked:
            self.stop_tool()
            return
        if not self.document.scene.shapes:
            self.act_place.setChecked(False)
            self.statusBar().showMessage("Add a part first, then place shapes on its faces.")
            return
        self.start_tool("place")
        self.act_place.blockSignals(True)
        self.act_place.setChecked(True)
        self.act_place.blockSignals(False)

    def toggle_measure(self, checked: bool = True) -> None:
        """Measure never changes the scene: no snapshot, no edit."""
        if not checked:
            self.stop_tool()
            return
        self.start_tool("measure")
        self.act_measure.blockSignals(True)
        self.act_measure.setChecked(True)
        self.act_measure.blockSignals(False)

    def _measure_picked(self, shape_id: str, point) -> None:
        if not shape_id:
            return
        point = np.asarray(point, dtype=np.float64)
        if len(self._measure_points) != 1:
            # First click, or a fresh measurement after a finished one.
            self._measure_points = [point]
            self.viewport.clear_measure_line()
            self.statusBar().showMessage(self.TOOL_PROMPTS["measure_second"])
            return
        first = self._measure_points[0]
        self._measure_points = [first, point]
        self.viewport.set_measure_line(first, point)
        self.statusBar().showMessage(
            f"Distance: {ops.distance(first, point):.2f} mm. "
            "Click again to measure something else, Esc to stop."
        )

    def start_lay_flat(self) -> None:
        if not self.document.scene.shapes:
            self.statusBar().showMessage("Add a part first, then lay it flat.")
            return
        self.start_tool("lay_flat")

    def _on_surface_picked(self, shape_id: str, face_index: int, point) -> None:
        if self.tool == "lay_flat":
            self._lay_flat_picked(shape_id, face_index)
        elif self.tool == "place":
            self._place_picked(shape_id, face_index, point)
        elif self.tool == "measure":
            self._measure_picked(shape_id, point)
        elif self.tool in self.EXPERT_CLICK_HANDLERS:
            getattr(self, self.EXPERT_CLICK_HANDLERS[self.tool])(shape_id, face_index, point)

    def _place_picked(self, shape_id: str, face_index: int, point) -> None:
        """Remember the clicked face; nothing in the scene changes until a
        shape is actually added, so this takes no undo step."""
        scene = self.document.scene
        try:
            direction = ops.face_direction(scene.get(shape_id), face_index, scene.fit_clearances)
        except (KeyError, IndexError):
            self.statusBar().showMessage(self.TOOL_PROMPTS["place"])
            return
        self._place_target = (np.asarray(point, dtype=np.float64), direction)
        self.statusBar().showMessage(self.TOOL_PROMPTS["place_ready"])

    def _lay_flat_picked(self, shape_id: str, face_index: int) -> None:
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            direction = ops.face_direction(shape, face_index, scene.fit_clearances)
            # Attempt on a copy first: a failure leaves no undo step behind.
            turned = copy.deepcopy(shape)
            ops.lay_flat(turned, direction)
        except (KeyError, IndexError, ValueError):
            self.statusBar().showMessage("Click on a face of a part. Esc cancels.")
            return
        self.document.snapshot("lay flat")
        shape.transform = turned.transform
        scene.select([shape.id])
        self._clear_tool()
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
        if field in ("is_hole", "fit"):
            trial = copy.copy(shape)
            setattr(trial, field, bool(value) if field == "is_hole" else str(value))
            if not self._fits_build([trial], "Cannot change the fit"):
                self.inspector.show_shape(shape)
                return
        elif field not in ("color", "x", "y", "z", "rx", "ry", "rz"):
            problem = create.edit_refusal(shape, field, value, self.document.scene.fit_clearances)
            if problem is not None:
                self._warn("Cannot change that", problem)
                self.inspector.show_shape(shape)
                return

        # One snapshot per burst of edits, not one per keystroke: see the
        # comment on self._edit_timer in __init__.
        if not self._edit_active:
            self.document.snapshot("edit")
            self._edit_active = True
        # A typed number replaces a formula (Expert mode's parameters).
        self._end_link(shape, field)

        if field == "is_hole":
            shape.is_hole = bool(value)
        elif field == "fit":
            shape.fit = str(value)
        elif field == "color":
            shape.color = str(value)
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
        elif isinstance(value, str):
            # A drop-down choice (screw size, head) or typed text.
            shape.params[field] = value
        else:
            if field == "depth" and self._opens_at_top(shape):
                # A hardware hole or engraved text is measured down from its
                # opening: keep the opening where it is (flush with the face
                # it was placed on) and move the bottom instead.
                old = float(shape.params.get("depth", value))
                lift = np.eye(4, dtype=np.float64)
                lift[2, 3] = old - float(value)
                shape.transform = np.asarray(shape.transform, dtype=np.float64) @ lift
            shape.params[field] = float(value)

        # Defer the expensive part (snapshot already happened above, once
        # per burst) until typing pauses. Every keystroke restarts the
        # window instead of firing sync() itself.
        self._edit_timer.start()

    OPENS_AT_TOP = ("screw_hole", "nut_trap", "magnet_pocket", "text")

    def _opens_at_top(self, shape) -> bool:
        return (
            shape.is_hole and shape.kind == "primitive"
            and shape.params.get("primitive") in self.OPENS_AT_TOP
        )

    def _finish_edit(self) -> None:
        """Fires once, EDIT_COALESCE_MS after the last keystroke in a burst
        of inspector edits. This is the one sync() the whole burst gets."""
        self._edit_active = False
        self.sync()

    # --- files ---------------------------------------------------------

    def export_to(self, path) -> None:
        export_scene(self.document.scene, path)

    def save_to(self, path) -> None:
        save_project(self.document.scene, path)

    def open_from(self, path) -> None:
        new_document = Document(load_project(path))
        # load_project() validates the scene's own structure (shapes,
        # transforms, ...), but a corrupt embedded mesh blob only fails
        # later, the first time something actually decodes it -- here,
        # inside sync()'s viewport.refresh()/update_status(). Guard that
        # first sync so a bad blob surfaces as the same plain-language
        # "cannot open" dialog as every other load failure, instead of a
        # raw zlib.error traceback, and roll back to whatever project (or
        # empty document) was open before rather than leaving the window
        # half-switched to a document it couldn't actually display.
        previous_document = self.document
        # A clicked face or measured point belongs to the old project, and
        # so does a section view's cut.
        self._clear_tool()
        self._end_inspecting()
        self.document = new_document
        try:
            self.sync()
        except Exception as exc:
            self.document = previous_document
            self.sync()
            raise ProjectError(
                f"{Path(path).name} contains a model that could not be loaded. "
                "It may be corrupted."
            ) from exc

    def do_export(self) -> None:
        pattern = "Printable models (" + " ".join(f"*{e}" for e in EXPORT_EXTS) + ")"
        path, _ = QFileDialog.getSaveFileName(self, "Save for Printing", "part.stl", pattern)
        if not path:
            return
        try:
            self.export_to(path)
        except ProjectError as exc:
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
        except ProjectError as exc:
            self._warn("Cannot open", str(exc))

    def _maybe_offer_unit_scale(self, shapes) -> None:
        """A file whose dimensions suggest metres or inches imports as a
        speck a few hundredths of a millimetre across if we take its
        numbers at face value. Ask, in plain language, whether to scale it
        up -- and if so, apply that scale to every shape from this import.

        Imported shapes carry no size params (see panels.Inspector's
        `_active_size_fields`), so the scale is applied directly to each
        shape's transform rather than baked into params the way a
        primitive's gizmo scale is.
        """
        if not shapes:
            return
        try:
            suggestion = suggest_unit_scale(shape_geometry(shapes[0]))
        except Exception:
            return
        if suggestion is None:
            return

        factor, unit_name = suggestion
        answer = QMessageBox.question(
            self,
            "Scale this model?",
            f"This model looks like it was saved in {unit_name}. "
            "Scale it up to millimetres?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        for shape in shapes:
            transform = np.asarray(shape.transform, dtype=np.float64).copy()
            transform[:3, :3] *= factor
            transform[:3, 3] *= factor
            shape.transform = transform

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

        self._maybe_offer_unit_scale(shapes)

        self.document.snapshot("import")
        for shape in shapes:
            self.document.scene.add(shape)
        self.document.scene.select([s.id for s in shapes])
        self.sync()


def make_window() -> MeshWindow:
    """The app's window, with this computer's saved preferences."""
    return MeshWindow(Settings.load(default_path()))


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
    window = make_window()
    window.show()
    window.viewport.start()
    return app.exec()
