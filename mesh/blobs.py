"""Compact, self-contained serialisation of a triangle mesh to text.

Used so that a .mesh project file can embed imported geometry without
sidecar files that go missing.
"""

import base64
import io
import zlib

import trimesh


def encode_mesh(tm: trimesh.Trimesh) -> str:
    raw = tm.export(file_type="stl")
    if isinstance(raw, str):
        raw = raw.encode()
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def decode_mesh(blob: str) -> trimesh.Trimesh:
    raw = zlib.decompress(base64.b64decode(blob))
    return trimesh.load(io.BytesIO(raw), file_type="stl", process=True)
