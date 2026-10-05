"""Loft (Expert mode): a skin through two or more sketches' outlines."""

import numpy as np
import pytest

from mesh import create, expert_actions, features, sketch, sketch_editor
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import PRIMITIVES, shape_geometry
from test_plain_language import assert_plain

BIG = [{"type": "rectangle", "corner": [-10, -10], "width": 20, "height": 20}]
SMALL = [{"type": "rectangle", "corner": [-5, -5], "width": 10, "height": 10}]
ROUND = [{"type": "circle", "centre": [0, 0], "diameter": 16}]


def at(height, turn=None):
    frame = np.eye(4)
    frame[2, 3] = height
    if turn is not None:
        frame[:3, :3] = turn
    return frame


def section(entities, height, turn=None):
    return {"entities": entities, "frame": at(height, turn).tolist()}


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


def test_two_squares_make_an_exact_frustum():
    tm = features.loft([section(BIG, 0), section(SMALL, 10)])
    assert tm.is_watertight
    assert tm.volume == pytest.approx(10 / 3 * (400 + 100 + 200))
    assert np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 10]])


@pytest.mark.parametrize("turn", [
    np.diag([1.0, -1.0, -1.0]),   # drawn facing down
    np.diag([-1.0, 1.0, 1.0]),    # mirrored
], ids=["facing down", "mirrored"])
def test_however_an_outlines_plane_faces_the_skin_comes_out_solid(turn):
    tm = features.loft([section(BIG, 0), section(BIG, 10, turn)])
    assert tm.is_watertight and tm.volume == pytest.approx(4000.0)


def test_corners_line_up_without_a_twist():
    diamond = [{"type": "polygon", "centre": [0, 0], "sides": 4, "radius": 10, "angle": 45}]
    tm = features.loft([section(BIG, 0), section(diamond, 10)])
    # Corners join corners: a straight frustum between the two squares.
    assert tm.volume == pytest.approx(10 / 3 * (400 + 200 + np.sqrt(400 * 200)))


def test_a_square_to_a_circle_through_three_outlines():
    tm = features.loft([section(BIG, 0), section(ROUND, 20), section(SMALL, 40)])
    assert tm.is_watertight
    assert np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 40]])
    assert 0 < tm.volume < 400 * 40


def winding(tm, points):
    """How many times the closed surface wraps each point: 1 inside, 0 outside."""
    a, b, c = (tm.triangles[:, i][None, :, :] - np.asarray(points)[:, None, :] for i in range(3))
    la, lb, lc = (np.linalg.norm(v, axis=2) for v in (a, b, c))
    top = np.einsum("pti,pti->pt", a, np.cross(b, c))
    bottom = (la * lb * lc + np.einsum("pti,pti->pt", a, b) * lc
              + np.einsum("pti,pti->pt", b, c) * la + np.einsum("pti,pti->pt", c, a) * lb)
    return np.round(np.arctan2(top, bottom).sum(axis=1) / (2 * np.pi), 3)


@pytest.mark.parametrize("small, height", [(SMALL, 10), ([{"type": "rectangle", "corner": [-1, -1],
                                                          "width": 2, "height": 2}], 5)],
                         ids=["gentle", "steep"])
def test_a_fitted_hole_loft_leaves_the_clearance_on_every_side(small, height):
    exact = features.loft([section(BIG, 0), section(small, height)])
    fitted = features.loft([section(BIG, 0), section(small, height)], clearance=0.4)
    assert fitted.is_watertight
    # Every side of the exact loft, pushed out 0.39 mm square to itself, is
    # still inside the fitted hole.
    pushed = exact.triangles_center + 0.39 * exact.face_normals
    assert np.all(winding(fitted, pushed) == 1)
    low, high = fitted.bounds[:, 2]
    assert low == pytest.approx(-0.4) and high == pytest.approx(height + 0.4)


def test_a_fitted_hole_loft_never_grows_more_than_three_times_the_fit():
    flat_step = [section(BIG, 0), section(SMALL, 0.5)]
    fitted = features.loft(flat_step, clearance=0.4)
    assert fitted.bounds[1][0] == pytest.approx(10 + 3 * 0.4, abs=1e-5)


