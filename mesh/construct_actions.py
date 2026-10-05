"""The window's Expert mode Construct menu: construction planes, axes and
points.

Mixed into MeshWindow through ExpertActions. The geometry is in
mesh.construct; this is only the wiring: ask, collect the clicks, then add
the guide as one undo step. A guide never changes a part, so a refused or
cancelled tool leaves no undo step behind.
"""

from PySide6.QtCore import QTimer

from mesh import construct, guides
from mesh.builders import BuildError
from mesh.history import replayable
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


PATH_ENDS = [("start", "The end the path starts from"), ("end", "The other end")]


def _at(point) -> str:
    return f"{round(float(point[0]), 2):g}, {round(float(point[1]), 2):g}"


def path_ends(points, closed: bool):
    """The form's choices of where to measure along a path from."""
    if closed:
        return [("start", f"Its point at {_at(points[0])} in the sketch, going one way round"),
                ("end", f"Its point at {_at(points[0])} in the sketch, going the other way round")]
    return [("start", f"The end at {_at(points[0])} in the sketch"),
            ("end", f"The end at {_at(points[-1])} in the sketch")]


def plane_path_fields(ends=None, length: float = 10000.0):
    ends = ends or PATH_ENDS
    return [
        ("distance", "Distance along the path (mm)", 0.0, {"min": 0.0, "max": max(float(length), 0.01)}),
        ("from", "Measured from", ends[0][0], {"choices": ends}),
    ]


def plane_path_note(length: float) -> str:
    return (f"Adds a construction plane square to the sketch's path, the distance you type along it. "
            f"The path is {length:.2f} mm long. Curves are followed in short straight pieces; on a "
            "curve the plane turns smoothly from one piece to the next.")


def ask_plane_path(parent, ends, length: float) -> dict | None:
    return run_form(parent, "Plane Along a Path", plane_path_fields(ends, length), note=plane_path_note(length))


