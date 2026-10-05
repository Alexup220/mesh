"""Sweep (Expert mode): a sketch's outline carried along another's path."""

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

SQUARE = [{"type": "rectangle", "corner": [-2, -2], "width": 4, "height": 4}]
DOT = [{"type": "circle", "centre": [0, 0], "diameter": 4}]
# Up 20 mm, then 30 mm across, drawn on the upright front plane.
ELBOW = [
    {"type": "line", "start": [0, 0], "end": [0, 20]},
    {"type": "line", "start": [0, 20], "end": [30, 20]},
]
UPRIGHT = sketch.named_plane_frame("xz")
FLAT = np.eye(4)


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


def test_a_square_swept_round_a_corner_is_exact():
    tm = features.sweep(SQUARE, FLAT, ELBOW, UPRIGHT)
    assert tm.is_watertight
    # Mitred at the corner, so exactly the two straight pieces' worth.
    assert tm.volume == pytest.approx(16 * (20 + 30))
    assert np.allclose(tm.bounds, [[-2, -2, 0], [30, 2, 22]])


def test_an_outline_drawn_elsewhere_is_moved_to_the_start_of_the_path():
    elsewhere = [{"type": "circle", "centre": [50, 50], "diameter": 4}]
    arc = [{"type": "arc", "centre": [0, 0], "radius": 20, "start": 0, "end": 180}]
    tm = features.sweep(elsewhere, FLAT, arc, FLAT)
    assert tm.is_watertight
    # A half ring: the circle's area times the length of the arc's middle.
    assert tm.volume == pytest.approx(math.pi * 4 * math.pi * 20, rel=0.01)
    # Its ends are square to the arc's first and last short straight steps.
    assert np.allclose(tm.bounds, [[-22, -0.1, -2], [22, 22, 2]], atol=0.05)


def test_an_outline_on_the_starts_plane_but_away_from_it_is_moved_too():
    # The workplane passes through the path's start, 45 mm from the circle.
    path_frame = sketch.named_plane_frame("xz")
    path_frame[0, 3] = -45
    tm = features.sweep(DOT, FLAT, ELBOW, path_frame)
    assert np.allclose(tm.bounds, [[-47, -2, 0], [-15, 2, 22]], atol=1e-6)


def test_an_outline_drawn_around_the_start_stays_where_it_is():
    off_centre = [{"type": "rectangle", "corner": [-1, -1], "width": 6, "height": 2}]
    tm = features.sweep(off_centre, FLAT, ELBOW[:1], UPRIGHT)
    assert np.allclose(tm.bounds, [[-1, -1, 0], [5, 1, 20]])


# The elbow drawn the other way round: across first, then down.
ELBOW_BACKWARDS = [
    {"type": "line", "start": [30, 20], "end": [0, 20]},
    {"type": "line", "start": [0, 0], "end": [0, 20]},
]
OFF_CENTRE = [{"type": "rectangle", "corner": [-1, -1], "width": 6, "height": 2}]


@pytest.mark.parametrize("path", [ELBOW, ELBOW_BACKWARDS], ids=["drawn from the start", "drawn backwards"])
def test_the_order_a_path_was_drawn_in_does_not_matter(path):
    tm = features.sweep(OFF_CENTRE, FLAT, path, UPRIGHT)
    # Used where it is, across the bottom end: x -1 to 5 up the first leg,
    # so the second leg runs from 1 mm above the corner to 5 mm below it.
    assert np.allclose(tm.bounds, [[-1, -1, 0], [30, 1, 21]], atol=1e-6)


def test_an_outline_drawn_across_the_far_end_is_used_there():
    far_end = np.eye(4)
    far_end[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]  # facing along the second leg
    far_end[:3, 3] = [30, 0, 20]
    tm = features.sweep(OFF_CENTRE, far_end, ELBOW, UPRIGHT)
    # The same part as the outline drawn across the bottom end, not
    # moved and centred (which would reach z = 23).
    assert np.allclose(tm.bounds, [[-1, -1, 0], [30, 1, 21]], atol=1e-6)


