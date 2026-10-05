"""Construction guides (Expert mode's Construct menu): planes to draw on,
mirror across, split by and cut the view with, axes to turn around, and
points to make planes and axes through.

Every function returns a new guide shape (or, for the helpers, plain
numbers) and changes nothing passed in; the window adds the guide in one
undo step. A guide is drawn as mesh.guides describes and is never printed
(mesh.shapes.is_reference). A request that can't be met raises BuildError
with a plain message.

A guide is its transform: a plane's Z is the way it faces and an axis's Z
the way it points, and the origin is the middle of what is drawn (a
point's is the point), so moving or turning it in the Details panel moves
the guide.

All exact: a guide is placed by numbers worked out from the faces and
points clicked, not drawn by eye.
"""

import math
import re
import uuid
from dataclasses import dataclass

import numpy as np

from mesh import edges, features, guides, hardware, sketch, threads
from mesh.builders import BuildError
from mesh.modify import MOVE_LIMIT, flat_face
from mesh.scene import Shape
from mesh.shapes import (
    _grow_for_clearance,
    default_params,
    hole_clearance,
    is_reference,
    primitive_mesh,
    shape_geometry,
)
from mesh.solids import m3

GUIDE_COLOR = "#5fc4b8"
SNAP = 2.0  # a click this close to a face's corner (mm) lands on the corner

# The world's planes a new plane can start from (as New Sketch offers them).
NAMED_PLANES = [
    ("xy", "The workplane (flat, facing up)"),
    ("xz", "Upright, facing the front"),
    ("yz", "Upright, facing the right side"),
]

# The world's lines through 0 a plane can turn around.
WORLD_LINES = [
    ("x", "The left / right line"),
    ("y", "The forward / back line"),
    ("z", "The upright line"),
]
_LINE_DIRECTIONS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def is_guide(shape, kind: str | None = None) -> bool:
    """A construction guide (of `kind`, if given): not a sketch, not a part."""
    if shape.kind != "primitive" or shape.params.get("primitive") not in guides.KINDS:
        return False
    return kind is None or shape.params["primitive"] == kind


def is_flat_guide(shape) -> bool:
    """A sketch or a construction plane: a guide that stands for a plane."""
    return is_reference(shape) and shape.params.get("primitive") in ("sketch", "plane")


def next_name(shapes, label: str) -> str:
    """"Plane N" (or another label), one more than the highest in use."""
    pattern = re.compile(rf"{re.escape(label)} (\d+)")
    numbers = [int(m.group(1)) for s in shapes if (m := pattern.fullmatch(s.name))]
    return f"{label} {max(numbers, default=0) + 1}"


def _unit(vector, what: str) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float64)
    length = float(np.linalg.norm(v))
    if not math.isfinite(length) or length < 1e-9:
        raise BuildError(f"{what} has no direction.")
    return v / length


def _point(value) -> np.ndarray:
    p = np.asarray([float(v) for v in value], dtype=np.float64)
    if p.shape != (3,) or not np.isfinite(p).all():
        raise BuildError("Type ordinary numbers for the position.")
    if np.abs(p).max() > MOVE_LIMIT:
        raise BuildError(f"A guide can be at most {MOVE_LIMIT:g} mm from the middle of the workplane.")
    return p


def _guide(kind: str, frame: np.ndarray, params: dict, name: str) -> Shape:
    return Shape(id=uuid.uuid4().hex, name=name, kind="primitive",
                 params={"primitive": kind, **params}, transform=frame, color=GUIDE_COLOR)


# --- What a guide stands for -------------------------------------------------------


def plane_of(shape) -> tuple[np.ndarray, np.ndarray]:
    """(a point on it, the way it faces) for a construction plane or a
    sketch's plane."""
    if not is_flat_guide(shape):
        raise BuildError(f"{shape.name} is not a plane or a sketch.")
    frame = np.asarray(shape.transform, dtype=np.float64)
    return frame[:3, 3].copy(), _unit(frame[:3, 2], shape.name)


# Parts round about their own up line (their transform's Z through its
# origin): a revolve's is the line it was turned around.
ROUND_KINDS = ("cylinder", "cone", "tube", "torus", "sphere", "rounded_cylinder", "revolve",
               "screw_hole", "nut_trap", "insert_pocket", "magnet_pocket", "thread")
