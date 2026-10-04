"""Move or Copy (Expert mode): parts moved and turned by exact amounts."""

import numpy as np
import pytest

from mesh import create, modify, modify_actions, ops
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

SQUARE = [{"type": "rectangle", "corner": [0, 0], "width": 10, "height": 10}]


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


def box(x=0.0, **params):
    shape = new_primitive("cube")
    shape.params.update(params)
    shape.transform[0, 3] = x
    return shape


# --- The moves ------------------------------------------------------------------------


def test_a_move_shifts_parts_by_exactly_the_amounts():
    part = box()
    [moved] = modify.move_copy([part], 5.5, -3.0, 2.25)
    assert np.allclose(shape_geometry(moved).bounds, shape_geometry(part).bounds + [5.5, -3.0, 2.25])
    assert moved.id == part.id
    assert np.allclose(part.transform, np.eye(4))  # the original is left alone


def test_a_turn_goes_around_a_line_through_the_parts_middle():
    a, b = box(0.0), box(40.0)  # together: x from -10 to 50, middle at x = 20
    turned = modify.move_copy([a, b], axis="z", angle=90.0)
    centres = [shape_geometry(s).bounds.mean(axis=0) for s in turned]
    assert np.allclose(centres, [[20, -20, 10], [20, 20, 10]], atol=1e-9)
    assert ops.euler_from_transform(turned[0].transform)[2] == pytest.approx(90.0)


@pytest.mark.parametrize("axis, expected", [
    ("x", [[-10, -10, 0], [10, 10, 20]]), ("y", [[-10, -10, 0], [10, 10, 20]]),
])
def test_a_quarter_turn_about_a_level_line_keeps_a_cube_in_its_box(axis, expected):
    [turned] = modify.move_copy([box()], axis=axis, angle=90.0)
    assert np.allclose(shape_geometry(turned).bounds, expected, atol=1e-9)


def test_turning_then_moving():
    part = box(width=40.0)
    [moved] = modify.move_copy([part], 0.0, 0.0, 10.0, "y", 90.0)
    assert np.allclose(shape_geometry(moved).bounds, [[-10, -10, 0], [10, 10, 40]], atol=1e-9)


def test_copies_are_new_parts_with_their_own_ids():
    group = ops.make_group([box(), box(30.0)])
    [copied] = modify.move_copy([group], dx=50.0, make_copy=True)
    assert copied.id != group.id
    inside = {c["id"] for c in copied.params["children"]}
    assert inside.isdisjoint({c["id"] for c in group.params["children"]})
    assert np.allclose(shape_geometry(copied).bounds, shape_geometry(group).bounds + [50, 0, 0])


def test_a_sketch_moves_with_its_plane():
    sketch_shape = create.new_sketch(SQUARE, np.eye(4))
    [moved] = modify.move_copy([sketch_shape], 1.0, 2.0, 3.0)
    assert np.allclose(moved.transform[:3, 3], [1, 2, 3])
    assert moved.params == sketch_shape.params


@pytest.mark.parametrize("args, words", [
    (([], 1, 0, 0), "Select the parts"),
    (([None], float("nan"), 0, 0), "ordinary numbers"),
    (([None], 0, 0, 0, "z", float("inf")), "ordinary numbers"),
    (([None], 20000, 0, 0), "at most 10000 mm"),
    (([None], 0, 0, 0, "z", 400), "at most 360 degrees"),
])
def test_move_or_copy_refuses_plainly(args, words):
    shapes = [box() for _ in args[0]]
    with pytest.raises(BuildError) as err:
        modify.move_copy(shapes, *args[1:])
    assert words in str(err.value)
    assert_plain(str(err.value))


# --- In the window --------------------------------------------------------------------


def test_moving_is_one_undo_step(window):
    window.add_primitive("cube")
    part = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert window.move_copy_selected(10.0, 0.0, 5.0, "z", 45.0)
    assert len(window.document._undo) == steps + 1
    assert len(window.document.scene.shapes) == 1
    moved = shape_geometry(part).bounds.mean(axis=0)
    assert np.allclose(moved[:2], [10, 0], atol=1e-9)
    window.do_undo()
    assert np.allclose(window.document.scene.shapes[0].transform, np.eye(4))
    window.do_redo()
    assert np.allclose(shape_geometry(window.document.scene.shapes[0]).bounds.mean(axis=0)[:2], [10, 0])


def test_copying_adds_selected_copies_in_one_undo_step(window):
    window.add_primitive("cube")
    window.add_primitive("sphere")
    scene = window.document.scene
    scene.select([s.id for s in scene.shapes])
    assert window.move_copy_selected(dx=30.0, make_copy=True)
    assert len(scene.shapes) == 4
    assert scene.selection == [s.id for s in scene.shapes[2:]]
    assert np.allclose(scene.shapes[0].transform, np.eye(4))
    window.do_undo()
    assert len(window.document.scene.shapes) == 2


def test_nothing_to_move_takes_no_undo_step(window):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.move_copy_selected()
    assert len(window.document._undo) == steps
    assert window.statusBar().currentMessage() == window.NOTHING_TO_MOVE


def test_move_or_copy_needs_a_selection(window, monkeypatch):
    asked = []
    monkeypatch.setattr(modify_actions, "ask_move_copy", lambda parent: asked.append(1))
    window.do_move_copy()
    assert not asked
    assert window.statusBar().currentMessage() == window.NOTHING_SELECTED


def test_a_refused_move_changes_nothing(window, warnings):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.move_copy_selected(dx=float("nan"))
    assert warnings and len(window.document._undo) == steps


def test_move_or_copy_asks_for_its_amounts(window, monkeypatch):
    window.add_primitive("cube")
    monkeypatch.setattr(modify_actions, "ask_move_copy", lambda parent: {
        "dx": 0.0, "dy": 7.0, "dz": 0.0, "axis": "z", "angle": 0.0, "make_copy": True,
    })
    window.do_move_copy()
    scene = window.document.scene
    assert len(scene.shapes) == 2
    assert scene.shapes[1].transform[1, 3] == pytest.approx(7.0)


def test_a_moved_and_turned_part_round_trips_through_a_project_file(tmp_path):
    [part] = modify.move_copy([box()], 3.0, 4.0, 5.0, "x", 30.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[part]), path)
    loaded = load_project(path).shapes[0]
    assert np.allclose(loaded.transform, part.transform)
    assert np.allclose(shape_geometry(loaded).vertices, shape_geometry(part).vertices)


def test_move_or_copy_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Move or Copy", modify_actions.move_copy_fields()))
    for text in dialog.labels():
        assert_plain(text)
