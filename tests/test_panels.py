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


def test_imported_shapes_have_no_size_fields(inspector):
    shape = new_primitive("cube")
    shape.kind = "imported"
    shape.params = {"blob": ""}
    inspector.show_shape(shape)
    assert inspector._active_size_fields(shape) == ()
    for field in ("width", "depth", "height", "diameter", "thickness", "wall"):
        assert inspector._layout.isRowVisible(inspector._rows[field]) is False


def test_group_shapes_have_no_size_fields(inspector):
    shape = new_primitive("cube")
    shape.kind = "group"
    inspector.show_shape(shape)
    assert inspector._active_size_fields(shape) == ()


@pytest.mark.parametrize("kind", list(PRIMITIVES.keys()))
def test_inspector_exposes_exactly_this_primitives_size_fields(inspector, kind):
    shape = new_primitive(kind)
    inspector.show_shape(shape)

    expected = set(PRIMITIVES[kind]["defaults"].keys())
    all_size_fields = {"width", "depth", "height", "diameter", "thickness", "wall"}
    shown = {
        field
        for field in all_size_fields
        if inspector._layout.isRowVisible(inspector._rows[field])
    }
    assert shown == expected

    # And every shown field actually reflects the shape's real value.
    for field in expected:
        assert np.isclose(inspector.field_value(field), shape.params[field])


def test_editing_a_spheres_diameter_changes_its_geometry(inspector):
    from mesh.shapes import shape_geometry

    shape = new_primitive("sphere")
    inspector.show_shape(shape)

    before = shape_geometry(shape)
    seen = []
    inspector.edited.connect(lambda *args: seen.append(args))
    inspector.fields["diameter"].setValue(80.0)
    assert (shape.id, "diameter", 80.0) in seen

    # Mirror what MeshWindow._on_edited does with an emitted size field.
    shape.params["diameter"] = 80.0
    after = shape_geometry(shape)

    assert not np.allclose(before.bounds, after.bounds)


def test_inspector_shows_rotation_from_the_transform(inspector):
    from mesh.scene import transform_with_euler

    shape = new_primitive("cube")
    shape.transform = transform_with_euler(shape.transform, 15.0, 30.0, 45.0)
    inspector.show_shape(shape)
    assert np.isclose(inspector.field_value("rx"), 15.0, atol=1e-6)
    assert np.isclose(inspector.field_value("ry"), 30.0, atol=1e-6)
    assert np.isclose(inspector.field_value("rz"), 45.0, atol=1e-6)
