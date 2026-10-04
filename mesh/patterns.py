"""Copies in a pattern: Expert mode's patterns.

Every function returns new shapes (copies with new ids, as Duplicate makes)
and leaves the shapes passed in alone; the window adds them in one undo
step. Copies keep their part's name, size numbers, Solid/Hole and fit, so a
patterned Hole still cuts once grouped. Sketches are guides: they are never
copied here. A request that can't be met raises BuildError with a plain
message.

    rectangular  rows and columns along two of the world's directions

Exact: copies are the same shapes moved.
"""

import math

import numpy as np

from mesh.builders import MAX_COPIES, BuildError, _check_count, _copy
from mesh.modify import MOVE_LIMIT
from mesh.ops import AXES, _canonical
from mesh.shapes import is_reference

PARTS_ONLY = "Select the parts to copy. Sketches are guides, so they are not copied."


def _parts(shapes) -> list:
    parts = [s for s in shapes if not is_reference(s)]
    if not parts:
        raise BuildError(PARTS_ONLY)
    return parts


def _check_total(positions: int, parts: list) -> None:
    if (positions - 1) * len(parts) > MAX_COPIES:
        raise BuildError(f"That is too many copies. Try {MAX_COPIES} or fewer in all.")


def _moved(parts: list, matrix: np.ndarray, canonical: bool = True) -> list:
    """Copies of `parts`, each moved by the world transform `matrix`."""
    out = []
    for part in parts:
        clone = _copy(part)
        moved = matrix @ np.asarray(part.transform, dtype=np.float64)
        clone.transform = _canonical(moved) if canonical else moved
        out.append(clone)
    return out


def _distance(value: float, what: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value == 0.0:
        raise BuildError(f"The {what} must be a distance other than 0 mm.")
    if abs(value) > MOVE_LIMIT:
        raise BuildError(f"The {what} can be at most {MOVE_LIMIT:g} mm.")
    return value


# --- Rectangular --------------------------------------------------------------------


def rectangular(shapes, count: int, spacing: float, axis: str = "x",
                count2: int = 1, spacing2: float = 10.0, axis2: str = "y") -> list:
    """Copies of the parts in rows along `axis` (`count` in a row,
    `spacing` mm apart, less than 0 going the other way) and, with `count2`
    more than 1, columns along `axis2`. Counts include the originals."""
    parts = _parts(shapes)
    if axis not in AXES or axis2 not in AXES:
        raise ValueError(f"unknown direction {axis!r} or {axis2!r}")
    count, count2 = int(count), int(count2)
    if count < 1 or count2 < 1:
        raise BuildError("Each direction needs at least 1 in a row.")
    _check_count(count * count2)
    _check_total(count * count2, parts)
    first = _distance(spacing, "spacing") if count > 1 else 0.0
    second = _distance(spacing2, "spacing") if count2 > 1 else 0.0
    if count > 1 and count2 > 1 and axis == axis2:
        raise BuildError("Choose two different directions for the rows and the columns.")
    step, step2 = np.zeros(3), np.zeros(3)
    step[AXES[axis]] = first
    step2[AXES[axis2]] = second
    out = []
    for j in range(count2):
        for i in range(count):
            if i == 0 and j == 0:
                continue
            matrix = np.eye(4)
            matrix[:3, 3] = i * step + j * step2
            out += _moved(parts, matrix, canonical=False)
    return out
