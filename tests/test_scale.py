"""Scale (Expert mode): parts made bigger or smaller, sizes kept editable."""

import json

import numpy as np
import pytest

from mesh import create, modify, modify_actions, ops
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

CIRCLE = [{"type": "circle", "centre": [3, 1], "diameter": 8}]
SOLIDS = ["cube", "sphere", "cylinder", "cone", "torus", "tube", "wedge", "pyramid",
          "rounded_box", "rounded_cylinder", "text", "extrude", "revolve", "sweep", "loft"]


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


def part(kind, x=7.0, **params):
    shape = new_primitive(kind)
    shape.params.update(params)
    if kind == "extrude":
        shape.params["entities"] = CIRCLE
    shape.transform[0, 3] = x
    return shape


def about_base(bounds, factors):
    pivot = bounds.mean(axis=0)
    pivot[2] = bounds[0][2]
    return pivot + (bounds - pivot) * np.asarray(factors)


def scale_one(shape, factors, about="base"):
    [changed] = modify.scaled([shape], factors, about)
    return changed


# --- The same amount in every direction ------------------------------------------------


@pytest.mark.parametrize("kind", SOLIDS)
def test_every_kind_of_part_scales_exactly_about_its_base(kind):
    shape = part(kind)
    before = shape_geometry(shape)
    changed = scale_one(shape, (1.5, 1.5, 1.5))
    after = shape_geometry(changed)
    assert np.allclose(after.bounds, about_base(before.bounds, 1.5), atol=1e-6)
    assert after.volume == pytest.approx(before.volume * 1.5**3, rel=1e-4)
    assert changed.id == shape.id
    assert np.allclose(changed.transform[:3, :3], shape.transform[:3, :3])  # sizes, not stretch


def test_scaling_about_the_middle_keeps_the_middle_still():
    shape = part("cube")
    changed = scale_one(shape, (0.5, 0.5, 0.5), "centre")
    assert np.allclose(shape_geometry(changed).bounds, [[2, -5, 5], [12, 5, 15]])


def test_several_parts_scale_about_their_shared_base():
    a, b = part("cube", x=0.0), part("cube", x=40.0)
    changed = modify.scaled([a, b], (2, 2, 2))
    assert np.allclose(shape_geometry(changed[0]).bounds, [[-40, -20, 0], [0, 20, 40]])
    assert np.allclose(shape_geometry(changed[1]).bounds, [[40, -20, 0], [80, 20, 40]])


def test_size_numbers_stay_plain_numbers_that_save():
    changed = scale_one(part("rounded_box", chamfer=1.0), (2, 2, 2))
    assert changed.params["radius"] == 6.0 and changed.params["chamfer"] == 2.0
    assert all(type(v) is float for k, v in changed.params.items() if k != "primitive")
    json.dumps(changed.params)


def test_a_sketch_scales_its_curves_about_the_scale_point():
    shape = create.new_sketch(CIRCLE, np.eye(4))
    changed = scale_one(shape, (2, 2, 2))
    assert changed.params["entities"] == [{"type": "circle", "centre": [6.0, 2.0], "diameter": 16.0}]
    assert np.allclose(changed.transform[:3, 3], [-3, -1, 0])


def test_a_revolve_keeps_turning_around_its_scaled_line():
    shape = create.make_revolve(create.new_sketch(
        [{"type": "rectangle", "corner": [5, 0], "width": 5, "height": 20},
         {"type": "line", "start": [2, 0], "end": [2, 20]}], np.eye(4)), "line:1")
    changed = scale_one(shape, (2, 2, 2))
    assert changed.params["axis"] == [4.0, 0.0, 0.0, 40.0]
    assert shape_geometry(changed).volume == pytest.approx(shape_geometry(shape).volume * 8, rel=1e-6)


def test_hardware_holes_keep_their_sizes_and_their_openings_follow_the_part():
    base = part("cube", x=0.0)
    hole = new_primitive("screw_hole")
    hole.is_hole = True
    ops.place_on_face(hole, (0, 0, 20), (0, 0, 1))
    changed = modify.scaled([base, hole], (2, 2, 2))
    assert changed[1].params == hole.params
    opening = shape_geometry(changed[1]).bounds[1][2]
    assert opening == pytest.approx(shape_geometry(changed[0]).bounds[1][2]) == pytest.approx(40.0)


# --- Different amounts --------------------------------------------------------------------


def test_a_box_stretches_exactly_along_each_direction():
    changed = scale_one(part("cube"), (2, 1, 0.5))
    assert (changed.params["width"], changed.params["depth"], changed.params["height"]) == (40, 20, 10)


def test_a_box_turned_by_a_quarter_turn_stretches_along_the_worlds_directions():
    [turned] = modify.move_copy([part("cube", width=30.0)], axis="x", angle=90.0)
    changed = scale_one(turned, (2, 1, 0.5))
    before = shape_geometry(turned).bounds
    assert np.allclose(shape_geometry(changed).bounds, about_base(before, (2, 1, 0.5)), atol=1e-9)
    assert (changed.params["depth"], changed.params["height"]) == (10.0, 20.0)


def test_a_cylinder_stretches_up_but_only_alike_across():
    changed = scale_one(part("cylinder", chamfer=1.0), (2, 2, 0.5))
    assert (changed.params["diameter"], changed.params["height"]) == (40.0, 10.0)
    assert changed.params["chamfer"] == 1.0  # a bevel keeps its size when stretched


