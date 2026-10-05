"""Screw threads (Expert mode's Thread tool): a cylinder with a real,
modeled thread along some or all of its height, like a bolt; as a Hole it
cuts a threaded hole for one.

The thread has the ISO metric shape (ISO 68-1): flanks at 60 degrees to
each other, a flat crest P/8 wide at the full diameter and a flat root P/4
wide, 5H/8 deep, where P is the pitch and H = 0.866 P. It is built as one
cross-section turned steadily as it rises, so the flanks are made of
narrow flat strips, STEPS to a turn. Built resting on the workplane, about
the Z axis, like a cylinder.

With several starts, that many threads run side by side, evenly round: the
pitch is still the distance from one ridge to the next, and each thread
rises the pitch times the number of starts in a turn (its lead). "starts"
is missing in older files, where it is 1.
"""

import numpy as np
import trimesh

from mesh.solids import from_manifold, m3


class ThreadError(ValueError):
    """Sizes that can't make a thread; the message says why, in plain words."""


# ISO 261 coarse pitches (mm) for the common metric sizes.
ISO_COARSE = {
    2.0: 0.4, 2.5: 0.45, 3.0: 0.5, 4.0: 0.7, 5.0: 0.8, 6.0: 1.0, 8.0: 1.25, 10.0: 1.5,
    12.0: 1.75, 14.0: 2.0, 16.0: 2.0, 18.0: 2.5, 20.0: 2.5, 22.0: 2.5, 24.0: 3.0,
    27.0: 3.0, 30.0: 3.5,
}

ENDS = [("top", "At the top"), ("bottom", "At the bottom")]
HANDS = [("right", "Right-hand (tightens clockwise)"), ("left", "Left-hand (tightens anticlockwise)")]

STEPS = 36  # flat strips to a turn, for each start
MAX_TURNS = 150  # turns of a one-start thread (fewer with more starts)
MAX_STARTS = 4
SEGMENTS = 64  # round the unthreaded part, as a cylinder

DEFAULTS = {"diameter": 10.0, "height": 20.0, "pitch": 1.5, "thread_length": 20.0,
            "end": "top", "hand": "right", "starts": 1}


def standard_size(diameter: float) -> tuple[str, float]:
    """The nearest ISO metric size to `diameter`: (its name, its coarse pitch)."""
    size = min(ISO_COARSE, key=lambda d: abs(d - float(diameter)))
    return f"M{size:g}", ISO_COARSE[size]


def depth(pitch: float) -> float:
    """How deep the thread is cut: 5H/8."""
    return 5.0 / 8.0 * np.sqrt(3.0) / 2.0 * float(pitch)


def starts_of(p: dict) -> int:
    """How many threads run side by side (see refusal for the allowed ones)."""
    return int(round(float(p.get("starts", 1))))


def refusal(p: dict) -> str | None:
    """Why these sizes can't make a thread, or None."""
    diameter, height = float(p["diameter"]), float(p["height"])
    pitch, length = float(p["pitch"]), float(p["thread_length"])
    starts = float(p.get("starts", 1))
    if pitch < 0.2:
        return "The pitch (how far the thread rises in one turn) must be at least 0.2 mm."
    if depth(pitch) > 0.4 * diameter:
        return (f"A {pitch:g} mm pitch cuts too deep for a {diameter:g} mm diameter. Use a pitch of "
                f"at most {0.4 * diameter / depth(1.0):.2f} mm, or a wider part.")
    if starts != round(starts) or not 1 <= starts <= MAX_STARTS:
        return f"A thread can have 1 to {MAX_STARTS} starts (threads side by side), as a whole number."
    if min(length, height) / pitch * starts > MAX_TURNS:
        if starts > 1:
            return (f"That thread would make more than {MAX_TURNS} turns, counting each start. Thread "
                    "less of the part, use a bigger pitch, or use fewer starts.")
        return (f"That thread would make more than {MAX_TURNS} turns. Thread less of the part, or use "
                "a bigger pitch.")
    if p.get("end", "top") not in dict(ENDS) or p.get("hand", "right") not in dict(HANDS):
        return "Choose where the thread starts and which way it turns."
    return None


def _profile(u: np.ndarray, pitch: float, outer: float, inner: float) -> np.ndarray:
    """The radius at `u` mm along one pitch of the thread: crest, flank
    down, root, flank up."""
    u = np.mod(u, pitch) / pitch
    corners = np.array([0.0, 1.0 / 8.0, 7.0 / 16.0, 11.0 / 16.0, 1.0])
    radii = np.array([outer, outer, inner, inner, outer])
    return np.interp(u, corners, radii)


def _section(pitch: float, outer: float, inner: float, start: float, starts: int = 1) -> "m3.CrossSection":
    """A right-hand thread across at height `start` (so every piece of a
    thread lines up, whatever height it starts at), with `starts` threads
    side by side."""
    turns = np.linspace(0.0, 1.0, STEPS * starts, endpoint=False)
    corners = np.array([0.0, 1.0 / 8.0, 7.0 / 16.0, 11.0 / 16.0])
    # The angle at which each corner of the profile is reached, on each
    # thread.
    reached = [np.mod((start / pitch - corners - k) / starts, 1.0) for k in range(starts)]
    turns = np.unique(np.round(np.concatenate([turns, *reached]), 12))
    theta = 2.0 * np.pi * turns
    radius = _profile(start - pitch * starts * turns, pitch, outer, inner)
    points = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    return m3.CrossSection([points])


def thread_mesh(p: dict, clearance: float = 0.0) -> trimesh.Trimesh:
    """The threaded cylinder `p` describes (see DEFAULTS). `clearance` > 0
    grows it that much on every side, as for a Hole's fit: the radius by
    `clearance`, the ends by `clearance` each, with the thread's turns kept
    where they were so a bolt of the same sizes fits it."""
    p = {**DEFAULTS, **p}
    problem = refusal(p)
    if problem is not None:
        raise ThreadError(problem)
    c = max(float(clearance), 0.0)
    height, pitch = float(p["height"]), float(p["pitch"])
    outer = float(p["diameter"]) / 2.0 + c
    inner = outer - depth(pitch)
    length = min(float(p["thread_length"]), height)
    low, high = -c, height + c
    if length >= height - 1e-9:
        threaded = (low, high)
        plain = None
    elif p["end"] == "bottom":
        threaded, plain = (low, length), (length, high)
    else:
        threaded, plain = (height - length, high), (low, height - length)
    start, stop = threaded
    starts = starts_of(p)
    # A layer every 1/STEPS of the pitch, so each turns 1/STEPS of a turn
    # divided by the number of starts: as fine as the cross-section.
    solid = m3.Manifold.extrude(
        _section(pitch, outer, inner, start, starts), stop - start,
        n_divisions=max(int(np.ceil((stop - start) / pitch * STEPS)), 1),
        twist_degrees=360.0 * (stop - start) / (pitch * starts),
    ).translate((0.0, 0.0, start))
    if p["hand"] == "left":
        # The mirror image of a right-hand thread. Twisting the other way
        # would join the strips across the slope and lose 1% of the thread.
        solid = solid.mirror((1.0, 0.0, 0.0))
    if plain is not None:
        shank = m3.Manifold.cylinder(plain[1] - plain[0], outer, outer, SEGMENTS).translate((0.0, 0.0, plain[0]))
        solid = solid + shank
    return from_manifold(solid)
