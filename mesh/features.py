"""Solids made from sketches (Expert mode): Extrude, Revolve, Sweep and Loft.

Each is a primitive (see mesh.shapes.PRIMITIVES) whose params keep a copy of
the sketch it was made from, so its numbers stay editable and its geometry
is always rebuilt from them. `build(kind, params, clearance)` turns those
params into a closed solid in the shape's own coordinates, which are its
sketch's: the shape's transform is the sketch's plane.

    extrude  entities (sketch coordinates), distance, side, taper
             The outline pushed straight out of its plane: the way the
             sketch faces ("one"), the other way ("other"), or half each
             way ("both"). With a taper (degrees), the sides slope in by
             that angle going away from the sketch's plane (out, for less
             than 0); missing in older files, where it is 0.
    revolve  entities, axis [x, y, dx, dy] (a line in the sketch), angle
             The outline turned about the axis line, anticlockwise seen
             from the line's far end. The solid's own Z is the axis, so a
             fresh revolve stands upright on the workplane; the shape's
             transform is its sketch's plane times axis_frame(axis), which
             puts the axis back where it was drawn.
    sweep    entities + profile_frame, path_entities + path_frame
             The outline carried along the path. Each frame is a 4x4 list
             placing that sketch in the sweep's own coordinates.
    loft     sections: [{entities, frame}, ...]
             A skin through two or more outlines, in order, each placed by
             its frame like a sweep's sketches.

A shape with no sketch of its own (a new primitive) uses a small built-in
one (DEFAULT_*), so every kind has a sensible default, standing on the
workplane like the other primitives.

`clearance` > 0 (a fitted Hole) grows the result by that much on every
side (a loft by at least that much; see loft).

Never imports mesh.scene or mesh.shapes, so mesh.shapes can import it.
"""

import math

import numpy as np
import trimesh
from shapely.geometry import LinearRing, LineString, Point, Polygon

from mesh.sketch import SEGMENTS, SketchError, profile, signed_area, single_path, to_world
from mesh.solids import from_manifold, m3

SOLIDS = ("extrude", "revolve", "sweep", "loft")
# The ones made from one outline, which Change Sketch can redraw.
ONE_OUTLINE = ("extrude", "revolve", "sweep")

SIDES = [
    ("one", "The way the sketch faces"),
    ("other", "The other way"),
    ("both", "Both ways, evenly"),
]

TAPER_LIMIT = 60.0  # degrees: the steepest an extrusion's sides may slope

DEFAULT_EXTRUDE = [{"type": "rectangle", "corner": [-10.0, -10.0], "width": 20.0, "height": 20.0}]
# Turned about the sketch's Y line: a tube 10 mm across inside, 20 outside.
DEFAULT_REVOLVE = [{"type": "rectangle", "corner": [5.0, 0.0], "width": 5.0, "height": 20.0}]
DEFAULT_AXIS = [0.0, 0.0, 0.0, 1.0]
# A circle on the workplane carried straight up a 20 mm line drawn upright.
DEFAULT_SWEEP_PROFILE = [{"type": "circle", "centre": [0.0, 0.0], "diameter": 10.0}]
DEFAULT_SWEEP_PATH = [{"type": "line", "start": [0.0, 0.0], "end": [0.0, 20.0]}]
_UPRIGHT = [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
_FLAT = np.eye(4).tolist()
# A 20 mm square on the workplane up to a 16 mm circle 20 mm above it.
DEFAULT_LOFT = [
    {"entities": [{"type": "rectangle", "corner": [-10.0, -10.0], "width": 20.0, "height": 20.0}],
     "frame": _FLAT},
    {"entities": [{"type": "circle", "centre": [0.0, 0.0], "diameter": 16.0}],
     "frame": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 20.0], [0.0, 0.0, 0.0, 1.0]]},
]


def _frame(values) -> np.ndarray:
    try:
        frame = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SketchError("A sketch's position is damaged.") from exc
    if frame.shape != (4, 4) or not np.isfinite(frame).all():
        raise SketchError("A sketch's position is damaged.")
    return frame


