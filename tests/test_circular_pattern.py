"""Pattern Around a Line (Expert mode's Circular Pattern): copies turned round any line."""

import math

import numpy as np
import pytest

from mesh import pattern_actions, patterns
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain


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


def middle(shape):
    return np.round(shape_geometry(shape).bounds.mean(axis=0), 6).tolist()


def test_copies_go_evenly_round_an_upright_line_and_the_part_stays():
    box = new_primitive("cube")
    copies = patterns.circular([box], 4, "z", (-30.0, 0.0, 0.0))
    assert [middle(c) for c in copies] == [[-30, 30, 10], [-60, 0, 10], [-30, -30, 10]]
    assert middle(box) == [0, 0, 10]
    turns = [math.degrees(math.atan2(c.transform[1, 0], c.transform[0, 0])) for c in copies]
    assert turns == pytest.approx([90.0, 180.0, -90.0])


def test_a_part_angle_puts_the_first_and_last_that_far_apart():
    copies = patterns.circular([new_primitive("cube")], 3, "z", (-30.0, 0.0, 0.0), angle=90.0)
    turned = [-30 + 30 * math.cos(math.radians(45)), 30 * math.sin(math.radians(45)), 10]
    assert [middle(c) for c in copies] == [pytest.approx(turned, abs=1e-5), [-30, 30, 10]]


@pytest.mark.parametrize("axis", ["x", "y"])
def test_copies_can_go_round_a_lying_line(axis):
    # Half a turn round a line lying on the floor puts the box under the floor.
    [copy] = patterns.circular([new_primitive("cube")], 2, axis, (0.0, 0.0, 0.0))
    assert middle(copy) == pytest.approx([0, 0, -10])


def test_several_parts_turn_together():
    a, b = new_primitive("cube"), new_primitive("sphere")
    b.transform[0, 3] = 30.0
    copies = patterns.circular([a, b], 2, "z", (0.0, 0.0, 0.0))
    assert [middle(c) for c in copies] == [[0, 0, 10], [-30, 0, 10]]


@pytest.mark.parametrize("count, angle, words", [
    (1, 360.0, "at least 2"), (6, 0.0, "more than 0"), (6, 400.0, "at most 360"),
    (6, float("nan"), "more than 0"), (600, 360.0, "too many copies"),
])
def test_circular_pattern_refuses_plainly(count, angle, words):
    with pytest.raises(BuildError) as err:
        patterns.circular([new_primitive("cube")], count, "z", (0, 0, 0), angle)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_the_form_starts_30_mm_left_of_the_parts_as_repeat_in_a_circle_does(window, monkeypatch):
    seen = {}

    def ask(parent, centre):
        seen["centre"] = [round(float(v), 6) for v in centre]
        return {"count": 4, "angle": 360.0, "axis": "z",
                "centre_x": centre[0], "centre_y": centre[1], "centre_z": centre[2]}

    monkeypatch.setattr(pattern_actions, "ask_circular", ask)
    window.add_primitive("cube")
    steps = len(window.document._undo)
    window.do_circular_pattern()
    assert seen["centre"] == [-30.0, 0.0, 10.0]
    assert len(window.document.scene.shapes) == 4 and len(window.document._undo) == steps + 1
    window.do_undo()
    assert len(window.document.scene.shapes) == 1


def test_a_refused_circular_pattern_changes_nothing(window, warnings):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.circular_pattern_selected(1)
    assert warnings and len(window.document._undo) == steps


def test_a_circular_pattern_round_trips_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    shapes = [box] + patterns.circular([box], 6, "z", (-30.0, 0.0, 0.0))
    path = tmp_path / "parts.mesh"
    save_project(Scene(shapes=shapes), path)
    for loaded, shape in zip(load_project(path).shapes, shapes):
        assert np.allclose(loaded.transform, shape.transform)


# --- Both ways, and leaving copies out ------------------------------------------------------


def test_both_ways_spreads_the_copies_evenly_either_side_of_the_part():
    copies = patterns.circular([new_primitive("cube")], 3, "z", (-30.0, 0.0, 0.0), angle=90.0,
                               symmetric=True)
    turns = [math.degrees(math.atan2(c.transform[1, 0], c.transform[0, 0])) for c in copies]
    assert turns == pytest.approx([45.0, 90.0, -45.0, -90.0])
    assert middle(copies[1]) == pytest.approx([-30, 30, 10]) and middle(copies[3]) == pytest.approx([-30, -30, 10])


def test_both_ways_needs_less_than_half_a_turn_each_way():
    with pytest.raises(BuildError) as err:
        patterns.circular([new_primitive("cube")], 3, "z", (0, 0, 0), 180.0, symmetric=True)
    assert "less than 180" in str(err.value)
    assert_plain(str(err.value))


def test_copies_round_a_line_are_left_out_by_number():
    copies = patterns.circular([new_primitive("cube")], 4, "z", (-30.0, 0.0, 0.0), skip=[3])
    assert [middle(c) for c in copies] == [[-30, 30, 10], [-30, -30, 10]]
    copies = patterns.circular([new_primitive("cube")], 2, "z", (-30.0, 0.0, 0.0), 60.0,
                               symmetric=True, skip=[2])
    assert len(copies) == 1 and middle(copies[0])[1] < 0  # only the one turned the other way


def test_round_an_axis_both_ways_too():
    copies = patterns.circular_about([new_primitive("cube")], 2, (-30.0, 0.0, 0.0), (0.0, 0.0, 2.0),
                                     90.0, symmetric=True)
    assert [middle(c) for c in copies] == [pytest.approx([-30, 30, 10]), pytest.approx([-30, -30, 10])]


def test_the_form_patterns_both_ways_and_leaves_copies_out(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_circular", lambda parent, centre: {
        "count": 3, "angle": 60.0, "axis": "z", "centre_x": -30.0, "centre_y": 0.0, "centre_z": 0.0,
        "symmetric": True, "skip": "5"})
    window.add_primitive("cube")
    steps = len(window.document._undo)
    window.do_circular_pattern()
    assert len(window.document.scene.shapes) == 4 and len(window.document._undo) == steps + 1
    window.do_undo()
    assert len(window.document.scene.shapes) == 1


def test_both_ways_round_a_line_round_trips_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    shapes = [box] + patterns.circular([box], 3, "z", (-30.0, 0.0, 0.0), 120.0, symmetric=True, skip=[4])
    path = tmp_path / "parts.mesh"
    save_project(Scene(shapes=shapes), path)
    for loaded, shape in zip(load_project(path).shapes, shapes):
        assert np.allclose(loaded.transform, shape.transform)


def test_circular_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Pattern Around a Line", pattern_actions.circular_fields((0, 0, 0)),
                                        note=pattern_actions.CIRCULAR_NOTE))
    for text in dialog.labels():
        assert_plain(text)
    keys = [f[0] for f in pattern_actions.circular_axis_fields()]
    assert keys == ["count", "angle", "symmetric", "skip"]
