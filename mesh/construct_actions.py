"""The window's Expert mode Construct menu: construction planes and axes.

Mixed into MeshWindow through ExpertActions. The geometry is in
mesh.construct; this is only the wiring: ask, collect the clicks, then add
the guide as one undo step. A guide never changes a part, so a refused or
cancelled tool leaves no undo step behind.
"""

from PySide6.QtCore import QTimer

from mesh import construct, guides
from mesh.builders import BuildError
from mesh.panels import run_form
from mesh.shapes import is_reference

DISTANCE = {"min": -10000.0, "max": 10000.0}


def plane_distance_fields(selected=None):
    sources = ([("selected", f"The selected {selected}")] if selected else []) + [
        ("face", "A flat face you click next"),
        *construct.NAMED_PLANES,
    ]
    return [
        ("source", "Start from", sources[0][0], {"choices": sources}),
        ("distance", "Distance along the way it faces (mm)", 10.0, DISTANCE),
    ]


PLANE_DISTANCE_NOTE = (
    "Adds a construction plane parallel to a face, a sketch, another plane or one of the "
    "workplane's planes, moved the distance you type along the way it faces (less than 0 "
    "goes the other way). Sketch on it, mirror across it or split a part with it."
)


def ask_plane_distance(parent, selected=None) -> dict | None:
    return run_form(parent, "Plane at a Distance", plane_distance_fields(selected), note=PLANE_DISTANCE_NOTE)


def plane_angle_fields(lines):
    return [
        ("line", "Turn around", lines[0][0], {"choices": lines}),
        ("angle", "Angle (degrees)", 45.0, {"min": -360.0, "max": 360.0}),
    ]


PLANE_ANGLE_NOTE = (
    "Adds a construction plane through a line, turned around it by the angle. At 0 the plane "
    "lies as flat as it can along the line; around the upright line, 0 faces the front."
)


def ask_plane_angle(parent, lines) -> dict | None:
    return run_form(parent, "Plane at an Angle", plane_angle_fields(lines), note=PLANE_ANGLE_NOTE)


