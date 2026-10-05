"""Coils (Expert mode's Create menu): a spring, a round or square wire
wound round an upright line, like Fusion's Coil.

The wire's cross-section is drawn in a plane through the coil's middle
line, the way Fusion draws a coil's section, and carried round that line
as it rises, so every turn is the same. The coil is built as a straight
bar of that cross-section bent round into the turns, STEPS straight pieces
to a turn; a round wire's outline has WIRE_SEGMENTS straight sides. The
ends are cut square across the wire, in that plane through the middle
line. Built resting on the workplane, about the Z axis, like a cylinder.

    diameter    across the outside of the coil (mm)
    pitch       how far the coil rises in one turn (mm)
    turns       how many turns (a part turn is allowed)
    wire        the wire's thickness (mm): a round wire's diameter, a
                square wire's side
    wire_shape  "round" or "square"
    winding     "right" (climbing anticlockwise seen from above, like
                most springs and screws) or "left"
"""

import math

import numpy as np
import trimesh

from mesh.solids import from_manifold, m3


class CoilError(ValueError):
    """Sizes that can't make a coil; the message says why, in plain words."""


WIRE_SHAPES = [("round", "Round"), ("square", "Square")]
WINDINGS = [
    ("right", "Right-hand (climbs anticlockwise seen from above)"),
    ("left", "Left-hand (climbs clockwise seen from above)"),
]

STEPS = 48  # straight pieces to a turn
WIRE_SEGMENTS = 24  # sides round a round wire
MAX_TURNS = 200

DEFAULTS = {"diameter": 20.0, "pitch": 5.0, "turns": 5.0, "wire": 2.0, "wire_shape": "round",
            "winding": "right"}


def refusal(p: dict, clearance: float = 0.0) -> str | None:
    """Why these sizes can't make a coil (grown by `clearance` on every
    side, for a fitted Hole), or None."""
    try:
        diameter, pitch = float(p["diameter"]), float(p["pitch"])
        turns, wire = float(p["turns"]), float(p["wire"])
    except (KeyError, TypeError, ValueError):
        return "A coil needs a diameter, a pitch, a number of turns and a wire size."
    if not all(math.isfinite(v) for v in (diameter, pitch, turns, wire)):
        return "Type ordinary numbers for the coil's sizes."
    if wire < 0.1:
        return "The wire must be at least 0.1 mm thick."
    if not 0.05 <= turns <= MAX_TURNS:
        return f"A coil can have from 0.05 to {MAX_TURNS} turns."
    if diameter / 2.0 - wire - clearance <= 0.05:
        return (f"A {wire:g} mm wire is too thick for a {diameter:g} mm coil: it would fill the "
                "middle. Use a thinner wire or a wider coil.")
    if pitch <= wire + 2.0 * clearance:
        if clearance > 0.0:
            return (f"With its fit, this coil Hole's turns would run into each other. Use a pitch "
                    f"of more than {wire + 2.0 * clearance:g} mm, or a smaller fit.")
        return (f"The pitch must be more than the wire's {wire:g} mm, or the turns would run into "
                "each other.")
    if p.get("wire_shape", "round") not in dict(WIRE_SHAPES):
        return "Choose a round or square wire."
    if p.get("winding", "right") not in dict(WINDINGS):
        return "Choose which way the coil winds."
    return None


def coil_mesh(p: dict, clearance: float = 0.0) -> trimesh.Trimesh:
    """The coil `p` describes (see DEFAULTS). `clearance` > 0 grows it that
    much on every side, as for a Hole's fit: the wire by `clearance` all
    round, the ends by `clearance` along the wire."""
    p = {**DEFAULTS, **p}
    c = max(float(clearance), 0.0)
    problem = refusal(p, c)
    if problem is not None:
        raise CoilError(problem)
    pitch, turns, wire = float(p["pitch"]), float(p["turns"]), float(p["wire"])
    middle = float(p["diameter"]) / 2.0 - wire / 2.0  # from the line to the wire's middle
    half = wire / 2.0 + c
    if p["wire_shape"] == "square":
        section = m3.CrossSection.square((2.0 * half, 2.0 * half), True)
    else:
        section = m3.CrossSection.circle(half, WIRE_SEGMENTS)
    # The ends reach `clearance` further along the wire.
    extra = c / math.hypot(2.0 * math.pi * middle, pitch)
    first, length = -extra, turns + 2.0 * extra
    bar = m3.Manifold.extrude(section, length, n_divisions=max(int(math.ceil(length * STEPS)), 1))

    def bend(points: np.ndarray) -> np.ndarray:
        # The bar's X goes in towards the middle line (so the bend keeps
        # the solid's inside in), its Y up, and its length round the turns.
        across, up, along = points[:, 0], points[:, 1], points[:, 2] + first
        radius = middle - across
        angle = 2.0 * math.pi * along
        return np.column_stack([radius * np.cos(angle), radius * np.sin(angle),
                                wire / 2.0 + up + pitch * along])

    solid = bar.warp_batch(bend)
    if p["winding"] == "left":
        solid = solid.mirror((1.0, 0.0, 0.0))
    if solid.status() != m3.Error.NoError or solid.is_empty():
        raise CoilError("Those sizes would not make a closed coil. Try different sizes.")
    return from_manifold(solid)