def _grow(area: "m3.CrossSection", clearance: float) -> "m3.CrossSection":
    """The outline grown by `clearance` all round, rounding its corners."""
    if clearance <= 0.0:
        return area
    return area.offset(clearance, m3.JoinType.Round, circular_segments=SEGMENTS)


def _closed(solid: "m3.Manifold", what: str) -> trimesh.Trimesh:
    if solid.status() != m3.Error.NoError or solid.is_empty() or solid.volume() < 1e-6:
        raise SketchError(f"That {what} would not make a closed solid. Try different sizes.")
    return from_manifold(solid)


def default_entities(kind: str) -> list[dict]:
    """The built-in sketch a `kind` uses when it has none of its own."""
    return {"extrude": DEFAULT_EXTRUDE, "revolve": DEFAULT_REVOLVE, "sweep": DEFAULT_SWEEP_PROFILE}[kind]


def build(kind: str, params: dict, clearance: float = 0.0) -> trimesh.Trimesh:
    if kind == "extrude":
        return extrude(params.get("entities", DEFAULT_EXTRUDE), params["distance"],
                       params.get("side", "one"), clearance, params.get("taper", 0.0))
    if kind == "revolve":
        return revolve(params.get("entities", DEFAULT_REVOLVE), params.get("axis", DEFAULT_AXIS),
                       params["angle"], clearance)
    if kind == "sweep":
        return sweep(
            params.get("entities", DEFAULT_SWEEP_PROFILE), params.get("profile_frame", _FLAT),
            params.get("path_entities", DEFAULT_SWEEP_PATH), params.get("path_frame", _UPRIGHT),
            clearance,
        )
    if kind == "loft":
        return loft(params.get("sections") or DEFAULT_LOFT, clearance)
    raise KeyError(f"unknown sketch solid: {kind}")


# --- Extrude --------------------------------------------------------------------


def extrude(entities, distance: float, side: str = "one", clearance: float = 0.0,
            taper: float = 0.0) -> trimesh.Trimesh:
    """The sketch's closed outlines pushed `distance` mm out of its plane,
    their sides sloping in by `taper` degrees (see _tapered)."""
    distance = float(distance)
    if not math.isfinite(distance) or distance <= 0.0:
        raise SketchError("The distance must be more than 0 mm.")
    low = {"one": 0.0, "other": -distance, "both": -distance / 2.0}.get(side)
    if low is None:
        raise SketchError("Choose which way to extrude: the way the sketch faces, the other way, or both.")
    taper = float(taper)
    if not math.isfinite(taper) or abs(taper) > TAPER_LIMIT:
        raise SketchError(f"The side slope must be between -{TAPER_LIMIT:g} and {TAPER_LIMIT:g} degrees.")
    if taper != 0.0:
        return _tapered(profile(entities), low, distance, side, taper, clearance)
    area = _grow(profile(entities), clearance)
    solid = m3.Manifold.extrude(area, distance + 2.0 * clearance).translate((0.0, 0.0, low - clearance))
    return _closed(solid, "extrusion")


TOO_STEEP = (
    "The sides slope so steeply that they would meet before the far end. Use a smaller "
    "angle or a shorter distance."
)


def _mitred(outlines: list, amount: float) -> list:
    """`outlines` (anticlockwise round areas, clockwise round holes) with
    every straight piece moved `amount` mm into the area (out of it, for
    less than 0), keeping its direction, so corners stay sharp."""
    moved = []
    for points in outlines:
        leaving = np.roll(points, -1, axis=0) - points
        leaving /= np.linalg.norm(leaving, axis=1)[:, None]
        arriving = np.roll(leaving, 1, axis=0)
        n_out = np.column_stack([-leaving[:, 1], leaving[:, 0]])
        n_in = np.column_stack([-arriving[:, 1], arriving[:, 0]])
        bend = 1.0 + np.einsum("ij,ij->i", n_in, n_out)
        if bend.min() < 1e-9:
            raise SketchError("An outline turns straight back on itself, so its sides can't slope.")
        moved.append(points + amount * (n_in + n_out) / bend[:, None])
    return moved