def test_an_outline_away_from_the_path_moves_to_the_nearer_end():
    brick = [{"type": "rectangle", "corner": [-2, -1], "width": 4, "height": 2}]
    beside_the_end = sketch.named_plane_frame("xz")
    beside_the_end[:3, 3] = [40, 0, 20]
    tm = features.sweep(brick, beside_the_end, ELBOW, UPRIGHT)
    # Turned to face along the second leg, its 4 mm side lies across the
    # path's plane (y -2 to 2). Moved to the start, it would lie in it.
    assert np.allclose(tm.bounds, [[-1, -2, 0], [30, 2, 21]], atol=1e-6)


def test_an_outline_across_a_closed_path_is_used_where_it_is():
    loop = [{"type": "rectangle", "corner": [0, 0], "width": 40, "height": 30}]
    # Drawn across the middle of the bottom side, all above the path.
    across = [{"type": "rectangle", "corner": [-2, 0], "width": 4, "height": 3}]
    tm = features.sweep(across, sketch.named_plane_frame("yz", 20), loop, FLAT)
    assert tm.is_watertight
    assert np.allclose(tm.bounds, [[-2, -2, 0], [42, 32, 3]], atol=1e-6)


@pytest.mark.parametrize("path", [
    [{"type": "line", "start": [0, 0], "end": [0, 30]},
     {"type": "line", "start": [0, 30], "end": [20, 30]},
     {"type": "line", "start": [20, 30], "end": [20, 15]},
     {"type": "line", "start": [20, 15], "end": [-15, 15]}],
    [{"type": "spline", "closed": True,
      "points": [[0, 0], [20, 15], [40, 0], [20, -15], [0, 0.5], [-20, 15], [-40, 0], [-20, -15]]}],
], ids=["open", "figure of eight"])
def test_a_path_that_crosses_itself_is_refused(path):
    with pytest.raises(sketch.SketchError) as err:
        features.sweep(DOT, FLAT, path, UPRIGHT)
    assert "crosses itself" in str(err.value)
    assert_plain(str(err.value))


def test_a_closed_path_makes_a_closed_ring():
    loop = [{"type": "circle", "centre": [0, 0], "diameter": 40}]
    tm = features.sweep(DOT, FLAT, loop, FLAT)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(math.pi * 4 * math.pi * 40, rel=0.01)


def test_an_outline_with_a_hole_sweeps_into_a_pipe():
    pipe = [{"type": "circle", "centre": [0, 0], "diameter": 8},
            {"type": "circle", "centre": [0, 0], "diameter": 6}]
    tm = features.sweep(pipe, FLAT, ELBOW, UPRIGHT)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(sketch.profile(pipe).area() * 50, rel=0.01)


def test_a_fitted_hole_sweep_grows_on_every_side_and_past_each_end():
    tm = features.sweep(SQUARE, FLAT, ELBOW, UPRIGHT, clearance=0.2)
    assert np.allclose(tm.bounds, [[-2.2, -2.2, -0.2], [30.2, 2.2, 22.2]], atol=1e-5)


@pytest.mark.parametrize("outline, path, words", [
    (SQUARE, [{"type": "line", "start": [0, 0], "end": [0, 20]},
              {"type": "line", "start": [0, 20], "end": [1, 0]}], "too tightly"),
    ([{"type": "circle", "centre": [0, 0], "diameter": 30}],
     [{"type": "arc", "centre": [0, 0], "radius": 5, "start": 0, "end": 180}], "too tightly"),
    (SQUARE, ELBOW + [{"type": "line", "start": [50, 50], "end": [60, 60]}], "exactly one path"),
    (SQUARE, ELBOW[:1] + [{"type": "line", "start": [0, 20], "end": [0, 0]}], "straight back"),
    ([{"type": "line", "start": [0, 0], "end": [1, 0]}], ELBOW, "no closed outline"),
])
def test_sweep_refuses_plainly(outline, path, words):
    with pytest.raises(sketch.SketchError) as err:
        features.sweep(outline, FLAT, path, UPRIGHT)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_damaged_sketch_positions_are_refused():
    with pytest.raises(sketch.SketchError):
        features.sweep(SQUARE, [[1, 2], [3, 4]], ELBOW, UPRIGHT)


def test_sweep_is_an_off_the_shelf_primitive_standing_on_the_workplane():
    assert PRIMITIVES["sweep"]["shelf"] is False
    assert PRIMITIVES["sweep"]["defaults"] == {"twist": 0.0, "end_scale": 100.0}
    tm = shape_geometry(new_primitive("sweep"))
    assert tm.is_watertight
    assert np.allclose(tm.bounds, [[-5, -5, 0], [5, 5, 20]])


