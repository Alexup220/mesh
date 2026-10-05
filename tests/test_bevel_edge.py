"""Bevel an Edge (Expert mode's Chamfer): the edge next to a click cut off or filled in flat."""

import numpy as np
import pytest

from mesh import create, edges, modify_actions, ops
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
BEVELLED_BOX = 8000.0 - 20 * 0.5 * 2.0 * 2.0


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


# --- Bevelling ------------------------------------------------------------------------


def test_a_box_edge_is_bevelled_exactly():
    box = new_primitive("cube")
    group = edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0)
    tm = shape_geometry(group)
    assert tm.volume == pytest.approx(BEVELLED_BOX)
    assert tm.is_volume and np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, 20]])
    assert solid_at(group, (7.9, 0, 19.9)) and not solid_at(group, (9.9, 0, 19.9))
    assert group.name == "Box (chamfered)"


def test_a_cylinders_rim_is_bevelled_all_the_way_round():
    cylinder = new_primitive("cylinder")
    group = edges.chamfer(cylinder, face_towards(cylinder, (0, 0, 1)), (10, 0, 20), 2.0)
    taken = shape_geometry(cylinder).volume - shape_geometry(group).volume
    # A 2 by 2 triangle carried round at its centre, 10 - 2/3 mm out: about 117.3.
    assert taken == pytest.approx(2.0 * np.pi * (10 - 2 / 3) * 2.0, rel=0.01)
    assert not solid_at(group, (0, 9.9, 19.9)) and not solid_at(group, (-9.9, 0, 19.9))


def test_an_inside_edge_is_filled_in_flat():
    part = create.make_extrude(create.new_sketch(L_SHAPE, np.eye(4)), 10.0)
    step = face_towards(part, (0, 1, 0), near=(15, 5, 5))
    group = edges.chamfer(part, step, (10.1, 5, 5), 2.0)
    added = shape_geometry(group).volume - shape_geometry(part).volume
    assert added == pytest.approx(10 * 0.5 * 2.0 * 2.0)
    assert not ops.ungroup(group)[1].is_hole


def test_ungroup_gives_the_part_and_the_piece_back():
    box = new_primitive("cube")
    restored = ops.ungroup(edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0))
    assert restored[0].params == box.params and restored[1].is_hole


@pytest.mark.parametrize("distance, words", [
    (0.0, "more than 0"), (float("nan"), "more than 0"), (25.0, "Try 20.0 mm or less"),
])
def test_chamfer_refuses_sizes_it_cant_make(distance, words):
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), distance)
    assert words in str(err.value)
    assert_plain(str(err.value))


@pytest.mark.parametrize("make, words", [
    (lambda: new_primitive("sphere"), "no sharp edge"),
    (lambda: create.new_sketch(SQUARE, np.eye(4)), "flat drawing"),
    (lambda: (lambda b: (setattr(b, "is_hole", True), b)[1])(new_primitive("cube")), "a Hole"),
])
def test_chamfer_needs_a_solid_part_with_an_edge(make, words):
    with pytest.raises(BuildError) as err:
        edges.chamfer(make(), 0, (0, 0, 20), 1.0)
    assert words in str(err.value)


# --- In the window --------------------------------------------------------------------


def test_clicking_next_to_an_edge_asks_how_far_and_bevels_it_in_one_undo_step(
        window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(modify_actions, "ask_chamfer", lambda parent: {"distance": 2.0})
    window.expert_actions["chamfer"].trigger()
    assert window.tool == "chamfer"
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (9, 0, 20))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()  # the form opens once the click is over
    group = window.document.scene.shapes[0]
    assert len(window.document._undo) == steps + 1
    assert shape_geometry(group).volume == pytest.approx(BEVELLED_BOX)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_a_click_on_a_ball_keeps_waiting(window):
    window.add_primitive("sphere")
    window.do_chamfer()
    window._on_surface_picked(window.document.scene.shapes[0].id, 0, (0, 0, 20))
    assert window.tool == "chamfer"
    assert "no sharp edge" in window.statusBar().currentMessage()