NOT_ROUND = ("{name} is not round about a line. Select a cylinder, cone, tube, ring, ball, "
             "thread, a round hardware hole or a revolved part.")


def axis_of(shape) -> tuple[np.ndarray, np.ndarray]:
    """(a point on it, the way it points) for a construction axis, or the
    line a round part is round about."""
    frame = np.asarray(shape.transform, dtype=np.float64)
    if not (is_guide(shape, "axis") or (shape.kind == "primitive" and shape.params.get("primitive") in ROUND_KINDS)):
        raise BuildError(NOT_ROUND.format(name=shape.name))
    return frame[:3, 3].copy(), _unit(frame[:3, 2], shape.name)


def point_of(shape) -> np.ndarray:
    """Where a construction point is."""
    if not is_guide(shape, "point"):
        raise BuildError(f"{shape.name} is not a point.")
    return np.asarray(shape.transform, dtype=np.float64)[:3, 3].copy()


def spot(shape, face_index: int, point, clearances: dict | None = None) -> np.ndarray:
    """Where a click on a part's face lands: the face's nearest corner if
    the click is within SNAP mm of it, otherwise the clicked point (on the
    face)."""
    if is_reference(shape):
        raise BuildError("Click a part, not a sketch or guide.")
    face = flat_face(shape, face_index, clearances)
    p = _point(point)
    p = p - float((p - face.centre) @ face.normal) * face.normal
    rings = [face.region] if face.region.geom_type == "Polygon" else list(face.region.geoms)
    corners = [np.asarray(ring.coords)[:-1] for poly in rings
               for ring in [poly.exterior, *poly.interiors]]
    corners = sketch.to_world(face.frame, np.vstack(corners))
    distances = np.linalg.norm(corners - p, axis=1)
    k = int(np.argmin(distances))
    return corners[k] if distances[k] <= SNAP else p


# --- Round surfaces ---------------------------------------------------------------
#
# A round part is drawn with narrow flat strips, but its own sizes say
# where its true round surface is. Each kind's outline is listed here in
# its own coordinates as (distance from its line, height) pieces, going
# anticlockwise round the solid, so the way out of the part is to the
# right of each line piece and away from the middle of each arc.

ROUND_ONLY = ("{name} is not a cylinder, cone, tube, ring, ball, thread, round hardware hole or "
              "revolved part, so where its round surfaces are can't be told from its own sizes.")
FLAT_HERE = "That face of {name} is flat, not round."
OFF_ROUND = "That spot on {name} is not on one of its round surfaces."
STRETCHED = "{name} is stretched, so its round surfaces can't be told from its own sizes."
NEAR_ROUND = 0.02  # a click this far off the true surface (times the part's size) is not on it
AGREE = math.cos(math.radians(30.0))  # the strip clicked faces within this of the true surface


@dataclass(frozen=True)
class RoundSpot:
    """Where a click on a round part lands on its true round surface."""

    point: np.ndarray   # on the round surface (world)
    facing: np.ndarray  # the way out of the part there (world)
    around: float       # how far the point is from the part's line (mm)
    piece: tuple        # the outline piece it is on: ("line", a, b) or ("arc", centre, radius, start, end)


def _line(a, b) -> tuple:
    return ("line", np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64))


def _arc(centre, radius: float, start: float = -180.0, end: float = 180.0) -> tuple:
    """An arc anticlockwise from `start` to `end` degrees (the solid inside it)."""
    return ("arc", np.asarray(centre, dtype=np.float64), float(radius), math.radians(start), math.radians(end))


