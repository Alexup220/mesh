"""Changing parts that already exist: Expert mode's Modify tools.

Every function here returns new shapes (or changed copies) and leaves the
scene alone; the window snapshots and applies the result only when the call
succeeds. A request that can't be met raises BuildError with a plain
message, and changes nothing.

Tools that change a part's shape return ordinary groups built from the part
plus pieces cut away or added (as Hollow out and Split do), so Ungroup gives
the original back.
"""

import copy
import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

from mesh import features, sketch
from mesh.builders import (
    APPROXIMATE_FACE_LIMIT,
    GUIDES_ARE_NOT_PARTS,
    NOT_CLEAN,
    BuildError,
    _baked_child,
    _group,
    _hole_child,
)
from mesh.ops import (
    AXES,
    NothingLeftError,
    NothingToCombineError,
    _canonical,
    fresh_ids,
    make_boolean_group,
    rotate_about,
    rotation_between,
)
from mesh.scene import new_primitive
from mesh.shapes import HARDWARE_PRIMITIVES, default_params, is_reference, primitive_mesh, shape_geometry
from mesh.solids import from_manifold, m3, to_manifold

MOVE_LIMIT = 10000.0  # mm: the furthest one move may go along each line


def _bounds(shapes) -> np.ndarray:
    """The box around all of `shapes` together: [[low x, y, z], [high x, y, z]]."""
    boxes = np.array([shape_geometry(s).bounds for s in shapes])
    return np.array([boxes[:, 0].min(axis=0), boxes[:, 1].max(axis=0)])


