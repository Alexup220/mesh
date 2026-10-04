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

from mesh import sketch
from mesh.builders import GUIDES_ARE_NOT_PARTS, BuildError
from mesh.ops import AXES, _canonical, fresh_ids, rotate_about, rotation_between
from mesh.shapes import is_reference, shape_geometry

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
