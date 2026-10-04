"""Rounding and bevelling a part's edges: Expert mode's Fillet and Chamfer.

An edge is where two faces meet at a sharp angle (more than SHARP_DEGREES).
A click on a face picks the edge of that face nearest the click, and follows
it along while it runs on smoothly into the next edge (round the rim of a
cylinder, say). The run stops where it turns a corner, or where another edge
meets it.

Along the run, the corner between the two faces is cut away (an outside
edge) or filled in (an inside edge), leaving a round of the given radius or
a flat bevel set back the given distance on both faces. The piece is built
as a ring of points at every point of the run, square to the run there,
skinned from one ring to the next; a round's arc is narrow straight pieces,
as many per turn as a circle has. The result is an ordinary group of the
part and that piece, so Ungroup gives the part back.

Exact for a straight edge between flat faces. Along a curved run the faces
are narrow flat strips, and the piece follows them. Where rounded or
bevelled edges meet at a corner, the corner is not blended into a ball.
"""

import copy
import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from mesh import sketch
from mesh.builders import GUIDES_ARE_NOT_PARTS, NOT_CLEAN, BuildError, _baked_child, _group
from mesh.features import _cap, _skin, _solid_from
from mesh.ops import NothingToCombineError
from mesh.shapes import is_reference, shape_geometry

SHARP_DEGREES = 20.0   # faces meeting at more than this make an edge
CHAIN_DEGREES = 30.0   # an edge runs on into the next one if it turns less than this
FACE_LIMIT = 50000     # parts more detailed than this are not searched for edges
NUDGE = 0.01           # mm the piece reaches past the faces and the run's ends
ARC_SEGMENTS = sketch.SEGMENTS  # straight pieces in a whole turn of a round


@dataclass
class Run:
    """A run of edges, in order along it."""

    vertices: list[int]       # the part's corner points along the run
    closed: bool              # it goes all the way round, back to its start
    convex: bool              # an outside edge: the part lies between the faces
    sides: list[tuple[int, int]]  # each piece of the run: (triangle on side A, on side B)


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _part_surface(shape, clearances):
    if is_reference(shape):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Rounding or bevelling edges"))
    if shape.is_hole:
        raise BuildError("Rounding and bevelling edges work on solid parts. This one is a Hole.")
    tm = shape_geometry(shape, clearances)
    if len(tm.faces) > FACE_LIMIT:
        raise BuildError("This part is too detailed to find its edges.")
    if not tm.is_volume:
        raise BuildError("This part has gaps in its surface, so its edges can't be rounded or bevelled.")
    return tm


def find_run(tm, face_index: int, point) -> Run:
    """The run of edges through the sharp edge of the clicked face (the
    flat face containing triangle `face_index`) nearest `point`."""
    if not 0 <= face_index < len(tm.faces):
        raise BuildError("Click on a face of a part, next to the edge.")
    sharp = np.flatnonzero(tm.face_adjacency_angles > math.radians(SHARP_DEGREES))
    pairs = tm.face_adjacency[sharp]
    corners = tm.face_adjacency_edges[sharp]
    convex = tm.face_adjacency_convex[sharp]

    clicked = {face_index}
    for facet in tm.facets:
        if face_index in facet:
            clicked = set(int(f) for f in facet)
            break
    near = [i for i, (f1, f2) in enumerate(pairs) if int(f1) in clicked or int(f2) in clicked]
    if not near:
        raise BuildError("The face you clicked has no sharp edge. Click a face next to the edge.")
    point = np.asarray(point, dtype=np.float64)
    a, b = tm.vertices[corners[near, 0]], tm.vertices[corners[near, 1]]
    along = np.clip(np.einsum("ij,ij->i", point - a, b - a) / np.einsum("ij,ij->i", b - a, b - a), 0, 1)
    first = near[int(np.argmin(np.linalg.norm(a + along[:, None] * (b - a) - point, axis=1)))]

    at_corner: dict[int, list[int]] = {}
    for i, (u, w) in enumerate(corners):
        at_corner.setdefault(int(u), []).append(i)
        at_corner.setdefault(int(w), []).append(i)

    def onward(edge: int, frm: int, to: int) -> tuple[int, int] | None:
        """The edge the run goes on into at corner `to`, arriving along
        `edge` from `frm`: (edge, its far corner), or None where it stops."""
        others = [e for e in at_corner[to] if e != edge]
        if len(others) != 1 or convex[others[0]] != convex[first]:
            return None
        nxt = others[0]
        far = int(corners[nxt][0]) if int(corners[nxt][1]) == to else int(corners[nxt][1])
        d1 = tm.vertices[to] - tm.vertices[frm]
        d2 = tm.vertices[far] - tm.vertices[to]
        turn = math.degrees(math.acos(np.clip(d1 @ d2 / (np.linalg.norm(d1) * np.linalg.norm(d2)), -1, 1)))
        return (nxt, far) if turn < CHAIN_DEGREES else None

    u, w = (int(v) for v in corners[first])
    forward, edges = [u, w], [first]
    closed = False
    while True:
        step = onward(edges[-1], forward[-2], forward[-1])
        if step is None:
            break
        if step[1] == forward[0]:
            edges.append(step[0])
            closed = True
            break
        if step[1] in forward:
            break
        edges.append(step[0])
        forward.append(step[1])
    if not closed:
        while True:
            step = onward(edges[0], forward[1], forward[0])
            if step is None or step[1] in forward:
                break
            edges.insert(0, step[0])
            forward.insert(0, step[1])

    sides = []
    count = len(forward)
    for k, edge in enumerate(edges):
        start, end = forward[k], forward[(k + 1) % count]
        f1, f2 = (int(f) for f in pairs[edge])
        tri = list(tm.faces[f1])
        directed = any(tri[i] == start and tri[(i + 1) % 3] == end for i in range(3))
        sides.append((f1, f2) if directed else (f2, f1))
    return Run(forward, closed, bool(convex[first]), sides)