def test_a_refused_chamfer_changes_nothing(window, warnings):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert not window.bevel_edge(box.id, face_towards(box, (0, 0, 1)), (10, 0, 20), 30.0)
    assert warnings and len(window.document._undo) == steps


def test_a_bevelled_part_round_trips_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    group = edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(BEVELLED_BOX)
    assert ops.ungroup(loaded)[0].params == box.params


# --- Set back differently on each face, or by an angle ---------------------------------------


def test_a_bevel_set_back_differently_on_each_face_starts_on_the_face_clicked():
    box = new_primitive("cube")
    group = edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, distance2=4.0)
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 20 * 0.5 * 2.0 * 4.0)
    # 2 mm in along the top, 4 mm down the side.
    assert solid_at(group, (7.9, 0, 19.9)) and not solid_at(group, (9.9, 0, 17.0))
    assert solid_at(group, (9.9, 0, 15.8))
    side = edges.chamfer(box, face_towards(box, (1, 0, 0)), (10, 0, 20), 2.0, distance2=4.0)
    # Clicked on the side instead: 2 mm down it, 4 mm in along the top.
    assert not solid_at(side, (7.0, 0, 19.9)) and solid_at(side, (9.9, 0, 17.0))


@pytest.mark.parametrize("angle, other", [(45.0, 2.0), (60.0, 2.0 * np.sqrt(3.0)), (30.0, 2.0 / np.sqrt(3.0))])
def test_a_bevel_given_by_a_distance_and_an_angle_from_the_face_clicked(angle, other):
    box = new_primitive("cube")
    group = edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, angle=angle)
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 20 * 0.5 * 2.0 * other, rel=1e-6)
    assert solid_at(group, (7.9, 0, 19.9)) and not solid_at(group, (9.9, 0, 20 - 0.5 * other))


def test_an_angled_bevel_round_a_cylinders_rim():
    cylinder = new_primitive("cylinder")
    group = edges.chamfer(cylinder, face_towards(cylinder, (0, 0, 1)), (10, 0, 20), 1.0, angle=60.0)
    taken = shape_geometry(cylinder).volume - shape_geometry(group).volume
    # A 1 by 1.73 triangle carried round at its centre, 10 - 1/3 mm out.
    assert taken == pytest.approx(2.0 * np.pi * (10 - 1 / 3) * 0.5 * np.sqrt(3.0), rel=0.01)


def test_an_uneven_inside_bevel_fills_in_flat():
    part = create.make_extrude(create.new_sketch(L_SHAPE, np.eye(4)), 10.0)
    step = face_towards(part, (0, 1, 0), near=(15, 5, 5))
    group = edges.chamfer(part, step, (10.1, 5, 5), 2.0, distance2=3.0)
    added = shape_geometry(group).volume - shape_geometry(part).volume
    assert added == pytest.approx(10 * 0.5 * 2.0 * 3.0)
    assert solid_at(group, (11.5, 5.15, 5)) and not solid_at(group, (12.2, 5.15, 5))  # 2 mm along the step


@pytest.mark.parametrize("kwargs, words", [
    ({"distance2": 0.0}, "more than 0"), ({"angle": 0.0}, "more than 0 and less than 180"),
    ({"angle": 90.0}, "too steep"), ({"distance2": 25.0}, "Try 1.6 mm or less along the face you clicked, and 20.0 mm along the other."),
    ({"angle": 85.0}, "along the face you clicked."),
])
def test_uneven_bevels_it_cant_make_are_refused(kwargs, words):
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, **kwargs)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_the_form_bevels_by_a_distance_and_an_angle_in_one_undo_step(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(modify_actions, "ask_chamfer", lambda parent: {
        "distance": 2.0, "how": "angle", "distance2": 9.0, "angle": 60.0})
    window.do_chamfer()
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (9, 0, 20))
    qapp.processEvents()
    group = window.document.scene.shapes[0]
    assert len(window.document._undo) == steps + 1
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 20 * 2.0 * np.sqrt(3.0), rel=1e-6)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_the_window_bevels_by_two_distances(window, warnings):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    top = face_towards(box, (0, 0, 1))
    assert window.bevel_edge(box.id, top, (10, 0, 20), 2.0, "two", 4.0)
    assert shape_geometry(window.document.scene.shapes[0]).volume == pytest.approx(8000.0 - 80.0)
    steps = len(window.document._undo)
    group = window.document.scene.shapes[0]
    assert not window.bevel_edge(group.id, face_towards(group, (0, 0, 1)), (0, -10, 20), 2.0, "angle", angle=95.0)
    assert warnings and len(window.document._undo) == steps


