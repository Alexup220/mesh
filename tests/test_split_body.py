"""Split Body (Expert mode): a part cut in two by a sketch's plane or another part."""

import numpy as np
import pytest

from mesh import create, modify, modify_actions, ops, sketch
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


def box(x=0.0):
    shape = new_primitive("cube")
    shape.transform[0, 3] = x
    return shape


def sketch_on(normal, point):
    return create.new_sketch(SQUARE, sketch.plane_frame(normal, point))


# --- By a sketch's plane ----------------------------------------------------------------


def test_a_flat_sketch_cuts_a_part_across_where_it_stands():
    first, second = modify.split_body(box(), sketch_on((0, 0, 1), (0, 0, 5)))
    assert np.allclose(shape_geometry(first).bounds, [[-10, -10, 5], [10, 10, 20]])
    assert np.allclose(shape_geometry(second).bounds, [[-10, -10, 0], [10, 10, 5]])


def test_a_sloping_sketch_plane_cuts_exactly_along_it():
    pieces = modify.split_body(box(), sketch_on((1, 1, 0), (3, 0, 0)))
    volumes = [shape_geometry(p).volume for p in pieces]
    assert volumes == pytest.approx([0.5 * 17 * 17 * 20, 8000 - 0.5 * 17 * 17 * 20])
    for piece in pieces:
        assert shape_geometry(piece).is_volume


def test_each_piece_ungroups_to_the_part_and_what_was_cut_away():
    part = box(30.0)
    first, second = modify.split_body(part, sketch_on((0, 0, 1), (0, 0, 5)))
    restored = ops.ungroup(first)
    assert restored[0].params == part.params and restored[1].is_hole
    assert np.allclose(shape_geometry(restored[0]).bounds, shape_geometry(part).bounds)
    ids = {c["id"] for g in (first, second) for c in g.params["children"]}
    assert len(ids) == 4 and part.id not in ids


def test_a_plane_that_misses_the_part_is_refused():
    with pytest.raises(BuildError) as err:
        modify.split_body(box(), sketch_on((0, 0, 1), (0, 0, 25)))
    assert "misses" in str(err.value)
    assert_plain(str(err.value))


# --- By another part --------------------------------------------------------------------


def test_another_part_splits_it_into_inside_and_outside_pieces():
    part, tool = box(), new_primitive("cylinder")
    tool.transform[0, 3] = 10.0
    inside, outside = modify.split_body(part, tool)
    half_cylinder = shape_geometry(tool).volume / 2.0
    assert shape_geometry(inside).volume == pytest.approx(half_cylinder, rel=1e-6)
    assert shape_geometry(outside).volume == pytest.approx(8000 - half_cylinder, rel=1e-6)
    assert inside.name == "Box (inside Cylinder)" and outside.name == "Box (outside Cylinder)"


def test_a_fitted_hole_used_to_split_cuts_at_its_exact_size():
    part, tool = box(), new_primitive("cylinder")
    tool.transform[0, 3] = 10.0
    tool.is_hole, tool.fit = True, "loose"
    inside, outside = modify.split_body(part, tool, {"loose": 0.4})
    total = shape_geometry(inside).volume + shape_geometry(outside).volume
    assert total == pytest.approx(8000.0, rel=1e-6)


@pytest.mark.parametrize("tool_x, words", [(100.0, "doesn't overlap"), (None, "covers all")])
def test_a_part_that_misses_or_covers_it_is_refused(tool_x, words):
    tool = box(tool_x or 0.0)
    if tool_x is None:
        tool.params.update(width=50.0, depth=50.0, height=50.0)
        tool.transform[2, 3] = -5.0
    with pytest.raises(BuildError) as err:
        modify.split_body(box(), tool)
    assert words in str(err.value)
    assert_plain(str(err.value))


@pytest.mark.parametrize("make, words", [
    (lambda: (sketch_on((0, 0, 1), (0, 0, 5)), box()), "flat drawing"),
    (lambda: (box(), None), "the sketch or part to split it with"),
])
def test_split_body_needs_a_solid_part_and_something_else(make, words):
    part, tool = make()
    with pytest.raises(BuildError) as err:
        modify.split_body(part, tool or part)
    assert words in str(err.value)


def test_a_hole_is_not_split():
    part = box()
    part.is_hole = True
    with pytest.raises(BuildError) as err:
        modify.split_body(part, sketch_on((0, 0, 1), (0, 0, 5)))
    assert "This one is a Hole" in str(err.value)


# --- In the window --------------------------------------------------------------------


def test_splitting_by_a_sketch_keeps_the_sketch_in_one_undo_step(window):
    window.add_primitive("cube")
    window.add_sketch(SQUARE, sketch.plane_frame((0, 0, 1), (0, 0, 5)))
    scene = window.document.scene
    part, guide = scene.shapes
    scene.select([guide.id, part.id])
    steps = len(window.document._undo)
    window.do_split_body()  # a sketch needs no questions
    assert len(window.document._undo) == steps + 1
    assert scene.shapes[0] is guide and len(scene.shapes) == 3
    assert scene.selection == [s.id for s in scene.shapes[1:]]
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [part.id, guide.id]


def test_splitting_by_a_part_asks_which_to_split(window, monkeypatch):
    window.add_primitive("cube")
    window.add_primitive("cylinder")
    scene = window.document.scene
    part, tool = scene.shapes
    tool.transform[0, 3] = 10.0
    scene.select([part.id, tool.id])
    seen = {}
    monkeypatch.setattr(modify_actions, "ask_split_body", lambda parent, parts: seen.update(
        parts=[p.id for p in parts]) or {"part": part.id, "keep_tool": True})
    window.do_split_body()
    assert seen["parts"] == [part.id, tool.id]
    assert scene.shapes[0] is tool and len(scene.shapes) == 3


def test_the_part_used_to_split_goes_unless_kept(window):
    window.add_primitive("cube")
    window.add_primitive("cylinder")
    scene = window.document.scene
    part, tool = scene.shapes
    scene.select([part.id, tool.id])
    assert window.split_body_selected(part.id)
    assert tool.id not in {s.id for s in scene.shapes} and len(scene.shapes) == 2


def test_a_refused_split_changes_nothing(window, warnings):
    window.add_primitive("cube")
    window.add_sketch(SQUARE, sketch.plane_frame((0, 0, 1), (0, 0, 50)))
    scene = window.document.scene
    scene.select([s.id for s in scene.shapes])
    steps = len(window.document._undo)
    assert not window.split_body_selected()
    assert warnings and len(window.document._undo) == steps


@pytest.mark.parametrize("count", [1, 3])
def test_split_body_needs_two_things_selected(window, count):
    for _ in range(count):
        window.add_primitive("cube")
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_split_body()
    assert window.statusBar().currentMessage() == window.SPLIT_BODY_HINT


def test_split_pieces_round_trip_through_a_project_file(tmp_path):
    pieces = modify.split_body(box(), sketch_on((1, 0, 1), (0, 0, 10)))
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=pieces), path)
    for loaded, piece in zip(load_project(path).shapes, pieces):
        assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(piece).volume)


def test_split_body_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Split Body", modify_actions.split_body_fields([box()])))
    for text in dialog.labels():
        assert_plain(text)
