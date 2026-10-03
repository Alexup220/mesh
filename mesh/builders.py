"""Tools that turn one part into something new: hollow out, split, box with lid.

Each one returns ordinary group shapes built from ordinary children (the
original part, Holes, pegs), so Ungroup always gives the pieces back, and
everything goes through the same Solid/Hole evaluation as Group -- which is
what keeps the results watertight.

Every function raises BuildError with a plain-language message, and changes
nothing, when the request can't be met. The caller snapshots only after a
call succeeds.
"""

import copy
import uuid

import numpy as np

from mesh.blobs import encode_mesh
from mesh.ops import make_group
from mesh.scene import Shape, new_primitive
from mesh.shapes import PRIMITIVES, shape_geometry
from mesh.solids import from_manifold, m3, to_manifold


class BuildError(Exception):
    """A tool could not do what was asked; the message says why, plainly."""


def _lift(transform, dz: float) -> np.ndarray:
    """`transform` with a move of `dz` along the shape's own up direction
    applied first, so an inset child follows a turned or mirrored parent."""
    local = np.eye(4, dtype=np.float64)
    local[2, 3] = dz
    return np.asarray(transform, dtype=np.float64) @ local


def _hole_child(primitive: str, params: dict, transform, color: str, name: str) -> Shape:
    child = new_primitive(primitive, name=name)
    child.params.update(params)
    child.transform = np.asarray(transform, dtype=np.float64).copy()
    child.is_hole = True
    child.color = color
    return child


def _baked_child(tm, name: str, color: str, is_hole: bool) -> Shape:
    return Shape(
        id=uuid.uuid4().hex,
        name=name,
        kind="imported",
        params={"blob": encode_mesh(tm), "source": name},
        transform=np.eye(4, dtype=np.float64),
        color=color,
        is_hole=is_hole,
    )


# --- Hollow out -----------------------------------------------------------

EXACT_HOLLOW = ("cube", "cylinder", "sphere")
APPROXIMATE_FACE_LIMIT = 20000


def hollows_exactly(shape: Shape) -> bool:
    """Box, cylinder and sphere hollow exactly (an inset copy of the same
    shape is cut out). Everything else is hollowed approximately."""
    return shape.kind == "primitive" and shape.params.get("primitive") in EXACT_HOLLOW


def hollow(
    shape: Shape,
    wall: float,
    open_top: bool = False,
    drain: float = 0.0,
    clearances: dict | None = None,
) -> Shape:
    """Return a group: the part with its inside cut away, leaving `wall` mm.

    `open_top` takes the top wall away too (box, cylinder, sphere only).
    `drain` > 0 adds a hole of that diameter through the bottom, so resin or
    powder can run out of a closed part.
    """
    wall = float(wall)
    drain = float(drain)
    if shape.is_hole:
        raise BuildError("Hollow out works on solid parts. This one is a Hole.")
    if wall <= 0.0:
        raise BuildError("The wall thickness must be more than 0 mm.")
    if drain < 0.0:
        raise BuildError("The drain hole size can't be less than 0 mm.")

    if hollows_exactly(shape):
        holes = _exact_cavity(shape, wall, open_top, drain)
    else:
        if open_top:
            raise BuildError(
                "Open top works on boxes, cylinders and spheres. "
                "Untick Open top to hollow out this shape."
            )
        holes = _approximate_cavity(shape, wall, drain, clearances)

    label = PRIMITIVES[shape.params["primitive"]]["label"] if shape.kind == "primitive" else shape.name
    original = copy.deepcopy(shape)
    return make_group([original] + holes, name=f"Hollow {label.lower()}", clearances=clearances)


def _too_thick(limit: float) -> BuildError:
    return BuildError(
        f"That wall is too thick for this part. Try a wall thinner than {limit:.1f} mm."
    )


def _exact_cavity(shape: Shape, t: float, open_top: bool, drain: float) -> list[Shape]:
    kind = shape.params["primitive"]
    p = {**PRIMITIVES[kind]["defaults"], **shape.params}
    color, transform = shape.color, shape.transform
    holes = []

    if kind == "sphere":
        d = float(p["diameter"])
        if 2.0 * t >= d:
            raise _too_thick(d / 2.0)
        inner = d - 2.0 * t
        holes.append(_hole_child("sphere", {"diameter": inner}, _lift(transform, t), color, "Inside"))
        if open_top:
            holes.append(_hole_child(
                "cylinder", {"diameter": inner, "height": d / 2.0 + 1.0},
                _lift(transform, d / 2.0), color, "Open top",
            ))
        footprint = inner
    else:
        if kind == "cube":
            sizes = (float(p["width"]), float(p["depth"]))
        else:
            sizes = (float(p["diameter"]),)
        h = float(p["height"])
        limit = min(min(sizes) / 2.0, h if open_top else h / 2.0)
        if t >= limit:
            raise _too_thick(limit)
        # Open top: the inside runs 1 mm past the top so the top wall is
        # cut clean away rather than left as a face-thin skin.
        inner_h = h - t + 1.0 if open_top else h - 2.0 * t
        if kind == "cube":
            params = {"width": sizes[0] - 2.0 * t, "depth": sizes[1] - 2.0 * t, "height": inner_h}
        else:
            params = {"diameter": sizes[0] - 2.0 * t, "height": inner_h}
        holes.append(_hole_child(kind, params, _lift(transform, t), color, "Inside"))
        footprint = min(sizes) - 2.0 * t

    if drain > 0.0:
        if drain >= footprint:
            raise BuildError(
                f"That drain hole is wider than the inside of the part. "
                f"Try less than {footprint:.1f} mm."
            )
        holes.append(_hole_child(
            "cylinder", {"diameter": drain, "height": t + 2.0},
            _lift(transform, -1.0), color, "Drain hole",
        ))
    return holes


def _approximate_cavity(shape: Shape, t: float, drain: float, clearances) -> list[Shape]:
    outside = shape_geometry(shape, clearances)
    if len(outside.faces) > APPROXIMATE_FACE_LIMIT:
        raise BuildError("This part is too detailed to hollow out.")
    # Shrinking the part evenly by the wall thickness: the inside is every
    # point at least `t` from the outside surface. The ball is a 24-sided
    # approximation, which is why this path is labelled approximate.
    inside = to_manifold(outside).minkowski_difference(m3.Manifold.sphere(t, 24))
    if inside.is_empty() or inside.volume() < 1e-3:
        raise BuildError(
            "That wall is too thick for this part: there would be no space left inside. "
            "Try a thinner wall."
        )
    holes = [_baked_child(from_manifold(inside), "Inside", shape.color, is_hole=True)]

    if drain > 0.0:
        low, high = inside.bounding_box()[:3], inside.bounding_box()[3:]
        centre = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)
        bottom = float(outside.bounds[0][2]) - 1.0
        top = float(low[2]) + min(1.0, (high[2] - low[2]) / 2.0)
        tube = m3.Manifold.cylinder(top - bottom, drain / 2.0, drain / 2.0, 32).translate(
            (centre[0], centre[1], bottom)
        )
        if (tube ^ inside).volume() < 1e-3:
            raise BuildError("There is no room for a drain hole under the inside of this part.")
        holes.append(_baked_child(from_manifold(tube), "Drain hole", shape.color, is_hole=True))
    return holes