def _round_pieces(shape, clearance: float) -> list:
    """The outline of a round part, in its own coordinates (see above)."""
    kind = shape.params.get("primitive")
    p = {**default_params(kind), **shape.params}
    c = clearance
    if kind in ("cylinder", "cone", "tube", "torus", "sphere", "rounded_cylinder"):
        # Grown and lowered as mesh.shapes draws a fitted Hole.
        if c > 0.0:
            p = _grow_for_clearance(kind, p, c)
        low = -c
        r, h = float(p["diameter"]) / 2.0, float(p.get("height", 0.0))
        if kind == "cylinder":
            bevel = min(float(p.get("chamfer", 0.0)), h - 1e-3, r - 1e-3)
            bevel = bevel if bevel > 1e-6 else 0.0
            pieces = [_line((0, 0), (r - bevel, 0)), _line((r - bevel, 0), (r, bevel)),
                      _line((r, bevel), (r, h)), _line((r, h), (0, h))]
        elif kind == "cone":
            pieces = [_line((0, 0), (r, 0)), _line((r, 0), (0, h))]
        elif kind == "tube":
            inner = max(r - float(p["wall"]), 0.01)
            pieces = [_line((inner, 0), (r, 0)), _line((r, 0), (r, h)), _line((r, h), (inner, h)),
                      _line((inner, h), (inner, 0))]
        elif kind == "rounded_cylinder":
            a = max(0.0, min(float(p["radius"]), min(2.0 * r, h) / 2.0))
            bevel = min(float(p.get("chamfer", 0.0)), h - 1e-3, r - 1e-3)
            pieces = [_line((0, 0), (r - a, 0)), _line((r, a), (r, h - a)), _line((r - a, h), (0, h))]
            if a > 1e-6:
                pieces += [_arc((r - a, a), a, -90.0, 0.0), _arc((r - a, h - a), a, 0.0, 90.0)]
            if bevel > 1e-6:
                pieces.append(_line((r - bevel, 0), (r, bevel)))
        else:
            # A ball and a ring are centred on their own drawing's middle.
            middle = float(primitive_mesh(kind, shape.params, c).bounds[:, 2].mean())
            if kind == "sphere":
                return [_arc((0, middle), r, -90.0, 90.0)]
            across = float(p["thickness"]) / 2.0
            return [_arc((r - across, middle), across)]
        up = np.array([0.0, low])
        return [_line(piece[1] + up, piece[2] + up) if piece[0] == "line" else ("arc", piece[1] + up, *piece[2:])
                for piece in pieces]
    if kind in ("screw_hole", "insert_pocket", "magnet_pocket", "nut_trap", "thread"):
        # Built with their clearance already in their sizes, from -c up.
        low, top = -c, None
        if kind == "screw_hole":
            depth = float(p["depth"])
            bore = hardware.dim("clearance", p["size"], "diameter") / 2.0 + c
            top = depth + c
            steps = [(bore, low)]
            if p["head"] == "countersunk":
                wide = hardware.dim("countersink", p["size"], "diameter") / 2.0 + c
                drop = min(wide - bore, depth)
                steps += [(bore, depth - drop), (wide - drop, depth - drop), (wide + c, top)]
            elif p["head"] == "counterbored":
                wide = hardware.dim("counterbore", p["size"], "diameter") / 2.0 + c
                start = max(depth - min(hardware.dim("counterbore", p["size"], "depth"), depth) - c, low)
                steps += [(bore, start), (wide, start), (wide, top)]
            else:
                steps.append((bore, top))
        elif kind == "nut_trap":
            depth = float(p["depth"])
            bore = hardware.dim("clearance", p["size"], "diameter") / 2.0 + c
            nut = min(hardware.dim("nut", p["size"], "depth"), depth)
            corner = (hardware.dim("nut", p["size"], "flats") / 2.0 + c) / math.cos(math.pi / 6.0)
            top = depth + c
            # The six-sided pocket for the nut is flat-sided, not round.
            steps = [(bore, low), (bore, depth - nut - c), (corner, depth - nut - c)]
            return [_line((0, low), steps[0])] + [_line(a, b) for a, b in zip(steps, steps[1:])] + [
                _line((corner, top), (0, top))]
        elif kind == "thread":
            # Only the crest of the thread and the plain part are round
            # about its line; the sloping sides wind round it.
            outer = float(p["diameter"]) / 2.0 + c
            top = float(p["height"]) + c
            steps = [(outer, low), (outer, top)]
        else:
            if kind == "insert_pocket":
                radius = hardware.dim("insert", p["size"], "diameter") / 2.0 + c
                top = hardware.dim("insert", p["size"], "depth") + c
            else:
                radius, top = float(p["diameter"]) / 2.0 + c, float(p["depth"]) + c
            steps = [(radius, low), (radius, top)]
        return ([_line((0, low), steps[0])] + [_line(a, b) for a, b in zip(steps, steps[1:])]
                + [_line(steps[-1], (0, top))])
    if kind == "revolve":
        return [_line(a, b) for a, b in _revolve_outline(p, c)
                if max(abs(a[0]), abs(b[0])) > 1e-9]
    raise BuildError(ROUND_ONLY.format(name=shape.name))