def _axis_turn(axis: str, degrees: float) -> np.ndarray:
    """The rotation of `degrees` about the world line `axis`, anticlockwise
    seen from the line's positive end."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    i = AXES[axis]
    j, k = (i + 1) % 3, (i + 2) % 3
    turn = np.eye(3)
    turn[j, j], turn[j, k], turn[k, j], turn[k, k] = c, -s, s, c
    return turn


# --- Move or Copy -----------------------------------------------------------------


def move_copy(shapes, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
              axis: str = "z", angle: float = 0.0, make_copy: bool = False) -> list:
    """`shapes` turned `angle` degrees about a line along `axis` through
    their middle, then moved (dx, dy, dz) mm. Exact for every kind of shape.

    Returns changed copies: with `make_copy` they are new shapes with new
    ids, to add beside the originals; otherwise they keep the originals'
    ids, for the caller to put in their place.
    """
    shapes = list(shapes)
    if not shapes:
        raise BuildError("Select the parts to move first.")
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}")
    values = [float(v) for v in (dx, dy, dz, angle)]
    if not all(math.isfinite(v) for v in values):
        raise BuildError("Type ordinary numbers for the move and the turn.")
    if max(abs(v) for v in values[:3]) > MOVE_LIMIT:
        raise BuildError(f"One move can go at most {MOVE_LIMIT:g} mm each way.")
    if abs(values[3]) > 360.0:
        raise BuildError("A turn can be at most 360 degrees either way.")

    moved = [fresh_ids(copy.deepcopy(s)) if make_copy else copy.deepcopy(s) for s in shapes]
    if values[3] != 0.0:
        centre = _bounds(shapes).mean(axis=0)
        turn = _axis_turn(axis, values[3])
        for shape in moved:
            rotate_about(shape, turn, centre)
    for shape in moved:
        shape.transform = np.asarray(shape.transform, dtype=np.float64).copy()
        shape.transform[:3, 3] += values[:3]
    return moved


# --- Flat faces ---------------------------------------------------------------------

CLICK_A_FACE = "Click on a face of a part."


@dataclass
class FlatFace:
    """The flat face a click landed on: every triangle lying flat and
    joined with the clicked one (so a box's top or a cylinder's end is one
    face; on a round surface, the one narrow flat strip clicked)."""

    normal: np.ndarray   # the way it faces, out of the part (world)
    centre: np.ndarray   # the middle of its area (world)
    frame: np.ndarray    # a sketch plane on it, Z along `normal`
    region: object       # its area in that plane's coordinates (shapely)
    faces: np.ndarray    # the triangles it is made of


def flat_face(shape, face_index: int, clearances: dict | None = None) -> FlatFace:
    """The flat face of `shape` containing triangle `face_index`, counted as
    the 3D view draws it (with the scene's fit clearances)."""
    tm = shape_geometry(shape, clearances)
    if not 0 <= face_index < len(tm.faces):
        raise BuildError(CLICK_A_FACE)
    faces = np.array([face_index])
    for facet in tm.facets:
        if face_index in facet:
            faces = np.asarray(facet)
            break
    areas = tm.area_faces[faces]
    normal = (tm.face_normals[faces] * areas[:, None]).sum(axis=0)
    if areas.sum() < 1e-12 or np.linalg.norm(normal) < 1e-12:
        raise BuildError(CLICK_A_FACE)
    normal = normal / np.linalg.norm(normal)
    centre = (tm.triangles_center[faces] * areas[:, None]).sum(axis=0) / areas.sum()
    frame = sketch.plane_frame(normal, centre)
    flat = sketch.to_sketch(frame, tm.triangles[faces].reshape(-1, 3)).reshape(-1, 3, 2)
    region = unary_union([Polygon(t) for t, a in zip(flat, areas) if a > 1e-12]).buffer(0)
    return FlatFace(normal, centre, frame, region, faces)


# --- Align face to face ---------------------------------------------------------------


def align_faces(moving, moving_face: int, target, target_face: int,
                clearances: dict | None = None) -> np.ndarray:
    """The transform that puts a flat face of `moving` against a flat face
    of `target`: the two faces touch, facing each other, with the middle
    of the first on the middle of the second. Exact; `moving` is turned
    the least it can be. Nothing is changed here."""
    if moving.id == target.id:
        raise BuildError("Click a face of a different part to put this one against.")
    if is_reference(moving) or is_reference(target):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Align"))
    first = flat_face(moving, moving_face, clearances)
    second = flat_face(target, target_face, clearances)
    turn = np.eye(4)
    turn[:3, :3] = rotation_between(first.normal, -second.normal)
    to_origin, to_target = np.eye(4), np.eye(4)
    to_origin[:3, 3] = -first.centre
    to_target[:3, 3] = second.centre
    return _canonical(to_target @ turn @ to_origin @ np.asarray(moving.transform, dtype=np.float64))


# --- Scale ----------------------------------------------------------------------------

SCALE_LIMITS = (0.01, 100.0)    # the smallest and largest factor in one scale
SIZE_LIMITS = (0.1, 10000.0)    # mm: a size number must stay within the Details panel's range
_ZERO_ALLOWED = ("radius", "chamfer")
SCALE_ABOUT = ("base", "centre")

# How each kind's size numbers follow a stretch along its own X, Y and Z:
# "x", "y", "z" one direction; "across" its own X and Y, which must stretch
# alike (it is round across); "all" every direction, which must stretch
# alike; "detail" a rounding or bottom bevel, which keeps its size unless
# every direction stretches alike.
_FOLLOWS = {
    "cube": {"width": "x", "depth": "y", "height": "z", "chamfer": "detail"},
    "wedge": {"width": "x", "depth": "y", "height": "z"},
    "pyramid": {"width": "x", "depth": "y", "height": "z"},
    "rounded_box": {"width": "x", "depth": "y", "height": "z", "radius": "detail", "chamfer": "detail"},
    "sphere": {"diameter": "all"},
    "cylinder": {"diameter": "across", "height": "z", "chamfer": "detail"},
    "cone": {"diameter": "across", "height": "z"},
    "tube": {"diameter": "across", "wall": "across", "height": "z"},
    "torus": {"diameter": "all", "thickness": "all"},
    "rounded_cylinder": {"diameter": "across", "height": "z", "radius": "detail", "chamfer": "detail"},
    "text": {"letter_height": "across", "depth": "z"},
    "extrude": {"distance": "z"},
    "thread": {"diameter": "across", "height": "z", "thread_length": "z", "pitch": "detail"},
    "coil": {"diameter": "all", "pitch": "all", "wire": "all"},
    "pipe": {"diameter": "all", "wall": "all"},
}


def _stretch_refusal(name: str, why: str, across: bool = False, group: bool = True) -> BuildError:
    how = ("must be scaled the same amount in both directions across it" if across
           else "can only be scaled the same amount in every direction")
    hint = " To stretch it anyway, Group it first: a group can be stretched any way." if group else ""
    return BuildError(f"{name} {why}, so it {how}.{hint}")


def _own_factors(shape, factors: np.ndarray) -> np.ndarray:
    """The stretch along the shape's own X, Y and Z for the world stretch
    `factors`. Different amounts need each of its own directions to lie
    along one of the world's (it is turned by whole quarter turns only)."""
    if np.allclose(factors, factors[0], rtol=1e-12, atol=0.0):
        return np.full(3, factors[0])
    linear = np.asarray(shape.transform, dtype=np.float64)[:3, :3]
    out = []
    for column in linear.T:
        length = np.linalg.norm(column)
        along = np.abs(column) / max(length, 1e-12)
        if along.max() < 1.0 - 1e-9:
            raise _stretch_refusal(shape.name, "is turned")
        out.append(factors[int(np.argmax(along))])
    return np.array(out)


def _alike(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9)


def _scaled_entities(shape, entities, factor: float) -> list:
    try:
        return sketch.scaled_entities(entities, factor)
    except sketch.SketchError as exc:
        raise BuildError(f"{shape.name} can't be scaled that much. {exc}") from exc


def _scaled_params(shape, own: np.ndarray) -> dict:
    """`shape`'s params with its sizes stretched by `own` along its own X,
    Y and Z, about its own origin."""
    kind = shape.params["primitive"]
    params = copy.deepcopy(shape.params)
    own = [float(v) for v in own]
    uniform = _alike(own[0], own[1]) and _alike(own[0], own[2])
    across = _alike(own[0], own[1])
    if is_reference(shape):
        if not across:
            raise _stretch_refusal(shape.name, "is a flat drawing of curves", across=True, group=False)
        params["entities"] = _scaled_entities(shape, params["entities"], own[0])
        return params
    if kind in ("revolve", "sweep", "loft", "pipe") and not uniform:
        raise _stretch_refusal(shape.name, "is made from a sketch")
    if kind == "extrude":
        if not across:
            raise _stretch_refusal(shape.name, "is made from a sketch's curves", across=True)
        entities = params.get("entities") or features.default_entities("extrude")
        params["entities"] = _scaled_entities(shape, entities, own[0])
        taper = float(params.get("taper", 0.0))
        if taper and not uniform:
            # Sloped sides stay flat: how far in they go per mm along
            # stretches with the outline, and the mm along with the distance.
            params["taper"] = math.degrees(math.atan(math.tan(math.radians(taper)) * own[0] / own[2]))
    elif kind == "revolve":
        entities = params.get("entities") or features.default_entities("revolve")
        params["entities"] = _scaled_entities(shape, entities, own[0])
        params["axis"] = [own[0] * float(v) for v in params.get("axis", features.DEFAULT_AXIS)]
    elif kind == "sweep":
        for key, default in (("entities", features.DEFAULT_SWEEP_PROFILE),
                             ("path_entities", features.DEFAULT_SWEEP_PATH)):
            params[key] = _scaled_entities(shape, params.get(key) or default, own[0])
        for key, default in (("profile_frame", features._FLAT), ("path_frame", features._UPRIGHT)):
            params[key] = _scaled_frame(params.get(key, default), own[0])
    elif kind == "pipe":
        params["path_entities"] = _scaled_entities(shape, params.get("path_entities") or features.DEFAULT_SWEEP_PATH,
                                                   own[0])
        params["path_frame"] = _scaled_frame(params.get("path_frame", features._UPRIGHT), own[0])
    elif kind == "loft":
        params["sections"] = [
            {"point": [own[0] * float(v) for v in section["point"]]} if "point" in section else
            {"entities": _scaled_entities(shape, section["entities"], own[0]),
             "frame": _scaled_frame(section["frame"], own[0])}
            for section in (params.get("sections") or features.DEFAULT_LOFT)
        ]

    factor = {"x": own[0], "y": own[1], "z": own[2]}
    for key, follows in _FOLLOWS.get(kind, {}).items():
        if key not in params:
            continue
        if follows == "all" and not uniform:
            raise _stretch_refusal(shape.name, "is round")
        if follows == "across" and not across:
            raise _stretch_refusal(shape.name, "is round", across=True)
        if follows == "detail":
            k = own[0] if uniform else 1.0
        elif follows in ("across", "all"):
            k = own[0]
        else:
            k = factor[follows]
        value = float(params[key]) * k
        low = 0.0 if key in _ZERO_ALLOWED else SIZE_LIMITS[0]
        if not low <= value <= SIZE_LIMITS[1]:
            raise BuildError(
                f"That would make {shape.name} {'smaller' if value < low else 'bigger'} than "
                f"the Details panel allows ({SIZE_LIMITS[0]:g} to {SIZE_LIMITS[1]:g} mm)."
            )
        params[key] = float(value)
    return params


def _scaled_frame(frame, factor: float) -> list:
    """A sketch plane placed in a sweep's or loft's own coordinates, with
    where it sits scaled by `factor` (it is not turned)."""
    frame = np.asarray(frame, dtype=np.float64).copy()
    frame[:3, 3] *= factor
    return frame.tolist()


def scaled(shapes, factors, about: str = "base", clearances: dict | None = None) -> list:
    """`shapes` scaled by `factors` (left/right, forward/back, up/down),
    about the middle of their base or their middle. Changed copies, with
    the originals' ids. Nothing is changed here.

    Size numbers are scaled, so a primitive stays editable: exactly, for
    the same amount in every direction. Different amounts need a shape
    whose sizes lie along the directions (a box turned by quarter turns,
    say); round directions must stretch alike, and a rounding or bottom
    bevel keeps its size. Imported parts and groups stretch any way, as
    their drag handles do. Hardware holes keep their standard sizes and
    move with the parts, their openings to where they were scaled to.
    """
    shapes = list(shapes)
    if not shapes:
        raise BuildError("Select the parts to scale first.")
    k = np.asarray([float(v) for v in factors], dtype=np.float64)
    if k.shape != (3,) or not np.isfinite(k).all():
        raise BuildError("Type ordinary numbers for the scale.")
    low, high = SCALE_LIMITS
    if k.min() < low - 1e-12 or k.max() > high + 1e-12:
        raise BuildError(f"Scale by between {low * 100:g}% and {high * 100:g}%.")
    if about not in SCALE_ABOUT:
        raise ValueError(f"unknown point to scale about {about!r}")
    box = _bounds(shapes)
    pivot = box.mean(axis=0)
    if about == "base":
        pivot[2] = box[0][2]
    stretch = np.diag(k)

    out = []
    for shape in shapes:
        changed = copy.deepcopy(shape)
        transform = np.asarray(shape.transform, dtype=np.float64).copy()
        if shape.kind != "primitive":
            # Imported parts and groups carry no sizes: the stretch goes in
            # their transform, as a drag of their handles does.
            whole = np.eye(4)
            whole[:3, :3], whole[:3, 3] = stretch, pivot - stretch @ pivot
            changed.transform = whole @ transform
        elif shape.params.get("primitive") in HARDWARE_PRIMITIVES:
            top = primitive_mesh(shape.params["primitive"], shape.params).bounds[1][2]
            opening = (transform @ np.array([0.0, 0.0, top, 1.0]))[:3]
            transform[:3, 3] += pivot + stretch @ (opening - pivot) - opening
            changed.transform = transform
        else:
            changed.params = _scaled_params(shape, _own_factors(shape, k))
            transform[:3, 3] = pivot + stretch @ (transform[:3, 3] - pivot)
            changed.transform = transform
            try:
                shape_geometry(changed, clearances)
            except (sketch.SketchError, ValueError) as exc:
                raise BuildError(f"{shape.name} can't be made at that size. {exc}") from exc
        out.append(changed)
    return out


# --- Combine --------------------------------------------------------------------------

COMBINE_OPS = {"union": "Join", "difference": "Cut", "intersection": "Keep overlap"}


def _parts_only(shapes, tool: str) -> None:
    if any(is_reference(s) for s in shapes):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool=tool))


