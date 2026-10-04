"""Making shapes from sketches: Expert mode's Sketch and Create tools.

Every function here returns new shapes (or a changed copy) and leaves the
scene alone; the window snapshots and applies the result only when the call
succeeds. A request that can't be met raises BuildError with a plain message.
"""

import copy
import re
import uuid

import numpy as np

from mesh import sketch
from mesh.builders import BuildError
from mesh.ops import face_direction
from mesh.scene import Shape
from mesh.shapes import shape_geometry

SKETCH_COLOR = "#e8a33d"


def _checked(build):
    """Run `build`, turning a sketch's complaint into a BuildError."""
    try:
        return build()
    except sketch.SketchError as exc:
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


def with_entities(shape: Shape, entities) -> Shape:
    """A copy of `shape` (a sketch) drawing `entities` instead, checked."""
    if not is_sketch(shape):
        raise BuildError("Select a sketch to change its curves.")
    entities = _checked(lambda: sketch.clean_entities(entities))
    if not entities:
        raise BuildError("A sketch needs at least one curve.")
    changed = copy.deepcopy(shape)
    changed.params["entities"] = entities
    return changed


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
