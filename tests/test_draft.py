"""Slope the Sides (Expert mode's Draft): an Extrusion's sides sloped in or out by an angle."""

import math

import numpy as np
import pytest

from mesh import create, features, modify, modify_actions, sketch
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

SQUARE = [{"type": "rectangle", "corner": [-10, -10], "width": 20, "height": 20}]
WASHER = [
    {"type": "circle", "centre": [0, 0], "diameter": 20},
    {"type": "circle", "centre": [0, 0], "diameter": 10},
]


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow(Settings(expert_mode=True)))


@pytest.fixture
def warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    return seen


def slope(degrees):
    return math.tan(math.radians(degrees))


def square_frustum(bottom, top, height):
    """A square-ended solid with flat sloping sides, `bottom` and `top` mm across."""
    a1, a2 = bottom**2, top**2
    return height / 3.0 * (a1 + a2 + math.sqrt(a1 * a2))


def polygon_area(apothem, sides=64):
    """A regular polygon `apothem` mm from its middle to each side's middle."""
    return sides * apothem**2 * math.tan(math.pi / sides)


def round_apothem(diameter, sides=64):
    return diameter / 2.0 * math.cos(math.pi / sides)


def sloped_ring(outside, inside, height, degrees):
    """A washer outline (circle diameters) pushed up `height`, sides sloping in."""
    t, a, b = slope(degrees), round_apothem(outside), round_apothem(inside)
    # The area at height z is n tan(pi/n) ((a - z t)^2 - (b + z t)^2): integrate it.
    def area_integral(z):
        return polygon_area(1.0) * (-(a - z * t) ** 3 / (3 * t) - (b + z * t) ** 3 / (3 * t))
    return area_integral(height) - area_integral(0.0)


def extrusion(entities=SQUARE, distance=20.0, side="one"):
    return create.make_extrude(create.new_sketch(entities, np.eye(4)), distance, side)


# --- Sloped extrusions ------------------------------------------------------------------


@pytest.mark.parametrize("degrees", [5.0, -5.0, 20.0])
def test_a_square_extrusions_sides_slope_flat_to_a_smaller_or_bigger_top(degrees):
    tm = features.extrude(SQUARE, 20.0, "one", 0.0, degrees)
    top = 20.0 - 2 * 20.0 * slope(degrees)
    assert tm.volume == pytest.approx(square_frustum(20.0, top, 20.0), rel=1e-6)
    assert tm.is_volume
    base = tm.vertices[np.isclose(tm.vertices[:, 2], 0.0)]
    assert np.allclose(np.abs(base[:, :2]), 10.0)  # the sketch's outline stays where it was drawn


@pytest.mark.parametrize("side, low, high", [("other", -20.0, 0.0), ("both", -10.0, 10.0)])
def test_the_sides_slope_in_going_away_from_the_sketch_either_way(side, low, high):
    tm = features.extrude(SQUARE, 20.0, side, 0.0, 10.0)
    assert np.allclose(tm.bounds, [[-10, -10, low], [10, 10, high]])
    run = 20.0 if side == "other" else 10.0
    whole = square_frustum(20.0, 20.0 - 2 * run * slope(10.0), run) * (20.0 / run)
    assert tm.volume == pytest.approx(whole, rel=1e-6)


def test_a_hole_in_the_outline_slopes_too():
    tm = features.extrude(WASHER, 10.0, "one", 0.0, 10.0)
    assert tm.volume == pytest.approx(sloped_ring(20.0, 10.0, 10.0, 10.0), rel=1e-6)


def test_sides_that_would_meet_are_refused():
    features.extrude(SQUARE, 20.0, "one", 0.0, 26.5)  # meets at 26.57 degrees
    with pytest.raises(sketch.SketchError) as err:
        features.extrude(SQUARE, 20.0, "one", 0.0, 27.0)
    assert str(err.value) == features.TOO_STEEP
    assert_plain(str(err.value))
    with pytest.raises(sketch.SketchError):
        features.extrude(WASHER, 20.0, "one", 0.0, 8.0)  # the hole's side meets the outside


@pytest.mark.parametrize("degrees", [61.0, float("nan")])
def test_the_slope_is_at_most_60_degrees(degrees):
    with pytest.raises(sketch.SketchError) as err:
        features.extrude(SQUARE, 20.0, "one", 0.0, degrees)
    assert "between -60 and 60 degrees" in str(err.value)


def test_a_fitted_hole_is_bigger_square_to_its_sloped_sides():
    c, degrees = 0.4, 10.0
    tm = features.extrude(SQUARE, 20.0, "one", c, degrees)
    half = 10.0 + c / math.cos(math.radians(degrees)) + c * slope(degrees)  # at the bottom, c below
    assert np.allclose(tm.bounds, [[-half, -half, -c], [half, half, 20.0 + c]], atol=1e-5)


def test_an_extrusion_saved_before_slopes_existed_stays_straight():
    shape = extrusion()
    assert "taper" not in shape.params
    assert shape_geometry(shape).volume == pytest.approx(8000.0)


# --- Slope the Sides --------------------------------------------------------------------


def test_a_box_becomes_a_sloped_extrusion_in_its_place():
    box = new_primitive("cube")
    box.params.update(width=30.0, depth=20.0)
    box.transform[:3, 3] = (5.0, 6.0, 7.0)
    changed = modify.drafted(box, 5.0)
    assert (changed.id, changed.name, changed.color) == (box.id, box.name, box.color)
    assert changed.params["primitive"] == "extrude" and changed.params["taper"] == 5.0
    assert np.allclose(changed.transform, box.transform)
    straight = modify.drafted(changed, 0.0)
    assert np.allclose(shape_geometry(straight).bounds, shape_geometry(box).bounds)
    assert shape_geometry(straight).volume == pytest.approx(30 * 20 * 20)
    assert box.params["primitive"] == "cube"  # the original is left alone


