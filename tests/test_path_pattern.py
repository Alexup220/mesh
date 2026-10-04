"""Pattern Along a Path (Expert mode's Path Pattern): copies along a sketch's path."""

import math

import numpy as np
import pytest

from mesh import create, pattern_actions, patterns, sketch
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

LINE = [{"type": "line", "start": [0, 0], "end": [60, 0]}]
CORNER = [{"type": "line", "start": [0, 0], "end": [40, 0]}, {"type": "line", "start": [40, 0], "end": [40, 40]}]
CIRCLE = [{"type": "circle", "centre": [0, 0], "diameter": 60}]
SQUARE = [{"type": "rectangle", "corner": [0, 0], "width": 40, "height": 40}]


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


def path(entities, frame=None):
    return create.new_sketch(entities, np.eye(4) if frame is None else frame)


def box_at(x=0.0, y=0.0):
    box = new_primitive("cube")
    box.transform[:2, 3] = (x, y)
    return box


def middles(shapes):
    return [tuple(np.round(shape_geometry(s).bounds.mean(axis=0), 6)) for s in shapes]


def turn_of(shape) -> float:
    """How far a part is turned round an upright line, in degrees."""
    return math.degrees(math.atan2(shape.transform[1, 0], shape.transform[0, 0]))


# --- Along an open path -----------------------------------------------------------------


def test_copies_spread_evenly_from_the_parts_to_the_far_end():
    copies = patterns.along_path([box_at()], path(LINE), 4)
    assert middles(copies) == [(20, 0, 10), (40, 0, 10), (60, 0, 10)]


def test_copies_can_be_a_set_spacing_apart():
    copies = patterns.along_path([box_at()], path(LINE), 3, spacing=15.0)
    assert middles(copies) == [(15, 0, 10), (30, 0, 10)]


def test_copies_start_from_the_end_nearest_the_parts():
    copies = patterns.along_path([box_at(60.0)], path(LINE), 4)
    assert middles(copies) == [(40, 0, 10), (20, 0, 10), (0, 0, 10)]


def test_copies_keep_the_parts_place_beside_the_path():
    copies = patterns.along_path([box_at(0.0, 25.0)], path(LINE), 3, spacing=30.0)
    assert middles(copies) == [(30, 25, 10), (60, 25, 10)]


def test_an_upright_path_carries_copies_upward():
    upright = path([{"type": "line", "start": [0, 0], "end": [0, 60]}], sketch.plane_frame((0, -1, 0)))
    copies = patterns.along_path([box_at()], upright, 3)
    assert middles(copies) == [(0, 0, 40), (0, 0, 70)]


def test_copies_turn_at_a_corner_only_when_asked():
    still = patterns.along_path([box_at()], path(CORNER), 3, spacing=40.0)
    turning = patterns.along_path([box_at()], path(CORNER), 3, spacing=40.0, follow=True)
    assert middles(still) == middles(turning) == [(40, 0, 10), (40, 40, 10)]
    assert [turn_of(c) for c in still] == [0, 0]
    assert [turn_of(c) for c in turning] == pytest.approx([90, 90])


def test_several_parts_go_along_together_and_holes_stay_holes():
    box, hole = box_at(), new_primitive("cylinder")
    hole.is_hole, hole.fit = True, "loose"
    copies = patterns.along_path([box, hole], path(LINE), 2)
    assert [c.is_hole for c in copies] == [False, True] and copies[1].fit == "loose"
    assert middles(copies) == [(60, 0, 10), (60, 0, 10)]


# --- Round a closed path ----------------------------------------------------------------


@pytest.mark.parametrize("follow, turns", [(False, [0, 0, 0]), (True, [90, 180, -90])])
def test_copies_go_round_a_circle_from_the_parts(follow, turns):
    copies = patterns.along_path([box_at(30.0)], path(CIRCLE), 4, follow=follow)
    assert [m for m in middles(copies)] == [pytest.approx(p, abs=1e-6) for p in [(0, 30, 10), (-30, 0, 10), (0, -30, 10)]]
    assert [turn_of(c) for c in copies] == pytest.approx(turns, abs=1e-6)


def test_following_a_circle_matches_a_pattern_around_a_line():
    along = patterns.along_path([box_at(30.0)], path(CIRCLE), 4, follow=True)
    around = patterns.circular([box_at(30.0)], 4, "z", (0.0, 0.0, 0.0))
    for a, b in zip(along, around):
        assert a.transform == pytest.approx(b.transform, abs=1e-6)


def test_a_closed_path_starts_at_its_point_nearest_the_parts():
    # The box sits below the middle of the square's bottom side.
    copies = patterns.along_path([box_at(20.0, -5.0)], path(SQUARE), 4)
    assert sorted(middles(copies)) == [(0, 15, 10), (20, 35, 10), (40, 15, 10)]


