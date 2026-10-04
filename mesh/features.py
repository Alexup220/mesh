"""Solids made from sketches (Expert mode): Extrude.

Each is a primitive (see mesh.shapes.PRIMITIVES) whose params keep a copy of
the sketch it was made from, so its numbers stay editable and its geometry
is always rebuilt from them. `build(kind, params, clearance)` turns those
params into a closed solid in the shape's own coordinates, which are its
sketch's: the shape's transform is the sketch's plane.

    extrude  entities (sketch coordinates), distance, side
             The outline pushed straight out of its plane: the way the
             sketch faces ("one"), the other way ("other"), or half each
             way ("both").

A shape with no sketch of its own (a new primitive) uses a small built-in
one (DEFAULT_*), so every kind has a sensible default, standing on the
workplane like the other primitives.

`clearance` > 0 (a fitted Hole) grows the result by that much on every
side.

Never imports mesh.scene or mesh.shapes, so mesh.shapes can import it.
"""

import math

import trimesh

from mesh.sketch import SEGMENTS, SketchError, profile
from mesh.solids import from_manifold, m3

SOLIDS = ("extrude",)

SIDES = [
    ("one", "The way the sketch faces"),
    ("other", "The other way"),
    ("both", "Both ways, evenly"),
]

DEFAULT_EXTRUDE = [{"type": "rectangle", "corner": [-10.0, -10.0], "width": 20.0, "height": 20.0}]


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
    return {"extrude": DEFAULT_EXTRUDE}[kind]


def build(kind: str, params: dict, clearance: float = 0.0) -> trimesh.Trimesh:
    if kind == "extrude":
        return extrude(params.get("entities", DEFAULT_EXTRUDE), params["distance"],
                       params.get("side", "one"), clearance)
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
