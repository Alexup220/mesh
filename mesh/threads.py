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

Inch (Unified) threads have the same shape as metric ones, so they are
the same thread with the pitch worked out from the threads per inch.
British pipe threads (parallel, "G", ISO 228-1) have the Whitworth shape
instead: flanks at 55 degrees, 0.640P deep, with round crests and roots of
radius 0.137P, each round made of short flat pieces. "thread_shape" is
missing in older files, where it is the 60 degree shape.

With a lead-in ("lead_in": "bevel"; missing in older files, where the ends
are cut square), the end where the thread starts is bevelled at 45
degrees: a bolt down to the thread's root at its end, a threaded Hole out
to its full size at the surface (a countersink), so they start into each
other easily. The bevel is a cone of flat strips, like a cylinder.
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

# Unified coarse (UNC) sizes: name -> (diameter in inches, threads per inch).
UNC = {
    "#2": (0.086, 56), "#4": (0.112, 40), "#5": (0.125, 40), "#6": (0.138, 32), "#8": (0.164, 32),
    "#10": (0.190, 24), "#12": (0.216, 24), "1/4": (0.25, 20), "5/16": (0.3125, 18),
    "3/8": (0.375, 16), "7/16": (0.4375, 14), "1/2": (0.5, 13), "9/16": (0.5625, 12),
    "5/8": (0.625, 11), "3/4": (0.75, 10), "7/8": (0.875, 9), "1": (1.0, 8), "1 1/8": (1.125, 7),
    "1 1/4": (1.25, 7),
}

# British parallel pipe sizes (ISO 228-1): name -> (diameter in mm, threads per inch).
PIPE = {
    "1/16": (7.723, 28), "1/8": (9.728, 28), "1/4": (13.157, 19), "3/8": (16.662, 19),
    "1/2": (20.955, 14), "5/8": (22.911, 14), "3/4": (26.441, 14), "7/8": (30.201, 14),
    "1": (33.249, 11), "1 1/4": (41.910, 11), "1 1/2": (47.803, 11), "2": (59.614, 11),
}

INCH = 25.4  # mm

STANDARDS = [
    ("metric", "Metric (pitch in mm)"),
    ("inch", "Inch, UNC (threads per inch)"),
    ("pipe", "British pipe, G (threads per inch)"),
]
THREAD_SHAPES = [
    ("flat", "60 degrees, flat tips (metric and inch)"),
    ("round", "55 degrees, round tips (British pipe)"),
]

ENDS = [("top", "At the top"), ("bottom", "At the bottom")]
HANDS = [("right", "Right-hand (tightens clockwise)"), ("left", "Left-hand (tightens anticlockwise)")]
LEAD_INS = [("none", "Cut square"), ("bevel", "Bevelled, to start easily")]

STEPS = 36  # flat strips to a turn, for each start
MAX_TURNS = 150  # turns of a one-start thread (fewer with more starts)
MAX_STARTS = 4
SEGMENTS = 64  # round the unthreaded part, as a cylinder

ROUND_PIECES = 6  # flat pieces to each half of a pipe thread's round crest or root

DEFAULTS = {"diameter": 10.0, "height": 20.0, "pitch": 1.5, "thread_length": 20.0,
            "end": "top", "hand": "right", "starts": 1, "thread_shape": "flat", "lead_in": "none"}


def standard_size(diameter: float) -> tuple[str, float]:
    """The nearest ISO metric size to `diameter`: (its name, its coarse pitch)."""
    size = min(ISO_COARSE, key=lambda d: abs(d - float(diameter)))
    return f"M{size:g}", ISO_COARSE[size]


def inch_size(diameter: float) -> tuple[str, int]:
    """The nearest UNC size to `diameter` mm: (its name, threads per inch)."""
    name = min(UNC, key=lambda n: abs(UNC[n][0] * INCH - float(diameter)))
    return name, UNC[name][1]