# --- Made from two sketches -----------------------------------------------------------


def make_pair():
    outline = create.new_sketch(SQUARE, FLAT, "Outline")
    path = create.new_sketch(ELBOW, UPRIGHT, "Path")
    return outline, path


def test_the_likely_path_is_the_sketch_without_a_closed_outline():
    outline, path = make_pair()
    assert create.likely_path(outline, path) is path
    assert create.likely_path(path, outline) is path
    ring = create.new_sketch([{"type": "circle", "centre": [0, 0], "diameter": 40}], FLAT, "Ring")
    assert create.likely_path(outline, ring) is ring  # both closed: the second one


def test_make_sweep_keeps_both_sketches_where_they_were():
    outline, path = make_pair()
    shape = create.make_sweep(outline, path, hole=True)
    assert shape.name == "Sweep of Outline" and shape.is_hole
    assert np.allclose(shape.transform, np.eye(4))
    assert np.allclose(shape.params["path_frame"], UPRIGHT)
    assert shape_geometry(shape).volume == pytest.approx(800.0)


def test_make_sweep_refuses_anything_but_two_different_sketches():
    outline, _path = make_pair()
    with pytest.raises(BuildError) as err:
        create.make_sweep(outline, outline)
    assert_plain(str(err.value))
    with pytest.raises(BuildError):
        create.make_sweep(outline, new_primitive("cube"))


def test_a_sweeps_outline_can_be_changed():
    shape = create.make_sweep(*make_pair())
    changed = create.with_entities(shape, DOT)
    assert changed.params["path_entities"] == shape.params["path_entities"]
    assert shape_geometry(changed).volume == pytest.approx(sketch.profile(DOT).area() * 50, rel=0.01)


def test_a_sweep_round_trips_through_a_project_file(tmp_path):
    scene = Scene()
    shape = create.make_sweep(*make_pair())
    scene.add(shape)
    path = tmp_path / "swept.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


# --- In the window --------------------------------------------------------------------


def add_pair(window, path_first=False):
    shapes = [(ELBOW, UPRIGHT, "Path"), (SQUARE, FLAT, "Outline")]
    if not path_first:
        shapes.reverse()
    for entities, frame, name in shapes:
        window.add_sketch(entities, frame, name)
    scene = window.document.scene
    scene.select([s.id for s in scene.shapes])
    return {s.name: s for s in scene.shapes}


@pytest.mark.parametrize("path_first", [False, True])
def test_sweep_replaces_both_sketches_in_one_undo_step(window, path_first):
    before = add_pair(window, path_first)
    steps = len(window.document._undo)
    assert window.sweep_selected()
    assert [s.name for s in window.document.scene.shapes] == ["Sweep of Outline"]
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert {s.id for s in window.document.scene.shapes} == {s.id for s in before.values()}


def test_the_form_can_pick_the_path(window, monkeypatch):
    sketches = add_pair(window)
    seen = {}

    def ask(parent, pair, path_id):
        seen["default"] = path_id
        return {"path": sketches["Path"].id, "result": "part", "keep_sketch": True}

    monkeypatch.setattr(expert_actions, "ask_sweep", ask)
    window.do_sweep()
    assert seen["default"] == sketches["Path"].id
    assert len(window.document.scene.shapes) == 3


def test_a_refused_sweep_changes_nothing(window, warnings):
    add_pair(window)
    steps = len(window.document._undo)
    # Swapped: the elbow can't be the outline, it closes nothing.
    assert not window.sweep_selected(path_id=window.document.scene.shapes[0].id)
    assert len(window.document._undo) == steps and len(window.document.scene.shapes) == 2
    assert warnings and "no closed outline" in warnings[0]


def test_sweep_needs_two_sketches_selected(window, monkeypatch):
    monkeypatch.setattr(expert_actions, "ask_sweep", lambda *a: pytest.fail("asked"))
    window.add_sketch(SQUARE, FLAT)
    window.do_sweep()
    window.add_primitive("cube")
    window.do_select_all()
    window.do_sweep()
    assert window.statusBar().currentMessage() == window.TWO_SKETCHES_HINT


