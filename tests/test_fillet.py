"""Round an Edge (Expert mode's Fillet): the edge next to a click rounded off or filled in."""

import math

import numpy as np
import pytest

from mesh import create, edges, modify, modify_actions, ops
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from mesh.solids import m3, to_manifold
from test_plain_language import assert_plain

SQUARE = [{"type": "rectangle", "corner": [0, 0], "width": 10, "height": 10}]
L_SHAPE = [
    {"type": "line", "start": [0, 0], "end": [20, 0]},
    {"type": "line", "start": [20, 0], "end": [20, 5]},
    {"type": "line", "start": [20, 5], "end": [10, 5]},
    {"type": "line", "start": [10, 5], "end": [10, 15]},
    {"type": "line", "start": [10, 15], "end": [0, 15]},
    {"type": "line", "start": [0, 15], "end": [0, 0]},
]


def corner_area(radius):
    """What a round of `radius` takes off a square corner: the arc is 16
    straight pieces, as a circle of 64 has in a quarter turn."""
    return radius**2 - 16 * 0.5 * radius**2 * math.sin(math.pi / 32)


ROUNDED_BOX = 8000.0 - 20 * corner_area(2.0)


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


def face_towards(shape, direction, near=None):
    """A triangle of `shape` facing `direction` (the one nearest `near`)."""
    tm = shape_geometry(shape)
    facing = tm.face_normals @ np.asarray(direction, dtype=np.float64) > 1.0 - 1e-9
    if near is None:
        return int(np.flatnonzero(facing)[0])
    distance = np.linalg.norm(tm.triangles_center - np.asarray(near), axis=1)
    return int(np.flatnonzero(facing)[np.argmin(distance[facing])])


def solid_at(shape, point) -> bool:
    """Whether there is material at `point` (a 0.2 mm cube around it)."""
    probe = m3.Manifold.cube((0.2, 0.2, 0.2), True).translate(tuple(point))
    return (to_manifold(shape_geometry(shape)) ^ probe).volume() > 1e-6


def l_shape():
    return create.make_extrude(create.new_sketch(L_SHAPE, np.eye(4)), 10.0)


# --- Rounding -------------------------------------------------------------------------


def test_a_box_edge_is_rounded_exactly_by_its_straight_pieces():
    box = new_primitive("cube")
    group = edges.fillet(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0)
    tm = shape_geometry(group)
    assert tm.volume == pytest.approx(ROUNDED_BOX)
    assert tm.is_volume and np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 20]])
    assert group.name == "Box (rounded)"


def test_the_edge_rounded_is_the_one_nearest_the_click():
    box = new_primitive("cube")
    group = edges.fillet(box, face_towards(box, (0, 0, 1)), (0, -9, 20), 2.0)
    assert not solid_at(group, (0, -9.8, 19.8))
    assert solid_at(group, (9.8, 0, 19.8)) and solid_at(group, (0, 9.8, 19.8))


def test_a_corner_stops_the_run_but_a_cylinders_rim_goes_all_the_way_round():
    box, cylinder = new_primitive("cube"), new_primitive("cylinder")
    run = edges.find_run(shape_geometry(box), face_towards(box, (0, 0, 1)), (10, 0, 20))
    assert len(run.vertices) == 2 and not run.closed and run.convex
    run = edges.find_run(shape_geometry(cylinder), face_towards(cylinder, (0, 0, 1)), (10, 0, 20))
    assert len(run.vertices) == 64 and run.closed
    group = edges.fillet(cylinder, face_towards(cylinder, (0, 0, 1)), (10, 0, 20), 2.0)
    assert shape_geometry(group).is_volume
    assert not solid_at(group, (0, 9.8, 19.8)) and not solid_at(group, (0, -9.8, 19.8))
    assert solid_at(group, (0, 9.8, 1.0))


def test_a_turned_box_is_rounded_the_same():
    [box] = modify.move_copy([new_primitive("cube")], axis="z", angle=30.0)
    click = box.transform[:3, 0] * 10.0 + (0, 0, 20)
    group = edges.fillet(box, face_towards(box, (0, 0, 1)), click, 2.0)
    assert shape_geometry(group).volume == pytest.approx(ROUNDED_BOX)


def test_an_inside_edge_is_filled_in_round():
    part = l_shape()
    step = face_towards(part, (0, 1, 0), near=(15, 5, 5))
    group = edges.fillet(part, step, (10.1, 5, 5), 2.0)
    added = shape_geometry(group).volume - shape_geometry(part).volume
    assert added == pytest.approx(10 * corner_area(2.0))
    assert not ops.ungroup(group)[1].is_hole


