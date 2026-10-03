"""Tools that turn one part into something new: hollow out, split, box with lid.

Each one returns ordinary group shapes built from ordinary children (the
original part, Holes, pegs), so Ungroup always gives the pieces back, and
everything goes through the same Solid/Hole evaluation as Group -- which is
what keeps the results watertight.

Every function raises BuildError with a plain-language message, and changes
nothing, when the request can't be met. The caller snapshots only after a
call succeeds.
"""

import copy
import uuid

import numpy as np

from mesh.blobs import encode_mesh
from mesh.ops import make_group
from mesh.scene import Shape, new_primitive
from mesh.shapes import PRIMITIVES, shape_geometry
from mesh.solids import from_manifold, m3, to_manifold


class BuildError(Exception):
    """A tool could not do what was asked; the message says why, plainly."""


def _lift(transform, dz: float) -> np.ndarray:
    """`transform` with a move of `dz` along the shape's own up direction
    applied first, so an inset child follows a turned or mirrored parent."""
    local = np.eye(4, dtype=np.float64)
    local[2, 3] = dz
    return np.asarray(transform, dtype=np.float64) @ local


def _hole_child(primitive: str, params: dict, transform, color: str, name: str) -> Shape:
    child = new_primitive(primitive, name=name)
    child.params.update(params)
    child.transform = np.asarray(transform, dtype=np.float64).copy()
    child.is_hole = True
    child.color = color
    return child


def _baked_child(tm, name: str, color: str, is_hole: bool) -> Shape:
    return Shape(
        id=uuid.uuid4().hex,
        name=name,
        kind="imported",
        params={"blob": encode_mesh(tm), "source": name},
        transform=np.eye(4, dtype=np.float64),
        color=color,
        is_hole=is_hole,
    )


# --- Hollow out -----------------------------------------------------------

EXACT_HOLLOW = ("cube", "cylinder", "sphere")
APPROXIMATE_FACE_LIMIT = 20000


def hollows_exactly(shape: Shape) -> bool:
    """Box, cylinder and sphere hollow exactly (an inset copy of the same
    shape is cut out). Everything else is hollowed approximately."""
    return shape.kind == "primitive" and shape.params.get("primitive") in EXACT_HOLLOW


def hollow(
    shape: Shape,
    wall: float,
    open_top: bool = False,
    drain: float = 0.0,
    clearances: dict | None = None,
) -> Shape:
    """Return a group: the part with its inside cut away, leaving `wall` mm.

    `open_top` takes the top wall away too (box, cylinder, sphere only).
    `drain` > 0 adds a hole of that diameter through the bottom, so resin or
    powder can run out of a closed part.
    """
    wall = float(wall)
    drain = float(drain)
    if shape.is_hole:
        raise BuildError("Hollow out works on solid parts. This one is a Hole.")
    if wall <= 0.0:
        raise BuildError("The wall thickness must be more than 0 mm.")
    if drain < 0.0:
        raise BuildError("The drain hole size can't be less than 0 mm.")

    if hollows_exactly(shape):
        holes = _exact_cavity(shape, wall, open_top, drain)
    else:
        if open_top:
            raise BuildError(
                "Open top works on boxes, cylinders and spheres. "
                "Untick Open top to hollow out this shape."
            )
        holes = _approximate_cavity(shape, wall, drain, clearances)

    label = PRIMITIVES[shape.params["primitive"]]["label"] if shape.kind == "primitive" else shape.name
    original = copy.deepcopy(shape)
    return make_group([original] + holes, name=f"Hollow {label.lower()}", clearances=clearances)


def _too_thick(limit: float) -> BuildError:
    return BuildError(
        f"That wall is too thick for this part. Try a wall thinner than {limit:.1f} mm."
    )