class ConstructActions:
    """Mixed into MeshWindow through ExpertActions."""

    CONSTRUCT_CLICK_TOOLS = ("plane_face", "midplane", "plane_points", "plane_round", "axis_points",
                             "axis_face", "axis_edge", "point_spot", "point_middle", "point_edge")
    CONSTRUCT_TOOL_PROMPTS = {
        "plane_face": "Click a flat face of a part for the new plane. Esc cancels.",
        "plane_round": "Click the round side of a cylinder, cone, ball, ring or other round part; the "
                       "plane touches it there. Esc cancels.",
        "midplane": "Click the first of two flat faces; the plane goes halfway between them. Esc cancels.",
        "midplane_second": "Now click the second flat face.",
        "plane_points": "Click the first of three points on parts (near a corner, it lands on the corner). Esc cancels.",
        "plane_points_second": "Now click the second point.",
        "plane_points_third": "Now click the third point.",
        "axis_points": "Click the first of two points on parts (near a corner, it lands on the corner). Esc cancels.",
        "axis_points_second": "Now click the second point; the axis points towards it.",
        "axis_face": "Click a point on a flat face of a part for the axis square to it. Esc cancels.",
        "axis_edge": "Click a face of a part next to a straight edge; the axis runs along that edge. "
                     "Esc cancels.",
        "point_spot": "Click a part where the point goes (near a corner, it lands on the corner). Esc cancels.",
        "point_middle": "Click a flat face of a part; the point goes at its middle. Esc cancels.",
        "point_edge": "Click a face of a part next to an edge, nearer the end where the point goes. "
                      "Esc cancels.",
    }
    CONSTRUCT_CLICK_HANDLERS = {
        "plane_face": "_plane_face_picked",
        "midplane": "_midplane_picked",
        "plane_points": "_plane_point_picked",
        "plane_round": "_plane_round_picked",
        "axis_points": "_axis_point_picked",
        "axis_face": "_axis_face_picked",
        "axis_edge": "_axis_edge_picked",
        "point_spot": "_point_spot_picked",
        "point_middle": "_point_middle_picked",
        "point_edge": "_point_edge_picked",
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

    def _selected_points(self):
        """The selected construction points, in the order they were picked."""
        return [s for s in self._picked() if construct.is_guide(s, "point")]

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

    def _clicked_edge(self, shape_id: str, face_index: int, point):
        """The part clicked, if the click was next to an edge of it; None
        (and why, with the prompt again) otherwise."""
        shape = self._clicked_part(shape_id, face_index)
        if shape is None:
            return None
        try:
            construct.edge_at(shape, face_index, point, self.document.scene.fit_clearances)
        except BuildError as exc:
            self.statusBar().showMessage(f"{exc} {self._tool_prompt()}")
            return None
        return shape

    # --- Plane at a distance ---------------------------------------------------------

    @replayable()
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

    @replayable(("shape_id", "face_index"))
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

    @replayable()
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

    @replayable()
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

    @replayable("first", "second")
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
        chosen = self._selected_points()
        if len(chosen) == 3:
            self.plane_through_spots([construct.point_of(p) for p in chosen])
            return
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

    # --- Plane along a path -----------------------------------------------------------

    PATH_HINT = "Select one sketch whose curves make a path; the plane goes square to the path."

    def _selected_path(self):
        chosen = self._picked()
        if len(chosen) != 1 or not (is_reference(chosen[0]) and chosen[0].params.get("primitive") == "sketch"):
            self.statusBar().showMessage(self.PATH_HINT)
            return None
        return chosen[0]

    @replayable()
    def plane_along_path_selected(self, distance: float = 0.0, from_end: bool = False) -> bool:
        """A plane square to the selected sketch's path, `distance` mm along
        it from where it starts (or from its other end)."""
        guide = self._selected_path()
        if guide is None:
            return False
        name = self._next_name("Plane")
        return self._add_guide("add plane", lambda: construct.plane_along_path(guide, distance, from_end, name))

    def do_plane_along_path(self) -> None:
        guide = self._selected_path()
        if guide is None:
            return
        found = self._attempt("Cannot add the guide", lambda: construct.path_of(guide))
        if found is None:
            return
        points, closed = found
        values = ask_plane_path(self, path_ends(points, closed), construct.path_length(points, closed))
        if values is not None:
            self.plane_along_path_selected(values["distance"], values["from"] == "end")

    # --- Plane touching a round part ------------------------------------------------

    @replayable(("shape_id", "face_index"))
    def plane_touching_round(self, shape_id: str, face_index: int, point) -> bool:
        """The plane touching a round part's true round surface where it
        was clicked."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        name = self._next_name("Plane")
        return self._add_guide("add plane", lambda: construct.plane_touching(
            shape, face_index, point, scene.fit_clearances, name))

    def do_plane_touching(self) -> None:
        self._start_construct_tool("plane_round")

    def _plane_round_picked(self, shape_id: str, face_index: int, point=None) -> None:
        shape = self._clicked_part(shape_id, face_index)
        if shape is None:
            return
        try:
            construct.round_spot(shape, face_index, point, self.document.scene.fit_clearances)
        except BuildError as exc:
            # Not a round surface: say why, and keep waiting for one.
            self.statusBar().showMessage(f"{exc} {self._tool_prompt()}")
            return
        self._finish_construct(lambda: self.plane_touching_round(shape_id, face_index, point))

    # --- Axes ------------------------------------------------------------------------

    AXIS_ROUND_HINT = "Select a round part (a cylinder, cone, tube, ring, ball or revolved part) first."

    @replayable()
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
        chosen = self._selected_points()
        if len(chosen) == 2:
            self.axis_through_spots([construct.point_of(p) for p in chosen])
            return
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

    @replayable(("shape_id", "face_index"))
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

    @replayable(("shape_id", "face_index"))
    def axis_along_edge(self, shape_id: str, face_index: int, point) -> bool:
        """The axis along the straight edge next to a click on a face."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        name = self._next_name("Axis")
        return self._add_guide("add axis", lambda: construct.axis_along_edge(
            shape, face_index, point, scene.fit_clearances, name))

    def do_axis_along_edge(self) -> None:
        self._start_construct_tool("axis_edge")

    def _axis_edge_picked(self, shape_id: str, face_index: int, point=None) -> None:
        if self._clicked_edge(shape_id, face_index, point) is None:
            return
        self._finish_construct(lambda: self.axis_along_edge(shape_id, face_index, point))

    AXIS_PLANES_HINT = "Select two sketches or planes at an angle; the axis runs where they meet."

    @replayable()
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

    # --- Points ----------------------------------------------------------------------

    @replayable(("shape_id", "face_index"))
    def point_at(self, shape_id: str, face_index: int, point, middle: bool = False) -> bool:
        """A point where a click on a face landed, or at the face's middle."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        name = self._next_name("Point")
        if middle:
            return self._add_guide("add point", lambda: construct.point_at_middle(
                shape, face_index, scene.fit_clearances, name))
        return self._add_guide("add point", lambda: construct.point_at_spot(
            shape, face_index, point, scene.fit_clearances, name))

    def do_point_at_spot(self) -> None:
        self._start_construct_tool("point_spot")

    def do_point_at_middle(self) -> None:
        self._start_construct_tool("point_middle")

    def _point_spot_picked(self, shape_id: str, face_index: int, point=None) -> None:
        if self._clicked_part(shape_id, face_index) is None:
            return
        self._finish_construct(lambda: self.point_at(shape_id, face_index, point))

    def _point_middle_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        if self._clicked_part(shape_id, face_index) is None:
            return
        self._finish_construct(lambda: self.point_at(shape_id, face_index, None, middle=True))

    @replayable(("shape_id", "face_index"))
    def point_at_edge_end(self, shape_id: str, face_index: int, point) -> bool:
        """A point on the end of the edge next to a click that is nearer it."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        name = self._next_name("Point")
        return self._add_guide("add point", lambda: construct.point_at_edge_end(
            shape, face_index, point, scene.fit_clearances, name))

    def do_point_at_edge_end(self) -> None:
        self._start_construct_tool("point_edge")

    def _point_edge_picked(self, shape_id: str, face_index: int, point=None) -> None:
        if self._clicked_edge(shape_id, face_index, point) is None:
            return
        self._finish_construct(lambda: self.point_at_edge_end(shape_id, face_index, point))