def test_the_next_edge_runs_on_round_the_first_rounding():
    box = new_primitive("cube")
    once = edges.fillet(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0)
    top = face_towards(once, (0, 0, 1))
    run = edges.find_run(shape_geometry(once), top, (0, -10, 20))
    assert len(run.vertices) == 19  # along the top, round the first rounding, down the side
    twice = edges.fillet(once, top, (0, -10, 20), 1.0)
    assert shape_geometry(twice).is_volume
    assert not solid_at(twice, (10 - 0.1, -10 + 0.1, 10))  # the upright edge it ran on into
    with pytest.raises(BuildError) as err:
        edges.fillet(once, top, (0, -10, 20), 2.0)
    assert "how tightly this edge bends" in str(err.value)


def test_ungroup_gives_the_part_and_the_piece_back():
    box = new_primitive("cube")
    restored = ops.ungroup(edges.fillet(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0))
    assert restored[0].params == box.params and restored[1].is_hole


# --- Refusals -------------------------------------------------------------------------


@pytest.mark.parametrize("radius, words", [
    (0.0, "more than 0"), (float("nan"), "more than 0"), (-1.0, "more than 0"),
    (25.0, "Try 20.0 mm or less"),
])
def test_fillet_refuses_sizes_it_cant_make(radius, words):
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        edges.fillet(box, face_towards(box, (0, 0, 1)), (10, 0, 20), radius)
    assert words in str(err.value)
    assert_plain(str(err.value))


@pytest.mark.parametrize("make, words", [
    (lambda: new_primitive("sphere"), "no sharp edge"),
    (lambda: new_primitive("rounded_box"), "no sharp edge"),
    (lambda: create.new_sketch(SQUARE, np.eye(4)), "flat drawing"),
    (lambda: (lambda b: (setattr(b, "is_hole", True), b)[1])(new_primitive("cube")), "a Hole"),
])
def test_fillet_needs_a_solid_part_with_an_edge(make, words):
    part = make()
    with pytest.raises(BuildError) as err:
        edges.fillet(part, 0, (0, 0, 20), 1.0)
    assert words in str(err.value)
    assert_plain(str(err.value))


# --- In the window --------------------------------------------------------------------


def test_clicking_next_to_an_edge_asks_for_the_radius_and_rounds_it_in_one_undo_step(
        window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(modify_actions, "ask_fillet", lambda parent: {"radius": 2.0})
    window.expert_actions["fillet"].trigger()
    assert window.tool == "fillet"
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (9, 0, 20))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()  # the form opens once the click is over
    group = window.document.scene.shapes[0]
    assert len(window.document._undo) == steps + 1
    assert shape_geometry(group).volume == pytest.approx(ROUNDED_BOX)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_a_click_where_there_is_no_edge_keeps_waiting_and_says_why(window):
    window.add_primitive("sphere")
    window.add_primitive("cube")
    window.do_toggle_hole()
    ball, hole = window.document.scene.shapes
    window.do_fillet()
    for shape in (ball, hole):
        window._on_surface_picked(shape.id, 0, (0, 0, 20))
        assert window.tool == "fillet"
    message = window.statusBar().currentMessage()
    assert "a Hole" in message and message.endswith(window.TOOL_PROMPTS["fillet"])


def test_fillet_needs_a_part(window):
    window.do_fillet()
    assert window.tool is None
    assert window.statusBar().currentMessage() == window.PARTS_FIRST


def test_a_refused_fillet_changes_nothing(window, warnings):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert not window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10, 0, 20), 30.0)
    assert warnings and len(window.document._undo) == steps


def test_a_rounded_part_round_trips_through_a_project_file(tmp_path):
    part = new_primitive("cylinder")
    group = edges.fillet(part, face_towards(part, (0, 0, 1)), (10, 0, 20), 2.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(group).volume)
    assert ops.ungroup(loaded)[0].params == part.params


def test_fillet_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Round an Edge", modify_actions.fillet_fields(),
                                        note=modify_actions.FILLET_NOTE))
    for text in dialog.labels():
        assert_plain(text)


# --- Several edges in one go ----------------------------------------------------------

# Where two rounds made in one go cross at a corner of a box, what both
# would take is taken once: (16 - 4 pi - 8/3) mm^3 for a true circle's
# round of 2 mm (the 16 straight pieces make it a little more).
CROSSING = 16 - 4 * math.pi - 8 / 3


def test_every_edge_round_a_face_is_rounded_in_one_go():
    box, cylinder = new_primitive("cube"), new_primitive("cylinder")
    top = face_towards(box, (0, 0, 1))
    assert len(edges.face_runs(shape_geometry(box), top)) == 4
    assert len(edges.face_runs(shape_geometry(cylinder), face_towards(cylinder, (0, 0, 1)))) == 1
    group = edges.fillet(box, top, (10, 0, 20), 2.0, whole_face=True)
    tm = shape_geometry(group)
    assert tm.is_volume
    assert tm.volume == pytest.approx(8000.0 - 80 * corner_area(2.0) + 4 * CROSSING, abs=0.1)
    assert len(ops.ungroup(group)) == 5  # the part and a piece for each edge
    assert not solid_at(group, (9.8, 9.8, 19.8))  # the corner, where two rounds cross
    assert solid_at(group, (9.9, 9.9, 10.0))  # the upright edges are left sharp


