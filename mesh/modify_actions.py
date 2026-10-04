"""The window's Expert mode actions for the Modify menu.

ExpertActions inherits these, so MeshWindow shares them with its document,
undo and click tools. The geometry lives in a core module (mesh.modify);
this is only the wiring: ask, try, then snapshot and apply on success.
"""

from PySide6.QtCore import QTimer

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


SCALE_ABOUT = [
    ("base", "The middle of their base (what stands on the workplane stays on it)"),
    ("centre", "Their middle"),
]


def scale_fields():
    percent = {"min": modify.SCALE_LIMITS[0] * 100.0, "max": modify.SCALE_LIMITS[1] * 100.0}
    return [
        ("size", "Size (%)", 100.0, percent),
        ("stretch_x", "Stretch left / right (%)", 100.0, percent),
        ("stretch_y", "Stretch forward / back (%)", 100.0, percent),
        ("stretch_z", "Stretch up / down (%)", 100.0, percent),
        ("about", "Scale about", "base", {"choices": SCALE_ABOUT}),
    ]


SCALE_NOTE = (
    "Size scales the selected parts the same in every direction, keeping their proportions; "
    "a stretch scales one direction more. Sizes stay editable in the Details panel. A round "
    "part must stretch alike across it, and a rounding or bottom chamfer keeps its size when "
    "the directions differ (Group a part first to stretch it any way). Screw holes, nut traps, "
    "insert pockets and magnet pockets keep their standard sizes and move with the parts."
)


def ask_scale(parent) -> dict | None:
    return run_form(parent, "Scale", scale_fields(), note=SCALE_NOTE)


def combine_fields(parts):
    return [
        ("target", "Part to change", parts[0].id, {"choices": [(s.id, s.name) for s in parts]}),
        ("op", "Combine by", "union", {"choices": list(modify.COMBINE_OPS.items())}),
        ("keep_tools", "Keep the other parts as well", False, {}),
    ]


COMBINE_NOTE = (
    "Join adds the other parts to the part to change, Cut takes them away from it, and Keep "
    "overlap keeps only where they overlap. The result is a group: Ungroup gives the parts back."
)


def ask_combine(parent, parts) -> dict | None:
    return run_form(parent, "Combine", combine_fields(parts), note=COMBINE_NOTE)


def split_body_fields(parts):
    return [
        ("part", "Part to split", parts[0].id, {"choices": [(s.id, s.name) for s in parts]}),
        ("keep_tool", "Keep the part used to split it as well", False, {}),
    ]


def ask_split_body(parent, parts) -> dict | None:
    return run_form(
        parent, "Split Body", split_body_fields(parts),
        note="Splits one part into the piece inside the other part and the piece outside it, "
             "where they stand.",
    )


def shell_fields():
    return [
        ("wall", "Wall thickness (mm)", 2.0, {"min": 0.1, "max": 100.0}),
        ("far_side", "Also leave open the face across from it", False, {}),
    ]


APPROXIMATE_SHELL_NOTE = (
    "This part is shelled approximately: the walls follow the outside evenly, but may come out "
    "a little thinner in places than the number you type. Boxes and cylinders are shelled "
    "exactly through their flat sides and ends."
)


def ask_shell(parent, exact: bool) -> dict | None:
    return run_form(parent, "Shell", shell_fields(), note=None if exact else APPROXIMATE_SHELL_NOTE)


def push_pull_fields():
    return [("distance", "Distance (mm)", 5.0, {"min": -modify.MOVE_LIMIT, "max": modify.MOVE_LIMIT})]


PUSH_PULL_NOTE = (
    "More than 0 pulls the face out of the part; less than 0 pushes it in. The face moves "
    "straight out, square to itself: a sloping side next to it is not extended. A round "
    "surface is made of narrow flat strips, and only the strip you clicked moves."
)


