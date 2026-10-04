"""Push/Pull (Expert mode): a flat face moved straight out of a part or into it."""

import numpy as np
import pytest

from mesh import create, modify, modify_actions, ops, sketch
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

WASHER = [
    {"type": "circle", "centre": [0, 0], "diameter": 20},
    {"type": "circle", "centre": [0, 0], "diameter": 10},
]
L_SHAPE = [
    {"type": "line", "start": [0, 0], "end": [20, 0]},
    {"type": "line", "start": [20, 0], "end": [20, 5]},
    {"type": "line", "start": [20, 5], "end": [10, 5]},
    {"type": "line", "start": [10, 5], "end": [10, 15]},
    {"type": "line", "start": [10, 15], "end": [0, 15]},
    {"type": "line", "start": [0, 15], "end": [0, 0]},
]


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


def extrusion(entities, distance=10.0):
    return create.make_extrude(create.new_sketch(entities, np.eye(4)), distance)


# --- Moving faces ---------------------------------------------------------------------


@pytest.mark.parametrize("distance, top, volume", [(5.0, 25.0, 10000.0), (-5.0, 15.0, 6000.0)])
def test_a_box_top_pulled_out_or_pushed_in_moves_exactly(distance, top, volume):
    box = new_primitive("cube")
    group = modify.push_pull(box, face_towards(box, (0, 0, 1)), distance)
    tm = shape_geometry(group)
    assert np.allclose(tm.bounds, [[-10, -10, 0], [10, 10, top]])
    assert tm.volume == pytest.approx(volume)
    assert group.name == ("Box (pulled)" if distance > 0 else "Box (pushed)")


def test_a_turned_box_side_moves_along_the_way_it_faces():
    [box] = modify.move_copy([new_primitive("cube")], axis="z", angle=30.0)
    side = box.transform[:3, 0]
    group = modify.push_pull(box, face_towards(box, side), 4.0)
    assert shape_geometry(group).volume == pytest.approx(8000 + 20 * 20 * 4)


def test_a_face_with_a_hole_in_it_keeps_the_hole_when_pulled():
    washer = extrusion(WASHER)
    group = modify.push_pull(washer, face_towards(washer, (0, 0, 1)), 5.0)
    ring = sketch.profile(WASHER).area()
    assert shape_geometry(group).volume == pytest.approx(ring * 15.0)


def test_pushing_a_lower_step_in_leaves_the_rest_alone():
    part = extrusion(L_SHAPE)  # on the workplane: the L's step faces +Y at y = 5
    step = face_towards(part, (0, 1, 0), near=(15, 5, 5))
    group = modify.push_pull(part, step, -2.0)
    assert shape_geometry(group).volume == pytest.approx((20 * 5 + 10 * 10) * 10 - 10 * 2 * 10)


def test_ungroup_gives_the_part_and_the_piece_back():
    box = new_primitive("cube")
    restored = ops.ungroup(modify.push_pull(box, face_towards(box, (0, 0, 1)), -3.0))
    assert restored[0].params == box.params and restored[1].is_hole


@pytest.mark.parametrize("distance, words", [
    (0.0, "other than 0"), (float("nan"), "other than 0"), (20000.0, "at most 10000 mm"),
    (-25.0, "leave nothing"),
])
def test_push_pull_refuses_plainly(distance, words):
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        modify.push_pull(box, face_towards(box, (0, 0, 1)), distance)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_push_pull_needs_a_solid_part():
    hole = new_primitive("cube")
    hole.is_hole = True
    with pytest.raises(BuildError) as err:
        modify.push_pull(hole, 0, 5.0)
    assert "This one is a Hole" in str(err.value)
    with pytest.raises(BuildError):
        modify.push_pull(create.new_sketch(WASHER, np.eye(4)), 0, 5.0)


# --- In the window --------------------------------------------------------------------


def test_clicking_a_face_asks_how_far_and_moves_it_in_one_undo_step(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(modify_actions, "ask_push_pull", lambda parent: {"distance": 6.0})
    window.expert_actions["push_pull"].trigger()
    assert window.tool == "push_pull"
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (0, 0, 20))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()
    group = window.document.scene.shapes[0]
    assert len(window.document._undo) == steps + 1
    assert shape_geometry(group).bounds[1][2] == pytest.approx(26.0)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_push_pull_has_a_shortcut():
    from mesh import expert

    assert next(t for t in expert.TOOLS if t.key == "push_pull").shortcut == "Q"


def test_a_refused_push_changes_nothing(window, warnings):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert not window.push_pull_face(box.id, face_towards(box, (0, 0, 1)), -30.0)
    assert warnings and len(window.document._undo) == steps


def test_a_click_on_a_hole_keeps_waiting(window):
    window.add_primitive("cube")
    window.do_toggle_hole()
    box = window.document.scene.shapes[0]
    window.do_push_pull()
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (0, 0, 20))
    assert window.tool == "push_pull"


def test_a_pushed_part_round_trips_through_a_project_file(tmp_path):
    washer = extrusion(WASHER)
    group = modify.push_pull(washer, face_towards(washer, (0, 0, 1)), -4.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(group).volume)
    assert ops.ungroup(loaded)[0].params == washer.params


def test_push_pull_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Push/Pull", modify_actions.push_pull_fields(),
                                        note=modify_actions.PUSH_PULL_NOTE))
    for text in dialog.labels():
        assert_plain(text)
