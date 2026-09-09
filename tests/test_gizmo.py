import numpy as np
import pytest
from vtkmodules.vtkCommonTransforms import vtkTransform

from mesh.scene import Scene, new_primitive


@pytest.fixture
def gizmo(qapp, close_qt_widget):
    from mesh.gizmo import Gizmo
    from mesh.viewport import Viewport

    viewport = close_qt_widget(Viewport())
    viewport.set_scene(Scene())
    return Gizmo(viewport)


@pytest.fixture
def attached(qapp, close_qt_widget):
    """A Gizmo attached to a shape that has a real vtkActor.

    Unlike the `gizmo` fixture, this adds the shape to the scene and
    refreshes the viewport BEFORE attaching, so `viewport.actor_for(...)`
    returns a real actor and the widget-driven path in `attach`/`_on_end`
    actually executes instead of silently early-returning.
    """
    from mesh.gizmo import Gizmo
    from mesh.viewport import Viewport

    viewport = close_qt_widget(Viewport())
    scene = Scene()
    shape = new_primitive("cube")
    scene.add(shape)
    viewport.set_scene(scene)
    viewport.refresh()

    gizmo = Gizmo(viewport)
    gizmo.attach(shape)
    return gizmo, shape, scene, viewport


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


# --- Widget-driven path: attach on a shape with a real actor -------------


def test_attach_with_actor_captures_base(attached):
    gizmo, shape, scene, viewport = attached
    assert gizmo.attached_id == shape.id
    assert gizmo._base is not None
    assert np.array_equal(gizmo._base, shape.transform)


def test_changing_signal_fires_on_interaction_start(attached):
    gizmo, shape, scene, viewport = attached
    seen = []
    gizmo.changing.connect(lambda: seen.append(True))
    gizmo._on_start()
    assert seen == [True]


def test_on_end_composes_delta_with_base(attached):
    """Drive the real _on_end path via the vtkBoxRepresentation's transform.

    vtkBoxRepresentation.SetTransform/GetTransform round-trip correctly, so
    rather than factoring the delta @ base composition out into a separate
    pure helper, we inject a known transform straight into the
    representation the widget actually reads from and invoke the real
    EndInteractionEvent handler. This exercises `_on_end` itself -
    including the `self._representation.GetTransform(...)` extraction step
    - not just the arithmetic.
    """
    gizmo, shape, scene, viewport = attached

    # Give the shape (and therefore gizmo._base) a non-trivial starting
    # transform so the composition is not masked by identity.
    base = np.array(
        [
            [1.0, 0.0, 0.0, 2.0],
            [0.0, 1.0, 0.0, 3.0],
            [0.0, 0.0, 1.0, 4.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    gizmo._base = base.copy()

    delta_transform = vtkTransform()
    delta_transform.Translate(7.0, 0.0, 0.0)
    gizmo._representation.SetTransform(delta_transform)

    gizmo._on_end()

    delta = np.eye(4)
    delta[0, 3] = 7.0
    expected = delta @ base
    expected[:3, 3] = np.round(expected[:3, 3] / gizmo.snap_mm) * gizmo.snap_mm

    assert np.allclose(shape.transform, expected)


def test_second_drag_without_reattach_compounds_not_double_applies(attached):
    """VTK's box widget transform is cumulative from PlaceWidget, not
    incremental per drag, so `_on_end` must keep composing against the
    ORIGINAL `_base` captured at attach time on every subsequent drag - not
    against the shape's own (already-moved) transform, which would double
    apply the first drag's movement."""
    gizmo, shape, scene, viewport = attached

    first_delta = vtkTransform()
    first_delta.Translate(5.0, 0.0, 0.0)
    gizmo._representation.SetTransform(first_delta)
    gizmo._on_end()
    assert np.isclose(shape.transform[0, 3], 5.0)

    # A further drag reports the TOTAL movement since PlaceWidget (12mm),
    # not an increment on top of the first drag.
    second_delta = vtkTransform()
    second_delta.Translate(12.0, 0.0, 0.0)
    gizmo._representation.SetTransform(second_delta)
    gizmo._on_end()

    assert np.isclose(shape.transform[0, 3], 12.0)


# --- Finding 2: a failed re-attach must not leave a stale _base ----------


def test_failed_reattach_clears_stale_base(attached):
    gizmo, shape, scene, viewport = attached
    assert gizmo._base is not None

    other = new_primitive("cube")  # never added to the scene/viewport
    gizmo.attach(other)

    assert gizmo.attached_id == other.id
    assert gizmo._base is None