def _unit(v) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise BuildError(NOT_CLEAN)
    return v / n


class _Corner:
    """The two faces' directions at one point of a run."""

    def __init__(self, p, heading, n_a, n_b, convex: bool) -> None:
        self.p, self.t = p, heading
        n_a = _unit(n_a - (n_a @ heading) * heading)
        n_b = _unit(n_b - (n_b @ heading) * heading)
        sign = -1.0 if convex else 1.0
        a = _unit(np.cross(n_a, heading))
        self.a = a if (a @ n_b) * sign > 0 else -a
        b = _unit(np.cross(n_b, heading))
        self.b = b if (b @ n_a) * sign > 0 else -b
        # Out of the wedge between the faces: out of the part at an outside
        # edge, into it at an inside one.
        self.out_a, self.out_b = (n_a, n_b) if convex else (-n_a, -n_b)
        self.angle = math.acos(float(np.clip(self.a @ self.b, -1.0, 1.0)))

    def set_back(self, radius: float) -> float:
        """How far along each face a round of `radius` starts."""
        return radius / math.tan(self.angle / 2.0)

    def ring(self, set_back: float, radius: float | None, pieces: int) -> np.ndarray:
        """The piece's cross-section here: a round of `radius` (or a flat
        bevel, for None) starting `set_back` along each face, closed off
        just outside the wedge."""
        ta, tb = self.p + set_back * self.a, self.p + set_back * self.b
        if radius is None:
            arc = [ta, tb]
        else:
            centre = self.p + radius / math.sin(self.angle / 2.0) * _unit(self.a + self.b)
            u1, u2 = (ta - centre) / radius, (tb - centre) / radius
            sweep = math.pi - self.angle
            arc = [centre + radius * (math.sin((1 - s) * sweep) * u1 + math.sin(s * sweep) * u2)
                   / math.sin(sweep) for s in np.linspace(0.0, 1.0, pieces + 1)]
        tail = [tb + NUDGE * self.out_b, self.p + NUDGE * (self.out_a + self.out_b), ta + NUDGE * self.out_a]
        return np.array(arc + tail)


def _room(tm, triangle: int, cache: dict) -> tuple[np.ndarray, object]:
    """The flat face around a triangle: (its plane's frame, its area)."""
    key = triangle
    for i, facet in enumerate(tm.facets):
        if triangle in facet:
            key = ("facet", i)
            faces = np.asarray(facet)
            break
    else:
        faces = np.array([triangle])
    if key not in cache:
        frame = sketch.plane_frame(tm.face_normals[triangle], tm.vertices[tm.faces[triangle][0]])
        flat = sketch.to_sketch(frame, tm.triangles[faces].reshape(-1, 3)).reshape(-1, 3, 2)
        cache[key] = (frame, unary_union([Polygon(t) for t in flat]).buffer(1e-6))
    return cache[key]


def _space(tm, triangle: int, p, direction, cache: dict) -> float:
    """How far the flat face of `triangle` reaches from `p` along
    `direction` (laid onto its plane)."""
    frame, area = _room(tm, triangle, cache)
    reach = 2.0 * float(np.linalg.norm(tm.bounds[1] - tm.bounds[0])) + 1.0
    start, end = sketch.to_sketch(frame, np.array([p, p + reach * direction]))
    inside = area.intersection(LineString([start, end]))
    pieces = [inside] if inside.geom_type == "LineString" else list(getattr(inside, "geoms", []))
    lengths = [g.length for g in pieces if g.geom_type == "LineString"
               and min(np.linalg.norm(np.asarray(g.coords)[[0, -1]] - start, axis=1)) < 1e-4]
    return max(lengths, default=0.0)