def pipe_size(diameter: float) -> tuple[str, int]:
    """The nearest British pipe size to `diameter` mm: (its name, threads per inch)."""
    name = min(PIPE, key=lambda n: abs(PIPE[n][0] - float(diameter)))
    return name, PIPE[name][1]


def standard_pitch(standard: str, diameter: float, pitch: float, per_inch: float = 0.0) -> float:
    """The pitch (mm) of a thread of `standard` on a `diameter` mm cylinder:
    a metric one's `pitch`; an inch or pipe one's from `per_inch`, or with
    0, from the standard count for the nearest size."""
    if standard == "metric":
        return float(pitch)
    if standard not in ("inch", "pipe"):
        raise ThreadError("Choose metric, inch or pipe.")
    count = float(per_inch)
    if count == 0.0:
        count = (inch_size if standard == "inch" else pipe_size)(diameter)[1]
    if not np.isfinite(count) or count <= 0.0:
        raise ThreadError("Type how many threads to an inch, or 0 for the standard count.")
    return INCH / count


def _shape(thread_shape: str) -> tuple[np.ndarray, np.ndarray]:
    """One pitch of the thread's shape, starting at a crest: where each
    corner is along the pitch (0 to 1) and how deep it is (in pitches)."""
    if thread_shape == "round":
        # Whitworth: arcs of radius r centred on the crest and the root,
        # meeting the 55 degree flanks where they touch them.
        r, h = 0.137329, 0.640327
        a = np.radians(np.linspace(0.0, 62.5, ROUND_PIECES + 1))
        crest_u, crest_d = r * np.sin(a), r * (1.0 - np.cos(a))
        root_u = np.concatenate([0.5 - crest_u[::-1], 0.5 + crest_u[1:]])
        root_d = np.concatenate([h - crest_d[::-1], h - crest_d[1:]])
        along = np.concatenate([crest_u, root_u, 1.0 - crest_u[::-1]])
        deep = np.concatenate([crest_d, root_d, crest_d[::-1]])
        return along, deep
    # ISO 68-1: crest P/8, flank, root P/4, flank, 5H/8 deep.
    h = 5.0 / 8.0 * np.sqrt(3.0) / 2.0
    return np.array([0.0, 1.0 / 8.0, 7.0 / 16.0, 11.0 / 16.0, 1.0]), np.array([0.0, 0.0, h, h, 0.0])


def depth(pitch: float, thread_shape: str = "flat") -> float:
    """How deep the thread is cut: 5H/8 for the 60 degree shape, 0.640P
    for the pipe shape."""
    return float(_shape(thread_shape)[1].max()) * float(pitch)


def starts_of(p: dict) -> int:
    """How many threads run side by side (see refusal for the allowed ones)."""
    return int(round(float(p.get("starts", 1))))


def refusal(p: dict) -> str | None:
    """Why these sizes can't make a thread, or None."""
    diameter, height = float(p["diameter"]), float(p["height"])
    pitch, length = float(p["pitch"]), float(p["thread_length"])
    starts = float(p.get("starts", 1))
    thread_shape = p.get("thread_shape", "flat")
    if thread_shape not in dict(THREAD_SHAPES):
        return "Choose the thread's shape."
    if pitch < 0.2:
        return "The pitch (how far the thread rises in one turn) must be at least 0.2 mm."
    if depth(pitch, thread_shape) > 0.4 * diameter:
        return (f"A {pitch:g} mm pitch cuts too deep for a {diameter:g} mm diameter. Use a pitch of "
                f"at most {0.4 * diameter / depth(1.0, thread_shape):.2f} mm, or a wider part.")
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
    if p.get("lead_in", "none") not in dict(LEAD_INS):
        return "Choose whether the thread's starting end is cut square or bevelled."
    return None


