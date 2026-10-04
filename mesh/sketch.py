"""Sketches: flat outlines drawn on a plane, the start of Extrude, Revolve,
Sweep and Loft.

A sketch is a list of curves in its own flat coordinates (millimetres, X to
the right, Y up), plus the transform of the shape that holds it, which puts
that plane in the world. Its local Z points out of the plane, the side the
sketch faces.

Curves ("entities") are plain dicts, so a project file stores them as they
are:

    line       {"type": "line", "start": [x, y], "end": [x, y]}
    rectangle  {"type": "rectangle", "corner": [x, y], "width": w, "height": h}
    circle     {"type": "circle", "centre": [x, y], "diameter": d}
    arc        {"type": "arc", "centre": [x, y], "radius": r, "start": a0, "end": a1}
               (degrees, anticlockwise from start to end)
    polygon    {"type": "polygon", "centre": [x, y], "sides": n, "radius": r, "angle": a}
               (radius to a corner; angle turns the first corner)
    spline     {"type": "spline", "points": [[x, y], ...], "closed": bool}
               (a smooth curve through every point)

There are no constraints between curves (the binding spec leaves them out):
every curve is placed by its own numbers. Closed curves (rectangle, circle,
polygon, closed spline) are outlines by themselves; lines, arcs and open
splines whose ends meet (within JOIN_TOLERANCE) chain into outlines or into
an open path. Outlines fill even-odd: an outline inside another is a hole
in it, as in a washer.

Curves become straight pieces here (a full circle is SEGMENTS pieces, the
same as a cylinder), which is as exact as the rest of the app.

This module never imports mesh.scene or mesh.shapes, so the shape code can
import it.
"""

import math

import numpy as np
import trimesh

from mesh.solids import m3

SEGMENTS = 64          # straight pieces in a full circle
SPLINE_STEPS = 16      # straight pieces between two spline points
JOIN_TOLERANCE = 0.01  # mm: curve ends this close count as meeting
MIN_SIZE = 1e-3        # mm: anything smaller is treated as nothing

ENTITY_TYPES = ("line", "rectangle", "circle", "arc", "polygon", "spline")
CLOSED_TYPES = ("rectangle", "circle", "polygon")


class SketchError(ValueError):
    """A sketch can't do what was asked; the message says why, plainly."""


# --- Checking curves -------------------------------------------------------------


