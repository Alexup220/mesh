import numpy as np
import pytest
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


def _legacy_stl_blob(tm) -> str:
    """A blob as the app wrote them before the exact format: binary STL."""
    import base64
    import zlib

    return base64.b64encode(zlib.compress(tm.export(file_type="stl"), 9)).decode("ascii")


def test_roundtrip_keeps_corners_and_triangles_exactly():
    original = trimesh.creation.icosphere(subdivisions=2)
    restored = decode_mesh(encode_mesh(original))
    assert np.array_equal(restored.vertices, original.vertices)
    assert np.array_equal(restored.faces, original.faces)


def test_a_closed_solid_with_very_short_edges_stays_closed():
    # Hollow out of a rounded box makes a cavity like this; the old STL
    # blob merged its corners on load and it stopped counting as closed.
    from mesh.solids import from_manifold, m3

    outer = m3.Manifold.cube((30.0, 20.0, 10.0)).translate((-15.0, -10.0, 0.0))
    ball = m3.Manifold.sphere(1.0, 24)
    cavity = from_manifold(outer.minkowski_difference(ball))
    assert cavity.is_volume
    assert decode_mesh(encode_mesh(cavity)).is_volume


def test_blobs_from_older_project_files_still_load():
    original = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    restored = decode_mesh(_legacy_stl_blob(original))
    assert restored.is_watertight
    assert np.isclose(restored.volume, original.volume, rtol=1e-6)


def _npz_blob(**arrays) -> str:
    import base64
    import io
    import zlib

    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return base64.b64encode(zlib.compress(buffer.getvalue(), 9)).decode("ascii")


@pytest.mark.parametrize("arrays", [
    {"vertices": np.zeros((3, 2)), "faces": np.array([[0, 1, 2]])},
    {"vertices": np.zeros((3, 3)), "faces": np.array([[0, 1, 5]])},
    {"vertices": np.full((3, 3), np.nan), "faces": np.array([[0, 1, 2]])},
    {"vertices": np.zeros((3, 3))},
])
def test_malformed_shape_data_is_refused(arrays):
    with pytest.raises((ValueError, KeyError)):
        decode_mesh(_npz_blob(**arrays))


def test_shape_data_is_never_unpickled():
    blob = _npz_blob(vertices=np.array([object()], dtype=object), faces=np.zeros((0, 3)))
    with pytest.raises(ValueError):
        decode_mesh(blob)
