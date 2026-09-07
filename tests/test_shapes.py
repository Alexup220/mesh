import numpy as np
import pytest
import trimesh

from mesh.shapes import PRIMITIVES, default_params, primitive_mesh, shape_geometry


class FakeShape:
    def __init__(self, kind, params, transform):
        self.kind = kind
        self.params = params
        self.transform = transform


@pytest.mark.parametrize("kind", sorted(PRIMITIVES))
def test_every_primitive_is_watertight(kind):
    tm = primitive_mesh(kind, default_params(kind))
    assert tm.is_watertight
    assert tm.volume > 0


@pytest.mark.parametrize("kind", sorted(PRIMITIVES))
def test_every_primitive_sits_on_the_workplane(kind):
    tm = primitive_mesh(kind, default_params(kind))
    assert np.isclose(tm.bounds[0][2], 0.0, atol=1e-6)


def test_box_dimensions_match_params():
    tm = primitive_mesh("cube", {"width": 10.0, "depth": 20.0, "height": 30.0})
    size = tm.bounds[1] - tm.bounds[0]
    assert np.allclose(size, [10.0, 20.0, 30.0], atol=1e-6)


def test_shape_geometry_applies_transform():
    move = np.eye(4)
    move[:3, 3] = [5.0, 0.0, 0.0]
    shape = FakeShape("cube", {"width": 2.0, "depth": 2.0, "height": 2.0}, move)
    tm = shape_geometry(shape)
    assert np.isclose(tm.bounds[0][0], 4.0, atol=1e-6)


def test_imported_shape_geometry_uses_blob():
    from mesh.blobs import encode_mesh

    source = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    shape = FakeShape("imported", {"blob": encode_mesh(source)}, np.eye(4))
    assert np.isclose(shape_geometry(shape).volume, 64.0, rtol=1e-6)
