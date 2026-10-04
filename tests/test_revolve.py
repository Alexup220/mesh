"""Revolve (Expert mode): a sketch's outlines turned around a line."""

import math

import numpy as np
import pytest

from mesh import create, expert_actions, features, sketch, sketch_editor
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import PRIMITIVES, shape_geometry
from test_plain_language import assert_plain

# A rectangle 5 to 10 mm right of the sketch's Y line, 20 mm tall.
BAND = [{"type": "rectangle", "corner": [5, 0], "width": 5, "height": 20}]
TUBE_VOLUME = math.pi * (10**2 - 5**2) * 20
Y_AXIS = [0, 0, 0, 1]


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


# --- The solid ---------------------------------------------------------------------


def test_a_full_turn_makes_a_tube_around_the_line():
    tm = features.revolve(BAND, Y_AXIS, 360)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(TUBE_VOLUME, rel=0.01)  # round = 64 flat strips
    assert np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 20]])


def test_a_part_turn_starts_at_the_sketch_and_turns_anticlockwise():
    tm = features.revolve(BAND, Y_AXIS, 90)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(TUBE_VOLUME / 4, rel=0.01)
    assert np.allclose(tm.bounds, [[0, 0, 0], [10, 10, 20]], atol=1e-6)


def test_an_outline_on_the_other_side_of_the_line_turns_from_where_it_is():
    left = [{"type": "rectangle", "corner": [-10, 0], "width": 5, "height": 20}]
    tm = features.revolve(left, Y_AXIS, 90)
    assert tm.volume == pytest.approx(TUBE_VOLUME / 4, rel=0.01)
    assert np.allclose(tm.bounds, [[-10, -10, 0], [0, 0, 20]], atol=1e-6)


def test_an_outline_touching_the_line_makes_a_solid_round_part():
    touching = [{"type": "rectangle", "corner": [0, 0], "width": 5, "height": 20}]
    tm = features.revolve(touching, Y_AXIS, 360)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(math.pi * 25 * 20, rel=0.01)


def test_a_fitted_hole_revolve_grows_but_never_past_the_line():
    grown = features.revolve(BAND, Y_AXIS, 360, clearance=0.2)
    assert np.allclose(grown.bounds, [[-10.2, -10.2, -0.2], [10.2, 10.2, 20.2]], atol=1e-5)
    touching = [{"type": "rectangle", "corner": [0, 0], "width": 5, "height": 20}]
    solid = features.revolve(touching, Y_AXIS, 360, clearance=0.2)
    assert solid.is_watertight
    assert solid.volume == pytest.approx(math.pi * 5.2**2 * 20.4, rel=0.01)


def test_axis_frame_puts_z_along_the_line():
    frame = features.axis_frame([3, 4, 1, 1])
    assert np.allclose(frame[:3, 2], [math.sqrt(0.5), math.sqrt(0.5), 0])
    assert np.allclose(frame[:3, 3], [3, 4, 0])
    assert np.linalg.det(frame[:3, :3]) == pytest.approx(1.0)
    with pytest.raises(sketch.SketchError):
        features.axis_frame([0, 0, 0, 0])
    with pytest.raises(sketch.SketchError):
        features.axis_frame("up")


@pytest.mark.parametrize("entities, axis, angle, words", [
    (BAND, Y_AXIS, 0.0, "more than 0 degrees"),
    ([{"type": "rectangle", "corner": [-5, 0], "width": 10, "height": 20}], Y_AXIS, 360, "crosses"),
    ([{"type": "line", "start": [5, 0], "end": [5, 9]}], Y_AXIS, 360, "no closed outline"),
])
def test_revolve_refuses_plainly(entities, axis, angle, words):
    with pytest.raises(sketch.SketchError) as err:
        features.revolve(entities, axis, angle)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_more_than_one_turn_is_one_turn():
    assert features.revolve(BAND, Y_AXIS, 720).volume == pytest.approx(features.revolve(BAND, Y_AXIS, 360).volume)


def test_revolve_is_an_off_the_shelf_primitive_standing_upright():
    assert PRIMITIVES["revolve"]["shelf"] is False
    assert PRIMITIVES["revolve"]["defaults"] == {"angle": 360.0}
    tm = shape_geometry(new_primitive("revolve"))
    assert np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 20]])


# --- Made from a sketch -----------------------------------------------------------


def sketch_of(entities=BAND, plane="xy", name="Sketch 1"):
    return create.new_sketch(entities, sketch.named_plane_frame(plane), name)


def test_make_revolve_turns_around_the_sketchs_own_line():
    shape = create.make_revolve(sketch_of(), "y")
    assert shape.name == "Revolve of Sketch 1"
    # Drawn flat, turned around the world's Y line.
    assert np.allclose(shape_geometry(shape).bounds, [[-10, 0, -10], [10, 20, 10]])
    across = create.make_revolve(sketch_of([{"type": "circle", "centre": [0, 10], "diameter": 4}]), "x")
    assert np.allclose(shape_geometry(across).bounds, [[-2, -12, -12], [2, 12, 12]], atol=1e-6)