def _revolve_outline(p: dict, clearance: float) -> list:
    """A revolve's outline pieces as features.revolve turns it: (distance
    from its line, height) pairs, anticlockwise round the solid."""
    entities = p.get("entities", features.DEFAULT_REVOLVE)
    to_axis = np.linalg.inv(features.axis_frame(p.get("axis", features.DEFAULT_AXIS)))
    try:
        polygons = []
        for polygon in sketch.profile(entities).to_polygons():
            flat = np.column_stack([polygon, np.zeros(len(polygon)), np.ones(len(polygon))])
            polygons.append((flat @ to_axis.T)[:, [0, 2]])
    except sketch.SketchError as exc:
        raise BuildError(str(exc)) from exc
    if max(float(poly[:, 0].max()) for poly in polygons) <= 1e-6:
        polygons = [poly * (-1.0, 1.0) for poly in polygons]
    area = features._grow(m3.CrossSection(polygons, m3.FillRule.EvenOdd), clearance)
    low_x, low, high_x, high = area.bounds()
    if low_x < 0.0 < high_x:
        area = area ^ m3.CrossSection.square((high_x + 1.0, high - low + 2.0)).translate((0.0, low - 1.0))
    out = []
    for polygon in area.to_polygons():
        polygon = np.asarray(polygon, dtype=np.float64)
        out += list(zip(polygon, np.roll(polygon, -1, axis=0)))
    return out


def _nearest_on(piece, q) -> tuple[np.ndarray, np.ndarray]:
    """The point of an outline piece nearest q, and the way out there."""
    if piece[0] == "line":
        a, b = piece[1], piece[2]
        along = b - a
        length = float(np.linalg.norm(along))
        if length < 1e-12:
            return a, np.zeros(2)
        t = min(max(float((q - a) @ along) / length**2, 0.0), 1.0)
        return a + t * along, np.array([along[1], -along[0]]) / length
    centre, radius, start, end = piece[1:]
    angle = math.atan2(q[1] - centre[1], q[0] - centre[0])
    span = end - start
    if span < 2.0 * math.pi - 1e-9:
        past = (angle - start) % (2.0 * math.pi)
        if past > span:  # outside the arc: its nearer end
            angle = end if past - span < 2.0 * math.pi - past else start
    out = np.array([math.cos(angle), math.sin(angle)])
    return centre + radius * out, out


# --- Edges ------------------------------------------------------------------------


@dataclass(frozen=True)
class ClickedEdge:
    """The edge next to a click, found as Round an Edge finds it (the sharp
    edge of the clicked face nearest the click, followed on round corners
    of less than 30 degrees): the straight stretch of it the click is next
    to, and the whole run of edges it is part of."""

    start: np.ndarray
    end: np.ndarray
    run: np.ndarray  # the run's corner points, in order (world)
    closed: bool     # the run goes all the way round

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    @property
    def run_length(self) -> float:
        ends = np.roll(self.run, -1, axis=0) if self.closed else self.run[1:]
        return float(np.linalg.norm(ends - self.run[: len(ends)], axis=1).sum())

    @property
    def straight(self) -> bool:
        """The whole run is this one straight stretch."""
        return not self.closed and abs(self.run_length - self.length) < 1e-6


def edge_at(shape, face_index: int, point, clearances: dict | None = None) -> ClickedEdge:
    """The edge of a part next to a click on one of its faces (see
    ClickedEdge). A round edge is made of short straight pieces, so its
    straight stretch is the one piece clicked."""
    if is_reference(shape):
        raise BuildError("Click a part, not a sketch or guide.")
    tm = shape_geometry(shape, clearances)
    if len(tm.faces) > edges.FACE_LIMIT:
        raise BuildError("This part is too detailed to find its edges.")
    click = _point(point)
    run = edges.find_run(tm, face_index, click)
    points = tm.vertices[run.vertices]
    count = len(points)
    pieces = count if run.closed else count - 1
    starts = points[:pieces]
    ends = points[(np.arange(pieces) + 1) % count]
    along = ends - starts
    reach = np.clip(np.einsum("ij,ij->i", click - starts, along) / np.einsum("ij,ij->i", along, along), 0.0, 1.0)
    first = int(np.argmin(np.linalg.norm(starts + reach[:, None] * along - click, axis=1)))
    ways = along / np.linalg.norm(along, axis=1)[:, None]

    def onward(k: int, step: int) -> int | None:
        """The next piece along that goes on in the same straight line."""
        nxt = k + step
        if run.closed:
            nxt %= pieces
        elif not 0 <= nxt < pieces:
            return None
        return nxt if nxt != first and np.linalg.norm(np.cross(ways[k], ways[nxt])) < 1e-6 else None

    low = high = first
    while (step := onward(low, -1)) is not None:
        low = step
    while (step := onward(high, 1)) is not None and step != low:
        high = step
    return ClickedEdge(starts[low].copy(), ends[high].copy(), points.copy(), bool(run.closed))