def test_a_rounding_keeps_its_size_when_stretched():
    changed = scale_one(part("rounded_box"), (2, 1, 1))
    assert changed.params["radius"] == 3.0 and changed.params["width"] == 40.0


def test_an_extrusion_scales_its_sketch_across_and_its_distance_up():
    changed = scale_one(part("extrude", distance=10.0), (3, 3, 2))
    assert changed.params["entities"][0]["diameter"] == 24.0
    assert changed.params["distance"] == 20.0


def test_imported_parts_and_groups_stretch_any_way():
    group = ops.make_group([part("sphere", x=0.0), part("cube", x=15.0)])
    [turned] = modify.move_copy([group], axis="z", angle=30.0)
    before = shape_geometry(turned).bounds
    changed = scale_one(turned, (2, 1, 0.5))
    assert np.allclose(shape_geometry(changed).bounds, about_base(before, (2, 1, 0.5)), atol=1e-9)
    assert changed.params == turned.params


@pytest.mark.parametrize("make, factors, words", [
    (lambda: part("sphere"), (2, 2, 1), "every direction"),
    (lambda: part("torus"), (1, 1, 2), "every direction"),
    (lambda: part("cylinder"), (2, 1, 1), "both directions across it"),
    (lambda: part("text"), (2, 1, 1), "both directions across it"),
    (lambda: part("extrude"), (2, 1, 1), "both directions across it"),
    (lambda: part("loft"), (1, 1, 2), "every direction"),
    (lambda: modify.move_copy([part("cube")], axis="z", angle=30.0)[0], (2, 1, 1), "is turned"),
])
def test_stretches_a_part_cant_take_are_refused_with_a_way_round(make, factors, words):
    with pytest.raises(BuildError) as err:
        scale_one(make(), factors)
    assert words in str(err.value) and "Group it first" in str(err.value)
    assert_plain(str(err.value))


def test_a_sketch_cant_be_stretched_unevenly():
    with pytest.raises(BuildError) as err:
        scale_one(create.new_sketch(CIRCLE, np.eye(4)), (2, 1, 1))
    assert "Group" not in str(err.value)


@pytest.mark.parametrize("shapes, factors, words", [
    ([], (2, 2, 2), "Select the parts"),
    ([20.0], (float("nan"), 1, 1), "ordinary numbers"),
    ([20.0], (0.001, 1, 1), "between 1% and 10000%"),
    ([20.0], (101, 101, 101), "between 1% and 10000%"),
    ([9000.0], (2, 2, 2), "bigger than"),
    ([5.0], (0.01, 1, 1), "smaller than"),
])
def test_scale_refuses_plainly(shapes, factors, words):
    with pytest.raises(BuildError) as err:
        modify.scaled([part("cube", width=w) for w in shapes], factors)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_a_curve_scaled_too_far_is_refused():
    shape = create.new_sketch([{"type": "circle", "centre": [9000, 0], "diameter": 4}], np.eye(4))
    with pytest.raises(BuildError) as err:
        scale_one(shape, (2, 2, 2), "centre")
    assert "within 10000 mm" in str(err.value)


# --- In the window --------------------------------------------------------------------


def test_scaling_is_one_undo_step(window):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert window.scale_selected(size=200.0, stretch_z=50.0)
    assert len(window.document._undo) == steps + 1
    assert (shape.params["width"], shape.params["height"]) == (40.0, 20.0)
    assert window.inspector.field_value("width") == 40.0
    window.do_undo()
    assert window.document.scene.shapes[0].params["width"] == 20.0


def test_a_scale_of_100_percent_takes_no_undo_step(window):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.scale_selected()
    assert len(window.document._undo) == steps


def test_a_refused_scale_changes_nothing(window, warnings):
    window.add_primitive("sphere")
    steps = len(window.document._undo)
    assert not window.scale_selected(stretch_x=200.0)
    assert warnings and "every direction" in warnings[0]
    assert len(window.document._undo) == steps


def test_scale_needs_a_selection_and_asks_for_its_amounts(window, monkeypatch):
    asked = []
    monkeypatch.setattr(modify_actions, "ask_scale", lambda parent: asked.append(1) or {
        "size": 50.0, "stretch_x": 100.0, "stretch_y": 100.0, "stretch_z": 100.0, "about": "base",
    })
    window.do_scale()
    assert not asked and window.statusBar().currentMessage() == window.NOTHING_TO_SCALE
    window.add_primitive("cube")
    window.do_scale()
    assert window.document.scene.shapes[0].params["width"] == 10.0


def test_scaled_parts_round_trip_through_a_project_file(tmp_path):
    shapes = modify.scaled([part("cube", x=0.0), part("extrude", x=30.0),
                            ops.make_group([part("sphere", x=60.0)])], (2, 2, 0.5))
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=shapes), path)
    for loaded, shape in zip(load_project(path).shapes, shapes):
        assert loaded.params.get("primitive") == shape.params.get("primitive")
        assert np.allclose(shape_geometry(loaded).bounds, shape_geometry(shape).bounds)


def test_scale_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Scale", modify_actions.scale_fields(),
                                        note=modify_actions.SCALE_NOTE))
    for text in dialog.labels():
        assert_plain(text)
