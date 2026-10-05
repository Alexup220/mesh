"""Pattern in Rows (Expert mode's Rectangular Pattern): copies in rows and columns."""

import numpy as np
import pytest

from mesh import construct, create, pattern_actions, patterns
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


def middles(shapes):
    return sorted(tuple(np.round(shape_geometry(s).bounds.mean(axis=0), 6)) for s in shapes)


def test_copies_fill_rows_and_columns_from_the_original():
    box = new_primitive("cube")
    copies = patterns.rectangular([box], 3, 30.0, "x", 2, -25.0, "y")
    assert middles(copies) == sorted([(30, 0, 10), (60, 0, 10), (0, -25, 10), (30, -25, 10), (60, -25, 10)])
    assert len({c.id for c in copies} | {box.id}) == 6
    assert all(c.params == box.params and c.name == box.name for c in copies)


def test_a_row_can_go_up():
    copies = patterns.rectangular([new_primitive("cube")], 3, 25.0, "z")
    assert middles(copies) == [(0, 0, 35), (0, 0, 60)]


def test_several_parts_are_copied_together_and_holes_stay_holes():
    box, hole = new_primitive("cube"), new_primitive("cylinder")
    hole.is_hole, hole.fit = True, "loose"
    copies = patterns.rectangular([box, hole], 2, 40.0)
    assert [c.is_hole for c in copies] == [False, True] and copies[1].fit == "loose"
    assert middles(copies) == [(40, 0, 10), (40, 0, 10)]


def test_sketches_are_left_out():
    box = new_primitive("cube")
    guide = create.new_sketch(SQUARE, np.eye(4))
    assert len(patterns.rectangular([box, guide], 2, 30.0)) == 1
    with pytest.raises(BuildError) as err:
        patterns.rectangular([guide], 2, 30.0)
    assert "Sketches are guides" in str(err.value)


@pytest.mark.parametrize("args, words", [
    ((1, 30.0), "at least 2"),
    ((3, 0.0), "other than 0"),
    ((3, 20000.0), "at most 10000"),
    ((3, 30.0, "x", 2, 30.0, "x"), "two different directions"),
    ((30, 30.0, "x", 30, 30.0, "y"), "too many copies"),
])
def test_rectangular_pattern_refuses_plainly(args, words):
    with pytest.raises(BuildError) as err:
        patterns.rectangular([new_primitive("cube")], *args)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_the_same_direction_twice_is_fine_with_one_row():
    assert len(patterns.rectangular([new_primitive("cube")], 3, 30.0, "x", 1, 0.0, "x")) == 2


def test_patterning_is_one_undo_step_and_selects_everything(window):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert window.rectangular_pattern_selected(2, 30.0, "x", 2, 30.0, "y")
    scene = window.document.scene
    assert len(scene.shapes) == 4 and len(window.document._undo) == steps + 1
    assert scene.selection[0] == box.id and len(scene.selection) == 4
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [box.id]


def test_the_form_fills_the_pattern(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_rectangular", lambda parent: {
        "count": 3, "spacing": 25.0, "axis": "y", "count2": 1, "spacing2": 30.0, "axis2": "x"})
    window.add_primitive("cube")
    window.do_rectangular_pattern()
    assert middles(window.document.scene.shapes) == [(0, 0, 10), (0, 25, 10), (0, 50, 10)]


def test_nothing_selected_or_only_a_sketch_says_what_to_do(window, warnings):
    window.do_rectangular_pattern()
    assert window.statusBar().currentMessage() == window.PATTERN_HINT
    window.add_sketch(SQUARE, np.eye(4))
    window.do_rectangular_pattern()
    assert window.statusBar().currentMessage() == window.PATTERN_HINT
    assert not warnings


def test_a_refused_pattern_changes_nothing(window, warnings):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.rectangular_pattern_selected(3, 0.0)
    assert warnings and len(window.document._undo) == steps and len(window.document.scene.shapes) == 1


def test_patterned_parts_round_trip_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    shapes = [box] + patterns.rectangular([box], 2, 30.0, "x", 2, 30.0, "z")
    path = tmp_path / "parts.mesh"
    save_project(Scene(shapes=shapes), path)
    assert middles(load_project(path).shapes) == middles(shapes)


def test_rectangular_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    for selected in (None, "Axis 1"):
        dialog = close_qt_widget(FormDialog(None, "Pattern in Rows", pattern_actions.rectangular_fields(selected),
                                            note=pattern_actions.RECTANGULAR_NOTE))
        for text in dialog.labels():
            assert_plain(text)
    assert_plain(pattern_actions.PatternActions.AXIS_FOR_ROWS)


# --- Both ways, the whole length, and leaving copies out --------------------------------


def test_both_ways_repeats_the_row_the_other_way_from_the_parts():
    copies = patterns.rectangular([new_primitive("cube")], 3, 30.0, "x", symmetric=True)
    assert middles(copies) == [(-60, 0, 10), (-30, 0, 10), (30, 0, 10), (60, 0, 10)]


def test_both_ways_in_rows_and_columns_fills_a_grid_round_the_parts():
    copies = patterns.rectangular([new_primitive("cube")], 2, 30.0, "x", 2, 25.0, "y", symmetric=True)
    expected = [(x, y, 10) for x in (-30, 0, 30) for y in (-25, 0, 25) if (x, y) != (0, 0)]
    assert middles(copies) == sorted(expected)


