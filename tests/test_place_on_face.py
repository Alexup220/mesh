"""Place on face: the next shape lands on (or, for a Hole, into) a clicked face."""

import numpy as np
import pytest

from mesh import ops
from mesh.scene import euler_from_transform, new_primitive, transform_with_euler
from mesh.shapes import shape_geometry


def block():
    b = new_primitive("cube")
    b.params.update(width=20.0, depth=20.0, height=20.0)
    return b


def face_pointing(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=float)))


def test_solid_sits_on_a_top_face_centred_on_the_click():
    cyl = new_primitive("cylinder")
    cyl.params.update(diameter=6.0, height=8.0)
    ops.place_on_face(cyl, (3.0, 4.0, 20.0), (0.0, 0.0, 1.0))
    tm = shape_geometry(cyl)
    assert np.isclose(tm.bounds[0][2], 20.0, atol=1e-9)
    assert np.isclose(tm.bounds[1][2], 28.0, atol=1e-9)
    assert np.allclose(tm.bounds.mean(axis=0)[:2], (3.0, 4.0), atol=1e-9)


def test_solid_on_a_side_face_points_outward_and_sits_flush():
    cyl = new_primitive("cylinder")
    cyl.params.update(diameter=6.0, height=8.0)
    ops.place_on_face(cyl, (10.0, 2.0, 12.0), (1.0, 0.0, 0.0))
    tm = shape_geometry(cyl)
    assert np.allclose(tm.bounds[:, 0], (10.0, 18.0), atol=1e-6)
    assert np.allclose(tm.bounds.mean(axis=0)[1:], (2.0, 12.0), atol=1e-6)
    # Rotation is in the transform, readable by the inspector's helpers.
    rx, ry, rz = euler_from_transform(cyl.transform)
    assert np.allclose(transform_with_euler(cyl.transform, rx, ry, rz), cyl.transform, atol=1e-9)


def test_hole_is_sunk_into_the_face_top_flush():
    hole = new_primitive("screw_hole")
    hole.params.update(size="M3", head="countersunk", depth=8.0)
    hole.is_hole = True
    ops.place_on_face(hole, (0.0, 0.0, 20.0), (0.0, 0.0, 1.0))
    tm = shape_geometry(hole)
    assert np.isclose(tm.bounds[1][2], 20.0, atol=1e-6)
    assert np.isclose(tm.bounds[0][2], 12.0, atol=1e-6)


def test_hole_on_a_slanted_face_cuts_into_the_part():
    wedge = new_primitive("wedge")  # slope faces (1, 0, 1)
    direction = ops.face_direction(wedge, face_pointing(wedge, (1, 0, 1)))
    point = (0.0, 0.0, 10.0)  # on the slope x + z = 10
    hole = new_primitive("magnet_pocket")
    hole.is_hole = True
    ops.place_on_face(hole, point, direction)
    from mesh.ops import evaluate

    result = evaluate([wedge, hole])
    assert result.is_watertight
    # The full pocket volume is inside the wedge, so all of it is removed.
    assert np.isclose(shape_geometry(wedge).volume - result.volume,
                      shape_geometry(hole).volume, rtol=2e-3)


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def _start_with_block(window):
    window.add_primitive("cube")
    return window.document.scene.shapes[0]


def test_place_mode_puts_the_next_shape_on_the_face_then_ends(window):
    base = _start_with_block(window)
    window.act_place.trigger()
    assert window.tool == "place" and window.act_place.isChecked()
    depth = len(window.document._undo)

    window._on_surface_picked(base.id, face_pointing(base, (0, 0, 1)), (2.0, -3.0, 20.0))
    assert len(window.document._undo) == depth  # picking a face changes nothing

    window.add_primitive("sphere")
    assert len(window.document._undo) == depth + 1
    sphere = window.document.scene.shapes[-1]
    tm = shape_geometry(sphere)
    assert np.isclose(tm.bounds[0][2], 20.0, atol=1e-6)
    assert np.allclose(tm.bounds.mean(axis=0)[:2], (2.0, -3.0), atol=1e-6)
    assert window.tool is None and not window.act_place.isChecked()

    # Mode is off again: the next shape lands on the workplane as before.
    window.add_primitive("cube")
    assert np.isclose(shape_geometry(window.document.scene.shapes[-1]).bounds[0][2], 0.0)


def test_hardware_hole_placed_on_a_face_is_sunk(window):
    base = _start_with_block(window)
    window.toggle_place_on_face(True)
    window._on_surface_picked(base.id, face_pointing(base, (0, 0, 1)), (0.0, 0.0, 20.0))
    window.add_hardware("insert_pocket", {"size": "M3"})
    hole = window.document.scene.shapes[-1]
    assert np.isclose(shape_geometry(hole).bounds[1][2], 20.0, atol=1e-6)


def test_without_a_picked_face_shapes_still_land_on_the_workplane(window):
    _start_with_block(window)
    window.toggle_place_on_face(True)
    window.add_primitive("sphere")
    assert np.isclose(shape_geometry(window.document.scene.shapes[-1]).bounds[0][2], 0.0)
    assert window.tool == "place"  # still waiting for a face


def test_unchecking_or_escape_turns_the_mode_off(window):
    _start_with_block(window)
    window.act_place.trigger()
    window.act_place.trigger()
    assert window.tool is None
    window.act_place.trigger()
    window.act_stop_tool.trigger()
    assert window.tool is None and not window.act_place.isChecked()


def test_place_mode_needs_a_part_to_click(window):
    window.act_place.trigger()
    assert window.tool is None and not window.act_place.isChecked()