def test_a_fit_that_closes_a_narrow_gap_is_refused():
    # A C shape whose 0.5 mm slot leads into a pocket: a 0.4 mm fit closes it.
    c_shape = [
        {"type": "line", "start": [0.25, 5], "end": [0.25, 10]},
        {"type": "line", "start": [0.25, 10], "end": [10, 10]},
        {"type": "line", "start": [10, 10], "end": [10, -10]},
        {"type": "line", "start": [10, -10], "end": [-10, -10]},
        {"type": "line", "start": [-10, -10], "end": [-10, 10]},
        {"type": "line", "start": [-10, 10], "end": [-0.25, 10]},
        {"type": "line", "start": [-0.25, 10], "end": [-0.25, 5]},
        {"type": "line", "start": [-0.25, 5], "end": [-5, 5]},
        {"type": "line", "start": [-5, 5], "end": [-5, -5]},
        {"type": "line", "start": [-5, -5], "end": [5, -5]},
        {"type": "line", "start": [5, -5], "end": [5, 5]},
        {"type": "line", "start": [5, 5], "end": [0.25, 5]},
    ]
    sections = [section(c_shape, 0), section(c_shape, 20)]
    assert features.loft(sections, clearance=0.1).is_watertight
    with pytest.raises(sketch.SketchError) as err:
        features.loft(sections, clearance=0.4)
    assert "narrow gap" in str(err.value)
    assert_plain(str(err.value))


# A thin L: lofted from a 20 mm circle its sides would pass through each
# other, turning part of it inside out.
L_SHAPE = [{"type": "line", "start": a, "end": b} for a, b in zip(
    [[-10, -10], [10, -10], [10, -8], [-8, -8], [-8, 10], [-10, 10]],
    [[10, -10], [10, -8], [-8, -8], [-8, 10], [-10, 10], [-10, -10]])]


@pytest.mark.parametrize("sections, words", [
    ([section(BIG, 0)], "at least two"),
    ("square", "at least two"),
    ([section(BIG, 0), section(BIG, 0)], "same place"),
    ([section(BIG, 0), section(BIG + [{"type": "circle", "centre": [0, 0], "diameter": 4}], 9)], "no holes"),
    ([section(BIG, 0), section([{"type": "line", "start": [0, 0], "end": [1, 1]}], 9)], "no closed outline"),
    ([section(BIG, 0), "damaged"], "damaged"),
    ([section([{"type": "circle", "centre": [0, 0], "diameter": 20}], 0), section(L_SHAPE, 20)],
     "pass through each other"),
    ([section(BIG, 0), section(ROUND, 20), section(SMALL, 10)], "fold back"),
])
def test_loft_refuses_plainly(sections, words):
    with pytest.raises(sketch.SketchError) as err:
        features.loft(sections)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_loft_is_an_off_the_shelf_primitive_standing_on_the_workplane():
    assert PRIMITIVES["loft"]["shelf"] is False and PRIMITIVES["loft"]["defaults"] == {"sides": "straight"}
    tm = shape_geometry(new_primitive("loft"))
    assert tm.is_watertight
    assert np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 20]])


# --- Made from sketches -----------------------------------------------------------------


def three_sketches():
    return [create.new_sketch(e, at(h), f"Sketch {i + 1}")
            for i, (e, h) in enumerate([(BIG, 0), (ROUND, 20), (SMALL, 40)])]


def test_make_loft_joins_the_sketches_in_the_order_given():
    sketches = three_sketches()
    shape = create.make_loft(sketches, hole=True)
    assert shape.name == "Loft of Sketch 1 to Sketch 3" and shape.is_hole
    assert [s["entities"] for s in shape.params["sections"]] == [s.params["entities"] for s in sketches]
    assert np.allclose(shape_geometry(shape).bounds, [[-10, -10, 0], [10, 10, 40]])


def test_make_loft_refuses_fewer_than_two_sketches():
    sketches = three_sketches()
    for attempt in ([sketches[0]], [sketches[0], new_primitive("cube")]):
        with pytest.raises(BuildError) as err:
            create.make_loft(attempt)
        assert_plain(str(err.value))


def test_a_lofts_outlines_are_not_changed_with_change_sketch():
    assert not create.has_sketch(create.make_loft(three_sketches()[:2]))


def test_a_loft_round_trips_through_a_project_file(tmp_path):
    scene = Scene()
    shape = create.make_loft(three_sketches())
    scene.add(shape)
    path = tmp_path / "lofted.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


# --- In the window --------------------------------------------------------------------


def add_three(window, pick=(0, 1, 2)):
    for entities, height in [(BIG, 0), (ROUND, 20), (SMALL, 40)]:
        window.add_sketch(entities, at(height))
    shapes = window.document.scene.shapes
    window.document.scene.select([shapes[i].id for i in pick])
    return list(shapes)


def test_loft_replaces_the_sketches_in_one_undo_step(window):
    before = add_three(window)
    steps = len(window.document._undo)
    assert window.loft_selected()
    assert [s.name for s in window.document.scene.shapes] == ["Loft of Sketch 1 to Sketch 3"]
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [s.id for s in before]