def combine(target, tools, op: str, keep_tools: bool = False, clearances: dict | None = None):
    """`target` joined with the `tools`, cut by them, or kept only where it
    overlaps them, as a group that Ungroup takes apart again. With
    `keep_tools`, the tools also stay where they are: the group holds
    copies of them. Exact (as Join, Cut Out and Keep Overlap are)."""
    if op not in COMBINE_OPS:
        raise ValueError(f"unknown way to combine {op!r}")
    tools = [t for t in tools if t.id != target.id]
    if not tools:
        raise BuildError("Select the part to change and at least one other part to combine with it.")
    _parts_only([target, *tools], "Combine")
    children = [copy.deepcopy(target)] + [
        fresh_ids(copy.deepcopy(t)) if keep_tools else copy.deepcopy(t) for t in tools
    ]
    try:
        group = make_boolean_group(children, op, f"{target.name} ({COMBINE_OPS[op].lower()})", clearances)
    except NothingToCombineError as exc:
        raise BuildError(str(exc)) from exc
    group.color = target.color
    return group


# --- Split body -----------------------------------------------------------------------


def _half_space(origin, normal, size: float, color: str):
    """A Hole filling the side of a plane that `normal` points to, `size`
    mm across, its flat bottom exactly on the plane."""
    cutter = new_primitive("cube", name="Cut away")
    cutter.params.update(width=size, depth=size, height=size)
    cutter.transform[:3, :3] = rotation_between((0.0, 0.0, 1.0), normal)
    cutter.transform[:3, 3] = origin
    cutter.is_hole = True
    cutter.color = color
    return cutter


