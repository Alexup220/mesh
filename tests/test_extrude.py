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
    assert info["defaults"] == {"distance": 20.0, "side": "one", "taper": 0.0}
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
    assert window.inspector.visible_param_fields() == {"distance", "side", "taper"}
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
    assert window.inspector.visible_param_fields() == {"distance", "side", "taper"}
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
    assert form.values() == {"distance": 20.0, "side": "one", "taper": 0.0, "result": "part",
                             "keep_sketch": False}


# --- Sloped sides from the Extrude form ------------------------------------------------


def test_make_extrude_can_slope_the_sides():
    shape = create.make_extrude(sketch_on(), 10.0, taper=10.0)
    assert shape.params["taper"] == 10.0
    tm = shape_geometry(shape)
    assert tm.is_watertight
    step = 10.0 * math.tan(math.radians(10.0))
    top = tm.vertices[np.isclose(tm.vertices[:, 2], 10.0)]
    assert np.allclose([top[:, 0].min(), top[:, 1].min()], [step, step])
    assert np.allclose([top[:, 0].max(), top[:, 1].max()], [20 - step, 10 - step])
    bottom, middle, upper = 200.0, (20 - step) * (10 - step), (20 - 2 * step) * (10 - 2 * step)
    assert tm.volume == pytest.approx(10.0 / 6.0 * (bottom + 4 * middle + upper))


def test_straight_sides_add_no_slope_setting():
    assert "taper" not in create.make_extrude(sketch_on(), 10.0).params
    assert "taper" not in create.make_extrude(sketch_on(), 10.0, taper=0.0).params


