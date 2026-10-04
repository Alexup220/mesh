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
