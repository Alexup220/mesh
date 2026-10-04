"""Solids made from sketches (Expert mode): Extrude, Revolve, Sweep and Loft.

Each is a primitive (see mesh.shapes.PRIMITIVES) whose params keep a copy of
the sketch it was made from, so its numbers stay editable and its geometry
is always rebuilt from them. `build(kind, params, clearance)` turns those
params into a closed solid in the shape's own coordinates, which are its
sketch's: the shape's transform is the sketch's plane.

    extrude  entities (sketch coordinates), distance, side
             The outline pushed straight out of its plane: the way the
             sketch faces ("one"), the other way ("other"), or half each
             way ("both").
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
side.

Never imports mesh.scene or mesh.shapes, so mesh.shapes can import it.
"""

import math

import numpy as np
import trimesh

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
                       params.get("side", "one"), clearance)
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


def extrude(entities, distance: float, side: str = "one", clearance: float = 0.0) -> trimesh.Trimesh:
    """The sketch's closed outlines pushed `distance` mm out of its plane."""
    distance = float(distance)
    if not math.isfinite(distance) or distance <= 0.0:
        raise SketchError("The distance must be more than 0 mm.")
    low = {"one": 0.0, "other": -distance, "both": -distance / 2.0}.get(side)
    if low is None:
        raise SketchError("Choose which way to extrude: the way the sketch faces, the other way, or both.")
    area = _grow(profile(entities), clearance)
    solid = m3.Manifold.extrude(area, distance + 2.0 * clearance).translate((0.0, 0.0, low - clearance))
    return _closed(solid, "extrusion")


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


def sweep(entities, profile_frame, path_entities, path_frame, clearance: float = 0.0) -> trimesh.Trimesh:
    """The outline carried along the path, staying square to it.

    If the outline is already drawn across the start of the path (its
    sketch facing along the path, with the path's first point within the
    outline's extent), it is used where it is. Otherwise its middle is
    moved onto the start of the path and it is turned to face along it. At each corner of the path the outline is cut
    on the plane halfway between the two directions (a mitre), which is
    exact for paths of straight pieces; curves are many short pieces.
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

    m = len(path)
    pieces = m if path_closed else m - 1
    directions = [_unit(path[(j + 1) % m] - path[j]) for j in range(pieces)]
    start, t0 = path[0], directions[0]

    # The outline in the world, then in flat coordinates across the start.
    area = _grow(profile(entities), clearance)
    world = [to_world(profile_frame, np.asarray(p, dtype=np.float64)) for p in area.to_polygons()]
    x_axis, origin = profile_frame[:3, 0], profile_frame[:3, 3]
    facing = _unit(np.cross(profile_frame[:3, 0], profile_frame[:3, 1]))
    # Where the path starts, in the outline's own sketch.
    on_sketch = np.linalg.lstsq(profile_frame[:3, :2], start - origin, rcond=None)[0]
    low_x, low_y, high_x, high_y = area.bounds()
    across_start = (abs(float(np.dot(facing, t0))) > math.cos(math.radians(1.0))
                    and abs(float(np.dot(start - origin, facing))) < 1e-6
                    and low_x - 1e-6 <= on_sketch[0] <= high_x + 1e-6
                    and low_y - 1e-6 <= on_sketch[1] <= high_y + 1e-6)
    if not across_start:
        flat = np.vstack(world)
        middle = (flat.min(axis=0) + flat.max(axis=0)) / 2.0
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


def loft(sections, clearance: float = 0.0) -> trimesh.Trimesh:
    """A skin through two or more outlines, in order, closed at both ends.

    Every corner of every outline is kept: each outline is walked from a
    matching start point and gets a point at every place (as a fraction of
    its length) where any outline has a corner, so the skin joins them with
    straight lines from one outline to the next.
    """
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        raise SketchError("A loft needs at least two sketches, each with one closed outline.")
    parsed = [_section(s) for s in sections]
    centres = [to_world(frame, points).mean(axis=0) for points, frame in parsed]
    heading = centres[-1] - centres[0]
    if np.linalg.norm(heading) < 1e-6:
        raise SketchError("The first and last outlines are in the same place, so there is nothing to join.")
    heading = _unit(heading)

    outlines = []
    for points, frame in parsed:
        if clearance > 0.0:
            grown = _grow(m3.CrossSection([np.ascontiguousarray(points)]), clearance)
            points = np.asarray(grown.to_polygons()[0], dtype=np.float64)
        # Every outline runs anticlockwise seen from behind, looking along
        # the heading, so the skin's sides face outwards.
        facing = np.cross(frame[:3, 0], frame[:3, 1])
        if signed_area(points) * np.dot(facing, heading) < 0.0:
            points = points[::-1]
        outlines.append((points, frame))

    # Start each outline at the point lying the same way from its middle
    # as the previous outline's start, so the skin does not twist.
    lined_up = []
    for index, (points, frame) in enumerate(outlines):
        world = to_world(frame, points)
        middle = world.mean(axis=0)
        if index > 0:
            reference = lined_up[-1][2]
            across = world - middle
            across = across - np.outer(across @ heading, heading)
            score = across @ reference / np.maximum(np.linalg.norm(across, axis=1), 1e-12)
            shift = int(np.argmax(score))
            points = np.roll(points, -shift, axis=0)
            world = np.roll(world, -shift, axis=0)
        start = world[0] - middle
        start = start - np.dot(start, heading) * heading
        lined_up.append((points, frame, start))

    at = np.unique(np.round(np.concatenate([_fractions(p) for p, _f, _s in lined_up]), 12))
    rings, flats = [], []
    for points, frame, _start in lined_up:
        flat = _resample(points, at)
        flats.append(flat)
        rings.append([to_world(frame, flat)])

    if clearance > 0.0:
        # A fitted Hole also reaches `clearance` past each end.
        rings[0][0] = rings[0][0] - heading * clearance
        rings[-1][0] = rings[-1][0] + heading * clearance

    count = len(at)
    vertices = np.vstack([r[0] for r in rings])
    faces = [
        _skin(rings, closed=False),
        _cap([flats[0]], rings[0][0], 0, -heading),
        _cap([flats[-1]], rings[-1][0], count * (len(rings) - 1), heading),
    ]
    return _solid_from(vertices, np.vstack(faces), "loft")
