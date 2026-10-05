"""The window's Expert mode actions: the Sketch and Create menus.

Create's patterns and Mirror are in mesh.pattern_actions, the Modify menu
in mesh.modify_actions, the Construct menu in mesh.construct_actions and
the Inspect menu in mesh.inspect_actions; all are mixed in here.

MeshWindow inherits these, so they share its document, undo and click
tools. Each tool's geometry lives in a core module (mesh.sketch,
mesh.create); this is only the wiring: ask, try, then snapshot and apply
on success.
"""

from PySide6.QtCore import QTimer

from mesh import construct, create, features, sketch, sketch_editor
from mesh.construct_actions import ConstructActions
from mesh.inspect_actions import InspectActions
from mesh.modify_actions import ModifyActions
from mesh.pattern_actions import PatternActions
from mesh.panels import run_form
from mesh.shapes import is_reference

# What a tool makes from a sketch: a new solid part, or a Hole that cuts
# the parts it is grouped with (Solid/Hole + Group, as everywhere in mesh).
RESULTS = [("part", "A new part"), ("hole", "A hole (cuts parts when grouped with them)")]


def _result_fields(sketches: int = 1):
    keep = "Keep the sketch as well" if sketches == 1 else "Keep the sketches as well"
    return [
        ("result", "Make", "part", {"choices": RESULTS}),
        ("keep_sketch", keep, False, {}),
    ]


def extrude_fields():
    return [
        ("distance", "Distance (mm)", 20.0, {"min": 0.1, "max": 10000.0}),
        ("side", "Direction", "one", {"choices": features.SIDES}),
    ] + _result_fields()


def ask_extrude(parent) -> dict | None:
    return run_form(parent, "Extrude", extrude_fields(),
                    note="Pushes the sketch's closed outlines straight out of its plane. A sketch "
                         "on a face faces out of the part: for a hole into that face, choose "
                         "\"The other way\".")


def revolve_fields(axes):
    return [
        ("axis", "Turn around", axes[0][0], {"choices": axes}),
        ("angle", "Angle (degrees)", 360.0, {"min": 0.1, "max": 360.0}),
    ] + _result_fields()


def ask_revolve(parent, axes) -> dict | None:
    return run_form(
        parent, "Revolve", revolve_fields(axes),
        note="Turns the sketch's closed outlines around a line, like a part on a lathe. "
             "The outline must lie all on one side of the line. Round surfaces are made "
             "of narrow flat strips, like a cylinder's.",
    )


def sweep_fields(sketches, path_id: str):
    return [
        ("path", "Path to follow", path_id, {"choices": [(s.id, s.name) for s in sketches]}),
    ] + _result_fields(len(sketches))


def ask_sweep(parent, sketches, path_id: str) -> dict | None:
    return run_form(
        parent, "Sweep", sweep_fields(sketches, path_id),
        note="Carries the other sketch's closed outlines along the path, square to it. "
             "If the outline is not drawn across an end of the path, it is moved to the nearer end. "
             "Curved paths are followed in short straight steps.",
    )


def loft_fields(count: int):
    return _result_fields(count)


def ask_loft(parent, sketches) -> dict | None:
    order = ", ".join(s.name for s in sketches)
    return run_form(
        parent, "Loft", loft_fields(len(sketches)),
        note=f"Joins the sketches' outlines with a smooth-sided skin, in the order you picked "
             f"them: {order}. Each sketch needs one closed outline with no holes. The sides "
             "are straight from one outline to the next.",
    )


