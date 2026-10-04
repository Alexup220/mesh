"""Compact, self-contained serialisation of a triangle mesh to text.

Used so that a .mesh project file can embed imported geometry without
sidecar files that go missing.

A blob is the exact corner points (float64) and triangles of the mesh,
stored with numpy's .npz layout, compressed and base64'd. Keeping the
triangles' shared corners matters: an earlier STL-based blob rounded
corners to float32 and re-merged them on load, which could turn a closed
solid from manifold3d (one with very short edges, as Hollow out and Split
make) into one that no longer counts as closed, and every combine on it
then failed. Blobs written that way still load.
"""

import base64
import io
import zlib

import numpy as np
import trimesh

_NPZ_MAGIC = b"PK\x03\x04"


def encode_mesh(tm: trimesh.Trimesh) -> str:
    buffer = io.BytesIO()
    np.savez(
        buffer,
        vertices=np.asarray(tm.vertices, dtype=np.float64),
        faces=np.asarray(tm.faces, dtype=np.int32),
    )
    return base64.b64encode(zlib.compress(buffer.getvalue(), 9)).decode("ascii")


def decode_mesh(blob: str) -> trimesh.Trimesh:
    raw = zlib.decompress(base64.b64decode(blob))
    if not raw.startswith(_NPZ_MAGIC):
        # A blob from before the exact format: a binary STL.
        return trimesh.load(io.BytesIO(raw), file_type="stl", process=True)
    # Project files come from anywhere: never unpickle, and check the
    # arrays before trusting them.
    with np.load(io.BytesIO(raw), allow_pickle=False) as data:
        vertices = np.asarray(data["vertices"], dtype=np.float64)
        faces = np.asarray(data["faces"], dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("embedded shape data has the wrong layout")
    if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
        raise ValueError("embedded shape data refers to missing corners")
    if not np.isfinite(vertices).all():
        raise ValueError("embedded shape data has invalid coordinates")
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
