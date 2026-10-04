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
    assert PRIMITIVES["loft"]["shelf"] is False and PRIMITIVES["loft"]["defaults"] == {}
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
    assert form.values() == {"result": "part", "keep_sketch": False}
