"""Making shapes from sketches: Expert mode's Sketch and Create tools.

Every function here returns new shapes (or a changed copy) and leaves the
scene alone; the window snapshots and applies the result only when the call
succeeds. A request that can't be met raises BuildError with a plain message.
"""

import copy
import re
import uuid

import numpy as np

from mesh import construct, features, sketch, threads
from mesh.builders import BuildError
from mesh.ops import face_direction
from mesh.scene import Shape
from mesh.shapes import shape_geometry

SKETCH_COLOR = "#e8a33d"


def _checked(build):
    """Run `build`, turning a sketch's or thread's complaint into a
    BuildError."""
    try:
        return build()
    except (sketch.SketchError, threads.ThreadError) as exc:
        raise BuildError(str(exc)) from exc


# --- Sketches -----------------------------------------------------------------------


def is_sketch(shape) -> bool:
    return shape.kind == "primitive" and shape.params.get("primitive") == "sketch"


def next_sketch_name(shapes) -> str:
    """"Sketch N", one more than the highest number in use."""
    numbers = [int(m.group(1)) for s in shapes if (m := re.fullmatch(r"Sketch (\d+)", s.name))]
    return f"Sketch {max(numbers, default=0) + 1}"


def new_sketch(entities, frame, name: str = "Sketch") -> Shape:
    """A sketch holding `entities`, drawn on the plane `frame` places."""
    entities = _checked(lambda: sketch.clean_entities(entities))
    if not entities:
        raise BuildError("Draw at least one curve first.")
    frame = np.asarray(frame, dtype=np.float64)
    if frame.shape != (4, 4) or not np.isfinite(frame).all():
        raise ValueError("a sketch's frame must be a 4x4 transform")
    return Shape(
        id=uuid.uuid4().hex,
        name=name,
        kind="primitive",
        params={"primitive": "sketch", "entities": entities},
        transform=frame.copy(),
        color=SKETCH_COLOR,
    )


def has_sketch(shape) -> bool:
    """A sketch, or a part made from one outline: its curves can be changed."""
    return shape.kind == "primitive" and (
        is_sketch(shape) or shape.params.get("primitive") in features.ONE_OUTLINE
    )


def sketch_entities(shape) -> list[dict]:
    """The curves of a sketch, or of the sketch a part was made from."""
    if is_sketch(shape):
        return shape.params["entities"]
    return shape.params.get("entities") or features.default_entities(shape.params["primitive"])


def with_entities(shape: Shape, entities, clearances: dict | None = None) -> Shape:
    """A copy of `shape` (a sketch, or a part made from one) drawing
    `entities` instead, checked: a part must still come out solid, at its
    fit if it is a Hole (pass the scene's fit clearances)."""
    if not has_sketch(shape):
        raise BuildError("Select a sketch, or a part made from one, to change its curves.")
    entities = _checked(lambda: sketch.clean_entities(entities))
    if not entities:
        raise BuildError("A sketch needs at least one curve.")
    changed = copy.deepcopy(shape)
    changed.params["entities"] = entities
    if "axis_line" in shape.params:
        _follow_axis_line(shape, changed)
    if not is_sketch(shape):
        _checked(lambda: shape_geometry(changed, clearances))
    return changed


def _follow_axis_line(old: Shape, changed: Shape) -> None:
    """A revolve made around one of its sketch's lines keeps turning around
    that line when the curves change, wherever the line was moved to."""
    before, after = old.params["entities"], changed.params["entities"]
    index = int(old.params["axis_line"])
    line = before[index] if 0 <= index < len(before) else None
    if line in after:
        index = after.index(line)
    elif len(after) != len(before) or after[index].get("type") != "line":
        raise BuildError(
            "The line this revolve turns around is gone. Keep that line, or undo the "
            "revolve and choose another line to turn around."
        )
    axis = revolve_axis(changed, f"line:{index}")
    turn = _checked(lambda: np.linalg.inv(features.axis_frame(old.params["axis"])) @ features.axis_frame(axis))
    changed.transform = np.asarray(old.transform, dtype=np.float64) @ turn
    changed.params["axis"] = axis
    changed.params["axis_line"] = index


def fit_refusal(shapes, clearances: dict | None) -> str | None:
    """Why one of `shapes`, a Hole made from a sketch, can't be made at its
    fit with these fit clearances; None if they all can. (A sweep or loft
    grown by a fit's clearance can bend too tightly or close a gap.)"""
    for shape in shapes:
        if (shape.kind == "primitive" and shape.is_hole
                and shape.params.get("primitive") in features.SOLIDS):
            try:
                shape_geometry(shape, clearances)
            except sketch.SketchError as exc:
                return f"{shape.name} can't be made at that fit. {exc}"
    return None


