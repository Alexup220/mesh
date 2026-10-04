"""Solids made from sketches (Expert mode): Extrude and Revolve.

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

from mesh.sketch import SEGMENTS, SketchError, profile
from mesh.solids import from_manifold, m3

SOLIDS = ("extrude", "revolve")

SIDES = [
    ("one", "The way the sketch faces"),
    ("other", "The other way"),
    ("both", "Both ways, evenly"),
]

DEFAULT_EXTRUDE = [{"type": "rectangle", "corner": [-10.0, -10.0], "width": 20.0, "height": 20.0}]
# Turned about the sketch's Y line: a tube 10 mm across inside, 20 outside.
DEFAULT_REVOLVE = [{"type": "rectangle", "corner": [5.0, 0.0], "width": 5.0, "height": 20.0}]
DEFAULT_AXIS = [0.0, 0.0, 0.0, 1.0]


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
    return {"extrude": DEFAULT_EXTRUDE, "revolve": DEFAULT_REVOLVE}[kind]


def build(kind: str, params: dict, clearance: float = 0.0) -> trimesh.Trimesh:
    if kind == "extrude":
        return extrude(params.get("entities", DEFAULT_EXTRUDE), params["distance"],
                       params.get("side", "one"), clearance)
    if kind == "revolve":
        return revolve(params.get("entities", DEFAULT_REVOLVE), params.get("axis", DEFAULT_AXIS),
                       params["angle"], clearance)
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
