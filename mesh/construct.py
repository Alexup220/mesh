"""Construction guides (Expert mode's Construct menu): planes to draw on,
mirror across, split by and cut the view with, and axes to turn around.

Every function returns a new guide shape (or, for the helpers, plain
numbers) and changes nothing passed in; the window adds the guide in one
undo step. A guide is drawn as mesh.guides describes and is never printed
(mesh.shapes.is_reference). A request that can't be met raises BuildError
with a plain message.

A guide is its transform: a plane's Z is the way it faces and an axis's Z
the way it points, and the origin is the middle of what is drawn, so
moving or turning it in the Details panel moves the guide.

All exact: a guide is placed by numbers worked out from the faces and
points clicked, not drawn by eye.
"""

import math
import re
import uuid

import numpy as np

from mesh import guides, sketch
from mesh.builders import BuildError
from mesh.modify import MOVE_LIMIT, flat_face
from mesh.scene import Shape
from mesh.shapes import is_reference, shape_geometry

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
               "screw_hole", "nut_trap", "insert_pocket", "magnet_pocket")
NOT_ROUND = ("{name} is not round about a line. Select a cylinder, cone, tube, ring, ball, "
             "a round hardware hole or a revolved part.")


def axis_of(shape) -> tuple[np.ndarray, np.ndarray]:
    """(a point on it, the way it points) for a construction axis, or the
    line a round part is round about."""
    frame = np.asarray(shape.transform, dtype=np.float64)
    if not (is_guide(shape, "axis") or (shape.kind == "primitive" and shape.params.get("primitive") in ROUND_KINDS)):
        raise BuildError(NOT_ROUND.format(name=shape.name))
    return frame[:3, 3].copy(), _unit(frame[:3, 2], shape.name)


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
