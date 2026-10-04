"""The window's Expert mode actions: the Sketch and Create menus.

MeshWindow inherits these, so they share its document, undo and click
tools. Each tool's geometry lives in a core module (mesh.sketch,
mesh.create); this is only the wiring: ask, try, then snapshot and apply
on success.
"""

from PySide6.QtCore import QTimer

from mesh import create, features, sketch, sketch_editor
from mesh.panels import run_form
from mesh.shapes import is_reference

# What a tool makes from a sketch: a new solid part, or a Hole that cuts
# the parts it is grouped with (Solid/Hole + Group, as everywhere in mesh).
RESULTS = [("part", "A new part"), ("hole", "A hole (cuts parts when grouped with them)")]


def _result_fields():
    return [
        ("result", "Make", "part", {"choices": RESULTS}),
        ("keep_sketch", "Keep the sketch as well", False, {}),
    ]


def extrude_fields():
    return [
        ("distance", "Distance (mm)", 20.0, {"min": 0.1, "max": 10000.0}),
        ("side", "Direction", "one", {"choices": features.SIDES}),
    ] + _result_fields()


def ask_extrude(parent) -> dict | None:
    return run_form(parent, "Extrude", extrude_fields(),
                    note="Pushes the sketch's closed outlines straight out of its plane.")


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


class ExpertActions:
    """Mixed into MeshWindow (see mesh.expert for the menu items)."""

    # The click-on-a-part tools Expert mode adds; turning the mode off
    # stops any of them that is waiting for a click.
    EXPERT_CLICK_TOOLS = ("sketch_face",)

    EXPERT_TOOL_PROMPTS = {
        "sketch_face": "Click a flat face of a part to sketch on it. Esc cancels.",
    }

    # --- Sketches ------------------------------------------------------------------

    def add_sketch(self, entities, frame, name: str | None = None) -> bool:
        """Add a sketch of `entities` on the plane `frame` places. One undo step."""
        scene = self.document.scene
        shape = self._attempt(
            "Cannot make the sketch",
            lambda: create.new_sketch(entities, frame, name or create.next_sketch_name(scene.shapes)),
        )
        if shape is None:
            return False
        self.add_shape(shape)
        return True

    def do_new_sketch(self) -> None:
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

    def _sketch_face_picked(self, shape_id: str, face_index: int) -> None:
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

    def do_edit_sketch(self) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) != 1 or not create.has_sketch(chosen[0]):
            self.statusBar().showMessage(self.CHANGE_SKETCH_HINT)
            return
        shape = chosen[0]
        entities = sketch_editor.edit_sketch(self, f"Change {shape.name}", create.sketch_entities(shape))
        if entities is not None:
            self.set_sketch_entities(shape, entities)

    def set_sketch_entities(self, shape, entities) -> bool:
        """Give a sketch, or a part made from one, new curves. One undo
        step; none if nothing changed or the part would not come out solid."""
        changed = self._attempt("Cannot change the sketch", lambda: create.with_entities(shape, entities))
        if changed is None or changed.params == shape.params:
            return False
        self.document.snapshot("change sketch")
        shape.params = changed.params
        self.sync()
        return True

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

    def do_extrude(self) -> None:
        if self._chosen_sketch("extrude") is None:
            return
        values = ask_extrude(self)
        if values is not None:
            self.extrude_selected(values["distance"], values["side"], values["result"] == "hole",
                                  values["keep_sketch"])
