"""Extrude (Expert mode): a sketch's outlines pushed out of its plane."""

import math

import numpy as np
import pytest

from mesh import create, expert_actions, features, ops, sketch, sketch_editor
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene
from mesh.settings import Settings
from mesh.shapes import PRIMITIVES, shape_geometry
from test_plain_language import assert_plain

RECT = [{"type": "rectangle", "corner": [0, 0], "width": 20, "height": 10}]
WASHER = [
    {"type": "circle", "centre": [0, 0], "diameter": 20},
    {"type": "circle", "centre": [0, 0], "diameter": 10},
]
OPEN = [{"type": "line", "start": [0, 0], "end": [10, 0]}]


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


@pytest.mark.parametrize("side, low, high", [("one", 0, 7), ("other", -7, 0), ("both", -3.5, 3.5)])
def test_extrude_goes_the_chosen_way(side, low, high):
    tm = features.extrude(RECT, 7.0, side)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(200 * 7)
    assert np.allclose(tm.bounds, [[0, 0, low], [20, 10, high]])


def test_an_outline_inside_another_extrudes_as_a_hole_through():
    tm = features.extrude(WASHER, 5.0)
    ring = sketch.profile(WASHER).area()
    assert tm.is_watertight and tm.volume == pytest.approx(ring * 5.0)


def test_a_fitted_hole_extrusion_grows_on_every_side():
    plain = features.extrude(RECT, 5.0, "one")
    grown = features.extrude(RECT, 5.0, "one", clearance=0.2)
    assert np.allclose(grown.bounds, plain.bounds + [[-0.2] * 3, [0.2] * 3], atol=1e-6)


@pytest.mark.parametrize("entities, distance, side, words", [
    (RECT, 0.0, "one", "more than 0"),
    (RECT, float("nan"), "one", "more than 0"),
    (RECT, 5.0, "up", "Choose which way"),
    (OPEN, 5.0, "one", "no closed outline"),
])
def test_extrude_refuses_plainly(entities, distance, side, words):
    with pytest.raises(sketch.SketchError) as err:
        features.extrude(entities, distance, side)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_extrusion_is_an_off_the_shelf_primitive_with_editable_numbers():
    info = PRIMITIVES["extrude"]
    assert info["shelf"] is False
    assert info["defaults"] == {"distance": 20.0, "side": "one"}
    assert [value for value, _label in info["choices"]["side"]] == ["one", "other", "both"]
    assert features.default_entities("extrude") == features.DEFAULT_EXTRUDE


# --- Made from a sketch -----------------------------------------------------------


def sketch_on(plane="xy", distance=0.0, entities=RECT, name="Sketch 1"):
    return create.new_sketch(entities, sketch.named_plane_frame(plane, distance), name)


def test_make_extrude_stands_on_the_sketchs_plane():
    source = sketch_on("xz", 3.0)
    shape = create.make_extrude(source, 4.0)
    assert shape.name == "Extrusion of Sketch 1" and not shape.is_hole
    assert shape.params["entities"] == source.params["entities"]
    assert shape.params["entities"] is not source.params["entities"]
    tm = shape_geometry(shape)
    # Drawn upright facing the front, so it comes out towards the front.
    assert np.allclose(tm.bounds, [[0, -7, 0], [20, -3, 10]])


def test_make_extrude_can_make_a_hole():
    assert create.make_extrude(sketch_on(), 4.0, "other", hole=True).is_hole


def test_make_extrude_refuses_what_is_not_a_closed_sketch():
    from mesh.scene import new_primitive

    with pytest.raises(BuildError):
        create.make_extrude(new_primitive("cube"), 4.0)
    with pytest.raises(BuildError) as err:
        create.make_extrude(sketch_on(entities=OPEN), 4.0)
    assert "no closed outline" in str(err.value)


def test_an_extrusions_curves_can_be_changed_but_must_stay_closed():
    shape = create.make_extrude(sketch_on(), 4.0)
    assert create.has_sketch(shape)
    assert create.sketch_entities(shape) == shape.params["entities"]
    changed = create.with_entities(shape, WASHER)
    assert shape_geometry(changed).volume == pytest.approx(sketch.profile(WASHER).area() * 4.0)
    with pytest.raises(BuildError):
        create.with_entities(shape, OPEN)
    # A sketch itself may hold open curves.
    create.with_entities(sketch_on(), OPEN)


def test_an_extrusion_cuts_a_box_when_it_is_a_hole_grouped_with_it():
    from mesh.scene import new_primitive

    box = new_primitive("cube")
    top = int(np.argmax(shape_geometry(box).face_normals[:, 2]))
    frame, _outlines = create.face_plane(box, top)
    source = create.new_sketch([{"type": "circle", "centre": [0, 0], "diameter": 6}], frame)
    cutter = create.make_extrude(source, 5.0, "other", hole=True)
    result = shape_geometry(ops.make_group([box, cutter]))
    expected = 8000 - sketch.profile(source.params["entities"]).area() * 5.0
    assert result.volume == pytest.approx(expected, rel=1e-6)