def test_change_sketch_on_a_sweep_changes_its_outline(window, monkeypatch):
    add_pair(window)
    window.sweep_selected()
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: DOT)
    window.do_edit_sketch()
    shape = window.document.scene.shapes[0]
    assert shape.params["entities"] == sketch.clean_entities(DOT)
    window.do_undo()
    assert window.document.scene.shapes[0].params["entities"] == sketch.clean_entities(SQUARE)


# Up 20, across 4.5, down 20: a 4 mm square fits round the two bends with
# 0.5 mm to spare inside, so it can grow by less than 0.25 mm a side.
U_BEND = [
    {"type": "line", "start": [0, 0], "end": [0, 20]},
    {"type": "line", "start": [0, 20], "end": [4.5, 20]},
    {"type": "line", "start": [4.5, 20], "end": [4.5, 0]},
]


def add_u_bend_hole(window):
    window.add_sketch(SQUARE, FLAT, "Outline")
    window.add_sketch(U_BEND, UPRIGHT, "Path")
    window.do_select_all()
    window.sweep_selected(hole=True)
    shape = window.document.scene.shapes[0]
    return shape, len(window.document._undo)


def test_a_fit_the_sweep_hole_cannot_take_is_refused_in_the_details_panel(window, warnings):
    shape, steps = add_u_bend_hole(window)
    window._on_edited(shape.id, "fit", "snug")
    window._finish_edit()
    assert shape.fit == "snug" and len(window.document._undo) == steps + 1
    window._on_edited(shape.id, "fit", "loose")
    assert shape.fit == "snug" and len(window.document._undo) == steps + 1
    assert window.inspector.fit_box.currentData() == "snug"
    assert warnings and "bends too tightly" in warnings[0] and shape.name in warnings[0]
    assert_plain(warnings[0])


def test_making_a_sweep_a_hole_at_a_fit_it_cannot_take_is_refused(window, warnings):
    shape, _steps = add_u_bend_hole(window)
    window.do_toggle_hole()
    shape.fit = "loose"  # kept from before, while it was a part
    steps = len(window.document._undo)
    window.do_toggle_hole()
    assert not shape.is_hole and len(window.document._undo) == steps
    window._on_edited(shape.id, "is_hole", True)
    assert not shape.is_hole and len(window.document._undo) == steps
    assert len(warnings) == 2


def test_fit_sizes_a_sweep_hole_cannot_take_are_refused(window, warnings):
    shape, steps = add_u_bend_hole(window)
    shape.fit = "press"
    assert not window.set_fit_clearances({"press": 0.3})
    assert window.document.scene.fit_clearances["press"] == 0.1
    assert len(window.document._undo) == steps and warnings
    assert window.set_fit_clearances({"press": 0.2})


def test_ungrouping_after_the_fits_changed_is_refused_if_a_sweep_hole_cannot_take_them(window, warnings):
    shape, _steps = add_u_bend_hole(window)
    shape.fit = "press"
    window.add_primitive("cube")
    window.do_select_all()
    window.do_group()
    assert window.set_fit_clearances({"press": 0.3})  # nothing loose to rebuild
    steps = len(window.document._undo)
    window.do_ungroup()
    assert [s.kind for s in window.document.scene.shapes] == ["group"]
    assert len(window.document._undo) == steps and warnings


def test_change_sketch_on_a_fitted_sweep_hole_is_checked_at_its_fit(window, monkeypatch, warnings):
    shape, steps = add_u_bend_hole(window)
    shape.fit = "snug"
    bigger = [{"type": "rectangle", "corner": [-2.2, -2.2], "width": 4.4, "height": 4.4}]
    answers = [bigger, None]
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: answers.pop(0))
    window.do_edit_sketch()  # fits exactly, but not with snug's 0.2 mm
    assert shape.params["entities"] == sketch.clean_entities(SQUARE)
    assert len(window.document._undo) == steps
    assert warnings and "bends too tightly" in warnings[0]


def test_sweep_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    pair = make_pair()
    form = close_qt_widget(FormDialog(None, "Sweep", expert_actions.sweep_fields(pair, pair[1].id)))
    for text in form.labels():
        assert_plain(text)
    assert form.values()["path"] == pair[1].id