def _nesting(outlines: list) -> list:
    """Which outlines lie inside which: [i][j] is True when j is inside i."""
    areas = [Polygon(o) for o in outlines]
    return [[i != j and areas[i].contains(Point(outlines[j][0])) for j in range(len(outlines))]
            for i in range(len(outlines))]


def _still_apart(outlines: list, moved: list) -> bool:
    """Whether the moved outlines kept the shape of the originals: every
    piece still runs the same way, no outline touches itself or another,
    and each still lies inside the same others (a hole that grew past the
    outside around it would not touch it, but has crossed it)."""
    for before, after in zip(outlines, moved):
        along = np.einsum("ij,ij->i", np.roll(before, -1, axis=0) - before, np.roll(after, -1, axis=0) - after)
        if along.min() <= 1e-12:
            return False
    rings = [LinearRing(m) for m in moved]
    if not all(r.is_simple for r in rings):
        return False
    if any(a.intersects(b) for i, a in enumerate(rings) for b in rings[i + 1:]):
        return False
    return len(outlines) == 1 or _nesting(outlines) == _nesting(moved)


def _tapered(area, low: float, distance: float, side: str, taper: float, clearance: float) -> trimesh.Trimesh:
    """An extrusion whose sides slope in by `taper` degrees going away from
    the sketch's plane (out, for less than 0): at each height, every straight
    piece of the outline is moved in by the height times tan(taper), keeping
    its direction, so the sides are flat and the corners sharp ("both" slopes
    each way from the plane). A fitted Hole is `clearance` bigger square to
    every side, and reaches that far past both ends."""
    slope = math.tan(math.radians(taper))
    grow = clearance / math.cos(math.radians(taper))
    outlines = []
    for polygon in area.to_polygons():
        points = np.asarray(polygon, dtype=np.float64)
        keep = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1) > 1e-9
        outlines.append(points[keep])
    if not outlines:
        raise SketchError("The sketch has no closed outline to extrude.")
    high = low + distance
    heights = [low - clearance, 0.0, high + clearance] if side == "both" else [low - clearance, high + clearance]
    away = {"one": lambda z: z, "other": lambda z: -z, "both": abs}[side]
    steps = []
    for z in heights:
        moved = _mitred(outlines, away(z) * slope - grow)
        if not _still_apart(outlines, moved):
            raise SketchError(TOO_STEEP)
        steps.append(moved)
    rings = [[np.column_stack([m, np.full(len(m), z)]) for m in moved] for moved, z in zip(steps, heights)]
    vertices = np.vstack([ring for step in rings for ring in step])
    top = sum(len(ring) for ring in rings[0]) * (len(rings) - 1)
    faces = [
        _skin(rings, False),
        _cap(steps[0], np.vstack(rings[0]), 0, (0.0, 0.0, -1.0)),
        _cap(steps[-1], np.vstack(rings[-1]), top, (0.0, 0.0, 1.0)),
    ]
    return _solid_from(vertices, np.vstack(faces), "extrusion")


# --- Revolve --------------------------------------------------------------------


def axis_frame(axis) -> np.ndarray:
    """Where a revolve's own coordinates sit in its sketch: origin on the
    axis line, Z along it, X across the sketch to the line's right."""
    try:
        ax, ay, dx, dy = (float(v) for v in axis)
    except (TypeError, ValueError) as exc:
        raise SketchError("The line to turn around is damaged.") from exc
    length = math.hypot(dx, dy)
    if not all(map(math.isfinite, (ax, ay, dx, dy))) or length < 1e-9:
        raise SketchError("The line to turn around needs a direction.")
    u = np.array([dx, dy, 0.0]) / length
    v = np.array([u[1], -u[0], 0.0])
    frame = np.eye(4)
    frame[:3, 0], frame[:3, 1], frame[:3, 2], frame[:3, 3] = v, np.cross(u, v), u, (ax, ay, 0.0)
    return frame