def _exact_cavity(shape: Shape, t: float, open_top: bool, drain: float) -> list[Shape]:
    kind = shape.params["primitive"]
    p = {**PRIMITIVES[kind]["defaults"], **shape.params}
    color, transform = shape.color, shape.transform
    holes = []

    if kind == "sphere":
        d = float(p["diameter"])
        if 2.0 * t >= d:
            raise _too_thick(d / 2.0)
        inner = d - 2.0 * t
        holes.append(_hole_child("sphere", {"diameter": inner}, _lift(transform, t), color, "Inside"))
        if open_top:
            holes.append(_hole_child(
                "cylinder", {"diameter": inner, "height": d / 2.0 + 1.0},
                _lift(transform, d / 2.0), color, "Open top",
            ))
        footprint = inner
    else:
        if kind == "cube":
            sizes = (float(p["width"]), float(p["depth"]))
        else:
            sizes = (float(p["diameter"]),)
        h = float(p["height"])
        limit = min(min(sizes) / 2.0, h if open_top else h / 2.0)
        if t >= limit:
            raise _too_thick(limit)
        # Open top: the inside runs 1 mm past the top so the top wall is
        # cut clean away rather than left as a face-thin skin.
        inner_h = h - t + 1.0 if open_top else h - 2.0 * t
        if kind == "cube":
            params = {"width": sizes[0] - 2.0 * t, "depth": sizes[1] - 2.0 * t, "height": inner_h}
        else:
            params = {"diameter": sizes[0] - 2.0 * t, "height": inner_h}
        holes.append(_hole_child(kind, params, _lift(transform, t), color, "Inside"))
        footprint = min(sizes) - 2.0 * t

    if drain > 0.0:
        if drain >= footprint:
            raise BuildError(
                f"That drain hole is wider than the inside of the part. "
                f"Try less than {footprint:.1f} mm."
            )
        holes.append(_hole_child(
            "cylinder", {"diameter": drain, "height": t + 2.0},
            _lift(transform, -1.0), color, "Drain hole",
        ))
    return holes


def _approximate_cavity(shape: Shape, t: float, drain: float, clearances) -> list[Shape]:
    outside = shape_geometry(shape, clearances)
    if len(outside.faces) > APPROXIMATE_FACE_LIMIT:
        raise BuildError("This part is too detailed to hollow out.")
    # Shrinking the part evenly by the wall thickness: the inside is every
    # point at least `t` from the outside surface. The ball is a 24-sided
    # approximation, which is why this path is labelled approximate.
    inside = to_manifold(outside).minkowski_difference(m3.Manifold.sphere(t, 24))
    if inside.is_empty() or inside.volume() < 1e-3:
        raise BuildError(
            "That wall is too thick for this part: there would be no space left inside. "
            "Try a thinner wall."
        )
    holes = [_baked_child(from_manifold(inside), "Inside", shape.color, is_hole=True)]

    if drain > 0.0:
        low, high = inside.bounding_box()[:3], inside.bounding_box()[3:]
        centre = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)
        bottom = float(outside.bounds[0][2]) - 1.0
        top = float(low[2]) + min(1.0, (high[2] - low[2]) / 2.0)
        tube = m3.Manifold.cylinder(top - bottom, drain / 2.0, drain / 2.0, 32).translate(
            (centre[0], centre[1], bottom)
        )
        if (tube ^ inside).volume() < 1e-3:
            raise BuildError("There is no room for a drain hole under the inside of this part.")
        holes.append(_baked_child(from_manifold(tube), "Drain hole", shape.color, is_hole=True))
    return holes


# --- Split part -------------------------------------------------------------

AXIS_VECTORS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
PEG_MARGIN = 1.5     # mm of material kept between a peg and the edge of the cut face
PEG_EMBED = 1.0      # mm a peg reaches back into its own half, so it joins solidly
HOLE_EXTRA = 0.5     # mm a peg hole is deeper than the peg, so the halves close fully
PEG_FIT = "snug"
SPLIT_GAP = 10.0     # mm between the two halves once they are laid out


def _cylinder_along(point, direction, start: float) -> np.ndarray:
    """Transform for a cylinder primitive whose axis runs along `direction`,
    its base at `point + start * direction`."""
    from mesh.ops import rotation_between

    direction = np.asarray(direction, dtype=np.float64)
    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = rotation_between((0.0, 0.0, 1.0), direction)
    out[:3, 3] = np.asarray(point, dtype=np.float64) + start * direction
    return out