def _corners(tm, run: Run) -> list[_Corner]:
    points = tm.vertices[run.vertices]
    count = len(points)
    pieces = count if run.closed else count - 1
    headings = [_unit(points[(k + 1) % count] - points[k]) for k in range(pieces)]
    normals = tm.face_normals
    out = []
    for k in range(count):
        touching = [j for j in (k - 1, k) if (0 <= j < pieces) or run.closed]
        touching = [j % pieces for j in touching]
        heading = _unit(sum(headings[j] for j in touching))
        n_a = sum(normals[run.sides[j][0]] for j in touching)
        n_b = sum(normals[run.sides[j][1]] for j in touching)
        out.append(_Corner(points[k], heading, n_a, n_b, run.convex))
    return out


def _round_down(value: float) -> float:
    return math.floor(value * 10.0 + 1e-9) / 10.0


def _edge_piece(shape, face_index: int, point, size: float, rounded: bool, clearances):
    """(the part's surface, the run, the piece to cut away or add)."""
    what = "rounding" if rounded else "bevel"
    size = float(size)
    if not math.isfinite(size) or size <= 0.0:
        raise BuildError(f"The {what} size must be more than 0 mm.")
    tm = _part_surface(shape, clearances)
    run = find_run(tm, face_index, point)
    corners = _corners(tm, run)

    cache: dict = {}
    count = len(run.vertices)
    pieces = count if run.closed else count - 1
    largest = math.inf
    for k, corner in enumerate(corners):
        side = run.sides[min(k, pieces - 1)]
        room = min(_space(tm, side[0], corner.p, corner.a, cache),
                   _space(tm, side[1], corner.p, corner.b, cache))
        largest = min(largest, room * math.tan(corner.angle / 2.0) if rounded else room)
    if size > largest + 1e-9:
        hint = (f"Try {_round_down(largest):.1f} mm or less." if largest >= 0.1
                else "There is no room for one here.")
        raise BuildError(f"That {what} is too big for the faces next to the edge. {hint}")

    arc = max(2, max(math.ceil(ARC_SEGMENTS * (math.pi - c.angle) / (2.0 * math.pi)) for c in corners))
    rings = []
    for k, corner in enumerate(corners):
        set_back = corner.set_back(size) if rounded else size
        ring = corner.ring(set_back, size if rounded else None, arc)
        if run.convex and not run.closed and k in (0, count - 1):
            # Reaching just past the ends of an outside edge cuts only air.
            ring = ring + (NUDGE if k else -NUDGE) * corner.t
        rings.append(ring)
    # Each ring's points go anticlockwise seen from behind, looking along the run.
    first = corners[0]
    flat = np.column_stack([(rings[0] - first.p) @ first.a, (rings[0] - first.p) @ np.cross(first.t, first.a)])
    if sketch.signed_area(flat) < 0.0:
        rings = [r[::-1].copy() for r in rings]
    for k in range(pieces):
        step = rings[(k + 1) % count] - rings[k]
        if (step @ corners[k].t).min() <= 1e-9 and (step @ corners[(k + 1) % count].t).min() <= 1e-9:
            raise BuildError(f"That {what} is too big for how tightly this edge bends. Try a smaller size.")

    vertices = np.vstack(rings)
    faces = [_skin([[r] for r in rings], run.closed)]
    if not run.closed:
        for k, facing, offset in ((0, -corners[0].t, 0), (count - 1, corners[-1].t, len(rings[0]) * (count - 1))):
            c = corners[k]
            outline = np.column_stack([(rings[k] - c.p) @ c.a, (rings[k] - c.p) @ np.cross(c.t, c.a)])
            faces.append(_cap([outline], rings[k], offset, facing))
    try:
        piece = _solid_from(vertices, np.vstack(faces), what)
    except sketch.SketchError as exc:
        raise BuildError(NOT_CLEAN) from exc
    return tm, run, piece


def _edge_group(shape, face_index: int, point, size: float, rounded: bool, clearances):
    tm, run, piece = _edge_piece(shape, face_index, point, size, rounded, clearances)
    name = "Rounded edge" if rounded else "Bevelled edge"
    child = _baked_child(piece, name, shape.color, is_hole=run.convex)
    label = "rounded" if rounded else "chamfered"
    try:
        group = _group([copy.deepcopy(shape), child], f"{shape.name} ({label})", clearances)
    except NothingToCombineError as exc:
        raise BuildError(NOT_CLEAN) from exc
    if abs(shape_geometry(group).volume - tm.volume) < 1e-9:
        raise BuildError(NOT_CLEAN)
    return group


def fillet(shape, face_index: int, point, radius: float, clearances: dict | None = None):
    """The edge next to the click rounded to `radius` mm, along its run (see
    the module notes). A group of the part and the piece cut away (an
    outside edge) or added (an inside edge)."""
    return _edge_group(shape, face_index, point, radius, True, clearances)