def test_an_extrusion_round_trips_through_a_project_file(tmp_path):
    scene = Scene()
    shape = create.make_extrude(sketch_on("yz", 2.0, WASHER), 6.0, "both")
    scene.add(shape)
    path = tmp_path / "extruded.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert np.allclose(shape_geometry(loaded).bounds, shape_geometry(shape).bounds)
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


# --- In the window --------------------------------------------------------------------


def add_sketch(window, entities=RECT, plane="xy"):
    window.add_sketch(entities, sketch.named_plane_frame(plane))
    return window.document.scene.shapes[-1]


def test_extrude_replaces_the_sketch_in_one_undo_step(window):
    source = add_sketch(window)
    steps = len(window.document._undo)
    assert window.extrude_selected(5.0)
    scene = window.document.scene
    assert [s.name for s in scene.shapes] == ["Extrusion of Sketch 1"]
    assert scene.selection == [scene.shapes[0].id]
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [source.id]
    window.do_redo()
    assert window.document.scene.shapes[0].params["primitive"] == "extrude"


def test_extrude_can_keep_the_sketch(window):
    source = add_sketch(window)
    window.extrude_selected(5.0, keep_sketch=True)
    assert [s.id for s in window.document.scene.shapes][0] == source.id
    assert len(window.document.scene.shapes) == 2


def test_a_refused_extrude_changes_nothing(window, warnings):
    add_sketch(window, OPEN)
    steps = len(window.document._undo)
    assert not window.extrude_selected(5.0)
    assert len(window.document._undo) == steps
    assert len(window.document.scene.shapes) == 1
    assert warnings and "no closed outline" in warnings[0]


def test_extrude_asks_for_its_numbers(window, monkeypatch):
    add_sketch(window)
    monkeypatch.setattr(expert_actions, "ask_extrude", lambda parent: {
        "distance": 3.0, "side": "other", "result": "hole", "keep_sketch": False})
    window.do_extrude()
    shape = window.document.scene.shapes[0]
    assert shape.is_hole and shape.params["side"] == "other" and shape.params["distance"] == 3.0


def test_extrude_needs_a_sketch_selected(window, monkeypatch):
    asked = []
    monkeypatch.setattr(expert_actions, "ask_extrude", lambda parent: asked.append(1))
    window.do_extrude()
    window.add_primitive("cube")
    window.do_extrude()
    assert not asked
    assert window.statusBar().currentMessage() == "Select one sketch to extrude."


def test_an_extrusions_numbers_are_in_the_details_panel(window):
    add_sketch(window)
    window.extrude_selected(5.0)
    shape = window.document.scene.shapes[0]
    assert window.inspector.visible_param_fields() == {"distance", "side"}
    window._on_edited(shape.id, "distance", 12.0)
    window._finish_edit()
    assert shape_geometry(shape).bounds[1][2] == pytest.approx(12.0)
    window._on_edited(shape.id, "side", "both")
    window._finish_edit()
    assert np.allclose(shape_geometry(shape).bounds[:, 2], [-6, 6])
    window.do_undo()
    assert np.allclose(shape_geometry(window.document.scene.shapes[0]).bounds[:, 2], [0, 12])
    window.do_undo()
    assert np.allclose(shape_geometry(window.document.scene.shapes[0]).bounds[:, 2], [0, 5])


def test_change_sketch_on_an_extrusion_changes_its_outline(window, monkeypatch):
    add_sketch(window)
    window.extrude_selected(5.0)
    seen = {}

    def edit(parent, title, entities=(), guides=(), note=None):
        seen["entities"] = entities
        return WASHER

    monkeypatch.setattr(sketch_editor, "edit_sketch", edit)
    window.do_edit_sketch()
    assert seen["entities"] == sketch.clean_entities(RECT)
    shape = window.document.scene.shapes[0]
    assert shape_geometry(shape).volume == pytest.approx(sketch.profile(WASHER).area() * 5.0)
    window.do_undo()
    assert window.document.scene.shapes[0].params["entities"] == sketch.clean_entities(RECT)


def test_an_extrusion_stays_editable_with_expert_mode_off(window):
    add_sketch(window)
    window.extrude_selected(5.0)
    window.set_expert_mode(False)
    assert window.inspector.visible_param_fields() == {"distance", "side"}
    assert window.gizmo._widget.GetEnabled()


def test_extrude_says_which_way_a_hole_into_a_sketched_face_goes(monkeypatch):
    seen = {}
    monkeypatch.setattr(expert_actions, "run_form", lambda *a, **k: seen.update(k))
    expert_actions.ask_extrude(None)
    assert "The other way" in seen["note"]
    assert_plain(seen["note"])


def test_extrude_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    form = close_qt_widget(FormDialog(None, "Extrude", expert_actions.extrude_fields()))
    for text in form.labels():
        assert_plain(text)
    assert form.values() == {"distance": 20.0, "side": "one", "result": "part", "keep_sketch": False}
