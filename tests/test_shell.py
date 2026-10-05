"""Shell (Expert mode): a part hollowed out with the clicked face left open."""

import numpy as np
import pytest

from mesh import create, modify, modify_actions, ops
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from mesh.solids import m3, to_manifold
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


def face_towards(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=np.float64)))


def solid_at(shape, point) -> bool:
    """Whether there is material at `point` (a 0.2 mm cube around it)."""
    probe = m3.Manifold.cube((0.2, 0.2, 0.2), True).translate(tuple(point))
    return (to_manifold(shape_geometry(shape)) ^ probe).volume() > 1e-6


def area64(radius):
    return 32 * radius**2 * np.sin(np.pi / 32)


# --- Exact: boxes and cylinders ---------------------------------------------------------


def test_a_box_shelled_through_its_top_is_an_open_box():
    box = new_primitive("cube")
    group = modify.shell(box, face_towards(box, (0, 0, 1)), 2.0)
    assert shape_geometry(group).volume == pytest.approx(8000 - 16 * 16 * 18)
    assert not solid_at(group, (0, 0, 19.5)) and solid_at(group, (0, 0, 1))
    assert solid_at(group, (9, 0, 19.5))  # the walls stand to the top


def test_a_box_opened_both_ways_is_a_square_tube():
    box = new_primitive("cube")
    group = modify.shell(box, face_towards(box, (1, 0, 0)), 2.0, far_side=True)
    assert shape_geometry(group).volume == pytest.approx(8000 - 16 * 16 * 20)


def test_a_turned_cylinder_opens_through_its_end():
    cylinder = new_primitive("cylinder")
    [cylinder] = modify.move_copy([cylinder], axis="x", angle=90.0)
    group = modify.shell(cylinder, face_towards(cylinder, (0, -1, 0)), 1.5)
    expected = area64(10) * 20 - area64(8.5) * 18.5
    assert shape_geometry(group).volume == pytest.approx(expected)
    assert modify.shells_exactly(cylinder)


def test_a_shell_ungroups_to_the_part_and_the_room_inside():
    box = new_primitive("cube")
    restored = ops.ungroup(modify.shell(box, face_towards(box, (0, 0, 1)), 2.0))
    assert restored[0].params == box.params
    assert restored[1].is_hole and restored[1].params["primitive"] == "cube"


# --- Approximate: everything else ----------------------------------------------------------


@pytest.mark.parametrize("make", [
    lambda: new_primitive("rounded_box"),
    lambda: (lambda b: (b.params.update(chamfer=1.0), b)[1])(new_primitive("cube")),
])
def test_other_parts_are_shelled_approximately_with_the_face_open(make):
    part = make()
    assert not modify.shells_exactly(part)
    group = modify.shell(part, face_towards(part, (0, 0, 1)), 2.0)
    tm = shape_geometry(group)
    assert tm.is_volume
    assert not solid_at(group, (0, 0, 19.5)) and solid_at(group, (0, 0, 1))
    assert 0.25 * shape_geometry(part).volume < tm.volume < 0.6 * shape_geometry(part).volume


def test_a_cylinders_side_strip_opens_only_with_a_wall_thinner_than_it_is_wide():
    cylinder = new_primitive("cylinder")
    strip = face_towards(cylinder, (1, 0, 0))  # one narrow flat strip, about 1 mm wide
    with pytest.raises(BuildError) as err:
        modify.shell(cylinder, strip, 2.0)
    assert "too small to leave open" in str(err.value)
    group = modify.shell(cylinder, strip, 0.3)
    centre = modify.flat_face(cylinder, strip).centre
    assert not solid_at(group, centre - (0.15, 0, 0))
    assert solid_at(group, centre * (-1, -1, 1) + (0.15, 0, 0))


@pytest.mark.parametrize("wall, words", [
    (0.0, "more than 0"), (float("nan"), "more than 0"), (10.0, "thinner than"),
])
def test_shell_refuses_walls_it_cant_make(wall, words):
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        modify.shell(box, face_towards(box, (0, 0, 1)), wall)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_a_face_with_nothing_across_from_it_is_refused():
    wedge = new_primitive("wedge")
    with pytest.raises(BuildError) as err:
        modify.shell(wedge, face_towards(wedge, (1, 0, 1)), 1.0, far_side=True)
    assert "across from" in str(err.value)


