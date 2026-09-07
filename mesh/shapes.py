"""Primitive catalogue and shape-to-geometry conversion.

Geometry is always derived here, never stored on the shape. A shape holds
parameters and a transform; this module turns that into triangles.

Every primitive is generated resting on the workplane (minimum Z = 0) so
that a freshly placed shape can never be floating in space.
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon

from mesh.blobs import decode_mesh

PRIMITIVES: dict[str, dict] = {
    "cube": {
        "label": "Box",
        "defaults": {"width": 20.0, "depth": 20.0, "height": 20.0},
    },
    "sphere": {
        "label": "Sphere",
        "defaults": {"diameter": 20.0},
    },
    "cylinder": {
        "label": "Cylinder",
        "defaults": {"diameter": 20.0, "height": 20.0},
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
}

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


def primitive_mesh(kind: str, params: dict) -> trimesh.Trimesh:
    p = {**default_params(kind), **params}

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
    else:
        raise KeyError(f"unknown primitive: {kind}")

    return _sit_on_plane(tm)


def shape_geometry(shape) -> trimesh.Trimesh:
    """Return the world-space mesh for a shape, transform applied."""
    if shape.kind in PRIMITIVES:
        tm = primitive_mesh(shape.kind, shape.params)
    elif shape.kind in ("imported", "group"):
        tm = decode_mesh(shape.params["blob"])
    else:
        raise KeyError(f"unknown shape kind: {shape.kind}")
    tm = tm.copy()
    tm.apply_transform(np.asarray(shape.transform, dtype=np.float64))
    return tm
