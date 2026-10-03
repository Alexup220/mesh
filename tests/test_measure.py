"""Measure: two clicks, a distance and a line; nothing in the scene changes."""

import copy

import numpy as np
import pytest

from mesh import ops


def test_distance_is_the_straight_line_length():
    assert ops.distance((0, 0, 0), (3, 4, 12)) == 13.0
    assert ops.distance((1, 1, 1), (1, 1, 1)) == 0.0


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def _scene_state(window):
    return copy.deepcopy(window.document.scene.to_dict())


def test_two_clicks_show_the_distance_and_a_line_without_changing_anything(window):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    depth, revision = len(window.document._undo), window.document.revision
    before = _scene_state(window)

    window.act_measure.trigger()
    assert window.tool == "measure" and window.act_measure.isChecked()
    window._on_surface_picked(shape.id, 0, (-10.0, 0.0, 5.0))
    assert "second point" in window.statusBar().currentMessage()
    assert window.viewport.measure_actor is None
    window._on_surface_picked(shape.id, 3, (10.0, 0.0, 5.0))

    assert "Distance: 20.00 mm" in window.statusBar().currentMessage()
    actor = window.viewport.measure_actor
    assert actor is not None
    bounds = actor.GetMapper().GetInput().GetBounds()
    assert np.allclose(bounds, (-10.0, 10.0, 0.0, 0.0, 5.0, 5.0))

    assert len(window.document._undo) == depth
    assert window.document.revision == revision
    assert _scene_state(window) == before


def test_a_third_click_starts_a_new_measurement(window):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    window.toggle_measure(True)
    window._on_surface_picked(shape.id, 0, (0.0, 0.0, 0.0))
    window._on_surface_picked(shape.id, 0, (0.0, 0.0, 20.0))
    window._on_surface_picked(shape.id, 0, (5.0, 5.0, 5.0))
    assert window.viewport.measure_actor is None
    window._on_surface_picked(shape.id, 0, (5.0, 5.0, 8.0))
    assert "Distance: 3.00 mm" in window.statusBar().currentMessage()


def test_clicking_empty_space_is_ignored(window):
    window.add_primitive("cube")
    window.toggle_measure(True)
    window._on_surface_picked("", -1, (0.0, 0.0, 0.0))
    assert window._measure_points == []


@pytest.mark.parametrize("how", ["escape", "measure again"])
def test_escape_or_measure_again_exits_and_removes_the_line(window, how):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    depth = len(window.document._undo)
    window.act_measure.trigger()
    window._on_surface_picked(shape.id, 0, (0.0, 0.0, 0.0))
    window._on_surface_picked(shape.id, 0, (1.0, 0.0, 0.0))
    if how == "escape":
        window.act_stop_tool.trigger()
    else:
        window.act_measure.trigger()
    assert window.tool is None and not window.act_measure.isChecked()
    assert window.viewport.measure_actor is None
    assert window.viewport.pick_mode is None
    assert len(window.document._undo) == depth


def test_measure_shortcut_is_m(window):
    assert window.act_measure.shortcut().toString() == "M"