@pytest.mark.parametrize("make, words", [
    (lambda: create.new_sketch(SQUARE, np.eye(4)), "flat drawing"),
    (lambda: (lambda b: (setattr(b, "is_hole", True), b)[1])(new_primitive("cube")), "a Hole"),
])
def test_shell_needs_a_solid_part(make, words):
    with pytest.raises(BuildError) as err:
        modify.shell(make(), 0, 2.0)
    assert words in str(err.value)


# --- In the window --------------------------------------------------------------------


def test_clicking_a_face_asks_for_the_wall_and_shells_in_one_undo_step(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    seen = {}
    monkeypatch.setattr(modify_actions, "ask_shell", lambda parent, exact: seen.update(
        exact=exact) or {"wall": 2.0, "far_side": False})
    window.do_shell()
    assert window.tool == "shell"
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (0, 0, 20))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()  # the form opens once the click is over
    assert seen["exact"] is True
    group = window.document.scene.shapes[0]
    assert group.kind == "group" and len(window.document._undo) == steps + 1
    assert shape_geometry(group).volume == pytest.approx(3392.0)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_a_click_off_a_part_or_on_a_sketch_keeps_waiting(window):
    window.add_primitive("cube")
    window.add_sketch(SQUARE, np.eye(4))
    window.do_shell()
    window._on_surface_picked("", -1, (0, 0, 0))
    window._on_surface_picked(window.document.scene.shapes[1].id, 0, (0, 0, 0))
    assert window.tool == "shell"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["shell"]


def test_shell_needs_a_part(window):
    window.do_shell()
    assert window.tool is None
    assert window.statusBar().currentMessage() == window.PARTS_FIRST


def test_a_refused_shell_changes_nothing(window, warnings):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    assert not window.shell_face(box.id, face_towards(box, (0, 0, 1)), 15.0)
    assert warnings and len(window.document._undo) == steps


def test_esc_and_turning_expert_mode_off_stop_shell(window):
    window.add_primitive("cube")
    window.do_shell()
    window.stop_tool()
    assert window.tool is None
    window.do_shell()
    window.set_expert_mode(False)
    assert window.tool is None


def test_a_shelled_part_round_trips_through_a_project_file(tmp_path):
    part = new_primitive("rounded_box")
    group = modify.shell(part, face_towards(part, (0, 0, 1)), 2.0)
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(group).volume)
    assert len(ops.ungroup(loaded)) == 2


@pytest.mark.parametrize("exact", [True, False])
def test_shell_form_is_plain_language(qapp, close_qt_widget, exact):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Shell", modify_actions.shell_fields(),
                                        note=None if exact else modify_actions.APPROXIMATE_SHELL_NOTE))
    for text in dialog.labels():
        assert_plain(text)


# --- Walls outside, and more faces left open -----------------------------------------------


def test_walls_outside_keep_a_boxs_inside_and_stop_level_with_the_open_face():
    box = new_primitive("cube")
    group = modify.shell(box, face_towards(box, (0, 0, 1)), 2.0, walls="outside")
    tm = shape_geometry(group)
    assert tm.volume == pytest.approx(24 * 24 * 22 - 8000)
    assert np.allclose(tm.bounds, [[-12, -12, -2], [12, 12, 20]])
    assert not solid_at(group, (9.5, 0, 10)) and solid_at(group, (10.5, 0, 19.5))
    restored = ops.ungroup(group)
    assert restored[0].params == box.params
    assert not restored[1].is_hole and restored[2].is_hole


def test_walls_half_each_side_of_a_box_and_a_cylinder():
    box, cylinder = new_primitive("cube"), new_primitive("cylinder")
    group = modify.shell(box, face_towards(box, (0, 0, 1)), 2.0, walls="both")
    assert shape_geometry(group).volume == pytest.approx(22 * 22 * 21 - 18 * 18 * 19)
    assert np.allclose(shape_geometry(group).bounds, [[-11, -11, -1], [11, 11, 20]])
    group = modify.shell(cylinder, face_towards(cylinder, (0, 0, 1)), 1.5, walls="outside")
    assert shape_geometry(group).volume == pytest.approx(area64(11.5) * 21.5 - area64(10) * 20)


