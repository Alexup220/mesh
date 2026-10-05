"""Measuring for Expert mode's Inspect menu: between two clicked faces
(distance, angle, gap and each face's area) and the selected parts'
volume, surface area and size.

Measuring never changes anything. The beginner Measure tool (distance
between two clicks, in mesh.app) is unchanged.
"""

from dataclasses import dataclass

import numpy as np

from mesh import construct, ops
from mesh.builders import BuildError
from mesh.modify import flat_face
from mesh.shapes import is_reference

PARALLEL = 0.01  # degrees: faces this close to parallel are parallel


@dataclass(frozen=True)
class Clicked:
    """One click on a part's face: where it landed (on the face's corner
    within construct.SNAP mm of it), the face's way out and its area."""

    point: np.ndarray
    facing: np.ndarray
    area: float


@dataclass(frozen=True)
class Between:
    distance: float
    along: np.ndarray  # how far the second point is from the first in X, Y and Z
    angle: float  # between the faces' planes, 0 to 90 degrees
    gap: float | None  # how far apart the faces are, when they are parallel


@dataclass(frozen=True)
class Amount:
    volume: float  # cubic mm
    area: float  # square mm, all the way round
    size: np.ndarray  # width, depth and height in mm


def clicked(shape, face_index: int, point, clearances: dict | None = None) -> Clicked:
    face = flat_face(shape, face_index, clearances)
    at = construct.spot(shape, face_index, point, clearances)
    return Clicked(at, face.normal, float(face.region.area))


def between(first: Clicked, second: Clicked) -> Between:
    along = second.point - first.point
    cos = abs(float(first.facing @ second.facing))
    angle = float(np.degrees(np.arccos(min(cos, 1.0))))
    gap = abs(float(along @ first.facing)) if angle < PARALLEL else None
    return Between(float(np.linalg.norm(along)), along, angle, gap)


def describe_face(face: Clicked) -> str:
    return f"Face area: {face.area:.2f} mm²"


def describe(first: Clicked, second: Clicked) -> str:
    """The plain-language lines Measure Between Faces shows."""
    result = between(first, second)
    dx, dy, dz = (abs(float(v)) for v in result.along)
    lines = [
        f"Distance between the points: {result.distance:.2f} mm",
        f"Left/right {dx:.2f} mm, forward/back {dy:.2f} mm, up/down {dz:.2f} mm",
    ]
    if result.gap is not None:
        lines.append(f"The faces are parallel, {result.gap:.2f} mm apart")
    else:
        lines.append(f"Angle between the faces: {result.angle:.2f}°")
    lines.append(f"First face area: {first.area:.2f} mm², second face area: {second.area:.2f} mm²")
    return "\n".join(lines)


HAS_GAPS = "{name} has gaps, so it has no inside to measure."


def amount(shapes, clearances: dict | None = None) -> Amount:
    """The selected parts as they would print together: overlaps counted
    once and selected Holes cut out. Sketches and guides are left out."""
    try:
        solid = ops.evaluate(shapes, clearances)
    except ops.NothingToCombineError as exc:
        raise BuildError(str(exc)) from exc
    if not solid.is_watertight:
        name = next(s.name for s in shapes if not s.is_hole and not is_reference(s))
        raise BuildError(HAS_GAPS.format(name=name))
    return Amount(float(solid.volume), float(solid.area), np.asarray(solid.extents, dtype=np.float64))


def describe_amount(found: Amount, count: int) -> str:
    what = "The selected part takes" if count == 1 else f"The {count} selected parts, together, take"
    w, d, h = found.size
    return "\n".join([
        f"{what} up {found.volume:.2f} mm³ ({found.volume / 1000.0:.2f} cm³).",
        f"Surface area all the way round: {found.area:.2f} mm².",
        f"Size: {w:.2f} x {d:.2f} x {h:.2f} mm (width x depth x height).",
    ])