def revolve(entities, axis, angle: float, clearance: float = 0.0) -> trimesh.Trimesh:
    """The outline turned `angle` degrees (at most 360) about `axis`, in the
    revolve's own coordinates (see axis_frame). A turn of less than 360
    starts at the sketch."""
    angle = float(angle)
    if not math.isfinite(angle) or angle <= 0.0:
        raise SketchError("The angle must be more than 0 degrees.")
    angle = min(angle, 360.0)
    to_axis = np.linalg.inv(axis_frame(axis))
    polygons = []
    for polygon in profile(entities).to_polygons():
        flat = np.column_stack([polygon, np.zeros(len(polygon)), np.ones(len(polygon))])
        # (distance from the axis, signed; distance along the axis)
        polygons.append((flat @ to_axis.T)[:, [0, 2]])
    across = np.concatenate([p[:, 0] for p in polygons])
    if across.max() > 1e-6 and across.min() < -1e-6:
        raise SketchError(
            "The outline crosses the line it turns around. Move it so it is all on one "
            "side of that line."
        )
    flipped = across.max() <= 1e-6
    if flipped:
        polygons = [p * (-1.0, 1.0) for p in polygons]
    area = _grow(m3.CrossSection(polygons, m3.FillRule.EvenOdd), clearance)
    # Nothing may reach past the axis (a fitted Hole grows towards it).
    low_x, low, high_x, high = area.bounds()
    if low_x < 0.0 and high_x > 0.0:
        area = area ^ m3.CrossSection.square((high_x + 1.0, high - low + 2.0)).translate((0.0, low - 1.0))
    if area.is_empty() or area.area() < 1e-6:
        raise SketchError("The outline lies on the line it turns around, so there is nothing to turn.")
    solid = m3.Manifold.revolve(area, SEGMENTS, angle)
    if clearance > 0.0 and angle < 360.0:
        # A fitted Hole also reaches `clearance` past both flat ends: the
        # grown outline pushed that far out of the start face (y = 0,
        # facing -y), and out of the end face, turned `angle` from it.
        before = m3.Manifold.extrude(area, clearance).rotate((90.0, 0.0, 0.0))
        after = before.mirror((0.0, 1.0, 0.0)).rotate((0.0, 0.0, angle))
        solid = solid + before + after
    if flipped:
        # Turning the mirrored outline, then half a turn, is the same as
        # turning the outline from its own side.
        solid = solid.rotate((0.0, 0.0, 180.0))
    return _closed(solid, "revolve")


# --- Sweep ------------------------------------------------------------------------


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise SketchError("The path has a piece with no length.")
    return v / n


def _turn(a, b) -> np.ndarray:
    """The rotation turning unit direction a onto unit direction b (as
    mesh.ops.rotation_between does; this module can't import mesh.ops)."""
    axis = np.cross(a, b)
    s, c = np.linalg.norm(axis), float(np.dot(a, b))
    if s < 1e-12:
        if c > 0.0:
            return np.eye(3)
        helper = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, helper)
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    axis /= s
    k = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]])
    return np.eye(3) + s * k + (1.0 - c) * (k @ k)


def _cap(outlines_2d: list, ring: np.ndarray, offset: int, facing) -> np.ndarray:
    """Triangles closing one end. `outlines_2d` are the end's outlines in
    2D and `ring` the same points in 3D, in the same order. Returned as
    indices into the full point list (starting at `offset`), turned to face
    `facing`."""
    polygons = [np.ascontiguousarray(o, dtype=np.float64) for o in outlines_2d]
    triangles = np.asarray(m3.triangulate(polygons), dtype=np.int64).reshape(-1, 3)
    if len(triangles) == 0:
        raise SketchError("An outline is too thin to close.")
    a, b, c = ring[triangles[:, 0]], ring[triangles[:, 1]], ring[triangles[:, 2]]
    if np.dot(np.cross(b - a, c - a).sum(axis=0), facing) < 0.0:
        triangles = triangles[:, ::-1]
    return triangles + offset