def _pointing_up(direction) -> np.ndarray:
    """`direction` or its opposite: up where it can, else right, else back."""
    d = _unit(direction, "The edge")
    for axis in (2, 0, 1):
        if abs(d[axis]) > 1e-9:
            return d if d[axis] > 0 else -d
    return d


def round_spot(shape, face_index: int, point, clearances: dict | None = None) -> RoundSpot:
    """Where a click on a round part (a cylinder, cone, tube, ring, ball,
    thread, round hardware hole or revolved part) lands on its true round
    surface, worked out from its own sizes, and the way out of it there."""
    if is_reference(shape):
        raise BuildError("Click a part, not a sketch or guide.")
    if shape.kind != "primitive" or shape.params.get("primitive") not in ROUND_KINDS:
        raise BuildError(ROUND_ONLY.format(name=shape.name))
    frame = np.asarray(shape.transform, dtype=np.float64)
    turn = frame[:3, :3]
    if not np.allclose(turn.T @ turn, np.eye(3), atol=1e-6):
        raise BuildError(STRETCHED.format(name=shape.name))
    tm = shape_geometry(shape, clearances)
    if not 0 <= face_index < len(tm.faces):
        raise BuildError("Click on a face of a part.")
    pieces = [piece for piece in _round_pieces(shape, hole_clearance(shape, clearances))
              if piece[0] == "arc" or np.linalg.norm(piece[2] - piece[1]) > 1e-9]
    local = turn.T @ (_point(point) - frame[:3, 3])
    strip = turn.T @ tm.face_normals[face_index]
    across = math.hypot(local[0], local[1])
    angle = math.atan2(local[1], local[0]) if across > 1e-9 else 0.0
    out_dir = np.array([math.cos(angle), math.sin(angle), 0.0])
    q = np.array([across, local[2]])
    found = []
    for piece in pieces:
        at, way = _nearest_on(piece, q)
        found.append((float(np.linalg.norm(at - q)), piece, at, way))
    distance, piece, at, way = min(found, key=lambda f: f[0])
    facing = way[0] * out_dir + np.array([0.0, 0.0, way[1]])
    near = distance <= NEAR_ROUND * float(tm.extents.max()) + 1e-3 and float(facing @ strip) >= AGREE
    if near and abs(way[0]) < 1e-9:
        raise BuildError(FLAT_HERE.format(name=shape.name))
    if not near:
        side = abs(float(strip @ np.array([-out_dir[1], out_dir[0], 0.0])))
        if abs(float(strip[2])) > math.cos(math.radians(1.0)) or side > 0.9:
            raise BuildError(FLAT_HERE.format(name=shape.name))
        raise BuildError(OFF_ROUND.format(name=shape.name))
    world = frame[:3, 3] + turn @ np.array([at[0] * out_dir[0], at[0] * out_dir[1], at[1]])
    return RoundSpot(world, _unit(turn @ facing, shape.name), float(at[0]), piece)


# --- Planes -----------------------------------------------------------------------


def new_plane(origin, normal, size: float = guides.PLANE_SIZE, name: str = "Plane") -> Shape:
    """A plane through `origin`, facing `normal`, drawn `size` mm across
    around `origin`. Its X and Y follow the sketch convention (sketch.plane_frame)."""
    n = _unit(normal, "The plane")
    frame = sketch.plane_frame(n)
    frame[:3, 3] = _point(origin)
    return _guide("plane", frame, {"size": float(size)}, name)


def _face_size(face) -> float:
    """A square that shows a face's plane round the whole face."""
    x0, y0, x1, y1 = face.region.bounds
    return float(min(max(guides.PLANE_SIZE / 2.0, 1.25 * max(x1 - x0, y1 - y0)), 1000.0))