def split_body(part, tool, clearances: dict | None = None) -> list:
    """`part` cut in two where it stands: by the plane of the sketch or
    construction plane `tool` (the side it faces first), or by the part `tool` into the piece
    inside it and the piece outside. Each piece is a group of a copy of the
    part and what was cut away from it, so Ungroup gives the part back.
    Exact."""
    if part.id == tool.id:
        raise BuildError("Select the part to split and the sketch, plane or part to split it with.")
    if is_reference(part):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Split Body"))
    if part.is_hole:
        raise BuildError("Split Body works on solid parts. This one is a Hole.")
    tm = shape_geometry(part, clearances)

    def copy_of(shape):
        return fresh_ids(copy.deepcopy(shape))

    if is_reference(tool):
        if tool.params.get("primitive") not in ("sketch", "plane"):
            raise BuildError("Split Body cuts along a sketch's plane or a construction plane, not "
                             f"along {tool.name}. Select a sketch, a plane or a part to split with.")
        frame = np.asarray(tool.transform, dtype=np.float64)
        normal = frame[:3, 2] / np.linalg.norm(frame[:3, 2])
        offset = float(normal @ frame[:3, 3])
        sides = to_manifold(tm).split_by_plane(tuple(normal), offset)
        if min(side.volume() for side in sides) < 1e-3:
            raise BuildError(
                f"The plane of {tool.name} misses {part.name}. Move it so its plane goes "
                "through the part."
            )
        centre = tm.bounds.mean(axis=0)
        origin = centre - (normal @ centre - offset) * normal
        # The plane crosses the part, so no point of it is further than the
        # length of its box's diagonal from `origin`.
        size = 2.0 * float(np.linalg.norm(tm.bounds[1] - tm.bounds[0])) + 2.0
        return [
            _group([copy_of(part), _half_space(origin, -normal, size, part.color)],
                   f"{part.name} (piece 1)", clearances),
            _group([copy_of(part), _half_space(origin, normal, size, part.color)],
                   f"{part.name} (piece 2)", clearances),
        ]

    inside_tool, outside_tool = copy_of(tool), copy_of(tool)
    for cutter, hole in ((inside_tool, False), (outside_tool, True)):
        cutter.is_hole, cutter.fit = hole, "exact"
    try:
        inside = make_boolean_group([copy_of(part), inside_tool], "intersection",
                                    f"{part.name} (inside {tool.name})", clearances)
    except NothingLeftError as exc:
        raise BuildError(f"{tool.name} doesn't overlap {part.name}, so there is nothing to split.") from exc
    except NothingToCombineError as exc:
        raise BuildError(str(exc)) from exc
    try:
        outside = _group([copy_of(part), outside_tool], f"{part.name} (outside {tool.name})", clearances)
    except NothingLeftError as exc:
        raise BuildError(
            f"{tool.name} covers all of {part.name}, so nothing would be left outside it."
        ) from exc
    inside.color = outside.color = part.color
    return [inside, outside]


# --- Shell ----------------------------------------------------------------------------