@pytest.mark.parametrize("taper, words", [(61.0, "between -60 and 60"), (45.0, "would meet")])
def test_a_slope_the_extrusion_cannot_take_is_refused(taper, words):
    with pytest.raises(BuildError) as err:
        create.make_extrude(sketch_on(), 10.0, taper=taper)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_a_sloped_extrusion_round_trips_through_a_project_file(tmp_path):
    shape = create.make_extrude(sketch_on("xz"), 6.0, "other", taper=-5.0)
    path = tmp_path / "sloped.mesh"
    save_project(Scene(shapes=[shape]), path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params["taper"] == -5.0
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


def test_the_extrude_form_slopes_the_sides_in_one_undo_step(window, monkeypatch):
    add_sketch(window)
    monkeypatch.setattr(expert_actions, "ask_extrude", lambda parent: {
        "distance": 10.0, "side": "one", "taper": 10.0, "result": "part", "keep_sketch": False})
    steps = len(window.document._undo)
    window.do_extrude()
    shape = window.document.scene.shapes[0]
    assert shape.params["taper"] == 10.0 and len(window.document._undo) == steps + 1
    assert window.inspector.field_value("taper") == pytest.approx(10.0)
    sloped = shape_geometry(shape).volume
    assert sloped < 200 * 10
    window.do_undo()
    assert window.document.scene.shapes[0].params["primitive"] == "sketch"
    window.do_redo()
    assert shape_geometry(window.document.scene.shapes[0]).volume == pytest.approx(sloped)


def test_a_refused_slope_changes_nothing(window, warnings):
    add_sketch(window)
    steps = len(window.document._undo)
    assert not window.extrude_selected(10.0, taper=45.0)
    assert len(window.document._undo) == steps
    assert window.document.scene.shapes[0].params["primitive"] == "sketch"
    assert warnings and "would meet" in warnings[0]


def test_the_extrude_note_says_how_the_sides_slope():
    assert "at most 60 degrees" in expert_actions.EXTRUDE_NOTE
    assert_plain(expert_actions.EXTRUDE_NOTE)


# --- Up to a construction plane ---------------------------------------------------------


def plane_at(height, tilt=0.0, name="Plane 1"):
    from mesh import construct

    normal = (0.0, np.sin(np.radians(tilt)), np.cos(np.radians(tilt)))
    return construct.new_plane((0.0, 0.0, height), normal, name=name)


@pytest.mark.parametrize("height, distance, side", [(15.0, 15.0, "one"), (-4.0, 4.0, "other")])
def test_the_distance_to_a_parallel_plane_is_worked_out(height, distance, side):
    from mesh import construct

    assert create.distance_to_plane(sketch_on(), plane_at(height)) == (pytest.approx(distance), side)
    # The way the plane faces doesn't matter, only where it is.
    upside_down = construct.new_plane((5.0, 5.0, height), (0.0, 0.0, -1.0))
    assert create.distance_to_plane(sketch_on(), upside_down) == (pytest.approx(distance), side)


def test_a_sketch_upright_extrudes_up_to_a_plane_the_way_it_lies():
    # Sketched facing the front 3 mm in front of 0; the plane 10 mm behind 0.
    from mesh import construct

    source = sketch_on("xz", 3.0)
    back = construct.new_plane((0.0, 10.0, 0.0), (0.0, 1.0, 0.0))
    distance, side = create.distance_to_plane(source, back)
    assert (distance, side) == (pytest.approx(13.0), "other")
    tm = shape_geometry(create.make_extrude(source, distance, side))
    assert tm.bounds[:, 1].tolist() == pytest.approx([-3.0, 10.0])


@pytest.mark.parametrize("plane, words", [
    (plane_at(10.0, tilt=20.0), "not parallel"),
    (plane_at(0.0), "lies on"),
], ids=["tilted", "on the sketch"])
def test_a_plane_the_extrusion_cannot_end_on_is_refused(plane, words):
    with pytest.raises(BuildError) as err:
        create.distance_to_plane(sketch_on(), plane)
    assert words in str(err.value)
    assert_plain(str(err.value))


def add_plane(window, height):
    window.plane_at_distance_selected("xy", height)
    return window.document.scene.selected()[0]


def test_extruding_up_to_a_plane_is_one_undo_step_and_keeps_the_plane(window):
    plane = add_plane(window, 12.0)
    source = add_sketch(window)
    window.document.scene.select([source.id, plane.id])
    steps = len(window.document._undo)
    assert window.extrude_selected(1.0, to_plane=True, taper=5.0)
    scene = window.document.scene
    assert scene.shapes[0].id == plane.id and len(scene.shapes) == 2
    shape = scene.shapes[1]
    assert (shape.params["distance"], shape.params["side"]) == (pytest.approx(12.0), "one")
    assert shape_geometry(shape).bounds[:, 2].tolist() == pytest.approx([0.0, 12.0])
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert {s.id for s in window.document.scene.shapes} == {plane.id, source.id}


def test_up_to_a_plane_needs_a_plane_and_one_that_fits(window, warnings):
    source = add_sketch(window)
    assert not window.extrude_selected(5.0, to_plane=True)
    assert window.statusBar().currentMessage() == window.NO_PLANE
    window.plane_at_angle_selected("x", 30.0)
    window.document.scene.select([source.id, window.document.scene.shapes[-1].id])
    steps = len(window.document._undo)
    assert not window.extrude_selected(5.0, to_plane=True)
    assert len(window.document._undo) == steps and warnings and "not parallel" in warnings[0]
    for text in (window.NO_PLANE, window.EXTRUDE_EXTRAS):
        assert_plain(text)


def test_the_extrude_form_offers_the_selected_plane(window, monkeypatch):
    plane = add_plane(window, 8.0)
    source = add_sketch(window)
    window.document.scene.select([source.id, plane.id])
    seen = {}

    def ask(parent, plane=None, part=None):
        seen["plane"] = plane
        return {"extent": "plane", "distance": 3.0, "side": "both", "taper": 0.0, "result": "hole",
                "keep_sketch": True}

    monkeypatch.setattr(expert_actions, "ask_extrude", ask)
    window.do_extrude()
    assert seen["plane"] == plane.name
    shape = window.document.scene.shapes[-1]
    assert shape.is_hole and (shape.params["distance"], shape.params["side"]) == (pytest.approx(8.0), "one")


def test_the_up_to_plane_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    note = expert_actions.EXTRUDE_NOTE + expert_actions.EXTRUDE_TO_PLANE_NOTE
    form = close_qt_widget(FormDialog(None, "Extrude", expert_actions.extrude_fields("Plane 1"), note=note))
    for text in form.labels():
        assert_plain(text)
    assert form.values()["extent"] == "plane"


def test_an_extrusion_up_to_a_plane_round_trips_through_a_project_file(window, tmp_path):
    plane = add_plane(window, 9.0)
    source = add_sketch(window, WASHER)
    window.document.scene.select([source.id, plane.id])
    window.extrude_selected(1.0, to_plane=True)
    file = tmp_path / "up_to.mesh"
    window.save_to(file)
    loaded = load_project(file)
    assert [s.params["primitive"] for s in loaded.shapes] == ["plane", "extrude"]
    assert shape_geometry(loaded.shapes[1]).bounds[:, 2].tolist() == pytest.approx([0.0, 9.0])


# --- Joined to, cut out of, or kept where it overlaps a part -----------------------------

DOT = [{"type": "circle", "centre": [0, 0], "diameter": 6}]
DOT_AREA = sketch.profile(DOT).area()


def top_sketch(box):
    top = int(np.argmax(shape_geometry(box).face_normals[:, 2]))
    frame, _outlines = create.face_plane(box, top)
    return create.new_sketch(DOT, frame, "Sketch 1")


@pytest.mark.parametrize("op, side, volume", [
    ("difference", "other", 8000 - DOT_AREA * 5),
    ("union", "one", 8000 + DOT_AREA * 5),
    ("intersection", "other", DOT_AREA * 5),
])
def test_an_extrusion_combines_with_a_part_as_combine_does(op, side, volume):
    from mesh import modify
    from mesh.scene import new_primitive

    box = new_primitive("cube")
    extrusion = create.make_extrude(top_sketch(box), 5.0, side)
    group = modify.combine(box, [extrusion], op)
    assert shape_geometry(group).volume == pytest.approx(volume, rel=1e-6)


def box_and_top_sketch(window):
    window.add_primitive("cube")
    box = window.document.scene.shapes[-1]
    source = top_sketch(box)
    window.add_sketch(source.params["entities"], source.transform)
    source = window.document.scene.shapes[-1]
    window.document.scene.select([source.id, box.id])
    return box, source


@pytest.mark.parametrize("op, side, volume, name", [
    ("difference", "other", 8000 - DOT_AREA * 5, "Box (cut)"),
    ("union", "one", 8000 + DOT_AREA * 5, "Box (join)"),
    ("intersection", "other", DOT_AREA * 5, "Box (keep overlap)"),
])
def test_extrude_combines_with_the_selected_part_in_one_undo_step(window, op, side, volume, name):
    box, source = box_and_top_sketch(window)
    steps = len(window.document._undo)
    assert window.extrude_selected(5.0, side, combine=op)
    scene = window.document.scene
    assert [s.name for s in scene.shapes] == [name] and scene.selection == [scene.shapes[0].id]
    assert shape_geometry(scene.shapes[0]).volume == pytest.approx(volume, rel=1e-6)
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [box.id, source.id]
    window.do_redo()
    window.do_ungroup()
    kinds = sorted(s.params["primitive"] for s in window.document.scene.shapes)
    assert kinds == ["cube", "extrude"]


def test_a_combined_extrusion_can_keep_its_sketch_and_slope(window):
    _box, source = box_and_top_sketch(window)
    assert window.extrude_selected(5.0, "other", hole=True, keep_sketch=True, taper=10.0, combine="difference")
    scene = window.document.scene
    assert [s.id for s in scene.shapes][0] == source.id and scene.shapes[1].kind == "group"
    tool = next(c for c in scene.shapes[1].params["children"] if c["params"]["primitive"] == "extrude")
    # Cut by Combine's way, so the extrusion itself stays a part.
    assert tool["params"]["taper"] == 10.0 and not tool["is_hole"]


def test_the_extrude_form_offers_the_selected_part(window, monkeypatch):
    box, _source = box_and_top_sketch(window)
    seen = {}

    def ask(parent, plane=None, part=None):
        seen.update(plane=plane, part=part)
        return {"distance": 5.0, "side": "other", "taper": 0.0, "result": "difference", "keep_sketch": False}

    monkeypatch.setattr(expert_actions, "ask_extrude", ask)
    window.do_extrude()
    assert seen == {"plane": None, "part": "Box"}
    assert [s.name for s in window.document.scene.shapes] == ["Box (cut)"]


def test_combining_needs_one_part_and_something_left(window, warnings):
    window.add_sketch(DOT, sketch.named_plane_frame("xy"))
    steps = len(window.document._undo)
    assert not window.extrude_selected(5.0, combine="union")
    assert window.statusBar().currentMessage() == window.NO_PART
    box, source = box_and_top_sketch(window)
    # Straight up from the top face, so it only touches the box.
    steps = len(window.document._undo)
    assert not window.extrude_selected(5.0, "one", combine="intersection")
    assert len(window.document._undo) == steps and warnings
    window.add_primitive("sphere")
    window.document.scene.select([source.id, box.id, window.document.scene.shapes[-1].id])
    assert not window.extrude_selected(5.0, combine="union")
    assert window.statusBar().currentMessage() == window.EXTRUDE_EXTRAS
    for text in (window.NO_PART, window.EXTRUDE_EXTRAS, *warnings):
        assert_plain(text)


def test_the_extrude_form_with_a_part_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    note = expert_actions.EXTRUDE_NOTE + expert_actions.EXTRUDE_WITH_PART_NOTE
    form = close_qt_widget(FormDialog(None, "Extrude", expert_actions.extrude_fields("Plane 1", "Box"), note=note))
    for text in form.labels():
        assert_plain(text)
    assert form.values()["result"] == "union"
    assert form.widgets["result"].count() == 5


def test_a_combined_extrusion_round_trips_through_a_project_file(window, tmp_path):
    box_and_top_sketch(window)
    window.extrude_selected(5.0, "other", combine="difference")
    before = shape_geometry(window.document.scene.shapes[0]).volume
    file = tmp_path / "cut.mesh"
    window.save_to(file)
    loaded = load_project(file).shapes
    assert len(loaded) == 1 and loaded[0].kind == "group"
    assert shape_geometry(loaded[0]).volume == pytest.approx(before)
