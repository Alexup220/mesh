"""The window's Expert mode actions for the Modify menu.

ExpertActions inherits these, so MeshWindow shares them with its document,
undo and click tools. The geometry lives in a core module (mesh.modify);
this is only the wiring: ask, try, then snapshot and apply on success.
"""

from mesh import modify
from mesh.builders import GUIDES_ARE_NOT_PARTS, BuildError
from mesh.panels import run_form
from mesh.shapes import is_reference

TURN_AXES = [
    ("z", "An upright line (turns it round, seen from above)"),
    ("x", "A left-right line (tips it forward or back)"),
    ("y", "A front-back line (tips it left or right)"),
]


def move_copy_fields():
    distance = {"min": -modify.MOVE_LIMIT, "max": modify.MOVE_LIMIT}
    return [
        ("dx", "Move left / right (mm)", 0.0, distance),
        ("dy", "Move forward / back (mm)", 0.0, distance),
        ("dz", "Move up / down (mm)", 0.0, distance),
        ("axis", "Turn around", "z", {"choices": TURN_AXES}),
        ("angle", "Turn (degrees)", 0.0, {"min": -360.0, "max": 360.0}),
        ("make_copy", "Make a copy, and leave the original where it is", False, {}),
    ]


def ask_move_copy(parent) -> dict | None:
    return run_form(
        parent, "Move or Copy", move_copy_fields(),
        note="Moves the selected parts by exact amounts. A turn goes around a line through "
             "their middle, before the move.",
    )


class ModifyActions:
    """Mixed into MeshWindow through ExpertActions (see mesh.expert for the
    menu items)."""

    # The click-on-a-part tools of the Modify menu, their prompts, and the
    # method each click goes to.
    MODIFY_CLICK_TOOLS = ("align_from", "align_to")
    MODIFY_TOOL_PROMPTS = {
        "align_from": "Click the flat face of the part to move. Esc cancels.",
        "align_to": "Now click the face to put it against. Esc cancels.",
    }
    MODIFY_CLICK_HANDLERS = {
        "align_from": "_align_from_picked",
        "align_to": "_align_to_picked",
    }

    # --- Move or Copy ------------------------------------------------------------

    NOTHING_SELECTED = "Select the parts to move first."
    NOTHING_TO_MOVE = "Nothing moved: every amount was 0."

    def move_copy_selected(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
                           axis: str = "z", angle: float = 0.0, make_copy: bool = False) -> bool:
        """Move or turn the selected shapes by exact amounts, or copies of
        them. One undo step; none when nothing would change."""
        scene = self.document.scene
        chosen = scene.selected()
        if not chosen:
            self.statusBar().showMessage(self.NOTHING_SELECTED)
            return False
        if not make_copy and dx == dy == dz == angle == 0.0:
            self.statusBar().showMessage(self.NOTHING_TO_MOVE)
            return False
        moved = self._attempt(
            "Cannot move", lambda: modify.move_copy(chosen, dx, dy, dz, axis, angle, make_copy)
        )
        if moved is None:
            return False
        self.document.snapshot("copy" if make_copy else "move")
        if make_copy:
            for shape in moved:
                scene.add(shape)
        else:
            for shape, changed in zip(chosen, moved):
                shape.transform = changed.transform
        scene.select([s.id for s in moved])
        self.sync()
        return True

    def do_move_copy(self) -> None:
        if not self.document.scene.selected():
            self.statusBar().showMessage(self.NOTHING_SELECTED)
            return
        values = ask_move_copy(self)
        if values is not None:
            self.move_copy_selected(**values)

    # --- Align face to face ------------------------------------------------------

    TWO_PARTS_FIRST = "Add two parts first, then put a face of one against the other."

    def do_align_faces(self) -> None:
        parts = [s for s in self.document.scene.shapes if not is_reference(s)]
        if len(parts) < 2:
            self.statusBar().showMessage(self.TWO_PARTS_FIRST)
            return
        self.start_tool("align_from")

    def _align_from_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        """Remember the face to move. Nothing changes yet: no undo step."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            if is_reference(shape):
                raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Align"))
            modify.flat_face(shape, face_index, scene.fit_clearances)
        except (KeyError, BuildError):
            self.statusBar().showMessage(self.TOOL_PROMPTS["align_from"])
            return
        self.start_tool("align_to")
        self._align_first = (shape_id, face_index)

    def _align_to_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        scene = self.document.scene
        moving_id, moving_face = self._align_first
        try:
            moving = scene.get(moving_id)
            transform = modify.align_faces(moving, moving_face, scene.get(shape_id), face_index,
                                           scene.fit_clearances)
        except KeyError:
            self.statusBar().showMessage(self.TOOL_PROMPTS["align_to"])
            return
        except BuildError as exc:
            self.statusBar().showMessage(f"{exc} {self.TOOL_PROMPTS['align_to']}")
            return
        self.document.snapshot("align faces")
        moving.transform = transform
        scene.select([moving.id])
        self._clear_tool()
        self.sync()
