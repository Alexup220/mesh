"""Operations on shapes: combining, arranging, duplicating.

All combining goes through manifold3d, which guarantees watertight output.
That guarantee is the whole reason this app can promise printable STLs.
"""

import copy
import uuid

import numpy as np
import trimesh

from mesh.blobs import encode_mesh
from mesh.scene import Shape, euler_from_transform, transform_with_euler
from mesh.shapes import is_reference, shape_geometry

ENGINE = "manifold"
OPS = ("union", "difference", "intersection")


class NothingToCombineError(Exception):
    """Raised when a combine has no solid shapes to build from."""


class NothingLeftError(NothingToCombineError):
    """Raised when a combine would leave no solid at all: the holes cover
    every solid part, or a cut or overlap removes everything."""


EVERYTHING_CUT_AWAY = (
    "The holes cut away all of the solid parts, so nothing would be left. "
    "Move a hole or make it smaller."
)

HAS_GAPS = (
    "A part here has gaps in its surface, so it can't be joined to the others. "
    "Hide or remove that part, or import a closed version of it."
)


class HasGapsError(NothingToCombineError):
    """Raised when a part is not a closed solid, so nothing can be combined
    with it (an imported model with holes in its surface, say)."""


NOTHING_LEFT = {
    "difference": (
        "The other shapes cover all of the first one, so cutting them out "
        "would leave nothing. Move them or make them smaller."
    ),
    "intersection": "These shapes do not overlap, so there is nothing to keep.",
}


def _something_left(result: trimesh.Trimesh, message: str) -> trimesh.Trimesh:
    # manifold3d returns an empty result (no faces, no bounds) rather than
    # failing; anything downstream that measures it would crash.
    if result.is_empty or len(result.faces) == 0:
        raise NothingLeftError(message)
    return result