def plane_from_named(name: str, distance: float = 0.0, label: str = "Plane") -> Shape:
    """One of the world's planes (NAMED_PLANES), moved `distance` mm along
    the way it faces."""
    if name not in sketch.PLANES:
        raise ValueError(f"unknown plane {name!r}")
    normal = np.asarray(sketch.PLANES[name], dtype=np.float64)
    return new_plane(normal * float(distance), normal, 100.0, label)


def plane_from_face(shape, face_index: int, distance: float = 0.0,
                    clearances: dict | None = None, label: str = "Plane") -> Shape:
    """The plane of a part's flat face, moved `distance` mm out of it (into
    the part for less than 0), facing the way the face does."""
    if is_reference(shape):
        raise BuildError("Click a flat face of a part, not a sketch or guide.")
    face = flat_face(shape, face_index, clearances)
    return new_plane(face.centre + float(distance) * face.normal, face.normal, _face_size(face), label)


def plane_from_guide(guide, distance: float = 0.0, label: str = "Plane") -> Shape:
    """A plane parallel to a construction plane or sketch, `distance` mm
    along the way it faces."""
    origin, normal = plane_of(guide)
    size = float(guide.params.get("size", guides.PLANE_SIZE)) if is_guide(guide, "plane") else guides.PLANE_SIZE
    return new_plane(origin + float(distance) * normal, normal, size, label)


def turned(vector, direction, degrees: float) -> np.ndarray:
    """`vector` turned `degrees` around `direction` (anticlockwise seen from
    its tip)."""
    k = _unit(direction, "The line")
    v = np.asarray(vector, dtype=np.float64)
    a = math.radians(float(degrees))
    return v * math.cos(a) + np.cross(k, v) * math.sin(a) + k * float(k @ v) * (1.0 - math.cos(a))


def plane_at_angle(point, direction, degrees: float, label: str = "Plane") -> Shape:
    """A plane through the line through `point` along `direction`, turned
    `degrees` around it. At 0 it is the flattest plane holding the line, or
    for an upright line the one facing the front."""
    d = _unit(direction, "The line")
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([0.0, -1.0, 0.0])
    start = up - float(up @ d) * d
    degrees = float(degrees)
    if not math.isfinite(degrees):
        raise BuildError("Type an ordinary number for the angle.")
    return new_plane(point, turned(start / np.linalg.norm(start), d, degrees), 100.0, label)


def world_line(axis: str) -> tuple[np.ndarray, np.ndarray]:
    """One of the world's lines through 0 (WORLD_LINES): (point, direction)."""
    return np.zeros(3), np.asarray(_LINE_DIRECTIONS[axis], dtype=np.float64)


def midplane(a, b, size: float = guides.PLANE_SIZE, label: str = "Plane") -> Shape:
    """The plane halfway between two planes, each (a point on it, the way
    it faces): halfway across when they are parallel, otherwise through the
    line where they meet, splitting the angle between them. Mirroring one
    plane across it gives the other."""
    pa, na = _point(a[0]), _unit(a[1], "The first face")
    pb, nb = _point(b[0]), _unit(b[1], "The second face")
    k = na - nb
    if np.linalg.norm(k) < 1e-6:  # parallel, facing the same way
        normal, offset = na, float(na @ (pa + pb)) / 2.0
    else:
        length = float(np.linalg.norm(k))
        normal, offset = k / length, float(na @ pa - nb @ pb) / length
    middle = (pa + pb) / 2.0
    origin = middle - (float(normal @ middle) - offset) * normal
    return new_plane(origin, normal, size, label)


def face_of(shape, face_index: int, clearances: dict | None = None):
    """(the face's middle, the way it faces, a size to draw a plane round it)
    for a part's flat face."""
    if is_reference(shape):
        raise BuildError("Click a flat face of a part, not a sketch or guide.")
    face = flat_face(shape, face_index, clearances)
    return face.centre, face.normal, _face_size(face)


def plane_through_points(a, b, c, label: str = "Plane") -> Shape:
    """The plane through three points, facing up where it can (else to the
    front or right), drawn round them."""
    a, b, c = _point(a), _point(b), _point(c)
    n = np.cross(b - a, c - a)
    span = max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))
    if span < 1e-6 or np.linalg.norm(n) < 1e-6 * span * span:
        raise BuildError("The three points are in one line (or on top of each other), so they "
                         "don't fix a plane. Pick three points that make a triangle.")
    n = n / np.linalg.norm(n)
    for axis in (2, 1, 0):  # facing up, else the front, else the right
        if abs(n[axis]) > 1e-9:
            if (n[axis] < 0) if axis != 1 else (n[axis] > 0):
                n = -n
            break
    middle = (a + b + c) / 3.0
    size = float(min(max(guides.PLANE_SIZE / 2.0, 1.5 * span), 1000.0))
    return new_plane(middle, n, size, label)