REACH = 1.0  # mm an open face's room reaches out past the face, so the opening is clean


def _area(region) -> "m3.CrossSection":
    """A shapely area as the solid kernel's flat area (even-odd, so a hole
    in it stays a hole)."""
    polygons = [region] if region.geom_type == "Polygon" else list(getattr(region, "geoms", []))
    loops = []
    for polygon in polygons:
        if polygon.geom_type != "Polygon" or polygon.is_empty:
            continue
        loops.append(np.asarray(polygon.exterior.coords, dtype=np.float64)[:-1])
        loops.extend(np.asarray(ring.coords, dtype=np.float64)[:-1] for ring in polygon.interiors)
    return m3.CrossSection([np.ascontiguousarray(loop) for loop in loops if len(loop) >= 3],
                           m3.FillRule.EvenOdd)


def _prism(face: FlatFace, low: float, high: float, region=None):
    """The face's area (or `region`, in its plane) pushed from `low` to
    `high` mm along the way it faces, as a closed solid in the world."""
    solid = m3.Manifold.extrude(_area(face.region if region is None else region), high - low)
    tm = from_manifold(solid.translate((0.0, 0.0, low)))
    return tm.apply_transform(face.frame)


def _far_face(shape, face: FlatFace, clearances) -> FlatFace:
    """The flat face facing the opposite way that lies most across from
    `face` (the other end of a tube, say)."""
    tm = shape_geometry(shape, clearances)
    best, best_overlap, seen = None, 1e-6, set()
    for index in np.flatnonzero(tm.face_normals @ face.normal < -1.0 + 1e-6):
        if int(index) in seen:
            continue
        other = flat_face(shape, int(index), clearances)
        seen.update(int(i) for i in other.faces)
        across = sketch.to_sketch(face.frame, tm.triangles[other.faces].reshape(-1, 3)).reshape(-1, 3, 2)
        overlap = unary_union([Polygon(t) for t in across]).buffer(0).intersection(face.region).area
        if overlap > best_overlap:
            best, best_overlap = other, overlap
    if best is None:
        raise BuildError("There is no flat face across from the one you clicked to leave open too.")
    return best


def _own_direction(shape, normal) -> np.ndarray | None:
    """The shape's own axis direction (+-X, Y or Z) that `normal` (world)
    lies along, or None."""
    own = np.linalg.solve(np.asarray(shape.transform, dtype=np.float64)[:3, :3], normal)
    own = own / np.linalg.norm(own)
    i = int(np.argmax(np.abs(own)))
    if abs(own[i]) < 1.0 - 1e-6:
        return None
    out = np.zeros(3)
    out[i] = np.sign(own[i])
    return out


def shells_exactly(shape) -> bool:
    """Boxes and cylinders with no bottom chamfer shell exactly, through
    their flat sides and ends. Everything else is shelled approximately."""
    return (shape.kind == "primitive" and shape.params.get("primitive") in ("cube", "cylinder")
            and float(shape.params.get("chamfer", 0.0)) <= 0.0)


# Where a shell's walls go: inside the part (its outside keeps its shape),
# outside it (its inside keeps its shape), or half each side.
SHELL_WALLS = ("inside", "outside", "both")


def _wall_sides(wall: float, walls: str) -> tuple[float, float]:
    """(how far the walls reach in from the outside, how far out)."""
    if walls == "inside":
        return wall, 0.0
    if walls == "outside":
        return 0.0, wall
    if walls == "both":
        return wall / 2.0, wall / 2.0
    raise ValueError(f"unknown place for the walls {walls!r}")


def _box_child(shape, kind: str, low, high, name: str, is_hole: bool):
    """A box or cylinder (`kind`) filling `low`..`high` in `shape`'s own
    frame (a cylinder upright and centred), placed as `shape` is."""
    size = np.asarray(high) - np.asarray(low)
    params = ({"width": size[0], "depth": size[1], "height": size[2]} if kind == "cube"
              else {"diameter": size[0], "height": size[2]})
    place = np.eye(4)
    place[:3, 3] = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0, low[2])
    child = _hole_child(kind, {k: float(v) for k, v in params.items()},
                        np.asarray(shape.transform, dtype=np.float64) @ place, shape.color, name)
    child.is_hole = is_hole
    return child


def _exact_room(shape, wall: float, opens: list, walls: str = "inside") -> list | None:
    """The room inside a box or cylinder as one Hole of the same kind,
    reaching out through each open face (own directions in `opens`), and
    for walls outside the part, the walls' outside as a part of the same
    kind, grown on every side but the open ones. None if a face to open
    isn't one of its flat sides or ends."""
    kind = shape.params["primitive"]
    p = shape.params
    inner, outer = _wall_sides(wall, walls)
    if kind == "cube":
        half = np.array([float(p["width"]), float(p["depth"])]) / 2.0
        part_low = np.array([-half[0], -half[1], 0.0])
        part_high = np.array([half[0], half[1], float(p["height"])])
    else:
        r = float(p["diameter"]) / 2.0
        part_low = np.array([-r, -r, 0.0])
        part_high = np.array([r, r, float(p["height"])])
    low, high = part_low + inner, part_high - inner
    if (high - low).min() <= 0.0:
        limit = min(float(p.get("width", p.get("diameter"))), float(p.get("depth", p.get("diameter"))),
                    2.0 * float(p["height"])) / 2.0 * wall / inner
        raise BuildError(f"That wall is too thick for this part. Try a wall thinner than {limit:.1f} mm.")
    grown_low, grown_high = part_low - outer, part_high + outer
    for direction in opens:
        if kind == "cylinder" and direction[2] == 0.0:
            return None
        i = int(np.argmax(np.abs(direction)))
        if direction[i] > 0:
            high[i] += inner + REACH
            grown_high[i] = part_high[i]
        else:
            low[i] -= inner + REACH
            grown_low[i] = part_low[i]
    room = [_box_child(shape, kind, low, high, "Inside", True)]
    if outer > 0.0:
        room.insert(0, _box_child(shape, kind, grown_low, grown_high, "Walls", False))
    return room