def test_copies_round_a_closed_path_never_land_back_on_the_parts():
    with pytest.raises(BuildError) as err:
        patterns.along_path([box_at(30.0)], path(CIRCLE), 4, spacing=50.0)
    assert "don't fit" in str(err.value)
    assert len(patterns.along_path([box_at(30.0)], path(CIRCLE), 4, spacing=45.0)) == 3


# --- Refusals ---------------------------------------------------------------------------


def test_copies_that_run_off_the_end_are_refused_with_the_length():
    with pytest.raises(BuildError) as err:
        patterns.along_path([box_at()], path(LINE), 5, spacing=20.0)
    assert "60.0 mm long" in str(err.value)
    assert_plain(str(err.value))


@pytest.mark.parametrize("guide, count, spacing, words", [
    (lambda: new_primitive("cube"), 3, None, "one sketch"),
    (lambda: path([{"type": "line", "start": [0, 0], "end": [10, 0]},
                   {"type": "line", "start": [10, 0], "end": [20, 0]},
                   {"type": "line", "start": [10, 0], "end": [10, 10]}]), 3, None, "branch"),
    (lambda: path(CIRCLE + LINE), 3, None, "exactly one path"),
    (lambda: path(LINE), 1, None, "at least 2"),
    (lambda: path(LINE), 3, 0.0, "more than 0"),
    (lambda: path(LINE), 3, -5.0, "more than 0"),
])
def test_path_pattern_refuses_plainly(guide, count, spacing, words):
    with pytest.raises(BuildError) as err:
        patterns.along_path([box_at()], guide(), count, spacing)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_sketches_are_not_copied_along_a_path():
    with pytest.raises(BuildError) as err:
        patterns.along_path([path(SQUARE)], path(LINE), 3)
    assert "Sketches are guides" in str(err.value)


# --- In the window ----------------------------------------------------------------------


def add_parts_and_path(window, entities=LINE):
    window.add_primitive("cube")
    window.add_sketch(entities, np.eye(4))
    box, guide = window.document.scene.shapes
    window.document.scene.select([box.id, guide.id])
    return box, guide


def test_patterning_along_a_path_is_one_undo_step(window):
    box, guide = add_parts_and_path(window)
    steps = len(window.document._undo)
    assert window.path_pattern_selected(3)
    scene = window.document.scene
    assert len(scene.shapes) == 4 and len(window.document._undo) == steps + 1
    assert guide.id not in scene.selection and scene.selection[0] == box.id and len(scene.selection) == 3
    assert middles(scene.shapes[2:]) == [(30, 0, 10), (60, 0, 10)]
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [box.id, guide.id]


@pytest.mark.parametrize("even, expected", [(True, [(30, 0, 10), (60, 0, 10)]), (False, [(10, 0, 10), (20, 0, 10)])])
def test_the_form_spreads_evenly_or_uses_the_spacing(window, monkeypatch, even, expected):
    monkeypatch.setattr(pattern_actions, "ask_path", lambda parent: {
        "count": 3, "even": even, "spacing": 10.0, "follow": False})
    add_parts_and_path(window)
    window.do_path_pattern()
    assert middles(window.document.scene.shapes[2:]) == expected


def test_a_path_pattern_needs_parts_and_one_sketch(window, warnings, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_path", lambda parent: pytest.fail("no form without a path"))
    window.add_primitive("cube")
    window.do_path_pattern()
    assert window.statusBar().currentMessage() == window.PATH_HINT
    window.add_sketch(LINE, np.eye(4))
    window.add_sketch(CIRCLE, np.eye(4))
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_path_pattern()
    assert window.statusBar().currentMessage() == window.PATH_HINT
    window.document.scene.select([window.document.scene.shapes[1].id])
    window.do_path_pattern()
    assert window.statusBar().currentMessage() == window.PATH_HINT
    assert not warnings


def test_a_refused_path_pattern_changes_nothing(window, warnings):
    add_parts_and_path(window)
    steps = len(window.document._undo)
    assert not window.path_pattern_selected(5, 20.0)
    assert warnings and "60.0 mm long" in warnings[0]
    assert len(window.document._undo) == steps and len(window.document.scene.shapes) == 2


def test_path_patterned_parts_round_trip_through_a_project_file(tmp_path):
    box, guide = box_at(30.0), path(CIRCLE)
    shapes = [box, guide] + patterns.along_path([box], guide, 6, follow=True)
    file = tmp_path / "parts.mesh"
    save_project(Scene(shapes=shapes), file)
    loaded = load_project(file).shapes
    assert middles(loaded) == middles(shapes)
    assert [s.transform for s in loaded] == [pytest.approx(s.transform) for s in shapes]


def test_path_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Pattern Along a Path", pattern_actions.path_fields(),
                                        note=pattern_actions.PATH_NOTE))
    for text in dialog.labels():
        assert_plain(text)
