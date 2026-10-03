"""Building solids that are guaranteed watertight.

Every new tool that makes geometry (hardware holes, rounded shapes, hollow
out, split, text) builds it through manifold3d, whose output is always a
closed solid. This module is the one place that converts between manifold3d
and the trimesh meshes the rest of the app works with.
"""

import manifold3d as m3
import numpy as np
import trimesh

__all__ = ["m3", "to_manifold", "from_manifold"]


def to_manifold(tm: trimesh.Trimesh) -> "m3.Manifold":
    mesh = m3.Mesh(
        vert_properties=np.ascontiguousarray(tm.vertices, dtype=np.float32),
        tri_verts=np.ascontiguousarray(tm.faces, dtype=np.uint32),
    )
    return m3.Manifold(mesh)


def from_manifold(solid: "m3.Manifold") -> trimesh.Trimesh:
    """manifold3d output as a trimesh.

    process=False on purpose: manifold3d already shares every vertex between
    the triangles that use it, and trimesh's own merge pass can collapse
    near-coincident vertices into a mesh that is no longer closed.
    """
    mesh = solid.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(mesh.vert_properties[:, :3], dtype=np.float64),
        faces=np.asarray(mesh.tri_verts, dtype=np.int64),
        process=False,
    )