def ask_push_pull(parent) -> dict | None:
    return run_form(parent, "Push/Pull", push_pull_fields(), note=PUSH_PULL_NOTE)


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
    MODIFY_CLICK_TOOLS = ("align_from", "align_to", "shell", "push_pull")
    MODIFY_TOOL_PROMPTS = {
        "align_from": "Click the flat face of the part to move. Esc cancels.",
        "align_to": "Now click the face to put it against. Esc cancels.",
        "shell": "Click the flat face of a part to leave open. Esc cancels.",
        "push_pull": "Click the flat face of a part to push in or pull out. Esc cancels.",
    }
    MODIFY_CLICK_HANDLERS = {
        "align_from": "_align_from_picked",
        "align_to": "_align_to_picked",
        "shell": "_shell_picked",
        "push_pull": "_push_pull_picked",
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

    # --- Scale -------------------------------------------------------------------------

    NOTHING_TO_SCALE = "Select the parts to scale first."

    def scale_selected(self, size: float = 100.0, stretch_x: float = 100.0,
                       stretch_y: float = 100.0, stretch_z: float = 100.0,
                       about: str = "base") -> bool:
        """Scale the selected shapes by percentages: `size` in every
        direction, times each direction's stretch. One undo step; none when
        nothing would change."""
        scene = self.document.scene
        chosen = scene.selected()
        if not chosen:
            self.statusBar().showMessage(self.NOTHING_TO_SCALE)
            return False
        factors = [float(size) * float(s) / 10000.0 for s in (stretch_x, stretch_y, stretch_z)]
        if all(f == 1.0 for f in factors):
            self.statusBar().showMessage("Nothing changed: the scale was 100%.")
            return False
        changed = self._attempt(
            "Cannot scale", lambda: modify.scaled(chosen, factors, about, scene.fit_clearances)
        )
        if changed is None:
            return False
        self.document.snapshot("scale")
        for shape, new in zip(chosen, changed):
            shape.params = new.params
            shape.transform = new.transform
        self.sync()
        return True

    def do_scale(self) -> None:
        if not self.document.scene.selected():
            self.statusBar().showMessage(self.NOTHING_TO_SCALE)
            return
        values = ask_scale(self)
        if values is not None:
            self.scale_selected(**values)

    # --- Combine -----------------------------------------------------------------------

    COMBINE_HINT = "Select two or more parts to combine."

    def _picked_parts(self, hint: str, least: int = 2):
        """The selected parts, in the order they were picked; None (and a
        message) if there are fewer than `least`. Sketches are left out."""
        parts = [s for s in self._picked() if not is_reference(s)]
        if len(parts) < least:
            self.statusBar().showMessage(hint)
            return None
        return parts

    def combine_selected(self, target_id: str | None = None, op: str = "union",
                         keep_tools: bool = False) -> bool:
        """Join, cut or keep the overlap of the selected parts, changing the
        part `target_id` (or the first picked). One undo step."""
        parts = self._picked_parts(self.COMBINE_HINT)
        if parts is None:
            return False
        target = next((s for s in parts if s.id == target_id), parts[0])
        tools = [s for s in parts if s is not target]
        scene = self.document.scene
        group = self._attempt(
            "Cannot combine",
            lambda: modify.combine(target, tools, op, keep_tools, scene.fit_clearances),
        )
        if group is None:
            return False
        self.document.snapshot("combine")
        scene.remove([target.id] + ([] if keep_tools else [s.id for s in tools]))
        scene.add(group)
        scene.select([group.id])
        self.sync()
        return True

    def do_combine(self) -> None:
        parts = self._picked_parts(self.COMBINE_HINT)
        if parts is None:
            return
        values = ask_combine(self, parts)
        if values is not None:
            self.combine_selected(values["target"], values["op"], values["keep_tools"])

    # --- Split body --------------------------------------------------------------------

    SPLIT_BODY_HINT = "Select the part to split and a sketch or another part to split it with."

    def _split_pair(self):
        """(the parts the selection could split, the sketch to split by or
        None), or None (and a message) if the selection isn't two things."""
        chosen = self._picked()
        guides = [s for s in chosen if is_reference(s)]
        parts = [s for s in chosen if not is_reference(s)]
        if len(chosen) != 2 or len(guides) > 1 or not parts:
            self.statusBar().showMessage(self.SPLIT_BODY_HINT)
            return None
        return parts, (guides[0] if guides else None)

    def split_body_selected(self, part_id: str | None = None, keep_tool: bool = False) -> bool:
        """Split the selected part by the selected sketch's plane, or one
        selected part by the other (`part_id`, or the first picked). One
        undo step; a sketch stays, a part used to split goes unless kept."""
        pair = self._split_pair()
        if pair is None:
            return False
        parts, guide = pair
        part = next((s for s in parts if s.id == part_id), parts[0])
        tool = guide or next(s for s in parts if s is not part)
        scene = self.document.scene
        pieces = self._attempt("Cannot split", lambda: modify.split_body(part, tool, scene.fit_clearances))
        if pieces is None:
            return False
        self.document.snapshot("split body")
        scene.remove([part.id] + ([] if guide is not None or keep_tool else [tool.id]))
        for piece in pieces:
            scene.add(piece)
        scene.select([p.id for p in pieces])
        self.sync()
        return True

    def do_split_body(self) -> None:
        pair = self._split_pair()
        if pair is None:
            return
        parts, guide = pair
        if guide is not None:
            self.split_body_selected(parts[0].id)
            return
        values = ask_split_body(self, parts)
        if values is not None:
            self.split_body_selected(values["part"], values["keep_tool"])

    # --- Faces clicked to change ----------------------------------------------------------

    PARTS_FIRST = "Add a part first, then click one of its faces."

    def _start_face_tool(self, tool: str) -> None:
        if not any(not is_reference(s) for s in self.document.scene.shapes):
            self.statusBar().showMessage(self.PARTS_FIRST)
            return
        self.start_tool(tool)

    def _face_clicked(self, tool: str, shape_id: str, face_index: int, then) -> None:
        """A click for a tool that changes the face clicked: if it landed on
        a flat face of a solid part, stop waiting and, once the click is
        over, call `then(part)`. Nothing changes yet: no undo step."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            if is_reference(shape) or shape.is_hole:
                raise BuildError(self.TOOL_PROMPTS[tool])
            modify.flat_face(shape, face_index, scene.fit_clearances)
        except (KeyError, BuildError):
            self.statusBar().showMessage(self.TOOL_PROMPTS[tool])
            return
        self._clear_tool()
        self.sync()
        # Opened once the click is over: a window opened during the click
        # would leave the 3D view thinking the button is still held down.
        QTimer.singleShot(0, lambda: then(shape))

    # --- Shell -------------------------------------------------------------------------

    def do_shell(self) -> None:
        self._start_face_tool("shell")

    def _shell_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        self._face_clicked("shell", shape_id, face_index,
                           lambda shape: self._ask_shell(shape, face_index))

    def _ask_shell(self, shape, face_index: int) -> None:
        self.viewport.end_drag()
        values = ask_shell(self, modify.shells_exactly(shape))
        if values is not None:
            self.shell_face(shape.id, face_index, values["wall"], values["far_side"])

    def shell_face(self, shape_id: str, face_index: int, wall: float, far_side: bool = False) -> bool:
        """Hollow out a part, leaving the face `face_index` open (and the
        one across from it, with `far_side`). One undo step on success."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        group = self._attempt(
            "Cannot shell",
            lambda: modify.shell(shape, face_index, wall, far_side, scene.fit_clearances),
        )
        if group is None:
            return False
        self._replace_with("shell", shape, [group])
        return True

    # --- Push/Pull ---------------------------------------------------------------------

    def do_push_pull(self) -> None:
        self._start_face_tool("push_pull")

    def _push_pull_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        self._face_clicked("push_pull", shape_id, face_index,
                           lambda shape: self._ask_push_pull(shape, face_index))

    def _ask_push_pull(self, shape, face_index: int) -> None:
        self.viewport.end_drag()
        values = ask_push_pull(self)
        if values is not None:
            self.push_pull_face(shape.id, face_index, values["distance"])

    def push_pull_face(self, shape_id: str, face_index: int, distance: float) -> bool:
        """Move a part's flat face out (`distance` > 0) or in. One undo step
        on success."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        group = self._attempt(
            "Cannot push or pull",
            lambda: modify.push_pull(shape, face_index, distance, scene.fit_clearances),
        )
        if group is None:
            return False
        self._replace_with("push/pull", shape, [group])
        return True