def _approximate_room(shape, faces: list, inner: float, outer: float, clearances) -> list:
    """The room inside any part (and, for walls outside it, the walls'
    outside), made with a many-sided ball: see shell."""
    outside = shape_geometry(shape, clearances)
    if len(outside.faces) > APPROXIMATE_FACE_LIMIT:
        raise BuildError("This part is too detailed to shell.")
    part = to_manifold(outside)
    if inner > 0.0:
        reach = part
        for face in faces:
            reach = reach + to_manifold(_prism(face, -0.01, inner + REACH))
        inside = reach.minkowski_difference(m3.Manifold.sphere(inner, 24))
        if inside.is_empty() or (inside ^ part).volume() < 1e-3:
            raise BuildError(
                "That wall is too thick for this part: there would be no space left inside. "
                "Try a thinner wall."
            )
        for face in faces:
            if (inside ^ to_manifold(_prism(face, 0.0, REACH))).volume() < 1e-6:
                raise BuildError(
                    "That face is too small to leave open with walls this thick. "
                    "Try a thinner wall, or a bigger face."
                )
    else:
        inside = part
        for face in faces:
            inside = inside + to_manifold(_prism(face, -0.01, REACH))
    room = [_baked_child(from_manifold(inside), "Inside", shape.color, is_hole=True)]
    if outer > 0.0:
        grown = part.minkowski_sum(m3.Manifold.sphere(outer, 24))
        room.insert(0, _baked_child(from_manifold(grown), "Walls", shape.color, is_hole=False))
        for face in faces:
            # What is grown round an open face, cut off level with it as far
            # as three walls from its edge (round a side curving away from it).
            rim = to_manifold(_prism(face, 0.0, outer + 0.01, face.region.buffer(3.0 * outer))) - part
            if not rim.is_empty():
                room.append(_baked_child(from_manifold(rim), "Opening", shape.color, is_hole=True))
    return room


def _open_faces(shape, face_index: int, far_side: bool, more, clearances) -> list:
    """The flat faces to leave open: the one clicked, the one across from
    it with `far_side`, and the faces of the further clicks `more` ((face,
    point) pairs); each once."""
    faces = [flat_face(shape, face_index, clearances)]
    if far_side:
        faces.append(_far_face(shape, faces[0], clearances))
    for pick in more or ():
        faces.append(flat_face(shape, int(pick[0]), clearances))
    kept, seen = [], set()
    for face in faces:
        key = frozenset(int(i) for i in face.faces)
        if key not in seen:
            seen.add(key)
            kept.append(face)
    return kept


def face_outline(face: FlatFace) -> list[np.ndarray]:
    """A flat face's outline (and the outlines of any holes in it) as
    closed lines of points in the world, to show it is picked."""
    polygons = [face.region] if face.region.geom_type == "Polygon" else list(getattr(face.region, "geoms", []))
    lines = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            lines.append(sketch.to_world(face.frame, np.asarray(ring.coords, dtype=np.float64)))
    return lines


def shell(shape, face_index: int, wall: float, far_side: bool = False,
          clearances: dict | None = None, more=(), walls: str = "inside"):
    """`shape` hollowed out to walls `wall` mm thick, with the flat face
    clicked left open (and, with `far_side`, the face across from it, and
    the faces of the further clicks `more`: (face, point) pairs on the
    same part). The walls go inside the part ("inside": its outside keeps
    its shape), outside it ("outside": its inside keeps its shape, and the
    walls stop level with each open face), or half each side ("both").

    Returns a group of the part, the walls' outside when they go outside
    it, and the room inside it (a Hole reaching out through the open
    faces), so Ungroup gives the part back. Exact for a box or cylinder
    opened through its flat sides or ends; otherwise the room and the
    walls' outside keep an even distance from the part's outside, made
    with a many-sided ball, so walls inside can come out a little thinner
    in places and walls outside get rounded corners.
    """
    if is_reference(shape):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Shell"))
    if shape.is_hole:
        raise BuildError("Shell works on solid parts. This one is a Hole.")
    wall = float(wall)
    if not math.isfinite(wall) or wall <= 0.0:
        raise BuildError("The wall thickness must be more than 0 mm.")
    inner, outer = _wall_sides(wall, walls)
    faces = _open_faces(shape, face_index, far_side, more, clearances)

    room = None
    if shells_exactly(shape):
        opens = [_own_direction(shape, face.normal) for face in faces]
        if all(direction is not None for direction in opens):
            room = _exact_room(shape, wall, opens, walls)
    if room is None:
        room = _approximate_room(shape, faces, inner, outer, clearances)
    try:
        return _group([copy.deepcopy(shape)] + room, f"{shape.name} (shell)", clearances)
    except NothingToCombineError as exc:
        raise BuildError("That wall is too thick for this part. Try a thinner wall.") from exc


