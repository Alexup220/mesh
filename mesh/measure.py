"""Measuring for Expert mode's Inspect menu: between two clicked faces
(distance, angle, gap and each face's area), a clicked round face's
radius, a clicked edge's length, the shortest distance between two parts, and the selected parts'
volume, surface area and size.

Measuring never changes anything. The beginner Measure tool (distance
between two clicks, in mesh.app) is unchanged.
"""

from dataclasses import dataclass

import numpy as np

from mesh import construct, ops
from mesh.builders import BuildError
from mesh.modify import flat_face
from mesh.shapes import default_params, hole_clearance, is_reference, shape_geometry
from mesh.solids import m3, to_manifold

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


# --- The radius of a round face ----------------------------------------------------------


@dataclass(frozen=True)
class RoundFace:
    text: str
    line: tuple | None  # (from, to): the radius measured, to draw; None if it can't be told


def round_face(shape, face_index: int, point, clearances: dict | None = None) -> RoundFace:
    """What a click on a part's round face measures, read from the part's
    own sizes (construct.round_spot), or plainly why it can't be told."""
    try:
        found = construct.round_spot(shape, face_index, point, clearances)
    except BuildError as exc:
        text = str(exc)
        if shape.kind == "primitive" and shape.params.get("primitive") == "thread" and not is_reference(shape):
            # Its sloping sides wind round it: give its outer size instead.
            size = float(shape.params.get("diameter", default_params("thread")["diameter"]))
            size += 2.0 * hole_clearance(shape, clearances)
            text += f" A thread's sloping sides wind round it; its outer diameter is {size:.2f} mm."
        return RoundFace(text, None)
    name = shape.name
    piece = found.piece
    here = found.around
    if piece[0] == "arc":
        across, middle = piece[2], abs(float(piece[1][0]))
        if middle < 1e-6:
            text = (f"{name}: this round face is part of a ball, radius {across:.2f} mm "
                    f"(diameter {2 * across:.2f} mm).")
        else:
            text = (f"{name}: this round face curves two ways. Across it, the radius is {across:.2f} mm, "
                    f"curving round a point {middle:.2f} mm from the part's middle line. Round that "
                    f"line, where clicked, the radius is {here:.2f} mm.")
    else:
        (low, z0), (high, z1) = piece[1], piece[2]
        if abs(high - low) < 1e-9:
            text = (f"{name}: this round face is a cylinder, radius {here:.2f} mm "
                    f"(diameter {2 * here:.2f} mm).")
        else:
            slope = float(np.degrees(np.arctan2(abs(high - low), abs(z1 - z0))))
            text = (f"{name}: this round face is a cone, its radius going from {min(low, high):.2f} mm to "
                    f"{max(low, high):.2f} mm, sloping {slope:.1f}° to the part's middle line. Where "
                    f"clicked the radius is {here:.2f} mm (diameter {2 * here:.2f} mm).")
            if shape.params.get("primitive") == "revolve":
                text += (" A revolved part's outline is made of short straight pieces, so on a curve in "
                         "it this is the one piece clicked.")
    return RoundFace(text, (found.centre, found.point))


# --- The length of an edge --------------------------------------------------------------

EDGE_NOTE = ("A round edge is drawn as short straight pieces, so measured along them it is a little "
             "shorter than the true curve.")


def describe_edge(name: str, found: construct.ClickedEdge) -> str:
    """The plain-language lines Length of an Edge shows for an edge
    construct.edge_at found."""
    if found.straight:
        return f"{name}: this edge is {found.length:.2f} mm long."
    lines = [f"{name}: the straight stretch of the edge clicked is {found.length:.2f} mm long."]
    if found.closed:
        lines.append(f"The edge goes on all the way round: {found.run_length:.2f} mm round.")
    else:
        lines.append(f"The edge goes on round its curves: {found.run_length:.2f} mm long in all.")
    lines.append(EDGE_NOTE)
    return "\n".join(lines)


# --- The shortest distance between two parts -------------------------------------------


@dataclass(frozen=True)
class Gap:
    distance: float  # the shortest distance between their surfaces (0 if they touch or overlap)
    overlap: bool    # they share some space (or one is inside the other)


GAP_NOTE = ("Measured on the parts as drawn: round surfaces are narrow flat strips, so near them "
            "it can be slightly off.")
OPEN_SURFACE = "{name} has gaps in its surface, so the distance to it can't be measured."


def gap(first, second, clearances: dict | None = None) -> Gap:
    """The shortest distance between two parts, as drawn (a Hole at its fit)."""
    if first.id == second.id:
        raise BuildError("Select two different parts.")
    solids, bounds = [], []
    for shape in (first, second):
        if is_reference(shape):
            raise BuildError(f"{shape.name} is a guide, not a part. Select two parts.")
        tm = shape_geometry(shape, clearances)
        solid = to_manifold(tm)
        if solid.status() != m3.Error.NoError or solid.is_empty():
            raise BuildError(OPEN_SURFACE.format(name=shape.name))
        solids.append(solid)
        bounds.append(tm.bounds)
    both = np.vstack(bounds)
    search = float(np.linalg.norm(both.max(axis=0) - both.min(axis=0))) + 1.0
    if (solids[0] ^ solids[1]).volume() > 1e-6:
        return Gap(0.0, True)
    return Gap(float(solids[0].min_gap(solids[1], search)), False)


def describe_gap(first_name: str, second_name: str, found: Gap) -> str:
    if found.overlap:
        head = f"{first_name} and {second_name} overlap: they share some space, so there is no gap between them."
    elif found.distance < 1e-6:
        head = f"{first_name} and {second_name} touch: the shortest distance between them is 0.00 mm."
    else:
        head = f"Shortest distance between {first_name} and {second_name}: {found.distance:.2f} mm."
    return f"{head}\n{GAP_NOTE}"


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
