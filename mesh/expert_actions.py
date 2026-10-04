"""The window's Expert mode actions: the Sketch and Create menus.

MeshWindow inherits these, so they share its document, undo and click
tools. Each tool's geometry lives in a core module (mesh.sketch,
mesh.create); this is only the wiring: ask, try, then snapshot and apply
on success.
"""

from PySide6.QtCore import QTimer

from mesh import create, sketch, sketch_editor
from mesh.shapes import is_reference


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

    def _chosen_sketch(self):
        chosen = self.document.scene.selected()
        if len(chosen) != 1 or not create.is_sketch(chosen[0]):
            self.statusBar().showMessage("Select one sketch to change its curves.")
            return None
        return chosen[0]

    def do_edit_sketch(self) -> None:
        shape = self._chosen_sketch()
        if shape is None:
            return
        entities = sketch_editor.edit_sketch(self, f"Change {shape.name}", shape.params["entities"])
        if entities is not None:
            self.set_sketch_entities(shape, entities)

    def set_sketch_entities(self, shape, entities) -> bool:
        """Give a sketch new curves. One undo step; none if nothing changed."""
        changed = self._attempt("Cannot change the sketch", lambda: create.with_entities(shape, entities))
        if changed is None or changed.params == shape.params:
            return False
        self.document.snapshot("change sketch")
        shape.params = changed.params
        self.sync()
        return True
