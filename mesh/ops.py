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
