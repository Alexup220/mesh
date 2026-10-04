"""The window's Expert mode actions for the Modify menu.

ExpertActions inherits these, so MeshWindow shares them with its document,
undo and click tools. The geometry lives in a core module (mesh.modify);
this is only the wiring: ask, try, then snapshot and apply on success.
"""

from mesh import modify
from mesh.panels import run_form

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
    MODIFY_CLICK_TOOLS: tuple[str, ...] = ()
    MODIFY_TOOL_PROMPTS: dict[str, str] = {}
    MODIFY_CLICK_HANDLERS: dict[str, str] = {}

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