def test_a_tube_slopes_inside_and_out_until_its_wall_would_close():
    tube = new_primitive("tube")
    changed = modify.drafted(tube, 2.0)
    assert shape_geometry(changed).volume == pytest.approx(sloped_ring(20.0, 16.0, 20.0, 2.0), rel=1e-6)
    with pytest.raises(BuildError) as err:  # the hole grows past the outside
        modify.drafted(tube, 7.0)
    assert "would meet" in str(err.value)


def test_a_cylinder_slopes_out_from_its_base():
    cylinder = new_primitive("cylinder")
    tm = shape_geometry(modify.drafted(cylinder, -10.0))
    a = round_apothem(20.0)
    expected = polygon_area(1.0) * ((a + 20.0 * slope(10.0)) ** 3 - a**3) / (3 * slope(10.0))
    assert tm.volume == pytest.approx(expected, rel=1e-6)


def test_a_sloped_hole_keeps_its_fit():
    box = new_primitive("cube")
    box.is_hole, box.fit = True, "loose"
    changed = modify.drafted(box, 5.0, {"loose": 0.4})
    assert changed.is_hole and changed.fit == "loose"
    assert shape_geometry(changed, {"loose": 0.4}).bounds[0][2] == pytest.approx(-0.4)


@pytest.mark.parametrize("make, angle, words", [
    (lambda: (lambda b: (b.params.update(chamfer=1.0), b)[1])(new_primitive("cube")), 5.0,
     "bottom chamfer"),
    (lambda: new_primitive("sphere"), 5.0, "works on Extrusions, boxes, cylinders and tubes"),
    (lambda: create.new_sketch(SQUARE, np.eye(4)), 5.0, "flat drawing"),
    (lambda: new_primitive("cube"), 0.0, "more than 0"),
    (lambda: new_primitive("cube"), 70.0, "between 0 and 60"),
    (lambda: new_primitive("cube"), 30.0, "would meet"),
])
def test_slope_the_sides_refuses_plainly(make, angle, words):
    with pytest.raises(BuildError) as err:
        modify.drafted(make(), angle)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_stretching_a_sloped_extrusion_keeps_its_sides_flat():
    shape = modify.drafted(extrusion(), 10.0)
    before = shape_geometry(shape).volume
    [taller] = modify.scaled([shape], (1.0, 1.0, 2.0))
    assert math.tan(math.radians(taller.params["taper"])) == pytest.approx(slope(10.0) / 2.0)
    assert shape_geometry(taller).volume == pytest.approx(before * 2.0, rel=1e-6)
    [same] = modify.scaled([shape], (2.0, 2.0, 2.0))
    assert same.params["taper"] == 10.0


# --- In the window --------------------------------------------------------------------


def test_sloping_a_boxs_sides_is_one_undo_step(window):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert window.draft_selected(5.0)
    shape = window.document.scene.shapes[0]
    assert shape.id == box.id and shape.params["primitive"] == "extrude"
    assert len(window.document._undo) == steps + 1
    assert "taper" in window.inspector.visible_param_fields()
    window.do_undo()
    assert window.document.scene.shapes[0].params["primitive"] == "cube"


def test_the_form_starts_from_the_parts_own_slope(window, monkeypatch):
    seen = []
    monkeypatch.setattr(modify_actions, "ask_draft", lambda parent, angle, direction: seen.append(
        (angle, direction)) or {"angle": 8.0, "direction": "out"})
    window.add_primitive("cube")
    window.do_draft()
    window.do_draft()
    assert seen == [(5.0, "in"), (8.0, "out")]
    assert window.document.scene.shapes[0].params["taper"] == -8.0


@pytest.mark.parametrize("kinds", [[], ["cube", "cube"], ["sphere"]])
def test_slope_the_sides_needs_one_part_it_can_slope(window, kinds):
    for kind in kinds:
        window.add_primitive(kind)
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_draft()
    assert window.statusBar().currentMessage() == window.DRAFT_HINT


def test_a_refused_slope_changes_nothing(window, warnings):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.draft_selected(40.0)
    assert warnings and len(window.document._undo) == steps
    assert window.document.scene.shapes[0].params["primitive"] == "cube"


def test_the_slope_can_be_typed_in_the_details_but_not_so_steep_the_sides_meet(window, warnings):
    window.add_primitive("cube")
    window.draft_selected(5.0)
    shape = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    for field, value in (("taper", 30.0), ("distance", 200.0)):
        window._on_edited(shape.id, field, value)
        assert len(warnings) == 1 and "would meet" in warnings.pop()
        assert len(window.document._undo) == steps
    assert window.inspector.fields["taper"].value() == 5.0
    window._on_edited(shape.id, "taper", -5.0)
    window._finish_edit()
    assert shape_geometry(shape).volume == pytest.approx(square_frustum(20.0, 20.0 + 40 * slope(5.0), 20.0))
    assert not warnings and len(window.document._undo) == steps + 1


def test_a_sloped_part_round_trips_through_a_project_file(tmp_path):
    shape = modify.drafted(new_primitive("tube"), 2.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[shape]), path)
    loaded = load_project(path).shapes[0]
    assert loaded.params == shape.params
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


def test_slope_the_sides_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FIELD_LABELS, FormDialog

    dialog = close_qt_widget(FormDialog(None, "Slope the Sides", modify_actions.draft_fields(),
                                        note=modify_actions.DRAFT_NOTE))
    for text in dialog.labels() + [FIELD_LABELS["taper"]]:
        assert_plain(text)
