"""Bottom chamfer on box, cylinder, rounded box and rounded cylinder."""

import numpy as np
import pytest

from mesh.scene import Shape, new_primitive
from mesh.shapes import PRIMITIVES, primitive_mesh, shape_geometry

CHAMFERABLE = ("cube", "cylinder", "rounded_box", "rounded_cylinder")


def bottom_area(tm):
    flat = (tm.face_normals[:, 2] < -0.999) & (np.abs(tm.triangles_center[:, 2]) < 1e-6)
    return float(tm.area_faces[flat].sum())


def test_chamfer_is_on_exactly_the_four_shapes_and_defaults_to_zero():
    for kind, info in PRIMITIVES.items():
        if kind in CHAMFERABLE:
            assert info["defaults"]["chamfer"] == 0.0
        else:
            assert "chamfer" not in info["defaults"]


def test_box_chamfer_volume_and_bottom_face():
    w, d, h, c = 30.0, 20.0, 10.0, 1.5
    tm = primitive_mesh("cube", {"width": w, "depth": d, "height": h, "chamfer": c})
    assert tm.is_watertight
    prismatoid = c / 6.0 * ((w - 2 * c) * (d - 2 * c) + 4 * (w - c) * (d - c) + w * d)
    assert np.isclose(tm.volume, prismatoid + w * d * (h - c), rtol=1e-9)
    assert np.isclose(bottom_area(tm), (w - 2 * c) * (d - 2 * c), rtol=1e-9)
    assert np.allclose(tm.bounds, [[-15, -10, 0], [15, 10, 10]], atol=1e-6)


def test_cylinder_chamfer_is_a_45_degree_cone_band():
    tm = primitive_mesh("cylinder", {"diameter": 20.0, "height": 10.0, "chamfer": 1.0})
    assert tm.is_watertight
    plain = primitive_mesh("cylinder", {"diameter": 20.0, "height": 10.0})
    frustum = np.pi * 1.0 / 3.0 * (81.0 + 90.0 + 100.0)
    expected = plain.volume - (np.pi * 100.0 * 1.0 - frustum) * (plain.volume / (np.pi * 1000.0))
    assert np.isclose(tm.volume, expected, rtol=2e-3)
    assert np.isclose(bottom_area(tm), np.pi * 81.0, rtol=3e-3)


@pytest.mark.parametrize("kind", ["rounded_box", "rounded_cylinder"])
def test_rounded_shapes_take_a_chamfer_bigger_than_their_rounding(kind):
    plain = primitive_mesh(kind, {"radius": 1.0})
    cut = primitive_mesh(kind, {"radius": 1.0, "chamfer": 3.0})
    assert cut.is_watertight
    assert cut.volume < plain.volume - 10.0
    assert np.isclose(cut.bounds[1][2] - cut.bounds[0][2], 20.0, atol=1e-6)


@pytest.mark.parametrize("kind", CHAMFERABLE)
def test_huge_chamfer_is_clamped_and_still_watertight(kind):
    tm = primitive_mesh(kind, {"chamfer": 500.0})
    assert tm.is_watertight
    assert tm.volume > 0
    assert np.isclose(tm.bounds[0][2], 0.0, atol=1e-6)


def test_projects_without_a_chamfer_param_build_unchanged():
    shape = Shape.from_dict({
        "id": "a", "name": "Box", "kind": "primitive",
        "params": {"width": 20.0, "depth": 20.0, "height": 20.0, "primitive": "cube"},
        "transform": np.eye(4).tolist(),
    })
    assert np.isclose(shape_geometry(shape).volume, 8000.0)


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


@pytest.mark.parametrize("kind", ["cube", "sphere"])
def test_inspector_shows_bottom_chamfer_only_where_it_applies(window, kind):
    window.add_primitive(kind)
    shown = "chamfer" in window.inspector.visible_param_fields()
    assert shown is (kind == "cube")


def test_typing_a_chamfer_is_one_undo_step(window):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    depth = len(window.document._undo)
    window._on_edited(shape.id, "chamfer", 0.5)
    window._finish_edit()
    assert len(window.document._undo) == depth + 1
    assert shape_geometry(shape).volume < 8000.0
    assert window.inspector.fields["chamfer"].minimum() == 0.0
