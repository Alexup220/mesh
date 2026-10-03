"""Lay flat: a picked face ends up resting on the workplane."""

import numpy as np
import pytest

from mesh import ops
from mesh.scene import euler_from_transform, new_primitive, transform_with_euler
from mesh.shapes import shape_geometry


def face_pointing(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=float)))


def down_faces_area(tm):
    down = tm.face_normals[:, 2] < -0.999
    return float(tm.area_faces[down].sum())


@pytest.mark.parametrize("a, b", [
    ((1, 0, 0), (0, 0, -1)), ((0, 0, 1), (0, 0, -1)), ((0, 0, -1), (0, 0, -1)),
    ((1, 2, 3), (-3, 0.5, 2)),
])
def test_rotation_between_is_a_proper_rotation_onto_the_target(a, b):
    r = ops.rotation_between(a, b)
    assert np.isclose(np.linalg.det(r), 1.0)
    a_unit = np.asarray(a, float) / np.linalg.norm(a)
    b_unit = np.asarray(b, float) / np.linalg.norm(b)
    assert np.allclose(r @ a_unit, b_unit, atol=1e-9)


def test_rotation_between_rejects_a_zero_direction():
    with pytest.raises(ValueError):
        ops.rotation_between((0, 0, 0), (0, 0, 1))


def test_box_side_face_ends_up_on_the_plane():
    box = new_primitive("cube")
    box.params.update(width=10.0, depth=20.0, height=30.0)
    box.transform[:3, 3] = [5.0, 7.0, 0.0]
    ops.lay_flat(box, ops.face_direction(box, face_pointing(box, (1, 0, 0))))
    tm = shape_geometry(box)
    assert np.isclose(tm.bounds[0][2], 0.0, atol=1e-9)
    # The 20 x 30 side is now the footprint, so the part is 10 tall.
    assert np.isclose(tm.bounds[1][2], 10.0, atol=1e-9)
    assert np.isclose(down_faces_area(tm), 600.0, rtol=1e-6)
    # It turned in place: the centre stays at the same X / Y.
    assert np.allclose(tm.bounds.mean(axis=0)[:2], [5.0, 7.0], atol=1e-9)
    assert tm.is_watertight


def test_wedge_slope_ends_up_on_the_plane():
    wedge = new_primitive("wedge")  # 20 x 20 x 20; the slope is 20 x 20*sqrt(2)
    slope = face_pointing(wedge, (1, 0, 1))
    ops.lay_flat(wedge, ops.face_direction(wedge, slope))
    tm = shape_geometry(wedge)
    assert np.isclose(tm.bounds[0][2], 0.0, atol=1e-9)
    assert np.isclose(down_faces_area(tm), 20.0 * 20.0 * np.sqrt(2.0), rtol=1e-6)


def test_rotation_stays_in_the_transform_and_matches_the_euler_helpers():
    cyl = new_primitive("cylinder")
    cyl.transform = transform_with_euler(cyl.transform, 20.0, 35.0, -10.0)
    params_before = dict(cyl.params)
    ops.lay_flat(cyl, ops.face_direction(cyl, face_pointing(cyl, (0, 0, 1))))
    assert cyl.params == params_before
    rx, ry, rz = euler_from_transform(cyl.transform)
    rebuilt = transform_with_euler(cyl.transform, rx, ry, rz)
    assert np.allclose(rebuilt, cyl.transform, atol=1e-9)
    tm = shape_geometry(cyl)
    # The (formerly top) circular face is now exactly on the plane.
    assert np.isclose(down_faces_area(tm), np.pi * 100.0, rtol=2e-3)


def test_a_mirrored_part_stays_mirrored():
    wedge = new_primitive("wedge")
    ops.mirror(wedge, "x")
    det_before = np.linalg.det(wedge.transform[:3, :3])
    ops.lay_flat(wedge, (0.0, 1.0, 0.0))
    assert np.sign(np.linalg.det(wedge.transform[:3, :3])) == np.sign(det_before) < 0
    assert np.isclose(shape_geometry(wedge).bounds[0][2], 0.0, atol=1e-9)


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_lay_flat_tool_turns_the_clicked_part_and_is_one_undo_step(window):
    window.add_primitive("wedge")
    shape = window.document.scene.shapes[0]
    depth = len(window.document._undo)

    window.start_lay_flat()
    assert window.tool == "lay_flat"
    assert window.viewport.pick_mode == "lay_flat"
    assert len(window.document._undo) == depth  # entering the tool changes nothing

    window._on_surface_picked(shape.id, face_pointing(shape, (1, 0, 1)), (0.0, 0.0, 10.0))

    assert len(window.document._undo) == depth + 1
    assert window.tool is None and window.viewport.pick_mode is None
    tm = shape_geometry(window.document.scene.get(shape.id))
    assert np.isclose(down_faces_area(tm), 400.0 * np.sqrt(2.0), rtol=1e-6)
    window.do_undo()
    assert np.allclose(window.document.scene.get(shape.id).transform, np.eye(4))


def test_clicking_empty_space_keeps_waiting_without_an_undo_step(window):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    window.start_lay_flat()
    window._on_surface_picked("", -1, (0.0, 0.0, 0.0))
    assert window.tool == "lay_flat"
    assert len(window.document._undo) == depth


def test_escape_leaves_the_tool_without_an_undo_step(window):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    window.start_lay_flat()
    window.act_stop_tool.trigger()
    assert window.tool is None and window.viewport.pick_mode is None
    assert len(window.document._undo) == depth
    assert window.act_stop_tool.shortcut().toString() == "Esc"


def test_lay_flat_with_an_empty_scene_does_not_start(window):
    window.start_lay_flat()
    assert window.tool is None


def test_viewport_reports_surface_clicks_in_pick_mode(window):
    window.add_primitive("cube")
    seen_pick, seen_surface = [], []
    window.viewport.picked.connect(lambda *a: seen_pick.append(a))
    window.viewport.surface_picked.connect(lambda *a: seen_surface.append(a))
    window.viewport.set_pick_mode("lay_flat")
    window.viewport._on_click(window.viewport.interactor, None)
    assert seen_pick == [] and len(seen_surface) == 1
