import numpy as np
import trimesh

from mesh.blobs import decode_mesh, encode_mesh


def test_roundtrip_preserves_geometry():
    original = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    blob = encode_mesh(original)
    assert isinstance(blob, str)
    restored = decode_mesh(blob)
    assert restored.is_watertight
    assert np.isclose(restored.volume, original.volume, rtol=1e-6)
    assert np.allclose(restored.bounds, original.bounds, atol=1e-6)


def test_blob_is_smaller_than_raw_stl():
    tm = trimesh.creation.icosphere(subdivisions=3)
    assert len(encode_mesh(tm)) < len(tm.export(file_type="stl"))