def test_loft_follows_the_order_the_sketches_were_picked(window):
    sketches = add_three(window, pick=(2, 1, 0))
    window.loft_selected(keep_sketch=True)
    loft = window.document.scene.shapes[-1]
    assert loft.name == "Loft of Sketch 3 to Sketch 1"
    assert [s["entities"] for s in loft.params["sections"]] == [
        sketches[i].params["entities"] for i in (2, 1, 0)]


def test_sketches_picked_out_of_order_are_refused(window, warnings):
    add_three(window, pick=(2, 0, 1))
    assert not window.loft_selected()
    assert len(window.document.scene.shapes) == 3
    assert warnings and "fold back" in warnings[0]


def test_a_refused_loft_changes_nothing(window, warnings):
    window.add_sketch(BIG, at(0))
    window.add_sketch(BIG, at(0))
    window.do_select_all()
    steps = len(window.document._undo)
    assert not window.loft_selected()
    assert len(window.document._undo) == steps and len(window.document.scene.shapes) == 2
    assert warnings and "same place" in warnings[0]


def test_loft_asks_then_makes_a_hole(window, monkeypatch):
    add_three(window)
    seen = {}

    def ask(parent, sketches):
        seen["names"] = [s.name for s in sketches]
        return {"result": "hole", "keep_sketch": False}

    monkeypatch.setattr(expert_actions, "ask_loft", ask)
    window.do_loft()
    assert seen["names"] == ["Sketch 1", "Sketch 2", "Sketch 3"]
    assert window.document.scene.shapes[0].is_hole


def test_loft_needs_two_sketches_selected(window, monkeypatch):
    monkeypatch.setattr(expert_actions, "ask_loft", lambda *a: pytest.fail("asked"))
    window.add_sketch(BIG, at(0))
    window.do_loft()
    assert window.statusBar().currentMessage() == window.LOFT_HINT


def test_change_sketch_says_a_loft_cannot_be_redrawn(window, monkeypatch):
    add_three(window)
    window.loft_selected()
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: pytest.fail("opened"))
    window.do_edit_sketch()
    assert window.statusBar().currentMessage() == window.LOFT_NOT_REDRAWN
    assert_plain(window.LOFT_NOT_REDRAWN)


def test_loft_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    form = close_qt_widget(FormDialog(None, "Loft", expert_actions.loft_fields(3)))
    for text in form.labels():
        assert_plain(text)
    assert form.values() == {"sides": "straight", "result": "part", "keep_sketch": False}


# --- Smooth sides --------------------------------------------------------------------

NARROW = [{"type": "circle", "centre": [0, 0], "diameter": 10}]
WIDE = [{"type": "circle", "centre": [0, 0], "diameter": 20}]
BARREL = [section(NARROW, 0), section(WIDE, 10), section(NARROW, 20)]


def widest_at(tm, height):
    cut = tm.section(plane_origin=[0, 0, height], plane_normal=[0, 0, 1])
    return float(np.linalg.norm(cut.vertices[:, :2], axis=1).max())


def test_smooth_sides_curve_through_three_outlines():
    straight = features.loft(BARREL)
    smooth = features.loft(BARREL, sides="smooth")
    assert smooth.is_watertight
    assert np.allclose(smooth.bounds, straight.bounds)
    # Half way between the ends and the middle the straight sides are half
    # way out (7.5 mm); the smooth curve (a natural spline through 5, 10
    # and 5 mm) is already at 8.4375 mm.
    assert widest_at(straight, 5) == pytest.approx(7.5, abs=1e-4)
    assert widest_at(smooth, 5) == pytest.approx(8.4375, abs=1e-4)
    # And it passes exactly through each outline.
    assert widest_at(smooth, 10) == pytest.approx(10.0, abs=1e-4)
    assert smooth.volume > straight.volume


def test_smooth_sides_between_two_outlines_are_straight():
    two = [section(BIG, 0), section(SMALL, 10)]
    assert features.loft(two, sides="smooth").volume == pytest.approx(features.loft(two).volume)


def test_a_fitted_hole_smooth_loft_leaves_the_clearance_on_every_side():
    exact = features.loft(BARREL, sides="smooth")
    fitted = features.loft(BARREL, clearance=0.4, sides="smooth")
    assert fitted.is_watertight
    # Sides of the exact loft all along it (every 29th: it is round),
    # pushed out 0.39 mm square to themselves, are still inside the hole.
    pushed = (exact.triangles_center + 0.39 * exact.face_normals)[::29]
    assert len(pushed) > 100
    assert np.all(winding(fitted, pushed) == 1)
    low, high = fitted.bounds[:, 2]
    assert low == pytest.approx(-0.4) and high == pytest.approx(20.4)


