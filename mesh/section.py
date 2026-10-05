"""Section view (Expert mode's Inspect menu): parts drawn cut open along a
plane, so their insides can be seen.

Only the drawing changes: the scene, the saved project and the printed
model are never cut. The side of the plane it faces is hidden; the cut
faces are drawn as a flat cap in SECTION_COLOR.
"""

import numpy as np
import trimesh

from mesh.solids import m3

SECTION_COLOR = "#e8743b"


def where(origin, normal) -> tuple[np.ndarray, np.ndarray]:
    """A section plane as (a point on it, the unit way it faces)."""
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    normal = np.asarray(normal, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(normal))
    if length < 1e-12:
        raise ValueError("a section plane needs a direction")
    return origin, normal / length


def cut_away(tm: trimesh.Trimesh, origin, normal):
    """`tm` with the side `normal` points to cut away.

    Returns (kept, face_map, cap): `kept` is what is left of the part's
    own surface, `face_map[i]` the triangle of `tm` that kept triangle i
    came from (so a click on the cut part still finds the part's face),
    and `cap` the flat faces that close the cut. A part with gaps can't be
    closed: it keeps its whole triangles behind the plane and gets no cap.
    """
    origin, normal = where(origin, normal)
    if len(tm.faces) == 0:
        return tm, np.zeros(0, dtype=np.int64), trimesh.Trimesh()
    mesh = m3.Mesh(
        vert_properties=np.ascontiguousarray(tm.vertices, dtype=np.float32),
        tri_verts=np.ascontiguousarray(tm.faces, dtype=np.uint32),
        face_id=np.arange(len(tm.faces), dtype=np.uint32),
    )
    solid = m3.Manifold(mesh)
    if solid.status() != m3.Error.NoError or solid.is_empty():
        return _behind(tm, origin, normal)
    own = {int(i) for i in solid.to_mesh().run_original_id}
    # trim_by_plane keeps the side its normal points to.
    out = solid.trim_by_plane(tuple(-normal), float(-normal @ origin)).to_mesh()
    vertices = np.asarray(out.vert_properties, dtype=np.float64)[:, :3]
    triangles = np.asarray(out.tri_verts, dtype=np.int64).reshape(-1, 3)
    faces = np.asarray(out.face_id, dtype=np.int64)
    mine = np.zeros(len(triangles), dtype=bool)
    bounds = np.asarray(out.run_index, dtype=np.int64) // 3
    for run, start, stop in zip(out.run_original_id, bounds[:-1], bounds[1:]):
        if int(run) in own:
            mine[start:stop] = True
    kept = trimesh.Trimesh(vertices=vertices, faces=triangles[mine], process=False)
    cap = trimesh.Trimesh(vertices=vertices, faces=triangles[~mine], process=False)
    return kept, faces[mine], cap


def _behind(tm: trimesh.Trimesh, origin, normal):
    """For a part with gaps: its triangles whose middle is behind the plane."""
    keep = np.flatnonzero((tm.triangles_center - origin) @ normal <= 0.0)
    kept = trimesh.Trimesh(vertices=tm.vertices, faces=tm.faces[keep], process=False)
    return kept, keep.astype(np.int64), trimesh.Trimesh()