def test_more_faces_are_left_open_and_a_face_picked_twice_once():
    box = new_primitive("cube")
    top, side, front = (face_towards(box, d) for d in ((0, 0, 1), (1, 0, 0), (0, -1, 0)))
    group = modify.shell(box, top, 2.0, more=[[side, (10, 0, 10)], [front, None]])
    assert shape_geometry(group).volume == pytest.approx(8000 - 18 * 18 * 18)
    assert not solid_at(group, (9.5, 0, 10)) and not solid_at(group, (0, -9.5, 10))
    twice = modify.shell(box, top, 2.0, more=[[top, (0, 0, 20)]])
    assert shape_geometry(twice).volume == pytest.approx(8000 - 16 * 16 * 18) and len(ops.ungroup(twice)) == 2


def test_other_parts_get_walls_outside_with_rounded_corners_cut_level_round_the_opening():
    part = new_primitive("cube")
    part.params["chamfer"] = 1.0
    group = modify.shell(part, face_towards(part, (0, 0, 1)), 2.0, walls="outside")
    tm = shape_geometry(group)
    assert tm.is_volume and np.allclose(tm.bounds, [[-12, -12, -2], [12, 12, 20]])
    assert not solid_at(group, (0, 0, 19.9)) and not solid_at(group, (9.5, 0, 10))
    assert solid_at(group, (10.5, 0, 19.5)) and not solid_at(group, (11.9, 11.9, -1.9))


def test_walls_half_each_side_too_thick_are_refused_with_what_fits():
    box = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        modify.shell(box, face_towards(box, (0, 0, 1)), 25.0, walls="both")
    assert "thinner than 20.0 mm" in str(err.value)


def test_clicking_more_faces_to_leave_open_then_shell_in_one_undo_step(window, monkeypatch, qapp):
    window.add_primitive("cube")
    window.add_sketch(SQUARE, np.eye(4))
    box, drawing = window.document.scene.shapes
    top, side = face_towards(box, (0, 0, 1)), face_towards(box, (1, 0, 0))
    monkeypatch.setattr(modify_actions, "ask_shell", lambda parent, exact: {
        "wall": 2.0, "far_side": False, "walls": "outside", "faces": "more"})
    steps = len(window.document._undo)
    window.do_shell()
    window._on_surface_picked(box.id, top, (0, 0, 20))
    qapp.processEvents()  # the form opens once the click is over
    assert window.tool == "shell_more" and window.viewport.marked_actor is not None
    window._on_surface_picked(box.id, side, (10, 0, 10))
    assert window.statusBar().currentMessage().startswith("Picked: 2.")
    window._on_surface_picked(drawing.id, 0, (0, 0, 0))
    assert window.statusBar().currentMessage().startswith("Click the same part")
    assert len(window.document._undo) == steps
    window.do_shell()
    assert window.tool is None and len(window.document._undo) == steps + 1
    group = window.document.scene.get(window.document.scene.selection[0])
    assert shape_geometry(group).volume == pytest.approx(22 * 24 * 22 - 8000)
    window.do_undo()
    assert window.document.scene.shapes[0].id == box.id


def test_shelled_with_walls_outside_round_trips_through_a_project_file(tmp_path):
    box = new_primitive("cube")
    group = modify.shell(box, face_towards(box, (0, 0, 1)), 2.0, walls="both",
                         more=[[face_towards(box, (1, 0, 0)), None]])
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[group]), path)
    loaded = load_project(path).shapes[0]
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(group).volume)
    assert len(ops.ungroup(loaded)) == 3


def test_picking_more_faces_is_plain_language(window):
    assert_plain(window.TOOL_PROMPTS["shell_more"])
    for _key, label in modify_actions.SHELL_WALLS:
        assert_plain(label)