def test_sides_that_are_neither_straight_nor_smooth_are_refused():
    with pytest.raises(sketch.SketchError) as err:
        features.loft(BARREL, sides="wavy")
    assert "straight or smooth" in str(err.value)
    assert_plain(str(err.value))


def test_make_loft_keeps_smooth_sides_only_when_chosen():
    assert "sides" not in create.make_loft(three_sketches()).params
    shape = create.make_loft(three_sketches(), sides="smooth")
    assert shape.params["sides"] == "smooth"
    straight = shape_geometry(create.make_loft(three_sketches())).volume
    assert shape_geometry(shape).volume != pytest.approx(straight)


def test_a_smooth_loft_round_trips_through_a_project_file(tmp_path):
    scene = Scene()
    shape = create.make_loft(three_sketches(), sides="smooth")
    scene.add(shape)
    path = tmp_path / "smooth.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params["sides"] == "smooth"
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(shape).volume)


def test_smooth_loft_in_the_window_is_one_undo_step(window, monkeypatch):
    before = add_three(window)
    monkeypatch.setattr(expert_actions, "ask_loft",
                        lambda parent, sketches: {"sides": "smooth", "result": "part", "keep_sketch": False})
    steps = len(window.document._undo)
    window.do_loft()
    loft = window.document.scene.shapes[0]
    assert loft.params["sides"] == "smooth" and len(window.document._undo) == steps + 1
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [s.id for s in before]


def test_the_sides_can_be_changed_in_the_details_panel(window):
    add_three(window)
    window.loft_selected()
    shape = window.document.scene.shapes[0]
    assert window.inspector.visible_param_fields() == {"sides"}
    # A loft made before there was a choice shows its sides as they are.
    assert window.inspector.field_value("sides") == "straight"
    straight = shape_geometry(shape).volume
    window._on_edited(shape.id, "sides", "smooth")
    window._finish_edit()
    assert shape.params["sides"] == "smooth"
    assert shape_geometry(shape).volume != pytest.approx(straight)
    window.do_undo()
    assert "sides" not in window.document.scene.shapes[0].params
    assert shape_geometry(window.document.scene.shapes[0]).volume == pytest.approx(straight)


def test_the_loft_note_and_sides_are_plain_language(window, monkeypatch):
    seen = {}

    def form(parent, title, fields, note=""):
        seen["note"] = note
        return None

    monkeypatch.setattr(expert_actions, "run_form", form)
    expert_actions.ask_loft(window, three_sketches())
    assert "smooth curve" in seen["note"]
    assert_plain(seen["note"])
    from mesh.panels import FIELD_LABELS

    assert_plain(FIELD_LABELS["sides"])
    for _value, label in features.LOFT_SIDES:
        assert_plain(label)


# --- Closing to a point -------------------------------------------------------------


def tip(x, y, z):
    return {"point": [x, y, z]}


def test_a_square_to_a_point_is_an_exact_pyramid():
    for sections in ([section(BIG, 0), tip(0, 0, 30)], [tip(0, 0, 30), section(BIG, 0)],
                     [tip(0, 0, -30), section(BIG, 0)], [section(BIG, 0), tip(15, 5, 30)]):
        tm = features.loft(sections)
        assert tm.is_watertight
        assert tm.volume == pytest.approx(400 * 30 / 3)
    assert np.allclose(features.loft([section(BIG, 0), tip(0, 0, 30)]).bounds, [[-10, -10, 0], [10, 10, 30]])


def test_a_point_at_each_end_makes_a_double_cone():
    tm = features.loft([tip(0, 0, -10), section(WIDE, 0), tip(0, 0, 10)])
    assert tm.is_watertight
    circle = sketch.profile(WIDE).area()
    assert tm.volume == pytest.approx(2 * circle * 10 / 3)
    assert np.allclose(tm.bounds, [[-10, -10, -10], [10, 10, 10]], atol=1e-6)


def test_smooth_sides_run_into_the_point():
    sections = [section(BIG, 0), section(ROUND, 10), tip(0, 0, 20)]
    smooth = features.loft(sections, sides="smooth")
    assert smooth.is_watertight
    assert smooth.bounds[1][2] == pytest.approx(20.0)
    assert smooth.volume != pytest.approx(features.loft(sections).volume)