def _skin(rings: list, closed: bool) -> np.ndarray:
    """Side triangles joining each ring of points to the next, for every
    outline. rings[k][c] is outline c at step k; counts match step to step."""
    faces, offsets, count = [], [], 0
    for step in rings:
        offsets.append([])
        for outline in step:
            offsets[-1].append(count)
            count += len(outline)
    steps = len(rings) if closed else len(rings) - 1
    for k in range(steps):
        k1 = (k + 1) % len(rings)
        for c, outline in enumerate(rings[k]):
            i = np.arange(len(outline))
            a, b = offsets[k][c] + i, offsets[k][c] + (i + 1) % len(outline)
            d, e = offsets[k1][c] + i, offsets[k1][c] + (i + 1) % len(outline)
            faces.append(np.column_stack([a, b, e]))
            faces.append(np.column_stack([a, e, d]))
    return np.vstack(faces)


def _solid_from(vertices: np.ndarray, faces: np.ndarray, what: str) -> trimesh.Trimesh:
    """A closed solid from outward-facing triangles, checked by the solid
    kernel."""
    built = m3.Mesh(
        vert_properties=np.ascontiguousarray(vertices, dtype=np.float32),
        tri_verts=np.ascontiguousarray(faces, dtype=np.uint32),
    )
    return _closed(m3.Manifold(built), what)


# How square to the path an outline's sketch must be to count as drawn
# across it: a little over half the turn between a circle's straight pieces.
ACROSS_DEGREES = 3.0


def _sweep_start(path: np.ndarray, closed: bool, area, profile_frame: np.ndarray,
                 middle: np.ndarray) -> tuple[np.ndarray, bool]:
    """The path, reordered to start where the outline is: (path, in_place).

    in_place is True when the outline is drawn across the path there: its
    sketch square to the path, with the path passing through the outline's
    extent. An open path may start at either end; a closed one at any
    point, which is added to it if need be. Otherwise the path starts at
    the end (or, round a closed path, the point) nearest the outline's
    middle `middle`, and the outline is moved there.
    """
    facing = _unit(np.cross(profile_frame[:3, 0], profile_frame[:3, 1]))
    origin = profile_frame[:3, 3]
    low_x, low_y, high_x, high_y = area.bounds()
    square = math.cos(math.radians(ACROSS_DEGREES))

    def within(point) -> bool:
        x, y = np.linalg.lstsq(profile_frame[:3, :2], point - origin, rcond=None)[0]
        return low_x - 1e-6 <= x <= high_x + 1e-6 and low_y - 1e-6 <= y <= high_y + 1e-6

    def across(point, heading) -> bool:
        return (abs(float(np.dot(facing, _unit(heading)))) >= square
                and abs(float(np.dot(point - origin, facing))) < 1e-5 and within(point))

    if not closed:
        if across(path[0], path[1] - path[0]):
            return path, True
        if across(path[-1], path[-2] - path[-1]):
            return path[::-1].copy(), True
        if np.linalg.norm(path[-1] - middle) < np.linalg.norm(path[0] - middle):
            return path[::-1].copy(), False
        return path, False

    m = len(path)
    for j in range(m):
        a, d = path[j], path[(j + 1) % m] - path[j]
        if abs(float(np.dot(facing, _unit(d)))) < square:
            continue
        s = float(np.dot(origin - a, facing) / np.dot(d, facing))
        if not -1e-9 <= s < 1.0 - 1e-6 or not within(a + s * d):
            continue
        if s > 1e-6:
            path = np.vstack([path[:j + 1], [a + s * d], path[j + 1:]])
            j += 1
        return np.roll(path, -j, axis=0), True
    nearest = int(np.argmin(np.linalg.norm(path - middle, axis=1)))
    return np.roll(path, -nearest, axis=0), False