# --- Push/Pull ------------------------------------------------------------------------

OVERLAP = 0.01  # mm a pulled piece reaches back into the part, so the two join solidly

SIDES_OFF = "Try it without extending the sloping sides."
# How nearly level with the face a side next to it may be and still be
# followed (the sine of the angle between them, squared: about 1.8 degrees).
LEVEL_SIDE = 1e-3
SIDE_CLEARANCE = 0.001  # mm a piece pushed in reaches out past the sloping sides it follows


def _side_moves(tm, face: FlatFace) -> tuple[np.ndarray, list, dict, dict]:
    """How each corner of the face moves per mm the face moves out, so
    that every side next to it keeps its slope (a square side: straight
    out). Returns (the face's triangles, its outline as edges in the
    triangles' order, {corner: its move}, {corner: how it moves, staying
    on the face, per mm the sides at outside edges next to it move out
    away from the face})."""
    tris = tm.faces[face.faces]
    inside = set(int(f) for f in face.faces)
    used: dict[tuple[int, int], int] = {}
    for tri in tris:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            used[(min(a, b), max(a, b))] = used.get((min(a, b), max(a, b)), 0) + 1
    beside = {}
    for (f1, f2), (a, b) in zip(tm.face_adjacency, tm.face_adjacency_edges):
        if (int(f1) in inside) != (int(f2) in inside):
            beside[(min(int(a), int(b)), max(int(a), int(b)))] = int(f2) if int(f1) in inside else int(f1)
    outline, at = [], {}
    for tri in tris:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            key = (min(a, b), max(a, b))
            if used[key] != 1:
                continue
            if key not in beside:
                raise BuildError("This part has gaps in its surface, so the sides next to the face can't "
                                 f"be followed. {SIDES_OFF}")
            outline.append((a, b))
            side = tm.face_normals[beside[key]]
            # Whether it is an outside edge: the side faces away from the face.
            away = np.cross(tm.vertices[b] - tm.vertices[a], face.normal)
            side = (side, 1.0 if side @ away > 0.0 else 0.0)
            at.setdefault(a, []).append(side)
            at.setdefault(b, []).append(side)
    n = face.normal
    moves, widen = {}, {}
    for corner in np.unique(tris):
        corner = int(corner)
        sides = at.get(corner, [])
        if len(sides) > 2:
            raise BuildError("This face's outline touches itself at a corner, so the sides next to it "
                             f"can't be followed. {SIDES_OFF}")
        if any(1.0 - (n @ m) ** 2 < LEVEL_SIDE for m, _ in sides):
            raise BuildError("A side next to this face is almost level with it, so it can't be "
                             f"extended along its slope. {SIDES_OFF}")
        rows = np.array([n] + [m for m, _ in sides])
        if len(sides) == 2 and abs(np.linalg.det(rows)) > 1e-9:
            moves[corner] = np.linalg.solve(rows, [1.0, 0.0, 0.0])
            widen[corner] = np.linalg.solve(rows, [0.0, sides[0][1], sides[1][1]])
        elif sides:  # one side (or two in one plane): carried on square to the edge
            m, sign = sides[0]
            moves[corner] = (n - (n @ m) * m) / (1.0 - (n @ m) ** 2)
            widen[corner] = sign * (m - (m @ n) * n) / (1.0 - (n @ m) ** 2)
        else:
            moves[corner], widen[corner] = n.copy(), np.zeros(3)
    return tris, outline, moves, widen


def _sloped_prism(shape, face: FlatFace, low: float, high: float, clearances, wider: float = 0.0):
    """Like _prism, but each side of the piece lies in the plane of the
    side next to the face on the part: sloping sides are carried on along
    their slope (at outside edges moved `wider` mm out, away from the
    face, so a piece cut away leaves no skin where its sides meet the
    part's). Refused where moving that far would make sides cross."""
    tm = shape_geometry(shape, clearances)
    tris, outline, moves, widen = _side_moves(tm, face)
    corners = sorted(moves)
    number = {c: i for i, c in enumerate(corners)}
    base = tm.vertices[corners] + wider * np.array([widen[c] for c in corners])
    move = np.array([moves[c] for c in corners])
    for h in np.linspace(low, high, 9):
        flat = sketch.to_sketch(face.frame, base + h * move)
        rest = sketch.to_sketch(face.frame, base)
        pieces = []
        for tri in tris:
            p = flat[[number[int(c)] for c in tri]]
            area = 0.5 * ((p[1, 0] - p[0, 0]) * (p[2, 1] - p[0, 1]) - (p[2, 0] - p[0, 0]) * (p[1, 1] - p[0, 1]))
            if area <= 1e-9:
                pieces = None
                break
            pieces.append(Polygon(p))
        turned = any((flat[number[b]] - flat[number[a]]) @ (rest[number[b]] - rest[number[a]]) <= 0.0
                     for a, b in outline)
        if pieces is None or turned or unary_union(pieces).area < sum(p.area for p in pieces) - 1e-6:
            raise BuildError("Moving the face that far would make the sloping sides next to it meet or "
                             "cross. Try a shorter distance.")
    k = len(corners)
    vertices = np.vstack([base + low * move, base + high * move])
    faces = []
    for a, b, c in ((number[int(x)] for x in tri) for tri in tris):
        faces += [[a, c, b], [k + a, k + b, k + c]]
    for a, b in outline:
        a, b = number[a], number[b]
        faces += [[a, b, k + b], [a, k + b, k + a]]
    try:
        return features._solid_from(vertices, np.array(faces), "piece")
    except sketch.SketchError as exc:
        raise BuildError(NOT_CLEAN) from exc