def _profile(u: np.ndarray, pitch: float, outer: float, thread_shape: str = "flat") -> np.ndarray:
    """The radius at `u` mm along one pitch of the thread: crest, flank
    down, root, flank up."""
    u = np.mod(u, pitch) / pitch
    along, deep = _shape(thread_shape)
    return np.interp(u, along, outer - deep * pitch)


def _section(pitch: float, outer: float, start: float, starts: int = 1,
             thread_shape: str = "flat") -> "m3.CrossSection":
    """A right-hand thread across at height `start` (so every piece of a
    thread lines up, whatever height it starts at), with `starts` threads
    side by side."""
    turns = np.linspace(0.0, 1.0, STEPS * starts, endpoint=False)
    corners = _shape(thread_shape)[0][:-1]
    # The angle at which each corner of the profile is reached, on each
    # thread.
    reached = [np.mod((start / pitch - corners - k) / starts, 1.0) for k in range(starts)]
    turns = np.unique(np.round(np.concatenate([turns, *reached]), 12))
    theta = 2.0 * np.pi * turns
    radius = _profile(start - pitch * starts * turns, pitch, outer, thread_shape)
    points = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    return m3.CrossSection([points])


def thread_mesh(p: dict, clearance: float = 0.0, hole: bool = False) -> trimesh.Trimesh:
    """The threaded cylinder `p` describes (see DEFAULTS). `clearance` > 0
    grows it that much on every side, as for a Hole's fit: the radius by
    `clearance`, the ends by `clearance` each, with the thread's turns kept
    where they were so a bolt of the same sizes fits it. `hole` says it is
    a Hole, whose lead-in widens instead of narrowing (see _lead_in)."""
    p = {**DEFAULTS, **p}
    problem = refusal(p)
    if problem is not None:
        raise ThreadError(problem)
    c = max(float(clearance), 0.0)
    height, pitch = float(p["height"]), float(p["pitch"])
    outer = float(p["diameter"]) / 2.0 + c
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
        _section(pitch, outer, start, starts, p["thread_shape"]), stop - start,
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
    if p["lead_in"] == "bevel":
        solid = _lead_in(solid, p, outer, c, hole)
    return from_manifold(solid)


def _lead_in(solid: "m3.Manifold", p: dict, outer: float, c: float, hole: bool) -> "m3.Manifold":
    """`solid` with the end where its thread starts bevelled at 45 degrees.
    A bolt is cut down to the thread's root at that end. A Hole gets a
    countersink: its full size (`outer`, grown by its fit `c`) at the
    surface, narrowing to the thread's root one thread depth in, and
    reaching past the surface as far as the Hole does."""
    height = float(p["height"])
    deep = depth(float(p["pitch"]), p["thread_shape"])
    inner = outer - deep
    top = p["end"] != "bottom"
    face = height if top else 0.0
    if hole:
        if top:
            cone = m3.Manifold.cylinder(deep + c, inner, outer + c, SEGMENTS).translate((0.0, 0.0, face - deep))
        else:
            cone = m3.Manifold.cylinder(deep + c, outer + c, inner, SEGMENTS).translate((0.0, 0.0, -c))
        return solid + cone
    # What is kept: a cone from the root at the face, widening past the
    # thread's full size, then a plain cylinder for the rest.
    wide = outer + 1.0
    reach = wide - inner
    rest = height + 2.0 - reach
    if top:
        keep = m3.Manifold.cylinder(reach, wide, inner, SEGMENTS).translate((0.0, 0.0, face - reach))
        if rest > 0.0:
            keep = keep + m3.Manifold.cylinder(rest, wide, wide, SEGMENTS).translate((0.0, 0.0, face - reach - rest))
    else:
        keep = m3.Manifold.cylinder(reach, inner, wide, SEGMENTS)
        if rest > 0.0:
            keep = keep + m3.Manifold.cylinder(rest, wide, wide, SEGMENTS).translate((0.0, 0.0, reach))
    return solid ^ keep