def test_an_uneven_bevel_round_trips_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    group = edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, angle=30.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(group).volume)
    assert ops.ungroup(loaded)[0].params == box.params


def test_chamfer_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Bevel an Edge", modify_actions.chamfer_fields(),
                                        note=modify_actions.CHAMFER_NOTE))
    for text in dialog.labels():
        assert_plain(text)


# --- Several edges in one go ----------------------------------------------------------


def test_every_edge_round_a_face_is_bevelled_in_one_go():
    box = new_primitive("cube")
    group = edges.chamfer(box, face_towards(box, (0, 0, 1)), (10, 0, 20), 2.0, whole_face=True)
    # Four 2 mm bevels, less the corners where two cross (8/3 mm^3 each, taken once).
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 4 * 20 * 2.0 + 4 * 8 / 3)
    assert len(ops.ungroup(group)) == 5


def test_more_edges_bevelled_unevenly_start_on_the_face_each_was_clicked_on():
    box = new_primitive("cube")
    top, side = face_towards(box, (0, 0, 1)), face_towards(box, (1, 0, 0))
    group = edges.chamfer(box, top, (0, -10, 20), 1.0, distance2=3.0, more=[[side, (10, 0, 1)]])
    assert len(ops.ungroup(group)) == 3
    assert shape_geometry(group).volume == pytest.approx(8000.0 - 2 * 20 * 1.5)
    assert not solid_at(group, (0, -9.9, 18.0))  # 1 mm across the top clicked, 3 mm down the front
    assert not solid_at(group, (8.5, 0, 0.2)) and solid_at(group, (9.9, 0, 1.5))  # 1 mm up the side


def test_finishing_with_nothing_picked_keeps_waiting_and_esc_changes_nothing(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    top = face_towards(box, (0, 0, 1))
    monkeypatch.setattr(modify_actions, "ask_chamfer",
                        lambda parent: {"distance": 1.0, "how": "equal", "edges": "more"})
    steps = len(window.document._undo)
    window.do_chamfer()
    window._on_surface_picked(box.id, top, (10, 0, 20))
    qapp.processEvents()
    assert window.tool == "chamfer_more"
    window._on_surface_picked(box.id, top, (9.5, 5, 20))  # the same edge again: left out
    assert window.statusBar().currentMessage().startswith("Picked: 0.")
    assert window.viewport.marked_actor is None
    window.do_chamfer()
    assert window.tool == "chamfer_more"
    assert window.statusBar().currentMessage() == window.NOTHING_PICKED.format(
        prompt=window.TOOL_PROMPTS["chamfer_more"])
    window.stop_tool()
    assert window.tool is None and len(window.document._undo) == steps


def test_bevelling_more_edges_in_one_undo_step(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    top = face_towards(box, (0, 0, 1))
    monkeypatch.setattr(modify_actions, "ask_chamfer",
                        lambda parent: {"distance": 2.0, "how": "equal", "edges": "more"})
    steps = len(window.document._undo)
    window.do_chamfer()
    window._on_surface_picked(box.id, top, (10, 0, 20))
    qapp.processEvents()
    window._on_surface_picked(box.id, top, (-10, 0, 20))
    window.do_chamfer()
    assert window.tool is None and len(window.document._undo) == steps + 1
    assert shape_geometry(window.document.scene.shapes[0]).volume == pytest.approx(8000.0 - 2 * 20 * 2.0)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id