# --- Twist and size at the far end -----------------------------------------------------

LINE = [{"type": "line", "start": [0, 0], "end": [0, 20]}]
BRICK = [{"type": "rectangle", "corner": [-2, -1], "width": 4, "height": 2}]
RING = [{"type": "circle", "centre": [0, 0], "diameter": 40}]


def ends(tm, low=0.0, high=20.0):
    """The points of the solid at its bottom and top."""
    return tm.vertices[np.isclose(tm.vertices[:, 2], low)], tm.vertices[np.isclose(tm.vertices[:, 2], high)]


def test_a_twist_turns_the_outline_evenly_along_the_path():
    tm = features.sweep(BRICK, FLAT, LINE, UPRIGHT, twist=90.0)
    assert tm.is_watertight
    bottom, top = ends(tm)
    assert np.allclose([bottom.min(axis=0)[:2], bottom.max(axis=0)[:2]], [[-2, -1], [2, 1]])
    assert np.allclose([top.min(axis=0)[:2], top.max(axis=0)[:2]], [[-1, -2], [1, 2]])
    # Half way up, turned 45 degrees: a corner (2, 1) is at 45 + 26.6 degrees.
    middle = tm.vertices[np.isclose(tm.vertices[:, 2], 10.0)]
    corner = np.degrees(np.arctan2(middle[:, 1], middle[:, 0]))
    assert np.isclose(corner, 45 + np.degrees(np.arctan2(1, 2))).any()
    # The twisted sides are flat strips about as fine as a cylinder's.
    assert tm.volume == pytest.approx(8 * 20, rel=0.005)


def test_a_twist_more_than_0_turns_like_a_screw_going_along_the_path():
    tm = features.sweep(BRICK, FLAT, LINE, UPRIGHT, twist=30.0)
    _bottom, top = ends(tm)
    # Seen from above (ahead, along the path), the corner (2, 1) has gone anticlockwise.
    turned = np.degrees(np.arctan2(top[:, 1], top[:, 0]))
    assert np.isclose(turned, 30 + np.degrees(np.arctan2(1, 2))).any()


def test_the_size_at_the_far_end_changes_evenly_and_exactly():
    tm = features.sweep(SQUARE, FLAT, LINE, UPRIGHT, end_scale=50.0)
    assert tm.is_watertight
    assert tm.volume == pytest.approx(20 / 3 * (16 + 4 + 8))
    _bottom, top = ends(tm)
    assert np.allclose([top.min(axis=0)[:2], top.max(axis=0)[:2]], [[-1, -1], [1, 1]])


def test_twist_and_size_change_round_a_corner_from_where_the_outline_is():
    tm = features.sweep(SQUARE, FLAT, ELBOW, UPRIGHT, twist=45.0, end_scale=200.0)
    assert tm.is_watertight
    far = tm.vertices[np.isclose(tm.vertices[:, 0], 30.0)]
    # 8 mm across at the far end, turned 45 degrees: corners 4 * sqrt(2) out.
    assert np.ptp(far[:, 1]) == pytest.approx(8 * np.sqrt(2)) and np.ptp(far[:, 2]) == pytest.approx(8 * np.sqrt(2))


def test_a_closed_path_twists_by_whole_turns():
    tm = features.sweep(BRICK, FLAT, RING, FLAT, twist=360.0)
    plain = features.sweep(BRICK, FLAT, RING, FLAT)
    assert tm.is_watertight and tm.volume == pytest.approx(plain.volume, rel=0.005)


