"""Align Face to Face (Expert mode): one part's flat face put against another's."""

import numpy as np
import pytest

from mesh import create, modify
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


def box(size=20.0, x=0.0):
    shape = new_primitive("cube")
    shape.params.update(width=size, depth=size, height=size)
    shape.transform[0, 3] = x
    return shape


def face_towards(shape, direction):
    """A triangle of `shape` facing `direction`."""
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=np.float64)))


# --- Flat faces -----------------------------------------------------------------------


def test_a_flat_face_is_every_triangle_flat_and_joined_with_the_clicked_one():
    part = box()
    face = modify.flat_face(part, face_towards(part, (0, 0, 1)))
    assert len(face.faces) == 2
    assert np.allclose(face.normal, [0, 0, 1]) and np.allclose(face.centre, [0, 0, 20])
    assert face.region.area == pytest.approx(400.0)


def test_a_cylinders_end_is_one_face_and_its_side_a_narrow_strip():
    part = new_primitive("cylinder")
    end = modify.flat_face(part, face_towards(part, (0, 0, 1)))
    assert end.region.area == pytest.approx(64 / 2 * 100 * np.sin(2 * np.pi / 64))
    strip = modify.flat_face(part, face_towards(part, (1, 0, 0)))
    assert len(strip.faces) == 2
    assert strip.region.area == pytest.approx(20 * 2 * 10 * np.sin(np.pi / 64))


def test_a_click_that_is_not_on_a_face_is_refused():
    with pytest.raises(BuildError) as err:
        modify.flat_face(box(), 99)
    assert str(err.value) == modify.CLICK_A_FACE


# --- Putting faces together -----------------------------------------------------------


def test_a_bottom_face_put_on_a_top_face_stands_the_part_on_it_middle_to_middle():
    base, small = box(), box(10.0, x=50.0)
    transform = modify.align_faces(small, face_towards(small, (0, 0, -1)),
                                   base, face_towards(base, (0, 0, 1)))
    small.transform = transform
    assert np.allclose(shape_geometry(small).bounds, [[-5, -5, 20], [5, 5, 30]], atol=1e-9)


def test_a_part_is_turned_to_put_its_face_against_a_side():
    base, small = box(), box(10.0, x=50.0)
    small.transform = modify.align_faces(small, face_towards(small, (0, 0, -1)),
                                         base, face_towards(base, (1, 0, 0)))
    assert np.allclose(shape_geometry(small).bounds, [[10, -5, 5], [20, 5, 15]], atol=1e-9)


def test_aligning_a_turned_part_to_a_turned_part():
    base, small = box(), box(10.0, x=50.0)
    [base] = modify.move_copy([base], axis="z", angle=30.0)
    [small] = modify.move_copy([small], axis="x", angle=50.0)
    small.transform = modify.align_faces(small, face_towards(small, small.transform[:3, 1]),
                                         base, face_towards(base, base.transform[:3, 0]))
    moved = modify.flat_face(small, face_towards(small, -base.transform[:3, 0]))
    target = modify.flat_face(base, face_towards(base, base.transform[:3, 0]))
    assert np.allclose(moved.normal, -target.normal)
    assert np.allclose(moved.centre, target.centre)


@pytest.mark.parametrize("which", ["same", "guide"])
def test_align_refuses_the_same_part_or_a_sketch(which):
    part = box()
    other = part if which == "same" else create.new_sketch(SQUARE, np.eye(4))
    with pytest.raises(BuildError) as err:
        modify.align_faces(part, face_towards(part, (0, 0, 1)), other, 0)
    assert_plain(str(err.value))


# --- In the window --------------------------------------------------------------------


def _two_boxes(window):
    window.add_primitive("cube")
    window.add_primitive("cube")
    base, small = window.document.scene.shapes
    small.params.update(width=10.0, depth=10.0, height=10.0)
    small.transform[0, 3] = 50.0
    window.sync()
    return base, small


def test_two_clicks_put_the_faces_together_in_one_undo_step(window):
    base, small = _two_boxes(window)
    steps = len(window.document._undo)
    window.do_align_faces()
    assert window.tool == "align_from"
    window._on_surface_picked(small.id, face_towards(small, (0, 0, -1)), (50, 0, 0))
    assert window.tool == "align_to"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["align_to"]
    assert len(window.document._undo) == steps  # the first click changes nothing
    window._on_surface_picked(base.id, face_towards(base, (0, 0, 1)), (0, 0, 20))
    assert window.tool is None
    assert len(window.document._undo) == steps + 1
    assert np.allclose(shape_geometry(small).bounds, [[-5, -5, 20], [5, 5, 30]], atol=1e-9)
    window.do_undo()
    assert window.document.scene.shapes[1].transform[0, 3] == pytest.approx(50.0)


def test_clicking_the_same_part_twice_keeps_waiting(window):
    _base, small = _two_boxes(window)
    window.do_align_faces()
    window._on_surface_picked(small.id, face_towards(small, (0, 0, -1)), (50, 0, 0))
    window._on_surface_picked(small.id, face_towards(small, (0, 0, 1)), (50, 0, 10))
    assert window.tool == "align_to"
    assert "different part" in window.statusBar().currentMessage()


def test_a_missed_click_keeps_waiting(window):
    _base, small = _two_boxes(window)
    window.do_align_faces()
    window._on_surface_picked("", -1, (0, 0, 0))
    assert window.tool == "align_from"
    window._on_surface_picked(small.id, face_towards(small, (0, 0, -1)), (50, 0, 0))
    window._on_surface_picked("", -1, (0, 0, 0))
    assert window.tool == "align_to"


def test_align_needs_two_parts(window):
    window.add_primitive("cube")
    window.add_sketch(SQUARE, np.eye(4))
    window.do_align_faces()
    assert window.tool is None
    assert window.statusBar().currentMessage() == window.TWO_PARTS_FIRST


def test_esc_and_turning_expert_mode_off_stop_align(window):
    _two_boxes(window)
    window.do_align_faces()
    window.stop_tool()
    assert window.tool is None
    window.do_align_faces()
    window.set_expert_mode(False)
    assert window.tool is None and window.viewport.pick_mode is None


def test_an_aligned_part_round_trips_through_a_project_file(tmp_path):
    base, small = box(), box(10.0, x=50.0)
    small.transform = modify.align_faces(small, face_towards(small, (0, 0, -1)),
                                         base, face_towards(base, (1, 0, 0)))
    path = tmp_path / "part.mesh"
    save_project(Scene(shapes=[base, small]), path)
    loaded = load_project(path).shapes[1]
    assert np.allclose(shape_geometry(loaded).bounds, shape_geometry(small).bounds)