def push_pull(shape, face_index: int, distance: float, clearances: dict | None = None,
              follow_sides: bool = False):
    """The flat face clicked moved `distance` mm straight out of the part
    (more than 0) or into it (less than 0).

    Returns a group of the part and the piece added (the face's outline
    pushed out) or taken away (pushed in, as a Hole), so Ungroup gives the
    part back. Exact where the sides next to the face are square to it.
    Otherwise the new sides are square to the face, or with `follow_sides`
    each new side lies in the plane of the side next to it, carrying its
    slope on: exact for flat sides (a round side is narrow flat strips,
    each carried on along its own slope).
    """
    if is_reference(shape):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Push/Pull"))
    if shape.is_hole:
        raise BuildError("Push/Pull works on solid parts. This one is a Hole.")
    distance = float(distance)
    if not math.isfinite(distance) or distance == 0.0:
        raise BuildError("Type a distance other than 0: more than 0 pulls the face out, "
                         "less than 0 pushes it in.")
    if abs(distance) > MOVE_LIMIT:
        raise BuildError(f"A face can move at most {MOVE_LIMIT:g} mm.")
    face = flat_face(shape, face_index, clearances)
    low, high = (-OVERLAP, distance) if distance > 0.0 else (distance, OVERLAP)
    if not follow_sides:
        solid = _prism(face, low, high)
    else:  # a piece cut away reaches a hair past the sides it follows
        solid = _sloped_prism(shape, face, low, high, clearances, 0.0 if distance > 0.0 else SIDE_CLEARANCE)
    if distance > 0.0:
        piece = _baked_child(solid, "Pulled out", shape.color, False)
        name = f"{shape.name} (pulled)"
    else:
        piece = _baked_child(solid, "Pushed in", shape.color, True)
        name = f"{shape.name} (pushed)"
    try:
        return _group([copy.deepcopy(shape), piece], name, clearances)
    except NothingToCombineError as exc:
        raise BuildError(
            "Pushing the face in that far would leave nothing of the part. Try a shorter distance."
        ) from exc


# --- Draft: sloped sides ----------------------------------------------------------------

DRAFT_KINDS = ("extrude", "cube", "cylinder", "tube")


def can_draft(shape) -> bool:
    return shape.kind == "primitive" and shape.params.get("primitive") in DRAFT_KINDS


def _outline_and_height(shape) -> tuple[list, float]:
    """A box, cylinder or tube as the outline of its base and its height."""
    kind = shape.params["primitive"]
    p = {**default_params(kind), **shape.params}
    if float(p.get("chamfer", 0.0)) > 0.0:
        raise BuildError(
            f"{shape.name} has a bottom chamfer, which sloped sides can't keep. Set its "
            "Bottom chamfer to 0 first."
        )
    if kind == "cube":
        w, d = float(p["width"]), float(p["depth"])
        return [{"type": "rectangle", "corner": [-w / 2.0, -d / 2.0], "width": w, "height": d}], float(p["height"])
    outline = [{"type": "circle", "centre": [0.0, 0.0], "diameter": float(p["diameter"])}]
    if kind == "tube":
        inside = float(p["diameter"]) - 2.0 * float(p["wall"])
        if inside > 0.0:
            outline.append({"type": "circle", "centre": [0.0, 0.0], "diameter": inside})
    return outline, float(p["height"])


def drafted(shape, angle: float, clearances: dict | None = None):
    """`shape` with its sides sloping in by `angle` degrees going away from
    its sketch's plane, or out for less than 0 (Fusion's Draft, on every side
    at once). An Extrusion gets that slope. A box, cylinder or tube becomes
    an Extrusion of the same size first: its base's outline pushed up its
    height, so its sides slope in from the base. A changed copy with the
    same id; nothing is changed here."""
    if is_reference(shape):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Slope the Sides"))
    if not can_draft(shape):
        raise BuildError(
            "Slope the Sides works on Extrusions, boxes, cylinders and tubes. To slope "
            "other sides, sketch the outline and extrude it."
        )
    angle = float(angle)
    limit = features.TAPER_LIMIT
    if not math.isfinite(angle) or abs(angle) > limit:
        raise BuildError(f"Type an angle between 0 and {limit:g} degrees.")
    changed = copy.deepcopy(shape)
    if shape.params["primitive"] != "extrude":
        if angle == 0.0:
            raise BuildError("Type an angle more than 0 to slope the sides.")
        entities, height = _outline_and_height(shape)
        changed.params = {"primitive": "extrude", "entities": entities, "distance": height, "side": "one"}
    changed.params["taper"] = angle
    try:
        shape_geometry(changed, clearances)
    except sketch.SketchError as exc:
        raise BuildError(str(exc)) from exc
    return changed
