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
from mesh.builders import GUIDES_ARE_NOT_PARTS, BuildError
from mesh.ops import AXES, _canonical, fresh_ids, rotate_about, rotation_between
from mesh.shapes import HARDWARE_PRIMITIVES, PRIMITIVES, is_reference, primitive_mesh, shape_geometry

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
    if kind in ("revolve", "sweep", "loft") and not uniform:
        raise _stretch_refusal(shape.name, "is made from a sketch")
    if kind == "extrude":
        if not across:
            raise _stretch_refusal(shape.name, "is made from a sketch's curves", across=True)
        entities = params.get("entities") or features.default_entities("extrude")
        params["entities"] = _scaled_entities(shape, entities, own[0])
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
    elif kind == "loft":
        params["sections"] = [
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
