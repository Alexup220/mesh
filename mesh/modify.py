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

import numpy as np

from mesh.builders import BuildError
from mesh.ops import AXES, fresh_ids, rotate_about
from mesh.shapes import shape_geometry

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
