import numpy as np
import pytest

from mesh.ops import align, drop_to_plane, duplicate, mirror
from mesh.scene import new_primitive
from mesh.shapes import shape_geometry


def cube(size=10.0, at=(0.0, 0.0, 0.0)):
    s = new_primitive("cube")
    s.params.update(width=size, depth=size, height=size)
    s.transform[:3, 3] = at
    return s


def test_duplicate_gets_a_new_id_and_an_offset():
    original = cube()
    copy_ = duplicate(original)
    assert copy_.id != original.id
    assert np.allclose(copy_.transform[:3, 3] - original.transform[:3, 3], [10.0, 10.0, 0.0])


def test_duplicate_does_not_alias_the_original_params():
    original = cube()
    copy_ = duplicate(original)
    copy_.params["width"] = 999.0
    assert original.params["width"] == 10.0


def test_duplicate_preserves_the_hole_flag():
    original = cube()
    original.is_hole = True
    assert duplicate(original).is_hole is True


def test_mirror_keeps_the_shape_in_place():
    s = cube(at=(5.0, 0.0, 0.0))
    before = shape_geometry(s).bounds.copy()
    mirrored = mirror(s, "x")
    assert np.allclose(shape_geometry(mirrored).bounds, before, atol=1e-6)


def test_mirror_flips_an_asymmetric_shape():
    s = new_primitive("wedge")
    before = shape_geometry(s).center_mass.copy()
    after = shape_geometry(mirror(s, "x")).center_mass
    assert not np.isclose(before[0], after[0], atol=1e-3)


def test_mirror_rejects_a_bad_axis():
    with pytest.raises(ValueError):
        mirror(cube(), "w")


def test_align_min_puts_every_shape_at_the_same_low_edge():
    a, b = cube(10.0, at=(0.0, 0.0, 0.0)), cube(20.0, at=(50.0, 0.0, 0.0))
    align([a, b], "x", "min")
    assert np.isclose(shape_geometry(a).bounds[0][0], shape_geometry(b).bounds[0][0], atol=1e-6)


def test_align_center_matches_centres():
    a, b = cube(10.0, at=(0.0, 0.0, 0.0)), cube(20.0, at=(50.0, 0.0, 0.0))
    align([a, b], "y", "center")
    ca = shape_geometry(a).bounds.mean(axis=0)[1]
    cb = shape_geometry(b).bounds.mean(axis=0)[1]
    assert np.isclose(ca, cb, atol=1e-6)


def test_align_rejects_a_bad_mode():
    with pytest.raises(ValueError):
        align([cube()], "x", "sideways")


def test_align_with_fewer_than_two_shapes_is_a_no_op():
    s = cube()
    before = s.transform.copy()
    align([s], "x", "min")
    assert np.allclose(s.transform, before)


def test_drop_to_plane_lands_the_shape_on_zero():
    s = cube(at=(0.0, 0.0, 37.0))
    drop_to_plane(s)
    assert np.isclose(shape_geometry(s).bounds[0][2], 0.0, atol=1e-6)
