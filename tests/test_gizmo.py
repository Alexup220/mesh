import numpy as np
import pytest

from mesh.scene import Scene, new_primitive


@pytest.fixture
def gizmo(qapp, close_qt_widget):
    from mesh.gizmo import Gizmo
    from mesh.viewport import Viewport

    viewport = close_qt_widget(Viewport())
    viewport.set_scene(Scene())
    return Gizmo(viewport)


def test_gizmo_starts_detached(gizmo):
    assert gizmo.attached_id is None


def test_attach_records_the_shape(gizmo):
    shape = new_primitive("cube")
    gizmo.attach(shape)
    assert gizmo.attached_id == shape.id


def test_attach_none_detaches(gizmo):
    gizmo.attach(new_primitive("cube"))
    gizmo.attach(None)
    assert gizmo.attached_id is None


def test_snap_quantises_to_the_grid(gizmo):
    gizmo.snap_mm = 1.0
    assert np.isclose(gizmo._snap(4.4), 4.0)
    assert np.isclose(gizmo._snap(4.6), 5.0)


def test_snap_of_zero_is_disabled(gizmo):
    gizmo.snap_mm = 0.0
    assert np.isclose(gizmo._snap(4.4), 4.4)


def test_apply_widget_transform_writes_back_to_the_shape(gizmo):
    shape = new_primitive("cube")
    gizmo.attach(shape)
    moved = np.eye(4)
    moved[:3, 3] = [12.3, 0.0, 0.0]
    gizmo._apply(moved)
    assert np.isclose(shape.transform[0, 3], 12.0)


def test_changed_signal_carries_the_shape_id(gizmo):
    shape = new_primitive("cube")
    gizmo.attach(shape)
    seen = []
    gizmo.changed.connect(seen.append)
    gizmo._apply(np.eye(4))
    assert seen == [shape.id]