class ConstructActions:
    """Mixed into MeshWindow through ExpertActions."""

    CONSTRUCT_CLICK_TOOLS = ("plane_face", "midplane", "plane_points", "axis_points", "axis_face")
    CONSTRUCT_TOOL_PROMPTS = {
        "plane_face": "Click a flat face of a part for the new plane. Esc cancels.",
        "midplane": "Click the first of two flat faces; the plane goes halfway between them. Esc cancels.",
        "midplane_second": "Now click the second flat face.",
        "plane_points": "Click the first of three points on parts (near a corner, it lands on the corner). Esc cancels.",
        "plane_points_second": "Now click the second point.",
        "plane_points_third": "Now click the third point.",
        "axis_points": "Click the first of two points on parts (near a corner, it lands on the corner). Esc cancels.",
        "axis_points_second": "Now click the second point; the axis points towards it.",
        "axis_face": "Click a point on a flat face of a part for the axis square to it. Esc cancels.",
    }
    CONSTRUCT_CLICK_HANDLERS = {
        "plane_face": "_plane_face_picked",
        "midplane": "_midplane_picked",
        "plane_points": "_plane_point_picked",
        "axis_points": "_axis_point_picked",
        "axis_face": "_axis_face_picked",
    }

    # Which later prompt each click tool shows after each click so far.
    _STAGED = {
        "midplane": ("midplane", "midplane_second"),
        "plane_points": ("plane_points", "plane_points_second", "plane_points_third"),
        "axis_points": ("axis_points", "axis_points_second"),
    }

    def _construct_prompt(self) -> str | None:
        """The prompt for a construct tool part way through its clicks."""
        stages = self._STAGED.get(self.tool)
        if stages is None:
            return None
        picks = getattr(self, "_construct_picks", [])
        return self.TOOL_PROMPTS[stages[min(len(picks), len(stages) - 1)]]

    def _start_construct_tool(self, tool: str) -> None:
        self.start_tool(tool)
        self._construct_picks = []

    def _add_guide(self, label: str, build) -> bool:
        """Add the guide (or list of guides) `build` makes as one undo step
        and select it; none if it refuses."""
        made = self._attempt("Cannot add the guide", build)
        if made is None:
            return False
        made = made if isinstance(made, list) else [made]
        self.document.snapshot(label)
        for guide in made:
            self.document.scene.add(guide)
        self.document.scene.select([g.id for g in made])
        self.sync()
        return True

    def _next_name(self, label: str) -> str:
        return construct.next_name(self.document.scene.shapes, label)

    def _selected_flat_guides(self):
        return [s for s in self._picked() if construct.is_flat_guide(s)]

    def _finish_construct(self, then) -> None:
        """The last click is in: stop waiting, and add the guide once the
        click is over (a refusal's message would otherwise open during it)."""
        self._clear_tool()
        self.sync()
        QTimer.singleShot(0, then)

    def _clicked_part(self, shape_id: str, face_index: int):
        """The part clicked, if the click landed on a flat face of one;
        None (and the prompt again) otherwise."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            if is_reference(shape):
                raise BuildError(self._tool_prompt())
            construct.face_of(shape, face_index, scene.fit_clearances)
        except (KeyError, BuildError):
            self.statusBar().showMessage(self._tool_prompt())
            return None
        return shape

    # --- Plane at a distance ---------------------------------------------------------

    def plane_at_distance_selected(self, source: str = "xy", distance: float = 10.0) -> bool:
        """A plane `distance` mm from the selected sketch or plane
        ("selected") or one of the world's planes ("xy", "xz", "yz")."""
        name = self._next_name("Plane")
        if source == "selected":
            chosen = self._selected_flat_guides()
            if len(chosen) != 1:
                self.statusBar().showMessage("Select one sketch or plane to start from.")
                return False
            return self._add_guide("add plane", lambda: construct.plane_from_guide(chosen[0], distance, name))
        return self._add_guide("add plane", lambda: construct.plane_from_named(source, distance, name))

    def plane_from_face(self, shape_id: str, face_index: int, distance: float = 0.0) -> bool:
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        return self._add_guide("add plane", lambda: construct.plane_from_face(
            shape, face_index, distance, scene.fit_clearances, self._next_name("Plane")))

    def do_plane_at_distance(self) -> None:
        chosen = self._selected_flat_guides()
        selected = chosen[0].name if len(chosen) == 1 else None
        values = ask_plane_distance(self, selected)
        if values is None:
            return
        if values["source"] != "face":
            self.plane_at_distance_selected(values["source"], values["distance"])
            return
        self._plane_distance = values["distance"]
        self._start_construct_tool("plane_face")

    def _plane_face_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        if self._clicked_part(shape_id, face_index) is None:
            return
        distance = getattr(self, "_plane_distance", 0.0)
        self._finish_construct(lambda: self.plane_from_face(shape_id, face_index, distance))

    # --- Plane at an angle -----------------------------------------------------------

    def _selected_axes(self):
        return [s for s in self._picked() if construct.is_guide(s, "axis")]

    def plane_at_angle_selected(self, line: str = "z", angle: float = 45.0) -> bool:
        """A plane through the selected construction axis ("selected") or
        one of the world's lines through 0 ("x", "y", "z"), turned `angle`
        degrees around it."""
        if line == "selected":
            chosen = self._selected_axes()
            if len(chosen) != 1:
                self.statusBar().showMessage("Select one axis to turn the plane around.")
                return False
            point, direction = construct.axis_of(chosen[0])
        else:
            point, direction = construct.world_line(line)
        name = self._next_name("Plane")
        return self._add_guide("add plane", lambda: construct.plane_at_angle(point, direction, angle, name))

    def do_plane_at_angle(self) -> None:
        chosen = self._selected_axes()
        lines = ([("selected", f"The selected {chosen[0].name}")] if len(chosen) == 1 else []) + construct.WORLD_LINES
        values = ask_plane_angle(self, lines)
        if values is not None:
            self.plane_at_angle_selected(values["line"], values["angle"])

    # --- Midplane ----------------------------------------------------------------------

    MIDPLANE_HINT = "Select two sketches or planes, or click two flat faces, for the plane halfway between."

    def midplane_selected(self) -> bool:
        """The plane halfway between the two selected sketches or planes."""
        chosen = self._selected_flat_guides()
        if len(chosen) != 2:
            self.statusBar().showMessage(self.MIDPLANE_HINT)
            return False
        a, b = chosen
        size = max(float(g.params.get("size", 0.0)) for g in chosen) or guides.PLANE_SIZE
        name = self._next_name("Plane")
        return self._add_guide("add plane", lambda: construct.midplane(
            construct.plane_of(a), construct.plane_of(b), size, name))

    def midplane_of_faces(self, first, second) -> bool:
        """The plane halfway between two clicked faces, each (part id,
        triangle clicked)."""
        scene = self.document.scene

        def build():
            faces = [construct.face_of(scene.get(i), f, scene.fit_clearances) for i, f in (first, second)]
            size = max(face[2] for face in faces)
            return construct.midplane(faces[0][:2], faces[1][:2], size, self._next_name("Plane"))

        try:
            scene.get(first[0]), scene.get(second[0])
        except KeyError:
            return False
        return self._add_guide("add plane", build)

    def do_midplane(self) -> None:
        if len(self._selected_flat_guides()) == 2:
            self.midplane_selected()
            return
        self._start_construct_tool("midplane")

    def _midplane_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        if self._clicked_part(shape_id, face_index) is None:
            return
        self._construct_picks.append((shape_id, face_index))
        if len(self._construct_picks) < 2:
            self.statusBar().showMessage(self._tool_prompt())
            return
        first, second = self._construct_picks
        self._finish_construct(lambda: self.midplane_of_faces(first, second))

    # --- Plane through three points -----------------------------------------------------

    def plane_through_spots(self, points) -> bool:
        a, b, c = points
        name = self._next_name("Plane")
        return self._add_guide("add plane", lambda: construct.plane_through_points(a, b, c, name))

    def do_plane_through_points(self) -> None:
        self._start_construct_tool("plane_points")

    def _plane_point_picked(self, shape_id: str, face_index: int, point=None) -> None:
        shape = self._clicked_part(shape_id, face_index)
        if shape is None:
            return
        try:
            spot = construct.spot(shape, face_index, point, self.document.scene.fit_clearances)
        except BuildError:
            self.statusBar().showMessage(self._tool_prompt())
            return
        self._construct_picks.append(spot)
        if len(self._construct_picks) < 3:
            self.statusBar().showMessage(self._tool_prompt())
            return
        points = list(self._construct_picks)
        self._finish_construct(lambda: self.plane_through_spots(points))

    # --- Axes ------------------------------------------------------------------------

    AXIS_ROUND_HINT = "Select a round part (a cylinder, cone, tube, ring, ball or revolved part) first."

    def axis_of_round_parts(self) -> bool:
        """An axis along the middle of each selected round part, together
        as one undo step."""
        parts = [s for s in self._picked() if not is_reference(s)]
        if not parts:
            self.statusBar().showMessage(self.AXIS_ROUND_HINT)
            return False
        scene = self.document.scene

        def build():
            made = []
            for part in parts:
                name = construct.next_name(scene.shapes + made, "Axis")
                made.append(construct.axis_of_round_part(part, scene.fit_clearances, name))
            return made

        return self._add_guide("add axis", build)

    def do_axis_round_part(self) -> None:
        self.axis_of_round_parts()

    def axis_through_spots(self, points) -> bool:
        a, b = points
        name = self._next_name("Axis")
        return self._add_guide("add axis", lambda: construct.axis_through_points(a, b, name))

    def do_axis_two_points(self) -> None:
        self._start_construct_tool("axis_points")

    def _axis_point_picked(self, shape_id: str, face_index: int, point=None) -> None:
        shape = self._clicked_part(shape_id, face_index)
        if shape is None:
            return
        try:
            spot = construct.spot(shape, face_index, point, self.document.scene.fit_clearances)
        except BuildError:
            self.statusBar().showMessage(self._tool_prompt())
            return
        self._construct_picks.append(spot)
        if len(self._construct_picks) < 2:
            self.statusBar().showMessage(self._tool_prompt())
            return
        points = list(self._construct_picks)
        self._finish_construct(lambda: self.axis_through_spots(points))

    def axis_square_to(self, shape_id: str, face_index: int, point) -> bool:
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        name = self._next_name("Axis")
        return self._add_guide("add axis", lambda: construct.axis_square_to_face(
            shape, face_index, point, scene.fit_clearances, name))

    def do_axis_square_to_face(self) -> None:
        self._start_construct_tool("axis_face")

    def _axis_face_picked(self, shape_id: str, face_index: int, point=None) -> None:
        if self._clicked_part(shape_id, face_index) is None:
            return
        self._finish_construct(lambda: self.axis_square_to(shape_id, face_index, point))

    AXIS_PLANES_HINT = "Select two sketches or planes at an angle; the axis runs where they meet."

    def axis_of_two_planes(self) -> bool:
        chosen = self._selected_flat_guides()
        if len(chosen) != 2:
            self.statusBar().showMessage(self.AXIS_PLANES_HINT)
            return False
        a, b = (construct.plane_of(g) for g in chosen)
        name = self._next_name("Axis")
        return self._add_guide("add axis", lambda: construct.axis_where_planes_meet(a, b, name))

    def do_axis_two_planes(self) -> None:
        self.axis_of_two_planes()
