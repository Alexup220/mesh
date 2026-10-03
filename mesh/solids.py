"""Building solids that are guaranteed watertight.

Every new tool that makes geometry (hardware holes, rounded shapes, hollow
out, split, text) builds it through manifold3d, whose output is always a
closed solid. This module is the one place that converts between manifold3d
and the trimesh meshes the rest of the app works with.
"""

import manifold3d as m3
import numpy as np
import trimesh

__all__ = ["m3", "to_manifold", "from_manifold", "rounded_box", "rounded_cylinder", "chamfer_bottom"]


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


# Facets on each rounded corner's ball. A multiple of 4, so the ball has a
# point exactly at each extreme and the rounded shape keeps its exact size.
ROUND_SEGMENTS = 48


def clamp_radius(radius: float, *sizes: float) -> float:
    """A rounding radius can't be more than half the smallest size."""
    return max(0.0, min(float(radius), min(float(s) for s in sizes) / 2.0))


def rounded_box(width: float, depth: float, height: float, radius: float) -> trimesh.Trimesh:
    """A box with every edge and corner rounded: the hull of eight balls,
    one tucked into each corner. Centred on X/Y, resting on Z = 0."""
    r = clamp_radius(radius, width, depth, height)
    if r < 1e-6:
        return trimesh.creation.box(extents=(width, depth, height)).apply_translation((0, 0, height / 2.0))
    ball = m3.Manifold.sphere(r, ROUND_SEGMENTS)
    x, y = width / 2.0 - r, depth / 2.0 - r
    balls = [
        ball.translate((sx * x, sy * y, z))
        for sx in (-1.0, 1.0) for sy in (-1.0, 1.0) for z in (r, height - r)
    ]
    return from_manifold(m3.Manifold.batch_hull(balls))


def rounded_cylinder(diameter: float, height: float, radius: float, segments: int = 64) -> trimesh.Trimesh:
    """A cylinder with its top and bottom edges rounded: a rounded profile
    turned around the vertical axis. Resting on Z = 0."""
    big = diameter / 2.0
    r = clamp_radius(radius, diameter, height)
    if r < 1e-6:
        return from_manifold(m3.Manifold.cylinder(height, big, big, segments))
    circle = m3.CrossSection.circle(r, ROUND_SEGMENTS)
    parts = [circle.translate((big - r, r)), circle.translate((big - r, height - r))]
    if big - r > 1e-6:
        parts.append(m3.CrossSection.square((big - r, height)))
    profile = m3.CrossSection.batch_hull(parts) ^ m3.CrossSection.square((big, height))
    return from_manifold(m3.Manifold.revolve(profile, segments))


def chamfer_bottom(
    tm: trimesh.Trimesh, footprint: tuple, chamfer: float, height: float, segments: int = 64
) -> trimesh.Trimesh:
    """Cut a 45-degree bevel around the bottom edge of a shape resting on
    Z = 0 and centred on X/Y.

    `footprint` is (width, depth) for a rectangular base or (diameter,) for
    a round one. The shape is kept only inside a "clip" solid whose sides
    start `chamfer` mm in at Z = 0 and lean out at 45 degrees, so above
    Z = chamfer the clip is wider than the shape and leaves it untouched.
    """
    top = height + 1.0
    if len(footprint) == 2:
        w, d = footprint
        bottom = [(sx * (w / 2.0 - chamfer), sy * (d / 2.0 - chamfer), 0.0)
                  for sx in (-1, 1) for sy in (-1, 1)]
        upper = [(sx * (w / 2.0 - chamfer + top), sy * (d / 2.0 - chamfer + top), top)
                 for sx in (-1, 1) for sy in (-1, 1)]
        clip = m3.Manifold.hull_points(bottom + upper)
    else:
        r = footprint[0] / 2.0 - chamfer
        clip = m3.Manifold.cylinder(top, r, r + top, segments)
    return from_manifold(to_manifold(tm) ^ clip)