SMOOTH_DEGREES = 10.0  # path pieces meeting at less than this are a curve, as in Pattern Along a Path


def path_of(guide) -> tuple[np.ndarray, bool]:
    """The one path a sketch draws (as Sweep and Pattern Along a Path take
    it), in the sketch's own plane: (points, closed), no point repeated."""
    if not (is_reference(guide) and guide.params.get("primitive") == "sketch"):
        raise BuildError(f"{guide.name} is not a sketch. Select a sketch whose curves make a path.")
    try:
        points, closed = sketch.single_path(guide.params.get("entities", []))
    except sketch.SketchError as exc:
        raise BuildError(str(exc)) from exc
    points = np.asarray(points, dtype=np.float64)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-9])
    points = points[keep]
    if closed and len(points) > 1 and np.linalg.norm(points[0] - points[-1]) < 1e-9:
        points = points[:-1]
    if len(points) < (3 if closed else 2):
        raise BuildError("The path is too short to put a plane on.")
    return points, closed


def path_length(points, closed: bool) -> float:
    ends = np.roll(points, -1, axis=0) if closed else points[1:]
    return float(np.linalg.norm(ends - points[: len(ends)], axis=1).sum())


def plane_along_path(guide, distance: float, from_end: bool = False, label: str = "Plane") -> Shape:
    """A plane square to the path a sketch draws, `distance` mm along it
    from where the path starts (or from its other end; round a closed
    path, the other way). On a curve, made of short straight pieces, the
    way it faces turns smoothly from one piece to the next."""
    points, closed = path_of(guide)
    if from_end:
        points = np.vstack([points[:1], points[:0:-1]]) if closed else points[::-1].copy()
    if closed:
        points = np.vstack([points, points[:1]])
    along = np.diff(points, axis=0)
    lengths = np.linalg.norm(along, axis=1)
    starts = np.concatenate([[0.0], np.cumsum(lengths)[:-1]])
    total = float(lengths.sum())
    distance = float(distance)
    if not math.isfinite(distance):
        raise BuildError("Type an ordinary number for the distance.")
    if distance < -1e-9 or distance > total + 1e-9:
        raise BuildError(f"The path is {total:.2f} mm long, so type a distance from 0 to {total:.2f} mm.")
    distance = min(max(distance, 0.0), total)
    pieces = len(lengths)
    k = min(max(int(np.searchsorted(starts, distance, side="right")) - 1, 0), pieces - 1)
    at = points[k] + (distance - starts[k]) / lengths[k] * along[k]
    headings = np.arctan2(along[:, 1], along[:, 0])
    heading = float(headings[k])
    middle = starts[k] + lengths[k] / 2.0
    other = k - 1 if distance < middle else k + 1
    if closed or 0 <= other < pieces:
        other %= pieces
        turn = math.remainder(float(headings[other] - headings[k]), 2.0 * math.pi)
        if abs(turn) <= math.radians(SMOOTH_DEGREES):
            heading += turn * abs(distance - middle) / ((lengths[k] + lengths[other]) / 2.0)
    frame = np.asarray(guide.transform, dtype=np.float64)
    origin = sketch.to_world(frame, at[None, :])[0]
    facing = frame[:3, :2] @ np.array([math.cos(heading), math.sin(heading)])
    return new_plane(origin, facing, guides.PLANE_SIZE, label)


def plane_touching(shape, face_index: int, point, clearances: dict | None = None,
                   label: str = "Plane") -> Shape:
    """The plane touching a round part's true round surface (see
    round_spot) where it was clicked, facing out of the part there."""
    found = round_spot(shape, face_index, point, clearances)
    extent = float(shape_geometry(shape, clearances).extents.max())
    size = float(min(max(guides.PLANE_SIZE / 2.0, 1.25 * extent), 1000.0))
    return new_plane(found.point, found.facing, size, label)


# --- Axes -------------------------------------------------------------------------