def sweep(entities, profile_frame, path_entities, path_frame, clearance: float = 0.0) -> trimesh.Trimesh:
    """The outline carried along the path, staying square to it.

    If the outline is already drawn across the path at one of its ends (or
    anywhere round a closed path), the sweep starts there and the outline
    is used where it is (see _sweep_start). Otherwise its middle is moved
    onto the nearest end of the path and it is turned to face along it. At
    each corner of the path the outline is cut on the plane halfway between
    the two directions (a mitre), which is exact for paths of straight
    pieces; curves are many short pieces.
    """
    profile_frame, path_frame = _frame(profile_frame), _frame(path_frame)
    path_2d, path_closed = single_path(path_entities)
    path = to_world(path_frame, path_2d)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(path, axis=0), axis=1) > 1e-9])
    path = path[keep]
    if path_closed and len(path) > 1 and np.linalg.norm(path[0] - path[-1]) < 1e-9:
        path = path[:-1]
    if len(path) < (3 if path_closed else 2):
        raise SketchError("The path is too short to sweep along.")

    # The outline in the world.
    area = _grow(profile(entities), clearance)
    world = [to_world(profile_frame, np.asarray(p, dtype=np.float64)) for p in area.to_polygons()]
    flat = np.vstack(world)
    middle = (flat.min(axis=0) + flat.max(axis=0)) / 2.0
    path, in_place = _sweep_start(path, path_closed, area, profile_frame, middle)

    m = len(path)
    pieces = m if path_closed else m - 1
    directions = [_unit(path[(j + 1) % m] - path[j]) for j in range(pieces)]
    start, t0 = path[0], directions[0]

    # The outline in flat coordinates across the start.
    x_axis = profile_frame[:3, 0]
    if not in_place:
        facing = _unit(np.cross(profile_frame[:3, 0], profile_frame[:3, 1]))
        turn = _turn(facing, t0)
        world = [(w - middle) @ turn.T + start for w in world]
        x_axis = turn @ x_axis
    e1 = _unit(x_axis - np.dot(x_axis, t0) * t0)
    e2 = np.cross(t0, e1)
    outlines = [np.column_stack([(w - start) @ e1, (w - start) @ e2]) for w in world]
    # Filled again in these coordinates, so every outline runs anticlockwise
    # seen from ahead along the path, and holes the other way.
    area = m3.CrossSection([np.ascontiguousarray(o) for o in outlines], m3.FillRule.EvenOdd)
    outlines = [np.asarray(p, dtype=np.float64) for p in area.to_polygons()]
    if not outlines:
        raise SketchError("The outline encloses no area.")

    if clearance > 0.0 and not path_closed:
        # A fitted Hole also reaches `clearance` past each end.
        path = path.copy()
        path[0] = path[0] - directions[0] * clearance
        path[-1] = path[-1] + directions[-1] * clearance

    # Carry the outline's axes along the path without twisting: each
    # piece's axes are the piece before's, turned by the bend between them.
    frames = [(e1, e2)]
    for j in range(1, pieces):
        turn = _turn(directions[j - 1], directions[j])
        frames.append((turn @ frames[-1][0], turn @ frames[-1][1]))

    def ring(k: int, outline: np.ndarray) -> np.ndarray:
        """The outline at path point k: square to the piece arriving there,
        then, at a corner, slid along that piece onto the mitre plane."""
        corner = path_closed or 0 < k < m - 1
        arriving = (k - 1) % pieces if corner else (0 if k == 0 else pieces - 1)
        a, b = frames[arriving]
        points = path[k] + outline[:, :1] * a + outline[:, 1:] * b
        if corner:
            d_in, d_out = directions[arriving], directions[k % pieces]
            mitre = d_in + d_out
            if np.linalg.norm(mitre) < 1e-6:
                raise SketchError("The path turns straight back on itself, so it can't be swept along.")
            mitre /= np.linalg.norm(mitre)
            points = points - np.outer((points - path[k]) @ mitre / np.dot(d_in, mitre), d_in)
        return points

    rings = [[ring(k, o) for o in outlines] for k in range(m)]
    if not (LinearRing(path_2d) if path_closed else LineString(path_2d)).is_simple:
        raise SketchError("The path crosses itself, so it can't be swept along.")

    # Every point of the outline must move forwards along each piece; one
    # that runs backwards means the outline is too big for that bend.
    for j in range(pieces):
        k0, k1 = j, (j + 1) % m
        for c in range(len(outlines)):
            if ((rings[k1][c] - rings[k0][c]) @ directions[j]).min() <= 1e-6:
                raise SketchError(
                    "The path bends too tightly for an outline this big. Use a smaller "
                    "outline or a gentler bend."
                )

    vertices = np.vstack([o for step in rings for o in step])
    faces = [_skin(rings, path_closed)]
    if not path_closed:
        end = sum(len(o) for o in rings[0]) * (m - 1)
        faces.append(_cap(outlines, np.vstack(rings[0]), 0, -directions[0]))
        faces.append(_cap(outlines, np.vstack(rings[-1]), end, directions[-1]))
    return _solid_from(vertices, np.vstack(faces), "sweep")