def _point(value, what: str) -> list[float]:
    try:
        x, y = (float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise SketchError(f"The {what} needs two numbers.") from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise SketchError(f"The {what} must be ordinary numbers.")
    return [x, y]


def _number(value, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SketchError(f"The {what} must be a number.") from exc
    if not math.isfinite(number):
        raise SketchError(f"The {what} must be an ordinary number.")
    return number


def _size(value, what: str) -> float:
    number = _number(value, what)
    if number < MIN_SIZE:
        raise SketchError(f"The {what} must be more than 0 mm.")
    return number


def clean_entity(entity) -> dict:
    """A checked copy of one curve, with plain floats, ready to store.
    Raises SketchError, in plain words, for a curve that can't be drawn."""
    if not isinstance(entity, dict) or entity.get("type") not in ENTITY_TYPES:
        raise SketchError("That is not a curve this sketch knows how to draw.")
    kind = entity["type"]
    if kind == "line":
        start, end = _point(entity.get("start"), "start point"), _point(entity.get("end"), "end point")
        if math.dist(start, end) < MIN_SIZE:
            raise SketchError("A line needs two different end points.")
        return {"type": "line", "start": start, "end": end}
    if kind == "rectangle":
        return {
            "type": "rectangle",
            "corner": _point(entity.get("corner"), "corner"),
            "width": _size(entity.get("width"), "width"),
            "height": _size(entity.get("height"), "height"),
        }
    if kind == "circle":
        return {
            "type": "circle",
            "centre": _point(entity.get("centre"), "centre"),
            "diameter": _size(entity.get("diameter"), "diameter"),
        }
    if kind == "arc":
        start, end = _number(entity.get("start"), "start angle"), _number(entity.get("end"), "end angle")
        if _sweep(start, end) < 1e-6:
            raise SketchError("An arc needs different start and end angles.")
        return {
            "type": "arc",
            "centre": _point(entity.get("centre"), "centre"),
            "radius": _size(entity.get("radius"), "radius"),
            "start": start,
            "end": end,
        }
    if kind == "polygon":
        try:
            sides = int(entity.get("sides"))
        except (TypeError, ValueError) as exc:
            raise SketchError("A polygon needs a whole number of sides.") from exc
        if not 3 <= sides <= 1000:
            raise SketchError("A polygon needs between 3 and 1000 sides.")
        return {
            "type": "polygon",
            "centre": _point(entity.get("centre"), "centre"),
            "sides": sides,
            "radius": _size(entity.get("radius"), "radius"),
            "angle": _number(entity.get("angle", 0.0), "angle"),
        }
    # spline
    raw = entity.get("points")
    if not isinstance(raw, (list, tuple)):
        raise SketchError("A spline needs a list of points.")
    points = []
    for value in raw:
        point = _point(value, "spline point")
        if not points or math.dist(points[-1], point) >= MIN_SIZE:
            points.append(point)
    closed = bool(entity.get("closed", False))
    if closed and len(points) > 1 and math.dist(points[0], points[-1]) < MIN_SIZE:
        points.pop()
    if len(points) < (3 if closed else 2):
        raise SketchError(
            "A closed spline needs at least 3 different points." if closed
            else "A spline needs at least 2 different points."
        )
    return {"type": "spline", "points": points, "closed": closed}


def clean_entities(entities) -> list[dict]:
    if not isinstance(entities, (list, tuple)):
        raise SketchError("A sketch's curves must be a list.")
    return [clean_entity(e) for e in entities]


# --- Curves as straight pieces ---------------------------------------------------


def _sweep(start: float, end: float) -> float:
    """Degrees an arc turns going anticlockwise from `start` to `end`."""
    return (end - start) % 360.0


def _circle_points(centre, radius: float, start: float = 0.0, sweep: float = 360.0,
                   closed: bool = True) -> np.ndarray:
    steps = max(2, int(math.ceil(SEGMENTS * sweep / 360.0 - 1e-9)))
    angles = np.radians(start + np.linspace(0.0, sweep, steps + 1))
    if closed:
        angles = angles[:-1]
    return np.column_stack([centre[0] + radius * np.cos(angles), centre[1] + radius * np.sin(angles)])


def _spline_points(points: list, closed: bool) -> np.ndarray:
    from scipy.interpolate import CubicSpline

    pts = np.asarray(points, dtype=np.float64)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    if len(pts) == 2:
        return pts
    chords = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    t = np.concatenate([[0.0], np.cumsum(chords)])
    spline = CubicSpline(t, pts, bc_type="periodic" if closed else "natural")
    samples = []
    for i in range(len(t) - 1):
        samples.append(spline(np.linspace(t[i], t[i + 1], SPLINE_STEPS, endpoint=False)))
    samples.append(pts[-1:])
    out = np.vstack(samples)
    # The spline passes exactly through every point the user typed.
    out[::SPLINE_STEPS] = pts
    return out[:-1] if closed else out


def entity_points(entity: dict) -> tuple[np.ndarray, bool]:
    """One curve as straight pieces: (points, closed). A closed curve's
    points do not repeat the first one at the end."""
    e = clean_entity(entity)
    kind = e["type"]
    if kind == "line":
        return np.array([e["start"], e["end"]], dtype=np.float64), False
    if kind == "rectangle":
        (x, y), w, h = e["corner"], e["width"], e["height"]
        return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float64), True
    if kind == "circle":
        return _circle_points(e["centre"], e["diameter"] / 2.0), True
    if kind == "arc":
        return _circle_points(e["centre"], e["radius"], e["start"], _sweep(e["start"], e["end"]),
                              closed=False), False
    if kind == "polygon":
        angles = np.radians(e["angle"] + 360.0 * np.arange(e["sides"]) / e["sides"])
        cx, cy = e["centre"]
        return np.column_stack([cx + e["radius"] * np.cos(angles), cy + e["radius"] * np.sin(angles)]), True
    return _spline_points(e["points"], e["closed"]), e["closed"]


class Chains:
    """A sketch's curves sorted into closed outlines and open paths."""

    def __init__(self, loops: list, paths: list, branching: bool) -> None:
        self.loops = loops          # closed outlines, (N, 2) arrays, no repeated end
        self.paths = paths          # open paths, (N, 2) arrays, first to last
        self.branching = branching  # some curve ends meet three or more at one point


def chains(entities) -> Chains:
    """Sort curves into outlines and paths. Lines, arcs and open splines
    are joined end to end where their ends meet."""
    loops, pieces = [], []
    for entity in entities:
        points, closed = entity_points(entity)
        (loops if closed else pieces).append(points)

    # Each piece's two ends become nodes; ends within JOIN_TOLERANCE share one.
    nodes: list[np.ndarray] = []

    def node_for(point) -> int:
        for index, existing in enumerate(nodes):
            if np.linalg.norm(existing - point) <= JOIN_TOLERANCE:
                return index
        nodes.append(np.asarray(point, dtype=np.float64))
        return len(nodes) - 1

    ends = [(node_for(p[0]), node_for(p[-1])) for p in pieces]
    touching: dict[int, list[int]] = {}
    for index, (a, b) in enumerate(ends):
        touching.setdefault(a, []).append(index)
        touching.setdefault(b, []).append(index)
    branching = any(len(v) > 2 for v in touching.values())

    used = [False] * len(pieces)

    def walk(first: int, start_node: int) -> tuple[np.ndarray, int]:
        """Follow pieces from `start_node` along piece `first`."""
        out = [nodes[start_node]]
        node, piece = start_node, first
        while piece is not None and not used[piece]:
            used[piece] = True
            a, b = ends[piece]
            points = pieces[piece] if a == node else pieces[piece][::-1]
            node = b if a == node else a
            out.extend(points[1:-1])
            out.append(nodes[node])
            onward = [p for p in touching[node] if not used[p]]
            piece = onward[0] if len(touching[node]) == 2 and onward else None
        return np.array(out), node

    paths = []
    # Open paths start at a free end (a node only one piece touches).
    for node, around in touching.items():
        if len(around) == 1 and not used[around[0]]:
            path, _end = walk(around[0], node)
            paths.append(path)
    for index in range(len(pieces)):
        if used[index]:
            continue
        start = ends[index][0]
        path, end = walk(index, start)
        if end == start and len(path) >= 4:
            loops.append(path[:-1])
        else:
            paths.append(path)
    return Chains(loops, paths, branching)


def signed_area(loop: np.ndarray) -> float:
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def profile(entities) -> "m3.CrossSection":
    """The filled area of a sketch's closed outlines (even-odd: an outline
    inside another is a hole). Raises SketchError when there is none."""
    found = chains(entities)
    if found.branching:
        raise SketchError(
            "Some curves in this sketch meet three or more at one point, so its outline "
            "is unclear. Draw each outline as one closed loop."
        )
    loops = [loop for loop in found.loops if abs(signed_area(loop)) > MIN_SIZE**2]
    if not loops:
        raise SketchError(
            "This sketch has no closed outline. Draw a rectangle, circle or polygon, "
            "or join lines and arcs end to end so they close."
        )
    area = m3.CrossSection([np.ascontiguousarray(loop) for loop in loops], m3.FillRule.EvenOdd)
    if area.is_empty() or area.area() < MIN_SIZE**2:
        raise SketchError("This sketch's outlines enclose no area.")
    return area


def single_path(entities) -> tuple[np.ndarray, bool]:
    """The one path a sketch draws, for Sweep: (points, closed). An open
    path is used if there is one; otherwise a single closed outline."""
    found = chains(entities)
    if found.branching:
        raise SketchError("The path's curves branch. Draw the path as one line of curves.")
    if len(found.paths) == 1 and not found.loops:
        return found.paths[0], False
    if len(found.loops) == 1 and not found.paths:
        return found.loops[0], True
    raise SketchError(
        "The path sketch must hold exactly one path: curves joined end to end, "
        "or one closed outline."
    )


# --- Planes ---------------------------------------------------------------------

# Named planes a new sketch can be drawn on: the direction it faces.
PLANES = {
    "xy": (0.0, 0.0, 1.0),    # the workplane, facing up
    "xz": (0.0, -1.0, 0.0),   # upright, facing the front
    "yz": (1.0, 0.0, 0.0),    # upright, facing the right side
}


def plane_frame(normal, point=(0.0, 0.0, 0.0)) -> np.ndarray:
    """The transform of a sketch drawn on the plane through `point` facing
    `normal`.

    Sketch X follows the world's X (or the world's Y when the plane faces
    along X), sketch Y = facing x sketch X, and the sketch's origin is the
    point of the plane nearest the world origin. So on the workplane, and
    on any flat face, sketch numbers are the world's own left/right and
    forward/back (or height) numbers.
    """
    n = np.asarray(normal, dtype=np.float64)
    length = np.linalg.norm(n)
    if length < 1e-12:
        raise SketchError("A plane needs a facing direction.")
    n = n / length
    across = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = across - np.dot(across, n) * n
    x /= np.linalg.norm(x)
    y = np.cross(n, x)
    origin = np.dot(np.asarray(point, dtype=np.float64), n) * n
    frame = np.eye(4)
    frame[:3, 0], frame[:3, 1], frame[:3, 2], frame[:3, 3] = x, y, n, origin
    return frame


def named_plane_frame(name: str, distance: float = 0.0) -> np.ndarray:
    """One of PLANES, moved `distance` mm along the way it faces."""
    if name not in PLANES:
        raise ValueError(f"unknown plane {name!r}")
    normal = np.asarray(PLANES[name])
    return plane_frame(normal, normal * float(distance))


def to_world(frame, points_2d) -> np.ndarray:
    """Sketch points (N, 2) into the world through `frame`."""
    frame = np.asarray(frame, dtype=np.float64)
    pts = np.asarray(points_2d, dtype=np.float64)
    return pts @ frame[:3, :2].T + frame[:3, 3]


def to_sketch(frame, points_3d) -> np.ndarray:
    """World points into a sketch's 2D coordinates (dropping the distance
    off the plane)."""
    frame = np.asarray(frame, dtype=np.float64)
    pts = np.asarray(points_3d, dtype=np.float64) - frame[:3, 3]
    return np.column_stack([pts @ frame[:3, 0], pts @ frame[:3, 1]])


# --- How a sketch is drawn ------------------------------------------------------


def sketch_lines(entities) -> list[np.ndarray]:
    """Every curve as a polyline in sketch coordinates (closed ones repeat
    their first point at the end), for drawing."""
    lines = []
    for entity in entities:
        points, closed = entity_points(entity)
        lines.append(np.vstack([points, points[:1]]) if closed else points)
    return lines


def sketch_geometry(entities) -> trimesh.Trimesh:
    """A sketch as flat triangles in its own coordinates (Z = 0): its
    filled outlines, plus one zero-area triangle per straight piece of
    every curve, so the sketch's size includes curves that close nothing.

    This is what the rest of the app measures (size, centre, Align, Mirror)
    and what the 3D view shows as the sketch's shading. It is never
    printed: see mesh.shapes.is_reference.
    """
    vertices, faces = [], []
    try:
        area = profile(entities)
    except SketchError:
        area = None
    if area is not None:
        polygons = [np.asarray(p, dtype=np.float64) for p in area.to_polygons()]
        triangles = np.asarray(m3.triangulate(polygons), dtype=np.int64).reshape(-1, 3)
        flat = np.vstack(polygons)
        vertices.append(np.column_stack([flat, np.zeros(len(flat))]))
        faces.append(triangles)
    count = sum(len(v) for v in vertices)
    for line in sketch_lines(entities):
        n = len(line)
        vertices.append(np.column_stack([line, np.zeros(n)]))
        index = count + np.arange(n - 1)
        faces.append(np.column_stack([index, index + 1, index + 1]))
        count += n
    if not vertices:
        return trimesh.Trimesh(vertices=np.zeros((1, 3)), faces=np.array([[0, 0, 0]]), process=False)
    return trimesh.Trimesh(vertices=np.vstack(vertices), faces=np.vstack(faces), process=False)


def describe(entity: dict) -> str:
    """One curve in plain words, for the sketch's list of curves."""

    def pt(p):
        return f"({p[0]:g}, {p[1]:g})"

    e = clean_entity(entity)
    kind = e["type"]
    if kind == "line":
        return f"Line from {pt(e['start'])} to {pt(e['end'])}"
    if kind == "rectangle":
        return f"Rectangle {e['width']:g} x {e['height']:g} mm, corner at {pt(e['corner'])}"
    if kind == "circle":
        return f"Circle {e['diameter']:g} mm across, centre {pt(e['centre'])}"
    if kind == "arc":
        return (f"Arc, radius {e['radius']:g} mm, centre {pt(e['centre'])}, "
                f"from {e['start']:g} to {e['end']:g} degrees")
    if kind == "polygon":
        return f"{e['sides']}-sided polygon, {e['radius']:g} mm to a corner, centre {pt(e['centre'])}"
    shape = "Closed spline" if e["closed"] else "Spline"
    return f"{shape} through {len(e['points'])} points"