class ExpertActions(ModifyActions, PatternActions, ConstructActions, InspectActions):
    """Mixed into MeshWindow (see mesh.expert for the menu items)."""

    # The click-on-a-part tools Expert mode adds; turning the mode off
    # stops any of them that is waiting for a click.
    EXPERT_CLICK_TOOLS = (
        ("sketch_face",) + ModifyActions.MODIFY_CLICK_TOOLS + PatternActions.PATTERN_CLICK_TOOLS
        + ConstructActions.CONSTRUCT_CLICK_TOOLS + InspectActions.INSPECT_CLICK_TOOLS
    )

    EXPERT_TOOL_PROMPTS = {
        "sketch_face": "Click a flat face of a part to sketch on it. Esc cancels.",
        **ModifyActions.MODIFY_TOOL_PROMPTS,
        **PatternActions.PATTERN_TOOL_PROMPTS,
        **ConstructActions.CONSTRUCT_TOOL_PROMPTS,
        **InspectActions.INSPECT_TOOL_PROMPTS,
    }

    # The method each of those tools' clicks goes to: (part id, triangle
    # clicked, world point).
    EXPERT_CLICK_HANDLERS = {
        "sketch_face": "_sketch_face_picked",
        **ModifyActions.MODIFY_CLICK_HANDLERS,
        **PatternActions.PATTERN_CLICK_HANDLERS,
        **ConstructActions.CONSTRUCT_CLICK_HANDLERS,
        **InspectActions.INSPECT_CLICK_HANDLERS,
    }

    # The later prompts of the tools that take several clicks.
    _STAGED = {**ConstructActions._STAGED, **InspectActions.INSPECT_STAGED}

    # --- Sketches ------------------------------------------------------------------

    def add_sketch(self, entities, frame, name: str | None = None) -> bool:
        """Add a sketch of `entities` on the plane `frame` places. One undo
        step. Not through add_shape: a sketch stays on its own plane, even
        while Place on a Face waits to place the next new part."""
        scene = self.document.scene
        shape = self._attempt(
            "Cannot make the sketch",
            lambda: create.new_sketch(entities, frame, name or create.next_sketch_name(scene.shapes)),
        )
        if shape is None:
            return False
        self.document.snapshot("add sketch")
        scene.add(shape)
        scene.select([shape.id])
        self.sync()
        return True

    def do_new_sketch(self) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) == 1 and construct.is_guide(chosen[0], "plane"):
            # Drawn straight onto the selected construction plane.
            origin, normal = construct.plane_of(chosen[0])
            entities = sketch_editor.edit_sketch(self, f"New sketch on {chosen[0].name}")
            if entities is not None:
                self.add_sketch(entities, sketch.plane_frame(normal, origin))
            return
        choice = sketch_editor.ask_sketch_plane(self)
        if choice is None:
            return
        frame = sketch.named_plane_frame(choice["plane"], choice["distance"])
        entities = sketch_editor.edit_sketch(
            self, "New sketch", note=sketch_editor.PLANE_NOTES[choice["plane"]]
        )
        if entities is not None:
            self.add_sketch(entities, frame)

    def do_sketch_on_face(self) -> None:
        if not any(not is_reference(s) for s in self.document.scene.shapes):
            self.statusBar().showMessage("Add a part first, then sketch on one of its flat faces.")
            return
        self.start_tool("sketch_face")

    def _sketch_face_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        """Nothing changes until the sketch window's OK, so a click takes no
        undo step."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            frame, outlines = create.face_plane(shape, face_index, scene.fit_clearances)
        except (KeyError, IndexError, ValueError):
            self.statusBar().showMessage(self.TOOL_PROMPTS["sketch_face"])
            return
        self._clear_tool()
        self.sync()
        # Opened once the click is over: a window opened during the click
        # would leave the 3D view thinking the button is still held down.
        QTimer.singleShot(0, lambda: self.sketch_on_face(frame, outlines, shape.name))

    def sketch_on_face(self, frame, outlines, part_name: str) -> bool:
        self.viewport.end_drag()
        entities = sketch_editor.edit_sketch(
            self, f"Sketch on a face of {part_name}", guides=outlines,
            note="The face's outline is shown dashed.",
        )
        return entities is not None and self.add_sketch(entities, frame)

    def _chosen_sketch(self, what: str = "use it"):
        chosen = self.document.scene.selected()
        if len(chosen) != 1 or not create.is_sketch(chosen[0]):
            self.statusBar().showMessage(f"Select one sketch to {what}.")
            return None
        return chosen[0]

    CHANGE_SKETCH_HINT = "Select one sketch, or one part made from a sketch, to change its curves."

    LOFT_NOT_REDRAWN = "A loft's outlines can't be changed. Undo the loft, change the sketches, and loft again."

    def do_edit_sketch(self) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) != 1 or not create.has_sketch(chosen[0]):
            loft = len(chosen) == 1 and chosen[0].params.get("primitive") == "loft"
            self.statusBar().showMessage(self.LOFT_NOT_REDRAWN if loft else self.CHANGE_SKETCH_HINT)
            return
        shape = chosen[0]
        entities = create.sketch_entities(shape)
        while True:
            entities = sketch_editor.edit_sketch(self, f"Change {shape.name}", entities)
            if entities is None:
                return
            changed = self._changed_sketch(shape, entities)
            if changed is not None:
                self._apply_sketch_change(shape, changed)
                return
            # Refused (and said why): back to the sketch window with the
            # curves as they were left, to fix them.

    def _changed_sketch(self, shape, entities):
        return self._attempt(
            "Cannot change the sketch",
            lambda: create.with_entities(shape, entities, self.document.scene.fit_clearances),
        )

    def _apply_sketch_change(self, shape, changed) -> bool:
        if changed.params == shape.params:
            return False
        self.document.snapshot("change sketch")
        shape.params = changed.params
        shape.transform = changed.transform
        self.sync()
        return True

    def set_sketch_entities(self, shape, entities) -> bool:
        """Give a sketch, or a part made from one, new curves. One undo
        step; none if nothing changed or the part would not come out solid."""
        changed = self._changed_sketch(shape, entities)
        return changed is not None and self._apply_sketch_change(shape, changed)

    # --- Solids from sketches -----------------------------------------------------

    def _add_from_sketches(self, label: str, sources, shape, keep_sketch: bool) -> None:
        """One undo step: add the new part and, unless kept, remove the
        sketches it was made from (it keeps a copy of their curves)."""
        scene = self.document.scene
        self.document.snapshot(label)
        if not keep_sketch:
            scene.remove([s.id for s in sources])
        scene.add(shape)
        scene.select([shape.id])
        self.sync()

    def extrude_selected(self, distance: float, side: str = "one", hole: bool = False,
                         keep_sketch: bool = False) -> bool:
        source = self._chosen_sketch("extrude")
        if source is None:
            return False
        shape = self._attempt("Cannot extrude",
                              lambda: create.make_extrude(source, distance, side, hole))
        if shape is None:
            return False
        self._add_from_sketches("extrude", [source], shape, keep_sketch)
        return True

    def revolve_selected(self, axis: str = "y", angle: float = 360.0, hole: bool = False,
                         keep_sketch: bool = False) -> bool:
        source = self._chosen_sketch("revolve")
        if source is None:
            return False
        shape = self._attempt("Cannot revolve",
                              lambda: create.make_revolve(source, axis, angle, hole))
        if shape is None:
            return False
        self._add_from_sketches("revolve", [source], shape, keep_sketch)
        return True

    def do_revolve(self) -> None:
        source = self._chosen_sketch("revolve")
        if source is None:
            return
        values = ask_revolve(self, create.revolve_axes(source))
        if values is not None:
            self.revolve_selected(values["axis"], values["angle"], values["result"] == "hole",
                                  values["keep_sketch"])

    TWO_SKETCHES_HINT = "Select two sketches: the outline, and the path to sweep it along."

    def _picked(self):
        """The selected shapes in the order they were picked."""
        scene = self.document.scene
        order = {shape_id: index for index, shape_id in enumerate(scene.selection)}
        return sorted(scene.selected(), key=lambda s: order[s.id])

    def _two_sketches(self):
        chosen = self._picked()
        if len(chosen) != 2 or not all(create.is_sketch(s) for s in chosen):
            self.statusBar().showMessage(self.TWO_SKETCHES_HINT)
            return None
        return chosen

    def sweep_selected(self, path_id: str | None = None, hole: bool = False,
                       keep_sketch: bool = False) -> bool:
        """Sweep one selected sketch's outline along the other's path
        (`path_id`, or the likelier one)."""
        pair = self._two_sketches()
        if pair is None:
            return False
        path = next((s for s in pair if s.id == path_id), None) or create.likely_path(*pair)
        outline = pair[1] if path is pair[0] else pair[0]
        shape = self._attempt("Cannot sweep", lambda: create.make_sweep(outline, path, hole))
        if shape is None:
            return False
        self._add_from_sketches("sweep", pair, shape, keep_sketch)
        return True

    def do_sweep(self) -> None:
        pair = self._two_sketches()
        if pair is None:
            return
        values = ask_sweep(self, pair, create.likely_path(*pair).id)
        if values is not None:
            self.sweep_selected(values["path"], values["result"] == "hole", values["keep_sketch"])

    LOFT_HINT = "Select two or more sketches, in the order to join them."

    def _sketches_in_order(self):
        chosen = self._picked()
        if len(chosen) < 2 or not all(create.is_sketch(s) for s in chosen):
            self.statusBar().showMessage(self.LOFT_HINT)
            return None
        return chosen

    def loft_selected(self, hole: bool = False, keep_sketch: bool = False) -> bool:
        sketches = self._sketches_in_order()
        if sketches is None:
            return False
        shape = self._attempt("Cannot loft", lambda: create.make_loft(sketches, hole))
        if shape is None:
            return False
        self._add_from_sketches("loft", sketches, shape, keep_sketch)
        return True

    def do_loft(self) -> None:
        sketches = self._sketches_in_order()
        if sketches is None:
            return
        values = ask_loft(self, sketches)
        if values is not None:
            self.loft_selected(values["result"] == "hole", values["keep_sketch"])

    def do_extrude(self) -> None:
        if self._chosen_sketch("extrude") is None:
            return
        values = ask_extrude(self)
        if values is not None:
            self.extrude_selected(values["distance"], values["side"], values["result"] == "hole",
                                  values["keep_sketch"])