def test_more_clicks_round_more_edges_and_an_edge_picked_twice_is_rounded_once():
    box = new_primitive("cube")
    top, side = face_towards(box, (0, 0, 1)), face_towards(box, (1, 0, 0))
    group = edges.fillet(box, top, (10, 0, 20), 2.0, more=[[top, (0, -10, 20)], [top, (9, 1, 20)]])
    assert len(ops.ungroup(group)) == 3
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 40 * corner_area(2.0) + CROSSING, abs=0.05)
    three = edges.fillet(box, top, (10, 0, 20), 2.0, more=[[side, (10, 0, 1)], [side, (10, 9.5, 10)]])
    assert shape_geometry(three).is_volume and len(ops.ungroup(three)) == 4
    assert not solid_at(three, (9.9, 9.9, 10.0)) and not solid_at(three, (9.8, 0.0, 0.2))


def test_a_face_with_inside_and_outside_edges_is_rounded_all_round():
    part = l_shape()
    step = face_towards(part, (0, 1, 0), near=(15, 5, 5))
    assert [run.convex for run in edges.face_runs(shape_geometry(part), step)].count(False) == 1
    group = edges.fillet(part, step, (10.1, 5, 5), 1.0, whole_face=True)
    assert shape_geometry(group).is_volume
    assert [child.is_hole for child in ops.ungroup(group)[1:]].count(False) == 1


def test_a_further_click_off_the_part_is_refused():
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        edges.fillet(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, more=[[10**6, (0, 0, 0)]])
    assert_plain(str(err.value))


def test_rounding_more_edges_picks_them_click_by_click_then_rounds_them_in_one_undo_step(
        window, monkeypatch, qapp):
    window.add_primitive("cube")
    window.add_primitive("sphere")
    box, ball = window.document.scene.shapes
    top, side = face_towards(box, (0, 0, 1)), face_towards(box, (1, 0, 0))
    monkeypatch.setattr(modify_actions, "ask_fillet", lambda parent: {"radius": 2.0, "edges": "more"})
    steps = len(window.document._undo)
    window.do_fillet()
    window._on_surface_picked(box.id, top, (10, 0, 20))
    qapp.processEvents()  # the form opens once the click is over
    assert window.tool == "fillet_more" and window.viewport.marked_actor is not None
    assert window.statusBar().currentMessage().startswith("Picked: 1.")
    window._on_surface_picked(box.id, top, (0, -10, 20))
    window._on_surface_picked(box.id, side, (10, 0, 1))
    assert window.statusBar().currentMessage().startswith("Picked: 3.")
    window._on_surface_picked(box.id, side, (10, 5, 0.5))  # the same edge again: left out
    assert window.statusBar().currentMessage().startswith("Picked: 2.")
    window._on_surface_picked(ball.id, 0, (0, 0, 20))
    assert window.statusBar().currentMessage() == window.SAME_PART.format(
        prompt=window.TOOL_PROMPTS["fillet_more"])
    assert len(window.document._undo) == steps
    window.expert_actions["fillet"].trigger()  # chosen again: round them all
    assert window.tool is None and window.viewport.marked_actor is None
    assert len(window.document._undo) == steps + 1
    [group] = [s for s in window.document.scene.shapes if s.name == "Box (rounded)"]
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 40 * corner_area(2.0) + CROSSING, abs=0.05)
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [box.id, ball.id]


def test_rounding_every_edge_round_a_face_from_the_form(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(modify_actions, "ask_fillet", lambda parent: {"radius": 2.0, "edges": "face"})
    steps = len(window.document._undo)
    window.do_fillet()
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (9, 0, 20))
    qapp.processEvents()
    assert window.tool is None and len(window.document._undo) == steps + 1
    group = window.document.scene.shapes[0]
    assert len(ops.ungroup(group)) == 5
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_turning_expert_mode_off_stops_picking_and_changes_nothing(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(modify_actions, "ask_fillet", lambda parent: {"radius": 2.0, "edges": "more"})
    monkeypatch.setattr(window.settings, "save", lambda: True)
    steps = len(window.document._undo)
    window.do_fillet()
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (10, 0, 20))
    qapp.processEvents()
    assert window.tool == "fillet_more"
    window.set_expert_mode(False)
    assert window.tool is None and window.viewport.marked_actor is None
    assert len(window.document._undo) == steps and window.document.scene.shapes[0].id == box.id


def test_several_rounded_edges_round_trip_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    group = edges.fillet(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, whole_face=True)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(group).volume)
    assert len(ops.ungroup(loaded)) == 5


def test_picking_more_edges_is_plain_language(window):
    for text in (window.TOOL_PROMPTS["fillet_more"], window.TOOL_PROMPTS["chamfer_more"],
                 window.PICKED, window.SAME_PART, window.NOTHING_PICKED, modify_actions.FILLET_NOTE):
        assert_plain(text)
    for _key, label in modify_actions.edge_choices("Round an Edge"):
        assert_plain(label)