def test_make_revolve_can_turn_around_a_line_in_the_sketch():
    entities = [
        {"type": "rectangle", "corner": [0, 5], "width": 20, "height": 5},
        {"type": "line", "start": [0, 0], "end": [20, 0]},
    ]
    source = sketch_of(entities, plane="xz")
    axes = create.revolve_axes(source)
    assert [key for key, _label in axes] == ["y", "x", "line:1"]
    shape = create.make_revolve(source, "line:1", 180, hole=True)
    assert shape.is_hole and shape.params["axis"] == [0, 0, 20, 0]
    assert np.allclose(shape_geometry(shape).bounds, [[0, -10, -10], [20, 0, 10]], atol=1e-6)


def test_make_revolve_refuses_plainly():
    with pytest.raises(BuildError):
        create.make_revolve(new_primitive("cube"))
    with pytest.raises(BuildError):
        create.make_revolve(sketch_of(), "line:0")  # a rectangle, not a line
    with pytest.raises(BuildError):
        create.make_revolve(sketch_of(), "line:9")
    with pytest.raises(BuildError) as err:
        create.make_revolve(sketch_of([{"type": "circle", "centre": [0, 0], "diameter": 4}]), "y")
    assert "crosses" in str(err.value)


def test_a_revolves_curves_can_be_changed_and_keep_its_line():
    shape = create.make_revolve(sketch_of(), "y", 180)
    wider = [{"type": "rectangle", "corner": [5, 0], "width": 10, "height": 20}]
    changed = create.with_entities(shape, wider)
    assert changed.params["axis"] == shape.params["axis"]
    assert shape_geometry(changed).volume == pytest.approx(math.pi * (225 - 25) * 20 / 2, rel=0.01)
    with pytest.raises(BuildError):
        create.with_entities(shape, [{"type": "circle", "centre": [0, 0], "diameter": 4}])


def test_a_revolve_round_trips_through_a_project_file(tmp_path):
    scene = Scene()
    shape = create.make_revolve(sketch_of(plane="yz"), "y", 270)
    scene.add(shape)
    path = tmp_path / "turned.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert np.allclose(loaded.transform, shape.transform)
    assert np.allclose(shape_geometry(loaded).bounds, shape_geometry(shape).bounds)


# --- In the window --------------------------------------------------------------------


def add_sketch(window, entities=BAND):
    window.add_sketch(entities, np.eye(4))
    return window.document.scene.shapes[-1]


def test_revolve_replaces_the_sketch_in_one_undo_step(window):
    source = add_sketch(window)
    steps = len(window.document._undo)
    assert window.revolve_selected("y", 360.0)
    assert [s.name for s in window.document.scene.shapes] == ["Revolve of Sketch 1"]
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [source.id]


def test_a_refused_revolve_changes_nothing(window, warnings):
    add_sketch(window, [{"type": "circle", "centre": [0, 0], "diameter": 4}])
    steps = len(window.document._undo)
    assert not window.revolve_selected("y")
    assert len(window.document._undo) == steps and len(window.document.scene.shapes) == 1
    assert warnings and "crosses" in warnings[0]
    assert_plain(warnings[0])


def test_revolve_offers_the_sketchs_lines(window, monkeypatch):
    add_sketch(window, BAND + [{"type": "line", "start": [0, 0], "end": [0, 30]}])
    seen = {}

    def ask(parent, axes):
        seen["axes"] = axes
        return {"axis": "line:1", "angle": 90.0, "result": "part", "keep_sketch": True}

    monkeypatch.setattr(expert_actions, "ask_revolve", ask)
    window.do_revolve()
    assert [key for key, _label in seen["axes"]] == ["y", "x", "line:1"]
    shapes = window.document.scene.shapes
    assert len(shapes) == 2 and shapes[1].params["angle"] == 90.0


def test_revolve_needs_a_sketch_selected(window, monkeypatch):
    monkeypatch.setattr(expert_actions, "ask_revolve", lambda *a: pytest.fail("asked"))
    window.add_primitive("cube")
    window.do_revolve()
    assert window.statusBar().currentMessage() == "Select one sketch to revolve."


def test_a_revolves_angle_is_in_the_details_panel(window):
    add_sketch(window)
    window.revolve_selected("y", 360.0)
    shape = window.document.scene.shapes[0]
    assert window.inspector.visible_param_fields() == {"angle"}
    assert window.inspector.fields["angle"].maximum() == 360.0
    window._on_edited(shape.id, "angle", 180.0)
    window._finish_edit()
    assert shape_geometry(shape).volume == pytest.approx(TUBE_VOLUME / 2, rel=0.01)


def test_change_sketch_on_a_revolve(window, monkeypatch):
    add_sketch(window)
    window.revolve_selected("y", 360.0)
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: [
        {"type": "rectangle", "corner": [5, 0], "width": 5, "height": 40}])
    window.do_edit_sketch()
    assert shape_geometry(window.document.scene.shapes[0]).volume == pytest.approx(2 * TUBE_VOLUME, rel=0.01)


def test_revolve_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    axes = create.revolve_axes(sketch_of(BAND + [{"type": "line", "start": [0, 0], "end": [0, 3]}]))
    form = close_qt_widget(FormDialog(None, "Revolve", expert_actions.revolve_fields(axes)))
    for text in form.labels():
        assert_plain(text)
    assert form.values()["axis"] == "y" and form.values()["angle"] == 360.0