# --- Loft ---------------------------------------------------------------------------


def _section(section) -> tuple[np.ndarray, np.ndarray]:
    """One loft outline: (its 2D points, its frame)."""
    if not isinstance(section, dict):
        raise SketchError("A loft outline is damaged.")
    frame = _frame(section.get("frame"))
    polygons = profile(section.get("entities", [])).to_polygons()
    if len(polygons) != 1:
        raise SketchError(
            "Each sketch in a loft must hold one closed outline, with no holes or separate pieces."
        )
    return np.asarray(polygons[0], dtype=np.float64), frame


def _resample(points: np.ndarray, at: np.ndarray) -> np.ndarray:
    """Points along a closed outline at fractions `at` of its length from
    its first point."""
    loop = np.vstack([points, points[:1]])
    lengths = np.linalg.norm(np.diff(loop, axis=0), axis=1)
    t = np.concatenate([[0.0], np.cumsum(lengths)]) / lengths.sum()
    return np.column_stack([np.interp(at, t, loop[:, i]) for i in range(loop.shape[1])])


def _fractions(points: np.ndarray) -> np.ndarray:
    """Where each corner of a closed outline is, as a fraction of its length."""
    lengths = np.linalg.norm(np.diff(np.vstack([points, points[:1]]), axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(lengths)[:-1]]) / lengths.sum()


# A fitted-Hole loft grows each outline more where the sides slope, so the
# gap square to the sides is the full clearance; but never more than this
# many times the clearance, where the sides are almost flat.
MOST_LOFT_GROWTH = 3.0


def _lined_up(outlines, heading) -> tuple[list, list]:
    """Each (points, frame) outline as (flat points, world points), all with
    the same number of points matched one to one.

    Each outline is walked from the point lying the same way from its
    middle as the previous outline's start, so the skin does not twist, and
    gets a point at every place (as a fraction of its length) where any
    outline has a corner, so the skin joins corners with straight lines.
    """
    lined_up, reference = [], None
    for points, frame in outlines:
        world = to_world(frame, points)
        middle = world.mean(axis=0)
        if reference is not None:
            across = world - middle
            across = across - np.outer(across @ heading, heading)
            score = across @ reference / np.maximum(np.linalg.norm(across, axis=1), 1e-12)
            shift = int(np.argmax(score))
            points = np.roll(points, -shift, axis=0)
            world = np.roll(world, -shift, axis=0)
        reference = world[0] - middle
        reference = reference - np.dot(reference, heading) * heading
        lined_up.append((points, frame))
    at = np.unique(np.round(np.concatenate([_fractions(p) for p, _f in lined_up]), 12))
    flats = [_resample(points, at) for points, _f in lined_up]
    return flats, [to_world(frame, flat) for flat, (_p, frame) in zip(flats, lined_up)]


