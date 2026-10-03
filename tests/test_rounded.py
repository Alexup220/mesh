"""Rounded box and rounded cylinder primitives."""

import numpy as np
import pytest

from mesh.scene import DEFAULT_FIT_CLEARANCES, new_primitive
from mesh.shapes import PRIMITIVES, primitive_mesh, shape_geometry, shelf_primitives


def rounded_box_volume(w, d, h, r):
    core = (w - 2 * r) * (d - 2 * r) * (h - 2 * r)
    faces = 2 * r * ((w - 2 * r) * (d - 2 * r) + (w - 2 * r) * (h - 2 * r) + (d - 2 * r) * (h - 2 * r))
    edges = np.pi * r * r * ((w - 2 * r) + (d - 2 * r) + (h - 2 * r))
    return core + faces + edges + 4.0 / 3.0 * np.pi * r**3


def rounded_cylinder_volume(diameter, h, r):
    big = diameter / 2.0
    core = np.pi * (big - r) ** 2 * h
    band = 2 * np.pi * (big - r / 2.0) * r * (h - 2 * r)
    quarter = 2 * np.pi * (big - r + 4 * r / (3 * np.pi)) * (np.pi * r * r / 4.0)
    return core + band + 2 * quarter


def test_both_are_on_the_shelf_with_plain_labels():
    assert PRIMITIVES["rounded_box"]["label"] == "Rounded box"
    assert PRIMITIVES["rounded_cylinder"]["label"] == "Rounded cylinder"
    assert {"rounded_box", "rounded_cylinder"} <= set(shelf_primitives())


@pytest.mark.parametrize("w, d, h, r", [(20, 20, 20, 3), (40, 10, 6, 2), (30, 20, 10, 0.5)])
def test_rounded_box_size_and_volume(w, d, h, r):
    tm = primitive_mesh("rounded_box", {"width": w, "depth": d, "height": h, "radius": r})
    assert tm.is_watertight
    assert np.allclose(tm.bounds, [[-w / 2, -d / 2, 0], [w / 2, d / 2, h]], atol=1e-4)
    assert np.isclose(tm.volume, rounded_box_volume(w, d, h, r), rtol=5e-3)


@pytest.mark.parametrize("diameter, h, r", [(20, 20, 3), (30, 8, 2), (10, 40, 4)])
def test_rounded_cylinder_size_and_volume(diameter, h, r):
    tm = primitive_mesh("rounded_cylinder", {"diameter": diameter, "height": h, "radius": r})
    assert tm.is_watertight
    assert np.allclose(tm.bounds[:, 2], (0.0, h), atol=1e-4)
    assert np.allclose(tm.bounds[1][:2] - tm.bounds[0][:2], (diameter, diameter), atol=1e-3)
    assert np.isclose(tm.volume, rounded_cylinder_volume(diameter, h, r), rtol=5e-3)


def test_radius_is_clamped_to_half_the_smallest_size():
    clamped = primitive_mesh("rounded_box", {"width": 30, "depth": 20, "height": 8, "radius": 50})
    at_limit = primitive_mesh("rounded_box", {"width": 30, "depth": 20, "height": 8, "radius": 4})
    assert clamped.is_watertight
    assert np.isclose(clamped.volume, at_limit.volume, rtol=1e-9)
    assert np.allclose(clamped.bounds, [[-15, -10, 0], [15, 10, 8]], atol=1e-4)

    cyl = primitive_mesh("rounded_cylinder", {"diameter": 10, "height": 30, "radius": 99})
    assert cyl.is_watertight
    assert np.isclose(cyl.volume, rounded_cylinder_volume(10, 30, 5), rtol=5e-3)


def test_zero_radius_is_the_plain_shape():
    box = primitive_mesh("rounded_box", {"width": 10, "depth": 20, "height": 30, "radius": 0})
    assert np.isclose(box.volume, 6000.0)
    cyl = primitive_mesh("rounded_cylinder", {"diameter": 20, "height": 10, "radius": 0})
    assert cyl.is_watertight
    assert np.isclose(cyl.volume, primitive_mesh("cylinder", {"diameter": 20, "height": 10}).volume, rtol=1e-6)


def test_rounded_hole_grows_with_its_fit():
    s = new_primitive("rounded_box")
    s.is_hole, s.fit = True, "loose"
    tm = shape_geometry(s, dict(DEFAULT_FIT_CLEARANCES))
    assert tm.is_watertight
    assert np.allclose(tm.bounds[1] - tm.bounds[0], (20.8, 20.8, 20.8), atol=1e-4)


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_shelf_adds_a_rounded_box_with_its_fields(window):
    depth = len(window.document._undo)
    window.shelf.buttons["rounded_box"].click()
    shape = window.document.scene.shapes[0]
    assert shape.params["primitive"] == "rounded_box"
    assert len(window.document._undo) == depth + 1
    assert {"width", "depth", "height", "radius"} <= window.inspector.visible_param_fields()
    window._on_edited(shape.id, "radius", 6.0)
    window._finish_edit()
    assert shape.params["radius"] == 6.0
    assert np.isclose(shape_geometry(shape).volume, rounded_box_volume(20, 20, 20, 6), rtol=5e-3)


def test_rounding_radius_can_be_typed_as_zero(window):
    window.add_primitive("rounded_cylinder")
    box = window.inspector.fields["radius"]
    assert box.minimum() == 0.0