@pytest.mark.parametrize("symmetric, expected", [
    (False, [(30, 0, 10), (60, 0, 10), (90, 0, 10)]),
    (True, [(-90, 0, 10), (-60, 0, 10), (-30, 0, 10), (30, 0, 10), (60, 0, 10), (90, 0, 10)]),
])
def test_spacing_can_be_the_whole_length_from_the_parts_to_the_last_copy(symmetric, expected):
    copies = patterns.rectangular([new_primitive("cube")], 4, 90.0, "x", extent=True, symmetric=symmetric)
    assert middles(copies) == expected


def test_the_whole_length_applies_to_the_columns_too():
    copies = patterns.rectangular([new_primitive("cube")], 1, 10.0, "x", 3, -40.0, "y", extent=True)
    assert middles(copies) == [(0, -40, 10), (0, -20, 10)]


def test_copies_are_left_out_by_number_row_by_row():
    # 1 2 3 along the first row, 4 5 6 along the second.
    copies = patterns.rectangular([new_primitive("cube")], 3, 30.0, "x", 2, 30.0, "y", skip=[3, 5])
    assert middles(copies) == [(0, 30, 10), (30, 0, 10), (60, 30, 10)]


def test_both_ways_numbers_the_other_way_after():
    # 1 is the part, 2 and 3 go right, 4 and 5 go left.
    copies = patterns.rectangular([new_primitive("cube")], 3, 30.0, "x", symmetric=True, skip=[3, 4])
    assert middles(copies) == [(-60, 0, 10), (30, 0, 10)]


def test_copy_numbers_are_read_from_typed_text():
    assert patterns.copy_numbers("3, 5  7-9;12") == [3, 5, 7, 8, 9, 12]
    assert patterns.copy_numbers("") == [] and patterns.copy_numbers(None) == []
    assert patterns.copy_numbers([5, 3, 5]) == [3, 5]
    for bad in ("three", "3-", "9-7", "1.5"):
        with pytest.raises(BuildError) as err:
            patterns.copy_numbers(bad)
        assert "such as 3, 5 or 7-9" in str(err.value)
        assert_plain(str(err.value))


@pytest.mark.parametrize("skip, words", [
    ([1], "Number 1 is the parts"), ([7], "no number 7"), ([2, 3], "every copy"),
])
def test_leaving_copies_out_is_checked(skip, words):
    with pytest.raises(BuildError) as err:
        patterns.rectangular([new_primitive("cube")], 3, 30.0, skip=skip)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_rows_go_along_any_direction_given_as_numbers():
    copies = patterns.rectangular([new_primitive("cube")], 3, 10.0, (3.0, 4.0, 0.0))
    assert middles(copies) == [(6, 8, 10), (12, 16, 10)]
    with pytest.raises(BuildError) as err:
        patterns.rectangular([new_primitive("cube")], 2, 10.0, (1.0, 1.0, 0.0), 2, 10.0, (-2.0, -2.0, 0.0))
    assert "two different directions" in str(err.value)


def add_axis(window, a, b):
    guide = construct.axis_through_points(a, b, "Axis 1")
    window.document.scene.add(guide)
    window.sync()
    return guide


def test_rows_go_along_a_construction_axis_selected_with_the_parts(window):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    guide = add_axis(window, (0, 0, 0), (0, 0, 5))
    window.document.scene.select([box.id, guide.id])
    steps = len(window.document._undo)
    assert window.rectangular_pattern_selected(3, 25.0, "selected", symmetric=True, skip="2")
    shapes = window.document.scene.shapes
    assert middles(shapes[2:]) == [(0, 0, -40), (0, 0, -15), (0, 0, 60)]
    assert len(window.document._undo) == steps + 1


def test_rows_along_an_axis_need_one_selected(window, warnings):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.rectangular_pattern_selected(3, 25.0, "x", 2, 10.0, "selected")
    assert window.statusBar().currentMessage() == window.AXIS_FOR_ROWS
    assert len(window.document._undo) == steps and not warnings


def test_the_form_offers_the_selected_axis(window, monkeypatch):
    seen = {}

    def ask(parent, selected=None):
        seen["selected"] = selected
        return {"count": 2, "spacing": 30.0, "axis": "selected", "count2": 1, "spacing2": 30.0,
                "axis2": "y", "extent": False, "symmetric": False, "skip": ""}

    monkeypatch.setattr(pattern_actions, "ask_rectangular", ask)
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    guide = add_axis(window, (0, 0, 0), (0, 1, 0))
    window.document.scene.select([box.id, guide.id])
    window.do_rectangular_pattern()
    assert seen["selected"] == "Axis 1"
    assert middles(window.document.scene.shapes[2:]) == [(0, 30, 10)]
    fields = pattern_actions.rectangular_fields("Axis 1")
    assert fields[2][3]["choices"][0] == ("selected", "Along the selected Axis 1")


def test_typed_numbers_that_cannot_be_read_change_nothing(window, warnings):
    window.add_primitive("cube")
    steps = len(window.document._undo)
    assert not window.rectangular_pattern_selected(3, 30.0, skip="two")
    assert warnings and "such as 3, 5" in warnings[0]
    assert len(window.document._undo) == steps and len(window.document.scene.shapes) == 1


def test_both_ways_and_left_out_copies_round_trip_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    shapes = [box] + patterns.rectangular([box], 3, 30.0, "x", 2, 20.0, "z", extent=True,
                                          symmetric=True, skip=[4, 9])
    path = tmp_path / "parts.mesh"
    save_project(Scene(shapes=shapes), path)
    assert middles(load_project(path).shapes) == middles(shapes)
    assert len(shapes) == 1 + 5 * 3 - 1 - 2
