"""Operations on shapes: combining, arranging, duplicating.

All combining goes through manifold3d, which guarantees watertight output.
That guarantee is the whole reason this app can promise printable STLs.
"""

import copy
import uuid

import numpy as np
import trimesh

from mesh.blobs import encode_mesh
from mesh.scene import Shape
from mesh.shapes import shape_geometry

ENGINE = "manifold"
OPS = ("union", "difference", "intersection")


class NothingToCombineError(Exception):
    """Raised when a combine has no solid shapes to build from."""


def _union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    if len(meshes) == 1:
        return meshes[0]
    return trimesh.boolean.union(meshes, engine=ENGINE)


def evaluate(shapes: list[Shape]) -> trimesh.Trimesh:
    """Union every solid, then subtract every hole."""
    solids = [shape_geometry(s) for s in shapes if not s.is_hole]
    holes = [shape_geometry(s) for s in shapes if s.is_hole]

    if not solids:
        raise NothingToCombineError(
            "Select at least one solid shape. A group made only of holes has nothing to cut into."
        )

    result = _union(solids)
    if holes:
        result = trimesh.boolean.difference([result, _union(holes)], engine=ENGINE)
    return result


def boolean(shapes: list[Shape], op: str) -> trimesh.Trimesh:
    """Explicit boolean, ignoring the is_hole flag."""
    if op not in OPS:
        raise ValueError(f"unknown operation {op!r}; expected one of {OPS}")
    meshes = [shape_geometry(s) for s in shapes]
    if not meshes:
        raise NothingToCombineError("Select at least one shape.")
    if len(meshes) == 1:
        return meshes[0]
    return getattr(trimesh.boolean, op)(meshes, engine=ENGINE)


# Plain-language labels for the explicit menu items. Solid/Hole + Group
# stays the primary path the UI teaches; these are the secondary route
# for a user who wants the operator directly instead of the flag.
BOOLEAN_LABELS = {"union": "Join", "difference": "Cut Out", "intersection": "Keep Overlap"}


def make_boolean_group(shapes: list[Shape], op: str, name: str | None = None) -> Shape:
    """Explicit Union/Subtract/Intersect, wrapped as a group shape exactly
    like make_group() -- same reversible-by-ungroup shape, just built from
    `boolean()` (which ignores is_hole) instead of `evaluate()`."""
    result = boolean(shapes, op)
    return Shape(
        id=uuid.uuid4().hex,
        name=name or BOOLEAN_LABELS.get(op, op),
        kind="group",
        params={
            "blob": encode_mesh(result),
            "children": [s.to_dict() for s in shapes],
        },
        transform=np.eye(4, dtype=np.float64),
        color=shapes[0].color,
    )


def make_group(shapes: list[Shape], name: str = "Group") -> Shape:
    """Combine shapes into one group shape, retaining children for ungroup."""
    result = evaluate(shapes)
    return Shape(
        id=uuid.uuid4().hex,
        name=name,
        kind="group",
        params={
            "blob": encode_mesh(result),
            "children": [s.to_dict() for s in shapes],
        },
        transform=np.eye(4, dtype=np.float64),
        color=next((s.color for s in shapes if not s.is_hole), shapes[0].color),
    )


def ungroup(shape: Shape) -> list[Shape]:
    """Restore a group's original children."""
    if shape.kind != "group":
        raise ValueError(f"{shape.name!r} is not a group")
    children = [Shape.from_dict(d) for d in shape.params["children"]]
    outer = np.asarray(shape.transform, dtype=np.float64)
    for child in children:
        child.transform = outer @ np.asarray(child.transform, dtype=np.float64)
    return children


AXES = {"x": 0, "y": 1, "z": 2}
ALIGN_MODES = ("min", "center", "max")


def duplicate(shape: Shape, offset=(10.0, 10.0, 0.0)) -> Shape:
    clone = copy.deepcopy(shape)
    clone.id = uuid.uuid4().hex
    clone.transform = np.asarray(clone.transform, dtype=np.float64).copy()
    clone.transform[:3, 3] += np.asarray(offset, dtype=np.float64)
    return clone


def mirror(shape: Shape, axis: str) -> Shape:
    """Mirror a shape about its own centre, leaving it where it sits."""
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}; expected one of {tuple(AXES)}")
    index = AXES[axis]
    centre = shape_geometry(shape).bounds.mean(axis=0)

    flip = np.eye(4, dtype=np.float64)
    flip[index, index] = -1.0

    to_origin = np.eye(4, dtype=np.float64)
    to_origin[:3, 3] = -centre
    back = np.eye(4, dtype=np.float64)
    back[:3, 3] = centre

    shape.transform = back @ flip @ to_origin @ np.asarray(shape.transform, dtype=np.float64)
    return shape


def align(shapes: list[Shape], axis: str, mode: str) -> None:
    """Line shapes up along one axis. Mutates their transforms."""
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}; expected one of {tuple(AXES)}")
    if mode not in ALIGN_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {ALIGN_MODES}")
    if len(shapes) < 2:
        return

    index = AXES[axis]
    bounds = [shape_geometry(s).bounds for s in shapes]

    if mode == "min":
        target = min(b[0][index] for b in bounds)
        current = [b[0][index] for b in bounds]
    elif mode == "max":
        target = max(b[1][index] for b in bounds)
        current = [b[1][index] for b in bounds]
    else:
        values = [(b[0][index] + b[1][index]) / 2.0 for b in bounds]
        target = sum(values) / len(values)
        current = values

    for shape, value in zip(shapes, current):
        shape.transform = np.asarray(shape.transform, dtype=np.float64).copy()
        shape.transform[index, 3] += target - value


def drop_to_plane(shape: Shape) -> None:
    """Sit a shape on the workplane."""
    low_z = shape_geometry(shape).bounds[0][2]
    shape.transform = np.asarray(shape.transform, dtype=np.float64).copy()
    shape.transform[2, 3] -= low_z
