"""Combine (Expert mode): join, cut or keep the overlap, choosing the part to change."""

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
BOX = 8000.0
OVERLAP = 10 * 20 * 20  # a 20 mm box moved 10 mm across another overlaps half of it


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


def box(x=0.0, name="Box"):
    shape = new_primitive("cube", name=name)
    shape.transform[0, 3] = x
    return shape


# --- Combining ------------------------------------------------------------------------


@pytest.mark.parametrize("op, volume", [
    ("union", 2 * BOX - OVERLAP), ("difference", BOX - OVERLAP), ("intersection", OVERLAP),
])
def test_combine_joins_cuts_or_keeps_the_overlap_exactly(op, volume):
    target, tool = box(), box(10.0)
    group = modify.combine(target, [tool], op)
    assert shape_geometry(group).volume == pytest.approx(volume)
    assert group.kind == "group" and group.color == target.color
    assert [c["id"] for c in group.params["children"]] == [target.id, tool.id]


def test_the_part_to_change_is_the_one_cut_from_whatever_order():
    a, b = box(name="A"), box(10.0, name="B")
    group = modify.combine(b, [a], "difference")
    assert np.allclose(shape_geometry(group).bounds, [[10, -10, 0], [20, 10, 20]])
    assert group.name == "B (cut)"


def test_ungroup_gives_the_parts_back():
    target, tool = box(), box(10.0)
    restored = ops.ungroup(modify.combine(target, [tool], "difference"))
    assert [s.id for s in restored] == [target.id, tool.id]
    assert np.allclose(shape_geometry(restored[1]).bounds, shape_geometry(tool).bounds)


def test_kept_tools_are_copied_into_the_group_with_their_own_ids():
    target, tool = box(), box(10.0)
    group = modify.combine(target, [tool], "union", keep_tools=True)
    inside = group.params["children"]
    assert inside[0]["id"] == target.id and inside[1]["id"] != tool.id


@pytest.mark.parametrize("make, words", [
    (lambda: (box(), []), "at least one other part"),
    (lambda: (box(), [create.new_sketch(SQUARE, np.eye(4))]), "flat drawing"),
    (lambda: (box(), [box(100.0)]), "do not overlap"),
])
def test_combine_refuses_plainly(make, words):
    target, tools = make()
    op = "intersection" if words == "do not overlap" else "union"
    with pytest.raises(BuildError) as err:
        modify.combine(target, tools, op)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_cutting_everything_away_is_refused():
    big = box()
    big.params.update(width=50.0, depth=50.0, height=50.0)
    with pytest.raises(BuildError) as err:
        modify.combine(box(), [big], "difference")
    assert "nothing" in str(err.value)


# --- In the window --------------------------------------------------------------------


def _two_boxes(window, pick_second_first=False):
    window.add_primitive("cube")
    window.add_primitive("cube")
    scene = window.document.scene
    first, second = scene.shapes[-2:]
    second.transform[0, 3] = 10.0
    scene.select([second.id, first.id] if pick_second_first else [first.id, second.id])
    return first, second


def test_combining_is_one_undo_step(window):
    first, second = _two_boxes(window)
    steps = len(window.document._undo)
    assert window.combine_selected(op="difference")
    scene = window.document.scene
    assert len(window.document._undo) == steps + 1
    assert len(scene.shapes) == 1 and scene.selection == [scene.shapes[0].id]
    assert shape_geometry(scene.shapes[0]).volume == pytest.approx(BOX - OVERLAP)
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [first.id, second.id]


def test_the_first_part_picked_is_the_one_changed(window):
    first, second = _two_boxes(window, pick_second_first=True)
    window.combine_selected(op="difference")
    group = window.document.scene.shapes[0]
    assert group.params["children"][0]["id"] == second.id


def test_kept_parts_stay_in_the_scene(window):
    first, second = _two_boxes(window)
    window.combine_selected(first.id, "union", keep_tools=True)
    scene = window.document.scene
    assert [s.id for s in scene.shapes][:1] == [second.id] and len(scene.shapes) == 2


def test_a_refused_combine_changes_nothing(window, warnings):
    first, second = _two_boxes(window)
    second.transform[0, 3] = 100.0
    steps = len(window.document._undo)
    assert not window.combine_selected(op="intersection")
    assert warnings and len(window.document._undo) == steps
    assert len(window.document.scene.shapes) == 2


def test_combine_needs_two_parts_and_asks_which_to_change(window, monkeypatch):
    seen = {}
    monkeypatch.setattr(modify_actions, "ask_combine", lambda parent, parts: seen.update(
        parts=[p.id for p in parts]) or {"target": parts[1].id, "op": "difference", "keep_tools": False})
    window.add_sketch(SQUARE, np.eye(4))
    window.add_primitive("cube")
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_combine()
    assert not seen and window.statusBar().currentMessage() == window.COMBINE_HINT
    window.document.scene.remove([window.document.scene.shapes[1].id])
    first, second = _two_boxes(window)
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_combine()
    assert seen["parts"] == [first.id, second.id]
    group = window.document.scene.shapes[-1]
    assert group.params["children"][0]["id"] == second.id


def test_a_combined_part_round_trips_through_a_project_file(tmp_path):
    group = modify.combine(box(), [box(10.0)], "difference")
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(BOX - OVERLAP)
    assert [s.id for s in ops.ungroup(loaded)] == [c["id"] for c in group.params["children"]]


def test_combine_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Combine", modify_actions.combine_fields([box(), box()]),
                                        note=modify_actions.COMBINE_NOTE))
    for text in dialog.labels():
        assert_plain(text)
