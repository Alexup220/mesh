import numpy as np
import pytest

from mesh.scene import new_primitive
from mesh.shapes import PRIMITIVES


@pytest.fixture
def shelf(qapp, close_qt_widget):
    from mesh.panels import ShapeShelf

    return close_qt_widget(ShapeShelf())


@pytest.fixture
def inspector(qapp, close_qt_widget):
    from mesh.panels import Inspector

    return close_qt_widget(Inspector())


def test_shelf_has_a_button_per_primitive(shelf):
    assert len(shelf.buttons) == len(PRIMITIVES)


def test_shelf_button_emits_its_primitive_kind(shelf):
    seen = []
    shelf.primitive_requested.connect(seen.append)
    shelf.buttons["cube"].click()
    assert seen == ["cube"]


def test_shelf_labels_use_plain_words(shelf):
    assert shelf.buttons["cube"].text() == "Box"
    assert shelf.buttons["torus"].text() == "Ring"


def test_inspector_is_disabled_with_no_shape(inspector):
    inspector.show_shape(None)
    assert inspector.isEnabled() is False


def test_inspector_shows_position_and_size(inspector):
    shape = new_primitive("cube")
    shape.transform[:3, 3] = [5.0, 6.0, 7.0]
    inspector.show_shape(shape)
    assert inspector.isEnabled() is True
    assert np.isclose(inspector.field_value("x"), 5.0)
    assert np.isclose(inspector.field_value("width"), 20.0)


def test_inspector_shows_the_hole_flag(inspector):
    shape = new_primitive("cube")
    shape.is_hole = True
    inspector.show_shape(shape)
    assert inspector.field_value("is_hole") is True


def test_editing_a_field_emits_the_shape_id_field_and_value(inspector):
    shape = new_primitive("cube")
    inspector.show_shape(shape)
    seen = []
    inspector.edited.connect(lambda *args: seen.append(args))
    inspector.fields["x"].setValue(12.0)
    assert (shape.id, "x", 12.0) in seen


def test_populating_the_inspector_emits_nothing(inspector):
    seen = []
    inspector.edited.connect(lambda *args: seen.append(args))
    inspector.show_shape(new_primitive("cube"))
    assert seen == []


def test_size_fields_fall_back_for_imported_shapes(inspector):
    shape = new_primitive("cube")
    shape.kind = "imported"
    shape.params = {"blob": ""}
    inspector.show_shape(shape)
    assert np.isclose(inspector.field_value("width"), 100.0)


def test_inspector_shows_rotation_from_the_transform(inspector):
    from mesh.scene import transform_with_euler

    shape = new_primitive("cube")
    shape.transform = transform_with_euler(shape.transform, 15.0, 30.0, 45.0)
    inspector.show_shape(shape)
    assert np.isclose(inspector.field_value("rx"), 15.0, atol=1e-6)
    assert np.isclose(inspector.field_value("ry"), 30.0, atol=1e-6)
    assert np.isclose(inspector.field_value("rz"), 45.0, atol=1e-6)