def edit_refusal(shape, field: str, value, clearances: dict | None) -> str | None:
    """Why `shape`, a part made from a sketch or a thread, can't take
    `value` for its number or choice `field` (typed in the Details panel,
    say: sloped sides can meet, or a pitch too deep for the diameter); None
    if it can, or if `shape` is neither."""
    kind = shape.params.get("primitive") if shape.kind == "primitive" else None
    if kind not in features.SOLIDS and kind != "thread":
        return None
    trial = copy.deepcopy(shape)
    trial.params[field] = value if isinstance(value, str) else float(value)
    try:
        shape_geometry(trial, clearances)
    except (sketch.SketchError, threads.ThreadError) as exc:
        return str(exc)
    return None


# --- Solids from sketches -----------------------------------------------------------


def _from_sketch(source: Shape, primitive: str, label: str, params: dict, hole: bool,
                 local=None) -> Shape:
    """A new part made from the sketch `source`, checked to come out solid.
    It sits on the sketch's plane, moved by `local` (in the sketch's own
    coordinates) when given."""
    transform = np.asarray(source.transform, dtype=np.float64).copy()
    if local is not None:
        transform = transform @ local
    shape = Shape(
        id=uuid.uuid4().hex,
        name=f"{label} of {source.name}",
        kind="primitive",
        params={"primitive": primitive, "entities": copy.deepcopy(source.params["entities"]), **params},
        transform=transform,
        is_hole=bool(hole),
    )
    _checked(lambda: shape_geometry(shape))
    return shape


def make_extrude(source: Shape, distance: float, side: str = "one", hole: bool = False,
                 taper: float = 0.0) -> Shape:
    """The sketch's closed outlines pushed `distance` mm out of its plane,
    their sides sloping in by `taper` degrees (out, for less than 0)."""
    if not is_sketch(source):
        raise BuildError("Select a sketch to extrude.")
    params = {"distance": float(distance), "side": str(side)}
    if float(taper) != 0.0:
        params["taper"] = float(taper)  # missing means straight sides, as before
    return _from_sketch(source, "extrude", "Extrusion", params, hole)


# How square a plane must be to a sketch to count as parallel to it (the
# cosine of the angle between the ways they face): within about 0.1 degrees.
PARALLEL = 1.0 - 1e-6


def distance_to_plane(source: Shape, plane: Shape) -> tuple[float, str]:
    """How far to extrude the sketch `source` so its far end lies on the
    construction plane `plane`, and which way: (distance, side). Fusion's
    "To object" extent, for a plane parallel to the sketch; worked out
    once, from where the plane is now."""
    if not is_sketch(source) or not construct.is_guide(plane, "plane"):
        raise BuildError("Select a sketch and a construction plane to extrude up to.")
    frame = np.asarray(source.transform, dtype=np.float64)
    facing = frame[:3, 2] / np.linalg.norm(frame[:3, 2])
    point, normal = construct.plane_of(plane)
    if abs(float(facing @ normal)) < PARALLEL:
        raise BuildError(
            f"{plane.name} is not parallel to {source.name}, so an extrusion can't end flat on it. "
            "Use a plane parallel to the sketch, or type a distance."
        )
    distance = float((point - frame[:3, 3]) @ facing)
    if abs(distance) < sketch.MIN_SIZE:
        raise BuildError(f"{plane.name} lies on {source.name}'s plane, so there is no distance to extrude.")
    return abs(distance), ("one" if distance > 0.0 else "other")


def revolve_axes(source: Shape) -> list[tuple[str, str]]:
    """The lines a sketch's outline can turn around: (key, plain label).
    The sketch's own Y and X lines, then every straight line drawn in it."""
    choices = [
        ("y", "The sketch's Y line (through 0, 0, going up)"),
        ("x", "The sketch's X line (through 0, 0, going right)"),
    ]
    for index, entity in enumerate(source.params.get("entities", [])):
        if entity.get("type") == "line":
            choices.append((f"line:{index}", sketch.describe(entity)))
    return choices


def revolve_axis(source: Shape, key: str) -> list[float]:
    """The axis [x, y, dx, dy] a key from revolve_axes stands for."""
    if key == "y":
        return [0.0, 0.0, 0.0, 1.0]
    if key == "x":
        return [0.0, 0.0, 1.0, 0.0]
    try:
        entity = source.params["entities"][int(key.removeprefix("line:"))]
    except (KeyError, IndexError, ValueError) as exc:
        raise BuildError("Choose a line of the sketch to turn around.") from exc
    if not key.startswith("line:") or entity.get("type") != "line":
        raise BuildError("Choose a line of the sketch to turn around.")
    (sx, sy), (ex, ey) = entity["start"], entity["end"]
    return [float(sx), float(sy), float(ex - sx), float(ey - sy)]


