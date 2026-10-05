"""The window's Expert mode patterns and Mirror (in the Create menu).

Mixed into MeshWindow through ExpertActions. The geometry is in
mesh.patterns; this is only the wiring: ask, try, then snapshot and add the
copies on success, as one undo step.
"""

from PySide6.QtCore import QTimer

from mesh import construct, create, patterns
from mesh.builders import MAX_COPIES, BuildError
from mesh.modify import MOVE_LIMIT, _bounds
from mesh.modify_actions import TURN_AXES
from mesh.panels import run_form
from mesh.shapes import is_reference

DIRECTIONS = [("x", "Left / right"), ("y", "Forward / back"), ("z", "Up / down")]


def rectangular_fields():
    spacing = {"min": -MOVE_LIMIT, "max": MOVE_LIMIT}
    return [
        ("count", "How many in a row", 3, {"min": 1, "max": MAX_COPIES}),
        ("spacing", "Spacing along a row (mm)", 30.0, spacing),
        ("axis", "Each row goes", "x", {"choices": DIRECTIONS}),
        ("count2", "How many rows", 1, {"min": 1, "max": MAX_COPIES}),
        ("spacing2", "Spacing between rows (mm)", 30.0, spacing),
        ("axis2", "The next rows go", "y", {"choices": DIRECTIONS}),
    ]


RECTANGULAR_NOTE = (
    "Copies the selected parts in a row, and in more rows if you like. The counts include the "
    "parts themselves. Spacing is from one copy to the next; less than 0 goes the other way."
)


def ask_rectangular(parent) -> dict | None:
    return run_form(parent, "Pattern in Rows", rectangular_fields(), note=RECTANGULAR_NOTE)


def circular_fields(centre):
    coordinate = {"min": -MOVE_LIMIT, "max": MOVE_LIMIT}
    return [
        ("count", "How many in total", 6, {"min": 2, "max": MAX_COPIES}),
        ("angle", "Angle to fill (degrees, 360 for a full circle)", 360.0, {"min": 1.0, "max": 360.0}),
        ("axis", "Turn around", "z", {"choices": TURN_AXES}),
        ("centre_x", "The line goes through: left / right (mm)", round(float(centre[0]), 2), coordinate),
        ("centre_y", "The line goes through: forward / back (mm)", round(float(centre[1]), 2), coordinate),
        ("centre_z", "The line goes through: height (mm)", round(float(centre[2]), 2), coordinate),
    ]


CIRCULAR_NOTE = (
    "Copies the selected parts round a line, turning each copy with it, like Repeat in a Circle "
    "but round any of the three lines and with the parts left where they are. The count "
    "includes the parts themselves."
)


def ask_circular(parent, centre) -> dict | None:
    return run_form(parent, "Pattern Around a Line", circular_fields(centre), note=CIRCULAR_NOTE)


def circular_axis_fields():
    return circular_fields((0.0, 0.0, 0.0))[:2]


def circular_axis_note(name: str) -> str:
    return (f"Copies the selected parts round {name}, turning each copy with it, anticlockwise "
            "seen from the end its arrow points to. The count includes the parts themselves.")


def ask_circular_axis(parent, name: str) -> dict | None:
    return run_form(parent, "Pattern Around a Line", circular_axis_fields(), note=circular_axis_note(name))


def path_fields():
    return [
        ("count", "How many in total", 5, {"min": 2, "max": MAX_COPIES}),
        ("even", "Spread them evenly along the whole path", True, {}),
        ("spacing", "Otherwise, spacing along the path (mm)", 10.0, {"min": 0.01, "max": MOVE_LIMIT}),
        ("follow", "Turn the copies as the path turns", False, {}),
    ]


PATH_NOTE = (
    "Copies the selected parts along the sketch's path, starting from the end nearest them. "
    "Each copy keeps the parts' place beside the path. Curves are followed in their short "
    "straight pieces. The count includes the parts themselves."
)


def ask_path(parent) -> dict | None:
    return run_form(parent, "Pattern Along a Path", path_fields(), note=PATH_NOTE)