@pytest.mark.parametrize("sides", ["straight", "smooth"])
def test_a_fitted_hole_closing_to_a_point_leaves_the_clearance(sides):
    sections = [section(WIDE, 0), section(ROUND, 8), tip(0, 0, 20)]
    exact = features.loft(sections, sides=sides)
    fitted = features.loft(sections, clearance=0.4, sides=sides)
    assert fitted.is_watertight
    pushed = (exact.triangles_center + 0.39 * exact.face_normals)[::29]
    assert np.all(winding(fitted, pushed) == 1)
    assert fitted.bounds[0][2] == pytest.approx(-0.4)
    # The tip moves out along the sides, so the gap at its sides is the fit.
    assert fitted.bounds[1][2] > 20.4


def test_a_fitted_pyramid_moves_its_tip_out_for_its_flat_sides():
    fitted = features.loft([section(BIG, 0), tip(0, 0, 30)], clearance=0.4)
    # Each flat side meets the upright at asin(1/sqrt(10)): moving the tip
    # out 0.4 / sin of that would be 1.26 mm, capped at three times the fit.
    assert fitted.bounds[1][2] == pytest.approx(30 + 3 * 0.4)


@pytest.mark.parametrize("sections, words", [
    ([section(BIG, 0), tip(0, 5, 0)], "on the plane"),
    ([tip(0, 0, 0), tip(0, 0, 5)], "not only points"),
    ([section(BIG, 0), tip(0, 0, 5), section(BIG, 10)], "first or last end"),
    ([section(BIG, 0), {"point": [0, "x", 5]}], "damaged"),
    ([section(BIG, 0), {"point": [0, 5]}], "damaged"),
])
def test_a_loft_to_a_point_refuses_plainly(sections, words):
    with pytest.raises(sketch.SketchError) as err:
        features.loft(sections)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_make_loft_closes_to_a_construction_point_picked_first_or_last():
    from mesh import construct

    base, middle = three_sketches()[:2]
    point = construct.new_point((0, 0, 50), "Point 1")
    shape = create.make_loft([base, middle, point])
    assert shape.name == "Loft of Sketch 1 to Point 1"
    assert shape.params["sections"][-1] == {"point": [0.0, 0.0, 50.0]}
    assert shape_geometry(shape).bounds[1][2] == pytest.approx(50.0)
    assert create.make_loft([point, base]).params["sections"][0] == {"point": [0.0, 0.0, 50.0]}
    for picks in ([base, point, middle], [point, construct.new_point((0, 0, 9))], [point]):
        with pytest.raises(BuildError) as err:
            create.make_loft(picks)
        assert "first or last" in str(err.value)
        assert_plain(str(err.value))


def test_a_loft_to_a_point_round_trips_through_a_project_file(tmp_path):
    from mesh import construct

    scene = Scene()
    shape = create.make_loft([three_sketches()[0], construct.new_point((0, 0, 30))])
    scene.add(shape)
    path = tmp_path / "pointed.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert shape_geometry(loaded).volume == pytest.approx(4000.0)


def test_a_loft_to_a_point_scales_with_its_point():
    from mesh import construct, modify

    shape = create.make_loft([three_sketches()[0], construct.new_point((0, 0, 30))])
    [scaled] = modify.scaled([shape], (2.0, 2.0, 2.0), about="base")
    assert scaled.params["sections"][-1] == {"point": [0.0, 0.0, 60.0]}
    assert shape_geometry(scaled).volume == pytest.approx(8 * 4000.0)


def test_lofting_to_a_point_in_the_window_keeps_the_point(window):
    from mesh import construct

    window.add_sketch(BIG, at(0))
    base = window.document.scene.shapes[-1]
    point = construct.new_point((0, 0, 30), "Point 1")
    window.document.scene.add(point)
    window.document.scene.select([base.id, point.id])
    steps = len(window.document._undo)
    assert window.loft_selected()
    names = [s.name for s in window.document.scene.shapes]
    assert names == ["Point 1", "Loft of Sketch 1 to Point 1"]
    assert len(window.document._undo) == steps + 1
    window.do_undo()
    assert {s.id for s in window.document.scene.shapes} == {base.id, point.id}


def test_a_point_between_the_sketches_shows_the_hint(window, monkeypatch):
    from mesh import construct

    monkeypatch.setattr(expert_actions, "ask_loft", lambda *a: pytest.fail("asked"))
    window.add_sketch(BIG, at(0))
    first = window.document.scene.shapes[-1]
    point = construct.new_point((0, 0, 10), "Point 1")
    window.document.scene.add(point)
    window.add_sketch(SMALL, at(20))
    last = window.document.scene.shapes[-1]
    window.document.scene.select([first.id, point.id, last.id])
    window.do_loft()
    assert window.statusBar().currentMessage() == window.LOFT_HINT
    assert_plain(window.LOFT_HINT)