def make_revolve(source: Shape, axis_key: str = "y", angle: float = 360.0, hole: bool = False) -> Shape:
    """The sketch's closed outlines turned `angle` degrees about a line."""
    if not is_sketch(source):
        raise BuildError("Select a sketch to revolve.")
    axis = revolve_axis(source, axis_key)
    local = _checked(lambda: features.axis_frame(axis))
    params = {"axis": axis, "angle": float(angle)}
    if axis_key.startswith("line:"):
        # Which of the sketch's curves is the line, so Change Sketch can follow it.
        params["axis_line"] = int(axis_key.removeprefix("line:"))
    return _from_sketch(source, "revolve", "Revolve", params, hole, local)


def likely_path(first: Shape, second: Shape) -> Shape:
    """Which of two sketches is the path for a Sweep: the one drawing an
    open path and no closed outline, else the second one picked."""
    for candidate in (first, second):
        try:
            found = sketch.chains(candidate.params["entities"])
        except sketch.SketchError:
            continue
        if found.paths and not found.loops:
            return candidate
    return second


def make_sweep(outline: Shape, path: Shape, hole: bool = False, twist: float = 0.0,
               end_scale: float = 100.0) -> Shape:
    """The closed outlines of the sketch `outline` carried along the one
    path drawn in the sketch `path`, turning `twist` degrees and changing
    to `end_scale` percent of their size by the far end. The part's own
    coordinates are the world's, so both sketches are stored with where
    they were."""
    if not (is_sketch(outline) and is_sketch(path)) or outline.id == path.id:
        raise BuildError("Select two sketches: the outline, and the path to sweep it along.")
    shape = Shape(
        id=uuid.uuid4().hex,
        name=f"Sweep of {outline.name}",
        kind="primitive",
        params={
            "primitive": "sweep",
            "entities": copy.deepcopy(outline.params["entities"]),
            "profile_frame": np.asarray(outline.transform, dtype=np.float64).tolist(),
            "path_entities": copy.deepcopy(path.params["entities"]),
            "path_frame": np.asarray(path.transform, dtype=np.float64).tolist(),
        },
        transform=np.eye(4),
        is_hole=bool(hole),
    )
    # Kept only when used, so a plain sweep's settings are as before.
    if float(twist) != 0.0:
        shape.params["twist"] = float(twist)
    if float(end_scale) != 100.0:
        shape.params["end_scale"] = float(end_scale)
    _checked(lambda: shape_geometry(shape))
    return shape


LOFT_PICKS = ("Select two or more sketches, in the order to join them. A construction point "
              "may come first or last, to close the loft to that point.")


def loft_picks_fit(shapes) -> bool:
    """Whether `shapes`, in order, can be lofted: two or more, sketches
    except that the first or last may be a construction point, and at least
    one sketch."""
    shapes = list(shapes)
    ends = (0, len(shapes) - 1)
    return (len(shapes) >= 2 and any(is_sketch(s) for s in shapes)
            and all(is_sketch(s) or (k in ends and construct.is_guide(s, "point"))
                    for k, s in enumerate(shapes)))


def make_loft(sketches, hole: bool = False, sides: str = "straight") -> Shape:
    """A skin through the closed outline of each sketch, in the order given,
    its sides straight or smooth (features.LOFT_SIDES). A construction point
    first or last closes it to that point (kept as where the point is now).
    Like a sweep, its own coordinates are the world's."""
    sketches = list(sketches)
    if not loft_picks_fit(sketches):
        raise BuildError(LOFT_PICKS)

    def section(s) -> dict:
        if not is_sketch(s):
            return {"point": construct.point_of(s).tolist()}
        return {"entities": copy.deepcopy(s.params["entities"]),
                "frame": np.asarray(s.transform, dtype=np.float64).tolist()}

    shape = Shape(
        id=uuid.uuid4().hex,
        name=f"Loft of {sketches[0].name} to {sketches[-1].name}",
        kind="primitive",
        params={
            "primitive": "loft",
            "sections": [section(s) for s in sketches],
        },
        transform=np.eye(4),
        is_hole=bool(hole),
    )
    # Kept only when used, so a plain loft's settings are as before.
    if sides != "straight":
        shape.params["sides"] = sides
    _checked(lambda: shape_geometry(shape))
    return shape