def _plane_basis(direction) -> tuple[np.ndarray, np.ndarray]:
    helper = np.array([1.0, 0.0, 0.0]) if abs(direction[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    a = _unit(np.cross(direction, helper))
    return a, np.cross(direction, a)


def _check_skin(rings: list) -> None:
    """Refuse a skin that would pass through itself: part way between each
    outline and the next, seen along the way between them, the in-between
    outline must not cross itself or turn inside out."""
    for first, second in zip(rings, rings[1:]):
        step = _unit(second.mean(axis=0) - first.mean(axis=0))
        a, b = _plane_basis(step)
        sides = set()
        for t in np.linspace(0.0, 1.0, 9)[1:-1]:
            between = (1.0 - t) * first + t * second
            flat = np.column_stack([between @ a, between @ b])
            area = signed_area(flat)
            if abs(area) < 1e-9 or not LinearRing(flat).is_simple:
                sides.add(0)
            sides.add(np.sign(area))
        if len(sides) > 1:
            raise SketchError(
                "The loft's sides would pass through each other between two of its outlines. "
                "Try outlines closer in shape, or another outline in between."
            )


def _slopes(rings: list, normals: list) -> list[float]:
    """For each outline, how square to its plane the sides leaving it are
    at their steepest, as a cosine (1 for sides straight out of the plane)."""
    cosines = [1.0] * len(rings)
    for k in range(len(rings) - 1):
        edges = rings[k + 1] - rings[k]
        lengths = np.maximum(np.linalg.norm(edges, axis=1), 1e-12)
        for j in (k, k + 1):
            cosines[j] = min(cosines[j], float((np.abs(edges @ normals[j]) / lengths).min()))
    return cosines


def loft(sections, clearance: float = 0.0) -> trimesh.Trimesh:
    """A skin through two or more outlines, in order, closed at both ends
    (see _lined_up for how the outlines are joined).

    A fitted Hole (`clearance` > 0) grows each outline within its plane, by
    more where the sides slope, so the gap square to the sides is at least
    `clearance` (up to MOST_LOFT_GROWTH times it); and reaches `clearance`
    past each end.
    """
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        raise SketchError("A loft needs at least two sketches, each with one closed outline.")
    parsed = [_section(s) for s in sections]
    centres = [to_world(frame, points).mean(axis=0) for points, frame in parsed]
    heading = centres[-1] - centres[0]
    if np.linalg.norm(heading) < 1e-6:
        raise SketchError("The first and last outlines are in the same place, so there is nothing to join.")
    heading = _unit(heading)
    steps = [centres[k + 1] - centres[k] for k in range(len(centres) - 1)]
    if any(np.dot(a, b) <= 0.0 for a, b in zip(steps, steps[1:])):
        raise SketchError(
            "The loft would fold back on itself. Pick the sketches in order, from one end to the other."
        )
    normals = [_unit(np.cross(frame[:3, 0], frame[:3, 1])) for _p, frame in parsed]

    def facing_on(outlines):
        """Every outline running anticlockwise seen from behind, looking
        along the heading, so the skin's sides face outwards."""
        turned = []
        for (points, frame), normal in zip(outlines, normals):
            if signed_area(points) * np.dot(normal, heading) < 0.0:
                points = points[::-1]
            turned.append((points, frame))
        return turned

    flats, rings = _lined_up(facing_on(parsed), heading)
    _check_skin(rings)

    if clearance > 0.0:
        grown = []
        for (points, frame), cosine in zip(parsed, _slopes(rings, normals)):
            distance = clearance / max(cosine, 1.0 / MOST_LOFT_GROWTH)
            polygons = _grow(m3.CrossSection([np.ascontiguousarray(points)]), distance).to_polygons()
            if len(polygons) != 1:
                raise SketchError(
                    "At this fit, a narrow gap in one of the loft's outlines closes up. "
                    "Choose a tighter fit, or widen the gap."
                )
            grown.append((np.asarray(polygons[0], dtype=np.float64), frame))
        flats, rings = _lined_up(facing_on(grown), heading)
        # Reaching `clearance` past each end: the end outlines again, that
        # far out of their planes, joined to them by straight sides.
        first = normals[0] * np.sign(np.dot(normals[0], steps[0])) * clearance
        last = normals[-1] * np.sign(np.dot(normals[-1], steps[-1])) * clearance
        flats = [flats[0]] + flats + [flats[-1]]
        rings = [rings[0] - first] + rings + [rings[-1] + last]

    count = len(flats[0])
    vertices = np.vstack(rings)
    faces = [
        _skin([[r] for r in rings], closed=False),
        _cap([flats[0]], rings[0], 0, -heading),
        _cap([flats[-1]], rings[-1], count * (len(rings) - 1), heading),
    ]
    return _solid_from(vertices, np.vstack(faces), "loft")