MIRROR_PLANES = [
    ("face", "A flat face you click next"),
    ("x", "The upright middle plane between left and right (through 0)"),
    ("y", "The upright middle plane between front and back (through 0)"),
    ("z", "The workplane (the copies end up below it)"),
]


def mirror_fields():
    return [("plane", "Mirror across", "face", {"choices": MIRROR_PLANES})]


MIRROR_NOTE = (
    "Adds a mirror image of each selected part on the other side of the plane. To mirror "
    "across a sketch's plane or a construction plane, select it with the parts. Combine joins "
    "a copy to its part."
)


def ask_mirror(parent) -> dict | None:
    return run_form(parent, "Mirror", mirror_fields(), note=MIRROR_NOTE)


class PatternActions:
    """Mixed into MeshWindow through ExpertActions."""

    PATTERN_CLICK_TOOLS = ("mirror_face",)
    PATTERN_TOOL_PROMPTS = {
        "mirror_face": "Click a flat face to mirror the selected parts across. Esc cancels.",
    }
    PATTERN_CLICK_HANDLERS = {"mirror_face": "_mirror_face_picked"}

    PATTERN_HINT = "Select the parts to copy first."

    def _pattern_parts(self):
        """The selected parts in pick order; None (and a message) if only
        sketches or nothing are selected."""
        parts = [s for s in self._picked() if not is_reference(s)]
        if not parts:
            self.statusBar().showMessage(self.PATTERN_HINT)
            return None
        return parts

    def _add_pattern(self, label: str, parts, build) -> bool:
        """Add the copies `build` makes, with the parts, as one undo step;
        none if it refuses."""
        copies = self._attempt("Cannot make the copies", build)
        if copies is None:
            return False
        self.document.snapshot(label)
        for clone in copies:
            self.document.scene.add(clone)
        self.document.scene.select([s.id for s in parts] + [c.id for c in copies])
        self.sync()
        return True

    # --- In rows ------------------------------------------------------------------

    def rectangular_pattern_selected(self, count: int = 3, spacing: float = 30.0, axis: str = "x",
                                     count2: int = 1, spacing2: float = 30.0, axis2: str = "y") -> bool:
        parts = self._pattern_parts()
        if parts is None:
            return False
        return self._add_pattern(
            "pattern in rows", parts,
            lambda: patterns.rectangular(parts, count, spacing, axis, count2, spacing2, axis2),
        )

    def do_rectangular_pattern(self) -> None:
        if self._pattern_parts() is None:
            return
        values = ask_rectangular(self)
        if values is not None:
            self.rectangular_pattern_selected(**values)

    # --- Around a line ------------------------------------------------------------

    def _selected_axis(self):
        """The one construction axis selected with the parts, or None."""
        axes = [s for s in self._picked() if construct.is_guide(s, "axis")]
        return axes[0] if len(axes) == 1 else None

    def circular_pattern_selected(self, count: int = 6, axis: str = "z", centre=(0.0, 0.0, 0.0),
                                  angle: float = 360.0) -> bool:
        """Copies round the selected construction axis, or else round the
        line along `axis` through `centre`."""
        parts = self._pattern_parts()
        if parts is None:
            return False
        guide = self._selected_axis()
        if guide is None:
            return self._add_pattern("pattern around a line", parts,
                                     lambda: patterns.circular(parts, count, axis, centre, angle))
        point, direction = construct.axis_of(guide)
        return self._add_pattern("pattern around a line", parts,
                                 lambda: patterns.circular_about(parts, count, point, direction, angle))

    def do_circular_pattern(self) -> None:
        parts = self._pattern_parts()
        if parts is None:
            return
        guide = self._selected_axis()
        if guide is not None:
            values = ask_circular_axis(self, guide.name)
            if values is not None:
                self.circular_pattern_selected(values["count"], angle=values["angle"])
            return
        # As Repeat in a Circle does: the line starts 30 mm to the left.
        middle = _bounds(parts).mean(axis=0) - (30.0, 0.0, 0.0)
        values = ask_circular(self, middle)
        if values is not None:
            self.circular_pattern_selected(
                values["count"], values["axis"],
                (values["centre_x"], values["centre_y"], values["centre_z"]), values["angle"],
            )

    # --- Along a path -------------------------------------------------------------

    PATH_HINT = "Select the parts to copy and one sketch whose curves make the path."

    def _path_selection(self):
        chosen = self._picked()
        guides = [s for s in chosen if is_reference(s)]
        parts = [s for s in chosen if not is_reference(s)]
        if len(guides) != 1 or not parts or not create.is_sketch(guides[0]):
            self.statusBar().showMessage(self.PATH_HINT)
            return None
        return parts, guides[0]

    def path_pattern_selected(self, count: int = 5, spacing: float | None = None,
                              follow: bool = False) -> bool:
        """Copies along the selected sketch's path: `spacing` mm apart, or
        spread evenly for None."""
        chosen = self._path_selection()
        if chosen is None:
            return False
        parts, guide = chosen
        return self._add_pattern(
            "pattern along a path", parts,
            lambda: patterns.along_path(parts, guide, count, spacing, follow),
        )

    def do_path_pattern(self) -> None:
        if self._path_selection() is None:
            return
        values = ask_path(self)
        if values is not None:
            self.path_pattern_selected(
                values["count"], None if values["even"] else values["spacing"], values["follow"],
            )

    # --- Mirror -------------------------------------------------------------------

    MIRROR_HINT = "Select the parts to mirror (and a sketch or plane, to mirror across it)."

    def _mirror_selection(self):
        chosen = self._picked()
        guides = [s for s in chosen if is_reference(s)]
        parts = [s for s in chosen if not is_reference(s)]
        if not parts or len(guides) > 1 or (guides and not construct.is_flat_guide(guides[0])):
            self.statusBar().showMessage(self.MIRROR_HINT)
            return None
        return parts, (guides[0] if guides else None)

    def _add_mirrored(self, parts, plane) -> bool:
        origin, normal = plane
        return self._add_pattern("mirror", parts, lambda: patterns.mirrored(parts, origin, normal))

    def mirror_copy_selected(self, plane: str = "x") -> bool:
        """Mirrored copies of the selected parts across the selected
        sketch's plane or construction plane, or else the middle plane
        `plane` ("x", "y", "z")."""
        chosen = self._mirror_selection()
        if chosen is None:
            return False
        parts, guide = chosen
        return self._add_mirrored(
            parts, construct.plane_of(guide) if guide else patterns.middle_plane(plane)
        )

    def do_mirror_copy(self) -> None:
        chosen = self._mirror_selection()
        if chosen is None:
            return
        parts, guide = chosen
        if guide is not None:
            self.mirror_copy_selected()
            return
        values = ask_mirror(self)
        if values is None:
            return
        if values["plane"] != "face":
            self.mirror_copy_selected(values["plane"])
            return
        self._mirror_ids = [s.id for s in parts]
        self.start_tool("mirror_face")

    def _mirror_face_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        """A click on a flat face: mirror across it once the click is over.
        Anything else keeps the tool waiting."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            if is_reference(shape):
                raise BuildError(self.TOOL_PROMPTS["mirror_face"])
            patterns.plane_of_face(shape, face_index, scene.fit_clearances)
        except (KeyError, BuildError):
            self.statusBar().showMessage(self.TOOL_PROMPTS["mirror_face"])
            return
        self._clear_tool()
        self.sync()
        QTimer.singleShot(0, lambda: self.mirror_across_face(shape_id, face_index))

    def mirror_across_face(self, shape_id: str, face_index: int, part_ids=None) -> bool:
        """Mirrored copies of the parts `part_ids` (those selected when
        Mirror started) across the flat face of `shape_id` holding
        `face_index`. One undo step."""
        scene = self.document.scene
        ids = part_ids if part_ids is not None else getattr(self, "_mirror_ids", [])
        parts = [s for s in scene.shapes if s.id in ids and not is_reference(s)]
        try:
            face_part = scene.get(shape_id)
        except KeyError:
            return False
        if not parts:
            self.statusBar().showMessage(self.MIRROR_HINT)
            return False
        plane = self._attempt(
            "Cannot mirror", lambda: patterns.plane_of_face(face_part, face_index, scene.fit_clearances)
        )
        return plane is not None and self._add_mirrored(parts, plane)