def _boundary_loops(tm, faces) -> list[np.ndarray]:
    """The outlines (3D point loops) around a group of triangles."""
    edges = np.sort(tm.faces[faces][:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    outer = unique[counts == 1]
    nxt: dict[int, list[int]] = {}
    for a, b in outer:
        nxt.setdefault(int(a), []).append(int(b))
        nxt.setdefault(int(b), []).append(int(a))
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, previous, current = [start], None, start
        seen.add(start)
        while True:
            onward = [v for v in nxt[current] if v != previous]
            if not onward or onward[0] == start or onward[0] in seen:
                break
            previous, current = current, onward[0]
            loop.append(current)
            seen.add(current)
        if len(loop) >= 3:
            loops.append(tm.vertices[loop])
    return loops


def face_plane(shape: Shape, face_index: int, clearances: dict | None = None):
    """The plane of the flat face a click landed on, for a new sketch:
    (frame, the face's outlines in that sketch's coordinates).

    The face is every triangle lying flat and joined with the clicked one,
    so a box's top or a cylinder's end is one face. On a curved surface it
    is just the clicked triangle's own plane.
    """
    tm = shape_geometry(shape, clearances)
    normal = face_direction(shape, face_index, clearances)
    faces = np.array([face_index])
    for facet in tm.facets:
        if face_index in facet:
            faces = np.asarray(facet)
            break
    frame = sketch.plane_frame(normal, tm.vertices[tm.faces[face_index][0]])
    outlines = [sketch.to_sketch(frame, loop) for loop in _boundary_loops(tm, faces)]
    return frame, outlines


def outline_entities(outlines) -> list[dict]:
    """A face's outlines as sketch lines, so they can be traced."""
    entities = []
    for loop in outlines:
        loop = np.asarray(loop, dtype=np.float64)
        for a, b in zip(loop, np.roll(loop, -1, axis=0)):
            if np.linalg.norm(b - a) >= sketch.MIN_SIZE:
                entities.append({"type": "line", "start": [float(a[0]), float(a[1])],
                                 "end": [float(b[0]), float(b[1])]})
    return entities


# --- Threads ------------------------------------------------------------------------


NOT_A_CYLINDER = "Select one cylinder (a part, or a Hole for a threaded hole) to put a thread on."
TUBE_THREAD = ("A thread goes on a cylinder, not a tube. For a thread on the outside, thread a cylinder "
               "and group a cylinder Hole through it; for one inside, group a threaded cylinder Hole "
               "inside a cylinder.")


def thread_choice(shape) -> tuple[str, float]:
    """The standard size nearest the cylinder's diameter: (name, pitch)."""
    return threads.standard_size(float(shape.params.get("diameter", 20.0)))


def threaded(shape: Shape, pitch: float, length: float, end: str = "top", hand: str = "right",
             clearances: dict | None = None, starts: int = 1, standard: str = "metric",
             per_inch: float = 0.0, lead_in: str = "none") -> Shape:
    """A copy of the cylinder `shape` with a thread along `length` mm of
    it, starting at `end`, with `starts` threads side by side. Its diameter
    is the thread's full diameter; everything else about it (where it is,
    its colour, Solid or Hole) is kept. As a Hole it cuts a threaded hole a
    bolt of the same sizes fits. A metric thread has the `pitch` given; an
    inch or pipe one has `per_inch` threads to an inch (0: the standard
    count for the nearest size), and a pipe one the pipe thread's shape.
    With `lead_in` "bevel", the end where the thread starts is bevelled."""
    if shape.kind != "primitive" or shape.params.get("primitive") != "cylinder":
        raise BuildError(NOT_A_CYLINDER)
    if float(shape.params.get("chamfer", 0.0)) > 0.0:
        raise BuildError(f"{shape.name} has a bottom chamfer, which a thread can't keep. Set its "
                         "bottom chamfer to 0 in the Details panel first.")
    diameter = float(shape.params.get("diameter", 20.0))
    try:
        pitch = threads.standard_pitch(standard, diameter, pitch, per_inch)
    except threads.ThreadError as exc:
        raise BuildError(str(exc)) from exc
    changed = copy.deepcopy(shape)
    changed.params = {
        "primitive": "thread",
        "diameter": diameter,
        "height": float(shape.params.get("height", 20.0)),
        "pitch": float(pitch),
        "thread_length": float(min(length, float(shape.params.get("height", 20.0)))),
        "end": end,
        "hand": hand,
    }
    # Kept only when used, so a one-start thread's settings are as before.
    if float(starts) != 1.0:
        changed.params["starts"] = int(starts) if float(starts) == int(starts) else float(starts)
    if standard == "pipe":
        changed.params["thread_shape"] = "round"
    if lead_in != "none":
        changed.params["lead_in"] = lead_in
    _checked(lambda: shape_geometry(changed, clearances))
    return changed