def _combine(op: str, meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    try:
        return getattr(trimesh.boolean, op)(meshes, engine=ENGINE)
    except ValueError as exc:
        # trimesh refuses anything that is not a closed solid ("Not all
        # meshes are volumes!") before the engine sees it.
        raise HasGapsError(HAS_GAPS) from exc


def _union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    if len(meshes) == 1:
        return meshes[0]
    return _combine("union", meshes)


def evaluate(shapes: list[Shape], clearances: dict | None = None) -> trimesh.Trimesh:
    """Union every solid, then subtract every hole.

    `clearances` is the scene's fit_clearances: Holes with a fit are cut at
    their fitted size (see mesh.shapes.hole_clearance). Guides (sketches)
    are never part of the result.
    """
    shapes = [s for s in shapes if not is_reference(s)]
    solids = [shape_geometry(s, clearances) for s in shapes if not s.is_hole]
    holes = [shape_geometry(s, clearances) for s in shapes if s.is_hole]

    if not solids:
        raise NothingToCombineError(
            "Select at least one solid shape. A group made only of holes has nothing to cut into."
        )

    result = _union(solids)
    if holes:
        result = _combine("difference", [result, _union(holes)])
    return _something_left(result, EVERYTHING_CUT_AWAY)


def boolean(shapes: list[Shape], op: str, clearances: dict | None = None) -> trimesh.Trimesh:
    """Explicit boolean, ignoring the is_hole flag. Guides (sketches) are
    left out."""
    if op not in OPS:
        raise ValueError(f"unknown operation {op!r}; expected one of {OPS}")
    meshes = [shape_geometry(s, clearances) for s in shapes if not is_reference(s)]
    if not meshes:
        raise NothingToCombineError("Select at least one shape.")
    if len(meshes) == 1:
        return meshes[0]
    result = _combine(op, meshes)
    return _something_left(result, NOTHING_LEFT.get(op, EVERYTHING_CUT_AWAY))


# Plain-language labels for the explicit menu items. Solid/Hole + Group
# stays the primary path the UI teaches; these are the secondary route
# for a user who wants the operator directly instead of the flag.
BOOLEAN_LABELS = {"union": "Join", "difference": "Cut Out", "intersection": "Keep Overlap"}


def make_boolean_group(
    shapes: list[Shape], op: str, name: str | None = None, clearances: dict | None = None
) -> Shape:
    """Explicit Union/Subtract/Intersect, wrapped as a group shape exactly
    like make_group() -- same reversible-by-ungroup shape, just built from
    `boolean()` (which ignores is_hole) instead of `evaluate()`."""
    result = boolean(shapes, op, clearances)
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


def make_group(
    shapes: list[Shape], name: str = "Group", clearances: dict | None = None
) -> Shape:
    """Combine shapes into one group shape, retaining children for ungroup.

    The stored result is evaluated once, here, with the given fit
    clearances; the children keep their fit so Ungroup restores it.
    """
    result = evaluate(shapes, clearances)
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


def fresh_ids(shape: Shape) -> Shape:
    """Give a copied shape a new id, and every part stored inside a group
    (at any depth) a new one too, so Ungroup on two copies never gives two
    parts the same id. Changes and returns `shape`."""
    shape.id = uuid.uuid4().hex

    def renew(children: list) -> None:
        for child in children:
            child["id"] = uuid.uuid4().hex
            if child.get("kind") == "group":
                renew(child.get("params", {}).get("children", []))

    if shape.kind == "group":
        renew(shape.params.get("children", []))
    return shape


def duplicate(shape: Shape, offset=(10.0, 10.0, 0.0)) -> Shape:
    clone = fresh_ids(copy.deepcopy(shape))
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


def rotation_between(a, b) -> np.ndarray:
    """The 3x3 rotation that turns direction `a` onto direction `b`.

    Always a proper rotation (no mirroring). Turning a direction onto its
    exact opposite picks a half turn about an axis perpendicular to it.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        raise ValueError("a direction needs a length")
    a, b = a / na, b / nb
    axis = np.cross(a, b)
    s = np.linalg.norm(axis)
    c = float(np.dot(a, b))
    if s < 1e-9:
        if c > 0.0:
            return np.eye(3)
        # Opposite: half turn about any axis perpendicular to a.
        helper = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, helper)
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    axis /= s
    k = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]])
    return np.eye(3) + s * k + (1.0 - c) * (k @ k)


def _canonical(transform: np.ndarray) -> np.ndarray:
    """Re-express a transform through the euler helpers, so its rotation is
    exactly what the inspector shows and edits (see mesh.scene).

    A slanted transform (a part stretched along a direction it was not
    built along) can't be written as turns and sizes; re-expressing it
    would change the part's shape, so it is kept exactly as it is.
    """
    gram = transform[:3, :3].T @ transform[:3, :3]
    slant = np.abs(gram - np.diag(np.diag(gram))).max()
    if slant > 1e-9 * max(float(np.abs(np.diag(gram)).max()), 1e-12):
        return transform
    rx, ry, rz = euler_from_transform(transform)
    return transform_with_euler(transform, rx, ry, rz)


def rotate_about(shape: Shape, rotation: np.ndarray, centre) -> None:
    """Turn a shape in place about a world point. Rotation lives in the
    transform, never in params."""
    centre = np.asarray(centre, dtype=np.float64)
    turn = np.eye(4, dtype=np.float64)
    turn[:3, :3] = rotation
    to_origin = np.eye(4, dtype=np.float64)
    to_origin[:3, 3] = -centre
    back = np.eye(4, dtype=np.float64)
    back[:3, 3] = centre
    shape.transform = _canonical(back @ turn @ to_origin @ np.asarray(shape.transform, dtype=np.float64))


def face_direction(shape: Shape, face_index: int, clearances: dict | None = None) -> np.ndarray:
    """Which way a face of the shape points, in world space.

    `face_index` counts triangles in the same order the viewport draws them
    (the viewport builds its picture from shape_geometry with the same
    clearances), so a picked triangle maps straight back to a direction.
    """
    tm = shape_geometry(shape, clearances)
    if not 0 <= face_index < len(tm.faces):
        raise IndexError(face_index)
    direction = np.asarray(tm.face_normals[face_index], dtype=np.float64)
    if np.linalg.norm(direction) < 1e-9:
        # A sliver triangle with no area has no direction of its own (a
        # bevel or rounded edge can leave these); use its neighbours'.
        pairs = tm.face_adjacency
        around = np.concatenate([
            pairs[pairs[:, 0] == face_index, 1], pairs[pairs[:, 1] == face_index, 0],
        ])
        direction = (tm.face_normals[around] * tm.area_faces[around, None]).sum(axis=0)
        length = np.linalg.norm(direction)
        if length < 1e-9:
            raise IndexError(face_index)
        direction = direction / length
    return direction


def lay_flat(shape: Shape, direction) -> None:
    """Turn the shape so the face pointing along `direction` (world space)
    rests on the workplane, then sit it on the plane. X/Y stay where the
    shape's centre was."""
    centre = shape_geometry(shape).bounds.mean(axis=0)
    rotate_about(shape, rotation_between(direction, (0.0, 0.0, -1.0)), centre)
    drop_to_plane(shape)


def place_on_face(shape: Shape, point, direction) -> None:
    """Stand a shape on a face of another part.

    The shape is turned so its "up" points along `direction` (the face's
    outward direction, world space) and moved so the centre of its
    footprint lands on `point`. A solid sits on the face; a Hole is sunk
    into it instead, top flush with the face, so a screw hole or engraved
    text placed this way actually cuts into the part.
    """
    point = np.asarray(point, dtype=np.float64)
    bounds = shape_geometry(shape).bounds
    anchor = np.array([
        (bounds[0][0] + bounds[1][0]) / 2.0,
        (bounds[0][1] + bounds[1][1]) / 2.0,
        bounds[1][2] if shape.is_hole else bounds[0][2],
    ])
    turn = np.eye(4, dtype=np.float64)
    turn[:3, :3] = rotation_between((0.0, 0.0, 1.0), direction)
    to_anchor = np.eye(4, dtype=np.float64)
    to_anchor[:3, 3] = -anchor
    to_point = np.eye(4, dtype=np.float64)
    to_point[:3, 3] = point
    shape.transform = _canonical(
        to_point @ turn @ to_anchor @ np.asarray(shape.transform, dtype=np.float64)
    )


def distance(a, b) -> float:
    """Straight-line distance between two world points, in mm."""
    return float(np.linalg.norm(np.asarray(b, dtype=np.float64) - np.asarray(a, dtype=np.float64)))
