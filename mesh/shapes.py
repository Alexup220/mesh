"""Primitive catalogue and shape-to-geometry conversion.

Geometry is always derived here, never stored on the shape. A shape holds
parameters and a transform; this module turns that into triangles.

Every primitive is generated resting on the workplane (minimum Z = 0) so
that a freshly placed shape can never be floating in space.
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon

from mesh import coils, features, guides, hardware, sketch, solids, text, threads
from mesh.blobs import decode_mesh

PRIMITIVES: dict[str, dict] = {
    "cube": {
        "label": "Box",
        "defaults": {"width": 20.0, "depth": 20.0, "height": 20.0, "chamfer": 0.0},
    },
    "sphere": {
        "label": "Sphere",
        "defaults": {"diameter": 20.0},
    },
    "cylinder": {
        "label": "Cylinder",
        "defaults": {"diameter": 20.0, "height": 20.0, "chamfer": 0.0},
    },
    "cone": {
        "label": "Cone",
        "defaults": {"diameter": 20.0, "height": 20.0},
    },
    "torus": {
        "label": "Ring",
        "defaults": {"diameter": 20.0, "thickness": 6.0},
    },
    "tube": {
        "label": "Tube",
        "defaults": {"diameter": 20.0, "wall": 2.0, "height": 20.0},
    },
    "wedge": {
        "label": "Wedge",
        "defaults": {"width": 20.0, "depth": 20.0, "height": 20.0},
    },
    "pyramid": {
        "label": "Pyramid",
        "defaults": {"width": 20.0, "depth": 20.0, "height": 20.0},
    },
    "rounded_box": {
        "label": "Rounded box",
        "defaults": {
            "width": 20.0, "depth": 20.0, "height": 20.0, "radius": 3.0, "chamfer": 0.0,
        },
    },
    "rounded_cylinder": {
        "label": "Rounded cylinder",
        "defaults": {"diameter": 20.0, "height": 20.0, "radius": 3.0, "chamfer": 0.0},
    },
    # Raised text is a solid; engraved text is the same shape as a Hole.
    # Added from Shape > Add Text..., where the words are typed.
    "text": {
        "label": "Text",
        "defaults": {"text": "Text", "letter_height": 10.0, "depth": 2.0},
        "shelf": False,
    },
    # Hardware holes (see mesh/hardware.py). Added from the "Add hardware
    # hole" menu rather than the shape shelf. "choices" lists the allowed
    # values of a non-numeric param, shown as a drop-down in the inspector.
    "screw_hole": {
        "label": "Screw hole",
        "defaults": {"size": "M3", "head": "plain", "depth": 10.0},
        "choices": {
            "size": [(s, s) for s in hardware.SCREW_SIZES],
            "head": hardware.HEAD_CHOICES,
        },
        "shelf": False,
    },
    "nut_trap": {
        "label": "Nut trap",
        "defaults": {"size": "M3", "depth": 10.0},
        "choices": {"size": [(s, s) for s in hardware.SCREW_SIZES]},
        "shelf": False,
    },
    "insert_pocket": {
        "label": "Heat-set insert pocket",
        "defaults": {"size": "M3"},
        "choices": {"size": [(s, s) for s in hardware.INSERT_SIZES]},
        "shelf": False,
    },
    "magnet_pocket": {
        "label": "Magnet pocket",
        "defaults": {"diameter": 6.0, "depth": 2.0},
        "shelf": False,
    },
    # Solids made from a sketch (Expert mode; see mesh/features.py). Their
    # params also hold the sketch's curves ("entities"), which are not a
    # Details panel field: Sketch > Change Sketch edits them.
    "extrude": {
        "label": "Extrusion",
        "defaults": {"distance": 20.0, "side": "one", "taper": 0.0},
        "choices": {"side": features.SIDES},
        "shelf": False,
    },
    # Also holds "axis", the line it turns around (see features.revolve).
    "revolve": {
        "label": "Revolve",
        "defaults": {"angle": 360.0},
        "shelf": False,
    },
    # Also holds its path's curves and both sketches' planes (features.sweep).
    "sweep": {
        "label": "Sweep",
        "defaults": {"twist": 0.0, "end_scale": 100.0},
        "shelf": False,
    },
    # Also holds its path's curves and plane (features.pipe).
    "pipe": {
        "label": "Pipe",
        "defaults": {"diameter": 10.0, "inside": "solid", "wall": 1.0},
        "choices": {"inside": features.PIPE_INSIDES},
        "shelf": False,
    },
    # Holds its outlines' curves and planes, in order (features.loft).
    "loft": {
        "label": "Loft",
        "defaults": {"sides": "straight"},
        "choices": {"sides": features.LOFT_SIDES},
        "shelf": False,
    },
    # A cylinder with a modeled screw thread (Expert mode's Thread tool;
    # see mesh/threads.py). As a Hole it cuts a threaded hole.
    "thread": {
        "label": "Thread",
        "defaults": dict(threads.DEFAULTS),
        "choices": {"end": threads.ENDS, "hand": threads.HANDS, "thread_shape": threads.THREAD_SHAPES,
                    "lead_in": threads.LEAD_INS},
        "shelf": False,
    },
    # A spring: a wire wound round an upright line (Expert mode's Coil
    # tool; see mesh/coils.py).
    "coil": {
        "label": "Coil",
        "defaults": dict(coils.DEFAULTS),
        "choices": {"wire_shape": coils.WIRE_SHAPES, "winding": coils.WINDINGS},
        "shelf": False,
    },
}

HARDWARE_PRIMITIVES = ("screw_hole", "nut_trap", "insert_pocket", "magnet_pocket")


def shelf_primitives() -> list[str]:
    """The primitives that get a button on the shape shelf."""
    return [k for k, info in PRIMITIVES.items() if info.get("shelf", True)]


# Guides drawn in the scene but never printed (Expert mode): a sketch is a
# flat drawing on a plane, and the others are construction guides (see
# mesh.guides). They are stored like primitives (kind "primitive",
# params["primitive"] one of these) but are not in PRIMITIVES, which lists
# solids only. Combining, the status bar check and Save for Printing leave
# them out; see is_reference.
REFERENCES: dict[str, dict] = {
    "sketch": {"label": "Sketch"},
    "plane": {"label": "Plane"},
    "axis": {"label": "Axis"},
    "point": {"label": "Point"},
}


def is_reference(shape) -> bool:
    """True for a guide that is shown but never printed (a sketch or a
    construction guide)."""
    return shape.kind == "primitive" and shape.params.get("primitive") in REFERENCES

SEGMENTS = 64


def default_params(kind: str) -> dict:
    if kind not in PRIMITIVES:
        raise KeyError(f"unknown primitive: {kind}")
    return dict(PRIMITIVES[kind]["defaults"])


def _sit_on_plane(tm: trimesh.Trimesh) -> trimesh.Trimesh:
    tm.apply_translation([0.0, 0.0, -tm.bounds[0][2]])
    return tm


def _extrude(polygon_2d: np.ndarray, height: float) -> trimesh.Trimesh:
    return trimesh.creation.extrude_polygon(Polygon(polygon_2d), height)


# How each size parameter grows when a Hole's fit clearance is added on every
# side: most sizes span two sides (+2c), a radius spans one (+c), and a bottom
# chamfer is a bevel rather than a size, so it stays put (+0). Anything not
# listed here grows by 2c.
_CLEARANCE_GROWTH = {"radius": 1.0, "chamfer": 0.0}


def _grow_for_clearance(kind: str, p: dict, clearance: float) -> dict:
    grown = dict(p)
    for key, default in PRIMITIVES[kind]["defaults"].items():
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            grown[key] = float(p[key]) + _CLEARANCE_GROWTH.get(key, 2.0) * clearance
    return grown


def hole_clearance(shape, clearances: dict | None) -> float:
    """The clearance (mm) to add on every side of this shape, or 0.

    Only Holes have a fit; a solid's fit choice (left over from when it was
    a Hole) is ignored, exactly as the inspector hides it.
    """
    if not clearances or not getattr(shape, "is_hole", False):
        return 0.0
    value = float(clearances.get(getattr(shape, "fit", "exact"), 0.0))
    return value if np.isfinite(value) and value > 0.0 else 0.0


def primitive_mesh(kind: str, params: dict, clearance: float = 0.0, hole: bool = False) -> trimesh.Trimesh:
    """Build a primitive resting on the workplane.

    `clearance` > 0 grows it by that much on every side (see hole_clearance);
    the grown shape is lowered by the same amount so it grows evenly in Z too.
    `hole` says the shape is a Hole (only a thread's lead-in differs).
    """
    if kind not in PRIMITIVES:
        raise KeyError(f"unknown primitive: {kind}")
    p = {**default_params(kind), **params}
    if kind in HARDWARE_PRIMITIVES:
        # Hardware holes add their clearance themselves, radius by radius.
        return hardware.build(kind, p, clearance)
    if kind in features.SOLIDS:
        # Placed by their sketch's plane, so not moved onto the workplane;
        # a fitted Hole grows along the outline, not by scaling.
        return features.build(kind, p, clearance)
    if kind == "thread":
        # Grows across and at the ends, but keeps its pitch and its turns
        # where they are, so a bolt fits the threaded Hole.
        return threads.thread_mesh(p, clearance, hole)
    if kind == "coil":
        # The wire grows all round and its ends grow along it.
        return coils.coil_mesh(p, clearance)
    if kind == "text":
        # Letters grow outward along their own outline, not by scaling.
        return text.text_mesh(str(p["text"]), float(p["letter_height"]), float(p["depth"]), clearance)
    if clearance > 0.0:
        tm = _primitive_mesh(kind, _grow_for_clearance(kind, p, clearance), clearance)
        tm.apply_translation([0.0, 0.0, -clearance])
        return tm
    return _primitive_mesh(kind, p, 0.0)


def _primitive_mesh(kind: str, p: dict, clearance: float) -> trimesh.Trimesh:

    if kind == "cube":
        tm = trimesh.creation.box(extents=(p["width"], p["depth"], p["height"]))
    elif kind == "sphere":
        tm = trimesh.creation.icosphere(subdivisions=3, radius=p["diameter"] / 2.0)
    elif kind == "cylinder":
        tm = trimesh.creation.cylinder(
            radius=p["diameter"] / 2.0, height=p["height"], sections=SEGMENTS
        )
    elif kind == "cone":
        tm = trimesh.creation.cone(
            radius=p["diameter"] / 2.0, height=p["height"], sections=SEGMENTS
        )
    elif kind == "torus":
        tm = trimesh.creation.torus(
            major_radius=(p["diameter"] - p["thickness"]) / 2.0,
            minor_radius=p["thickness"] / 2.0,
            major_sections=SEGMENTS,
            minor_sections=SEGMENTS // 2,
        )
    elif kind == "tube":
        outer = trimesh.creation.cylinder(
            radius=p["diameter"] / 2.0, height=p["height"], sections=SEGMENTS
        )
        inner = trimesh.creation.cylinder(
            radius=max(p["diameter"] / 2.0 - p["wall"], 0.01),
            height=p["height"] * 2.0,
            sections=SEGMENTS,
        )
        tm = trimesh.boolean.difference([outer, inner], engine="manifold")
    elif kind == "wedge":
        w, d, h = p["width"], p["depth"], p["height"]
        profile = np.array([[0.0, 0.0], [w, 0.0], [0.0, h]])
        tm = _extrude(profile, d)
        tm.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        tm.apply_translation([-w / 2.0, d / 2.0, 0.0])
    elif kind == "pyramid":
        w, d, h = p["width"], p["depth"], p["height"]
        vertices = np.array([
            [-w / 2, -d / 2, 0.0], [w / 2, -d / 2, 0.0],
            [w / 2, d / 2, 0.0], [-w / 2, d / 2, 0.0],
            [0.0, 0.0, h],
        ])
        faces = np.array([
            [0, 2, 1], [0, 3, 2],
            [0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4],
        ])
        tm = trimesh.Trimesh(vertices=vertices, faces=faces)
    elif kind == "rounded_box":
        tm = solids.rounded_box(p["width"], p["depth"], p["height"], p["radius"])
    elif kind == "rounded_cylinder":
        tm = solids.rounded_cylinder(p["diameter"], p["height"], p["radius"], SEGMENTS)
    else:
        raise KeyError(f"unknown primitive: {kind}")

    tm = _sit_on_plane(tm)
    if float(p.get("chamfer", 0.0)) > 0.0 and kind in CHAMFER_FOOTPRINTS:
        tm = _chamfer(kind, p, tm)
    return tm


# Primitives that can have a bottom chamfer, and the shape of their
# footprint: a rectangle (width x depth) or a circle (diameter).
CHAMFER_FOOTPRINTS = {
    "cube": "rect",
    "rounded_box": "rect",
    "cylinder": "circle",
    "rounded_cylinder": "circle",
}


def _chamfer(kind: str, p: dict, tm: trimesh.Trimesh) -> trimesh.Trimesh:
    """Bevel the bottom edge at 45 degrees, `p["chamfer"]` mm in and up.

    Counters "elephant's foot", the first layer squashing outward. Clamped
    so it can't eat the whole bottom face or be taller than the part.
    """
    height = float(p["height"])
    if CHAMFER_FOOTPRINTS[kind] == "rect":
        footprint = (float(p["width"]), float(p["depth"]))
    else:
        footprint = (float(p["diameter"]),)
    chamfer = min(float(p["chamfer"]), height - 1e-3, min(footprint) / 2.0 - 1e-3)
    if chamfer <= 1e-6:
        return tm
    return solids.chamfer_bottom(tm, footprint, chamfer, height, SEGMENTS)


def _grow_baked(tm: trimesh.Trimesh, clearance) -> trimesh.Trimesh:
    """Grow baked (imported/group) geometry by `clearance` on every side.

    There are no size params to grow, so this scales each axis about the
    shape's centre so that each outside size grows by 2 * clearance (one
    value, or one per axis). Exact for box-like shapes, approximate for
    anything else. shape_geometry calls it in the shape's own frame, before
    its turn, so a turned Hole grows across its own sides.
    """
    clearance = np.broadcast_to(np.asarray(clearance, dtype=np.float64), (3,))
    size = tm.bounds[1] - tm.bounds[0]
    centre = tm.bounds.mean(axis=0)
    factors = np.where(size > 1e-9, (size + 2.0 * clearance) / np.maximum(size, 1e-9), 1.0)
    scale = np.eye(4)
    scale[:3, :3] = np.diag(factors)
    to_origin = np.eye(4)
    to_origin[:3, 3] = -centre
    back = np.eye(4)
    back[:3, 3] = centre
    tm.apply_transform(back @ scale @ to_origin)
    return tm


def shape_geometry(shape, clearances: dict | None = None) -> trimesh.Trimesh:
    """Return the world-space mesh for a shape, transform applied.

    Pass the scene's `fit_clearances` to get a Hole at its fitted size (see
    hole_clearance). Every place that shows or combines geometry -- the
    viewport, Group, export, the status bar check -- passes them, so they all
    agree on what a fitted Hole looks like.
    """
    clearance = hole_clearance(shape, clearances)
    if is_reference(shape):
        # In the guide's own coordinates; a fit means nothing for it.
        kind = shape.params["primitive"]
        if kind == "sketch":
            tm = sketch.sketch_geometry(shape.params.get("entities", []))
        else:
            tm = guides.guide_geometry(kind, shape.params)
        clearance = 0.0
    elif shape.kind == "primitive":
        tm = primitive_mesh(shape.params["primitive"], shape.params, clearance,
                            bool(getattr(shape, "is_hole", False)))
    elif shape.kind in ("imported", "group"):
        tm = decode_mesh(shape.params["blob"])
    else:
        raise KeyError(f"unknown shape kind: {shape.kind}")
    tm = tm.copy()
    transform = np.asarray(shape.transform, dtype=np.float64)
    if clearance > 0.0 and shape.kind != "primitive":
        # Grown in the shape's own frame, by the clearance divided by the
        # transform's stretch along each of its axes, so the world-space
        # room is `clearance` on every side however the hole is turned.
        stretch = np.linalg.norm(transform[:3, :3], axis=0)
        tm = _grow_baked(tm, clearance / np.maximum(stretch, 1e-9))
    tm.apply_transform(transform)
    return tm
