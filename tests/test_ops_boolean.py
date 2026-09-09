import numpy as np
import pytest

from mesh.ops import (
    BOOLEAN_LABELS,
    NothingToCombineError,
    boolean,
    evaluate,
    make_boolean_group,
    make_group,
    ungroup,
)
from mesh.scene import new_primitive


def cube(size, at=(0.0, 0.0, 0.0), hole=False):
    s = new_primitive("cube")
    s.params.update(width=size, depth=size, height=size)
    s.transform[:3, 3] = at
    s.is_hole = hole
    return s


def test_evaluate_unions_two_overlapping_solids():
    a = cube(10.0)
    b = cube(10.0, at=(5.0, 0.0, 0.0))
    result = evaluate([a, b])
    assert result.is_watertight
    assert np.isclose(result.volume, 1500.0, rtol=1e-3)


def test_evaluate_subtracts_a_hole():
    solid = cube(10.0)
    hole = cube(4.0, at=(0.0, 0.0, 2.0), hole=True)
    result = evaluate([solid, hole])
    assert result.is_watertight
    assert np.isclose(result.volume, 1000.0 - 64.0, rtol=1e-3)


def test_evaluate_with_only_holes_raises():
    with pytest.raises(NothingToCombineError):
        evaluate([cube(10.0, hole=True)])


def test_evaluate_with_no_shapes_raises():
    with pytest.raises(NothingToCombineError):
        evaluate([])


def test_explicit_intersection():
    a = cube(10.0)
    b = cube(10.0, at=(5.0, 0.0, 0.0))
    result = boolean([a, b], "intersection")
    assert np.isclose(result.volume, 500.0, rtol=1e-3)


def test_boolean_rejects_unknown_op():
    with pytest.raises(ValueError):
        boolean([cube(10.0), cube(10.0)], "smoosh")


def test_make_group_produces_a_watertight_group_shape():
    solid, hole = cube(10.0), cube(4.0, at=(0.0, 0.0, 2.0), hole=True)
    group = make_group([solid, hole])
    assert group.kind == "group"
    assert group.is_hole is False
    assert len(group.params["children"]) == 2

    from mesh.shapes import shape_geometry

    assert np.isclose(shape_geometry(group).volume, 936.0, rtol=1e-3)


def test_ungroup_restores_the_original_children():
    solid, hole = cube(10.0), cube(4.0, at=(0.0, 0.0, 2.0), hole=True)
    restored = ungroup(make_group([solid, hole]))
    assert [s.id for s in restored] == [solid.id, hole.id]
    assert restored[1].is_hole is True


def test_ungroup_on_a_non_group_raises():
    with pytest.raises(ValueError):
        ungroup(cube(10.0))


def test_groups_can_nest():
    inner = make_group([cube(10.0), cube(4.0, at=(0.0, 0.0, 2.0), hole=True)])
    outer = make_group([inner, cube(6.0, at=(20.0, 0.0, 0.0))])
    assert len(outer.params["children"]) == 2
    assert ungroup(outer)[0].kind == "group"


def test_make_boolean_group_produces_a_group_shape():
    a = cube(10.0)
    b = cube(10.0, at=(5.0, 0.0, 0.0))
    group = make_boolean_group([a, b], "union")
    assert group.kind == "group"
    assert len(group.params["children"]) == 2
    assert group.name == "Join"


def test_make_boolean_group_uses_the_operator_ignoring_is_hole():
    solid = cube(10.0)
    other = cube(10.0, at=(5.0, 0.0, 0.0), hole=True)
    group = make_boolean_group([solid, other], "difference")
    # difference() treats operand order literally, unlike evaluate()'s
    # solid-union-then-hole-subtract -- this is the whole point of the
    # explicit operator being a *different*, secondary path.
    from mesh.blobs import decode_mesh
    result = decode_mesh(group.params["blob"])
    assert np.isclose(result.volume, 500.0, rtol=1e-3)


def test_make_boolean_group_rejects_an_empty_selection():
    with pytest.raises(NothingToCombineError):
        make_boolean_group([], "union")


def test_boolean_labels_are_plain_language():
    for label in BOOLEAN_LABELS.values():
        for word in ("union", "difference", "intersection", "boolean", "csg"):
            assert word not in label.lower()