@pytest.mark.parametrize("path, twist, end_scale, words", [
    (RING, 90.0, 100.0, "whole turns"),
    (RING, 0.0, 50.0, "can't change size"),
    (LINE, 3601.0, 100.0, "between -3600 and 3600"),
    (LINE, float("nan"), 100.0, "between -3600 and 3600"),
    (LINE, 0.0, 0.5, "between 1% and 1000%"),
    (LINE, 0.0, 1001.0, "between 1% and 1000%"),
])
def test_a_twist_or_size_the_sweep_cannot_take_is_refused(path, twist, end_scale, words):
    with pytest.raises(sketch.SketchError) as err:
        features.sweep(BRICK, FLAT, path, FLAT if path is RING else UPRIGHT, twist=twist, end_scale=end_scale)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_a_fitted_hole_that_changes_size_keeps_its_gap_all_along():
    tm = features.sweep(SQUARE, FLAT, LINE, UPRIGHT, clearance=0.2, end_scale=50.0)
    assert tm.is_watertight
    bottom, top = ends(tm, -0.2, 20.2)
    assert np.allclose([bottom.min(axis=0)[:2], bottom.max(axis=0)[:2]], [[-2.2, -2.2], [2.2, 2.2]], atol=1e-5)
    assert np.allclose([top.min(axis=0)[:2], top.max(axis=0)[:2]], [[-1.2, -1.2], [1.2, 1.2]], atol=1e-5)
    twisted = features.sweep(SQUARE, FLAT, LINE, UPRIGHT, clearance=0.2, twist=90.0)
    assert twisted.is_watertight and twisted.bounds[:, 2] == pytest.approx([-0.2, 20.2])


def test_make_sweep_keeps_a_twist_and_size_only_when_used():
    assert {"twist", "end_scale"}.isdisjoint(create.make_sweep(*make_pair()).params)
    shape = create.make_sweep(*make_pair(), twist=30.0, end_scale=150.0)
    assert (shape.params["twist"], shape.params["end_scale"]) == (30.0, 150.0)
    with pytest.raises(BuildError) as err:
        create.make_sweep(*make_pair(), end_scale=0.5)
    assert "between 1% and 1000%" in str(err.value)


def test_a_twisted_sweep_round_trips_through_a_project_file(tmp_path):
    shape = create.make_sweep(*make_pair(), twist=-60.0, end_scale=75.0)
    path = tmp_path / "twisted.mesh"
    save_project(Scene(shapes=[shape]), path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


def test_twisting_in_the_window_is_one_undo_step(window, monkeypatch):
    sketches = add_pair(window)

    def ask(parent, pair, path_id):
        return {"path": path_id, "twist": 90.0, "end_scale": 50.0, "result": "part", "keep_sketch": False}

    monkeypatch.setattr(expert_actions, "ask_sweep", ask)
    steps = len(window.document._undo)
    window.do_sweep()
    shape = window.document.scene.shapes[0]
    assert (shape.params["twist"], shape.params["end_scale"]) == (90.0, 50.0)
    assert len(window.document._undo) == steps + 1
    assert window.inspector.visible_param_fields() == {"twist", "end_scale"}
    window.do_undo()
    assert {s.id for s in window.document.scene.shapes} == {s.id for s in sketches.values()}


def test_twist_and_size_are_in_the_details_panel(window, warnings):
    add_pair(window)
    window.sweep_selected()
    shape = window.document.scene.shapes[0]
    # A sweep made without them shows them as they act: no twist, 100%.
    assert window.inspector.field_value("end_scale") == pytest.approx(100.0)
    window._on_edited(shape.id, "end_scale", 50.0)
    window._finish_edit()
    assert shape.params["end_scale"] == 50.0
    smaller = shape_geometry(shape).volume
    window._on_edited(shape.id, "twist", 45.0)
    window._finish_edit()
    assert shape.params["twist"] == 45.0
    window._on_edited(shape.id, "end_scale", 0.5)
    assert shape.params["end_scale"] == 50.0 and warnings and "between 1% and 1000%" in warnings[0]
    window.do_undo()
    assert "twist" not in window.document.scene.shapes[0].params
    assert shape_geometry(window.document.scene.shapes[0]).volume == pytest.approx(smaller)


def test_a_closed_sweep_refuses_a_part_turn_in_the_details_panel(window, warnings):
    window.add_sketch(BRICK, FLAT, "Outline")
    window.add_sketch(RING, FLAT, "Path")
    window.do_select_all()
    window.sweep_selected(window.document.scene.shapes[1].id, twist=360.0)
    shape = window.document.scene.shapes[0]
    window._on_edited(shape.id, "twist", 90.0)
    assert shape.params["twist"] == 360.0 and warnings and "whole turns" in warnings[0]


def test_the_sweep_note_is_plain_language():
    assert_plain(expert_actions.SWEEP_NOTE)
    from mesh.panels import FIELD_LABELS

    for key in ("twist", "end_scale"):
        assert_plain(FIELD_LABELS[key])