def new_axis(point, direction, length: float = guides.AXIS_LENGTH, name: str = "Axis") -> Shape:
    """An axis through `point` along `direction`, drawn `length` mm long with
    its middle at `point`."""
    frame = sketch.plane_frame(_unit(direction, "The axis"))
    frame[:3, 3] = _point(point)
    return _guide("axis", frame, {"length": float(length)}, name)


def _length_for(span: float) -> float:
    return float(min(max(guides.AXIS_LENGTH / 2.0, 1.5 * span), 2000.0))


def axis_of_round_part(shape, clearances: dict | None = None, label: str = "Axis") -> Shape:
    """The line a round part is round about, drawn through its length."""
    if is_reference(shape):
        raise BuildError(NOT_ROUND.format(name=shape.name))
    point, direction = axis_of(shape)
    tm = shape_geometry(shape, clearances)
    middle = tm.bounds.mean(axis=0)
    centre = point + float((middle - point) @ direction) * direction
    return new_axis(centre, direction, _length_for(float(np.linalg.norm(tm.extents))), label)


def axis_through_points(a, b, label: str = "Axis") -> Shape:
    """The axis from point `a` through point `b`."""
    a, b = _point(a), _point(b)
    if np.linalg.norm(b - a) < 1e-6:
        raise BuildError("The two points are on top of each other, so they don't fix a line. "
                         "Pick two different points.")
    return new_axis((a + b) / 2.0, b - a, _length_for(float(np.linalg.norm(b - a))), label)


def axis_square_to_face(shape, face_index: int, point, clearances: dict | None = None,
                        label: str = "Axis") -> Shape:
    """The axis through the point clicked on a flat face (on its corner if
    the click is that close), square to the face and pointing out of it."""
    at = spot(shape, face_index, point, clearances)
    _centre, normal, size = face_of(shape, face_index, clearances)
    return new_axis(at, normal, max(guides.AXIS_LENGTH / 2.0, size), label)


def axis_where_planes_meet(a, b, label: str = "Axis") -> Shape:
    """The line where two planes, each (a point on it, the way it faces),
    meet, drawn nearest the middle of their points."""
    pa, na = _point(a[0]), _unit(a[1], "The first plane")
    pb, nb = _point(b[0]), _unit(b[1], "The second plane")
    direction = np.cross(na, nb)
    if np.linalg.norm(direction) < 1e-6:
        raise BuildError("The two planes are parallel, so they never meet. Pick two planes at an angle.")
    direction = direction / np.linalg.norm(direction)
    # The point of the line nearest the middle of the two planes' points.
    middle = (pa + pb) / 2.0
    matrix = np.array([na, nb, direction])
    point = np.linalg.solve(matrix, [na @ pa, nb @ pb, direction @ middle])
    return new_axis(point, direction, guides.AXIS_LENGTH, label)


def axis_along_edge(shape, face_index: int, point, clearances: dict | None = None,
                    label: str = "Axis") -> Shape:
    """The axis along the straight stretch of edge next to a click (see
    edge_at), pointing up where it can (else right, else back)."""
    edge = edge_at(shape, face_index, point, clearances)
    return new_axis((edge.start + edge.end) / 2.0, _pointing_up(edge.end - edge.start),
                    _length_for(edge.length), label)


# --- Points -----------------------------------------------------------------------


def new_point(position, name: str = "Point") -> Shape:
    frame = np.eye(4)
    frame[:3, 3] = _point(position)
    return _guide("point", frame, {}, name)


def point_at_spot(shape, face_index: int, point, clearances: dict | None = None,
                  label: str = "Point") -> Shape:
    """A point where a click on a part's face lands (on the face's corner
    if the click is within SNAP mm of it)."""
    return new_point(spot(shape, face_index, point, clearances), label)


def point_at_middle(shape, face_index: int, clearances: dict | None = None, label: str = "Point") -> Shape:
    """A point at the middle of a flat face's area: the centre of a
    cylinder's end, or of a box's side."""
    centre, _normal, _size = face_of(shape, face_index, clearances)
    return new_point(centre, label)


def point_at_edge_end(shape, face_index: int, point, clearances: dict | None = None,
                      label: str = "Point") -> Shape:
    """A point on the end of the straight stretch of edge next to a click
    (see edge_at) that is nearer the click."""
    edge = edge_at(shape, face_index, point, clearances)
    click = _point(point)
    near_start = np.linalg.norm(edge.start - click) <= np.linalg.norm(edge.end - click)
    return new_point(edge.start if near_start else edge.end, label)