def _peg_spots(tm, origin, normal, radius: float) -> list[np.ndarray]:
    """Up to two points on the cut face with room for a peg of `radius`."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    section = tm.section(plane_origin=origin, plane_normal=normal)
    if section is None:
        return []
    planar, to_3d = section.to_2D()
    face = unary_union(list(planar.polygons_full))
    room = face.buffer(-(radius + PEG_MARGIN))
    if room.is_empty:
        return []

    spots_2d = []
    # Two pegs, spread along the long direction of the face, stop the halves
    # from turning against each other; fall back to one where only one fits.
    rect = room.minimum_rotated_rectangle
    corners = np.asarray(rect.exterior.coords)[:4] if rect.geom_type == "Polygon" else None
    if corners is not None:
        edges = [corners[1] - corners[0], corners[2] - corners[1]]
        long_edge = max(edges, key=np.linalg.norm)
        centre = np.asarray(room.centroid.coords[0])
        reach = np.linalg.norm(long_edge)
        unit = long_edge / max(reach, 1e-9)
        line = LineString([centre - unit * reach, centre + unit * reach]).intersection(room)
        segments = [line] if line.geom_type == "LineString" else list(getattr(line, "geoms", []))
        segments = [s for s in segments if s.geom_type == "LineString" and s.length > 0]
        if segments:
            longest = max(segments, key=lambda s: s.length)
            a = np.asarray(longest.interpolate(0.2, normalized=True).coords[0])
            b = np.asarray(longest.interpolate(0.8, normalized=True).coords[0])
            spots_2d = [a, b] if np.linalg.norm(a - b) >= 2.0 * radius + PEG_MARGIN else [(a + b) / 2.0]
    if not spots_2d:
        spots_2d = [np.asarray(room.representative_point().coords[0])]

    to_3d = np.asarray(to_3d, dtype=np.float64)
    return [(to_3d @ np.array([p[0], p[1], 0.0, 1.0]))[:3] for p in spots_2d]


def _inside(piece: "m3.Manifold", probe: "m3.Manifold") -> bool:
    return (piece ^ probe).volume() >= probe.volume() * 0.995


def split(
    shape: Shape,
    axis: str,
    position: float,
    pegs: bool = False,
    peg_diameter: float = 4.0,
    clearances: dict | None = None,
) -> tuple[Shape, Shape]:
    """Cut a part in two across a flat plane, ready to print.

    `axis` is the direction the cut crosses: "z" cuts flat at height
    `position`, "x" / "y" cut upright at that X / Y (world mm). With `pegs`,
    the lower / left / front half gets pegs and the other half gets matching
    Snug-fit Holes. Both halves come back as groups, laid out side by side
    on the workplane: each half without pegs rests on its cut face; a half
    with pegs rests the other way up, pegs pointing up, since pegs facing
    the bed would not print.
    """
    from mesh.ops import lay_flat

    if axis not in AXIS_VECTORS:
        raise ValueError(f"unknown axis {axis!r}")
    if shape.is_hole:
        raise BuildError("Split works on solid parts. This one is a Hole.")
    normal = np.asarray(AXIS_VECTORS[axis])
    index = "xyz".index(axis)
    tm = shape_geometry(shape, clearances)
    low, high = float(tm.bounds[0][index]), float(tm.bounds[1][index])
    position = float(position)
    if not low + 0.01 < position < high - 0.01:
        raise BuildError(
            f"That cut misses the part. Pick a position between {low:.1f} and {high:.1f} mm."
        )

    whole = to_manifold(tm)
    upper, lower = whole.split_by_plane(tuple(normal), position)
    if upper.is_empty() or lower.is_empty() or min(upper.volume(), lower.volume()) < 1e-3:
        raise BuildError("That cut misses the part. Try a position through the middle of it.")

    origin = normal * position
    peg_children, hole_children = [], []
    if pegs:
        radius = float(peg_diameter) / 2.0
        if radius <= 0.0:
            raise BuildError("The peg size must be more than 0 mm.")
        length = float(peg_diameter)
        c = float((clearances or {}).get(PEG_FIT, 0.0))
        for spot in _peg_spots(tm, origin, normal, radius):
            hole_probe = m3.Manifold.cylinder(length + HOLE_EXTRA + c, radius + c, radius + c, 32)
            hole_probe = hole_probe.transform(_cylinder_along(spot, normal, 0.01)[:3, :])
            peg_probe = m3.Manifold.cylinder(PEG_EMBED, radius, radius, 32)
            peg_probe = peg_probe.transform(_cylinder_along(spot, normal, -PEG_EMBED - 0.01)[:3, :])
            if not (_inside(upper, hole_probe) and _inside(lower, peg_probe)):
                continue
            peg = new_primitive("cylinder", name="Peg")
            peg.params.update(diameter=2.0 * radius, height=PEG_EMBED + length)
            peg.transform = _cylinder_along(spot, normal, -PEG_EMBED)
            peg.color = shape.color
            peg_children.append(peg)
            hole = _hole_child(
                "cylinder", {"diameter": 2.0 * radius, "height": length + HOLE_EXTRA + 0.5},
                _cylinder_along(spot, normal, -0.5), shape.color, "Peg hole",
            )
            hole.fit = PEG_FIT
            hole_children.append(hole)
        if not peg_children:
            raise BuildError(
                "There isn't room for pegs on that cut. Try smaller pegs, a different "
                "position, or no pegs."
            )

    first = make_group(
        [_baked_child(from_manifold(lower), "Part 1", shape.color, False)] + peg_children,
        name=f"{shape.name} (part 1)", clearances=clearances,
    )
    second = make_group(
        [_baked_child(from_manifold(upper), "Part 2", shape.color, False)] + hole_children,
        name=f"{shape.name} (part 2)", clearances=clearances,
    )

    lay_flat(first, -normal if pegs else normal)
    lay_flat(second, -normal)

    centre = tm.bounds.mean(axis=0)
    b1, b2 = shape_geometry(first).bounds, shape_geometry(second).bounds
    w1, w2 = b1[1][0] - b1[0][0], b2[1][0] - b2[0][0]
    start = centre[0] - (w1 + SPLIT_GAP + w2) / 2.0
    for part, bounds, x0 in ((first, b1, start), (second, b2, start + w1 + SPLIT_GAP)):
        part.transform = np.asarray(part.transform, dtype=np.float64).copy()
        part.transform[0, 3] += x0 - bounds[0][0]
        part.transform[1, 3] += centre[1] - (bounds[0][1] + bounds[1][1]) / 2.0
    return first, second


# --- Patterns ---------------------------------------------------------------

MAX_COPIES = 500


def _check_count(count: int) -> int:
    count = int(count)
    if count < 2:
        raise BuildError("A pattern needs at least 2 parts.")
    if count > MAX_COPIES:
        raise BuildError(f"That is too many copies. Try {MAX_COPIES} or fewer.")
    return count


def _copy(shape: Shape) -> Shape:
    """An independent copy: new id, its own params and transform, and the
    same Solid/Hole flag and fit."""
    clone = copy.deepcopy(shape)
    clone.id = uuid.uuid4().hex
    clone.transform = np.asarray(clone.transform, dtype=np.float64).copy()
    return clone


def repeat_row(shape: Shape, count: int, spacing: float, axis: str = "x") -> list[Shape]:
    """`count` parts in a straight line, `spacing` mm apart (centre to centre)
    along X or Y. `count` includes the original; returns the new copies."""
    count = _check_count(count)
    if axis not in ("x", "y"):
        raise ValueError(f"unknown axis {axis!r}")
    if float(spacing) <= 0.0:
        raise BuildError("The spacing must be more than 0 mm.")
    index = "xyz".index(axis)
    copies = []
    for i in range(1, count):
        clone = _copy(shape)
        clone.transform[index, 3] += i * float(spacing)
        copies.append(clone)
    return copies


def repeat_circle(
    shape: Shape, count: int, radius: float, centre, angle: float = 360.0
) -> tuple[np.ndarray, list[Shape]]:
    """`count` parts around a vertical line through `centre` (X, Y).

    The original is moved straight out (or in) to `radius` from the centre,
    keeping its direction from it; the copies follow round the circle, each
    turned to face out the same way. A full 360 degrees spaces them evenly
    all the way round; a smaller angle puts the first and last part exactly
    that far apart. `count` includes the original.

    Returns (the original's new transform, the new copies). Nothing is
    changed until the caller applies them.
    """
    from mesh.ops import rotate_about

    count = _check_count(count)
    radius, angle = float(radius), float(angle)
    if radius <= 0.0:
        raise BuildError("The circle's radius must be more than 0 mm.")
    if not 0.0 < angle <= 360.0:
        raise BuildError("The angle must be more than 0 and at most 360 degrees.")

    centre = np.asarray(centre, dtype=np.float64)[:2]
    position = shape_geometry(shape).bounds.mean(axis=0)
    outward = position[:2] - centre
    length = float(np.linalg.norm(outward))
    outward = outward / length if length > 1e-9 else np.array([1.0, 0.0])

    placed = _copy(shape)
    placed.transform[:2, 3] += centre + outward * radius - position[:2]

    full = angle >= 360.0 - 1e-9
    step = angle / count if full else angle / (count - 1)
    pivot = (centre[0], centre[1], 0.0)
    copies = []
    for i in range(1, count):
        clone = _copy(placed)
        turn = np.radians(i * step)
        c, s = np.cos(turn), np.sin(turn)
        rotate_about(clone, np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]), pivot)
        copies.append(clone)
    return placed.transform, copies


# --- Box with lid -----------------------------------------------------------

LID_GAP = 10.0   # mm between the box and its lid once laid out
MAX_LIP = 3.0    # mm the lid's lip reaches down into the box


def _box(name: str, width: float, depth: float, height: float, z: float,
         color: str, is_hole: bool = False) -> Shape:
    part = new_primitive("cube", name=name)
    part.params.update(width=width, depth=depth, height=height)
    part.transform[2, 3] = z
    part.color = color
    part.is_hole = is_hole
    return part


def box_with_lid(
    width: float,
    depth: float,
    height: float,
    wall: float,
    lid_height: float,
    fit: str = "snug",
    clearances: dict | None = None,
    color: str = "#4a90d9",
) -> tuple[Shape, Shape]:
    """A hollow box and a lid that drops onto it, ready to print.

    `height` is the closed box's total outside height; the lid takes
    `lid_height` of it. The inner half of the box's wall is cut away at the
    top (a recess), and the lid has a matching lip that drops into it,
    `fit` clearance smaller on every side. Returns (box, lid) as groups,
    side by side on the workplane, the lid upside down so its lip points up.
    """
    from mesh.ops import drop_to_plane, rotate_about

    w, d, h, t, hl = (float(v) for v in (width, depth, height, wall, lid_height))
    c = float((clearances or {}).get(fit, 0.0)) if fit != "exact" else 0.0
    if min(w, d, h) <= 0.0:
        raise BuildError("The box's width, depth and height must all be more than 0 mm.")
    if t <= 0.0:
        raise BuildError("The wall thickness must be more than 0 mm.")
    if 2.0 * t >= min(w, d) - 1.0:
        raise BuildError("That wall is too thick for a box this size. Try a thinner wall.")
    if hl < t:
        raise BuildError("The lid must be at least as tall as the wall is thick.")
    body_h = h - hl
    if body_h < t + 1.0:
        raise BuildError("The lid is too tall for this box. Try a shorter lid or a taller box.")
    lip_wall = t / 2.0 - c
    if lip_wall < 0.4:
        raise BuildError(
            f"The wall is too thin for a lip with that fit. "
            f"Try a wall of at least {2.0 * (0.4 + c):.1f} mm."
        )
    lip = min(MAX_LIP, (body_h - t) / 2.0)

    inner_w, inner_d = w - 2.0 * t, d - 2.0 * t
    body = make_group([
        _box("Box", w, d, body_h, 0.0, color),
        _box("Inside", inner_w, inner_d, body_h - t + 1.0, t, color, is_hole=True),
        _box("Lip recess", w - t, d - t, lip + 1.0, body_h - lip, color, is_hole=True),
    ], name="Box", clearances=clearances)

    # Built closed (the lid's underside at Z = 0, lip hanging below it), then
    # flipped for printing.
    lip_drop = lip - c
    lid = make_group([
        _box("Lid", w, d, hl, 0.0, color),
        _box("Lip", w - t - 2.0 * c, d - t - 2.0 * c, lip_drop + 0.5, -lip_drop, color),
        _box("Inside", inner_w, inner_d, (hl - t) + lip_drop + 1.0, -lip_drop - 1.0, color,
             is_hole=True),
    ], name="Lid", clearances=clearances)
    rotate_about(lid, np.diag([1.0, -1.0, -1.0]), (0.0, 0.0, 0.0))
    drop_to_plane(lid)
    lid.transform[0, 3] += w + LID_GAP
    return body, lid
