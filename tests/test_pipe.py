"""Pipe (Expert mode's Create menu): a round tube carried along a sketch's path."""

import math

import numpy as np
import pytest
import trimesh

from mesh import create, expert_actions, features, modify, parameters, sketch
from mesh.builders import BuildError
from mesh.expert import TOOLS
from mesh.io_formats import load_project, save_project
from mesh.panels import FIELD_LABELS, FormDialog
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import PRIMITIVES, shape_geometry
from test_plain_language import assert_plain

# Up 20 mm, then 30 mm across, drawn on the upright front plane.
ELBOW = [
    {"type": "line", "start": [0, 0], "end": [0, 20]},
    {"type": "line", "start": [0, 20], "end": [30, 20]},
]
RING = [{"type": "circle", "centre": [0, 0], "diameter": 40}]
UPRIGHT = sketch.named_plane_frame("xz")
FLAT = np.eye(4)
SIDES = 64  # a round outline's straight sides (mesh.sketch.SEGMENTS)


def circle_area(diameter):
    return SIDES / 2 * (diameter / 2) ** 2 * math.sin(2 * math.pi / SIDES)


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


def path_sketch(entities=ELBOW, frame=UPRIGHT):
    return create.new_sketch(entities, frame)


# --- The tube ----------------------------------------------------------------------------


def test_a_solid_pipe_is_a_round_rod_along_the_path():
    tm = features.pipe(ELBOW, UPRIGHT, 4.0)
    assert tm.is_watertight
    # Mitred at the corner, so exactly the two straight pieces' worth.
    assert tm.volume == pytest.approx(circle_area(4.0) * (20 + 30), rel=1e-6)
    assert np.allclose(tm.bounds, [[-2, -2, 0], [30, 2, 22]], atol=1e-6)


def test_a_hollow_pipe_has_a_wall_all_along():
    tm = features.pipe(ELBOW, UPRIGHT, 4.0, "hollow", 0.5)
    assert tm.is_watertight
    assert tm.volume == pytest.approx((circle_area(4.0) - circle_area(3.0)) * 50, rel=1e-6)
    # Across the first piece, a ring from 1.5 to 2 mm out.
    points = trimesh.intersections.mesh_plane(tm, (0, 0, 1), (0, 0, 10)).reshape(-1, 3)
    radius = np.hypot(points[:, 0], points[:, 1])
    assert radius.min() == pytest.approx(1.5, abs=0.01) and radius.max() == pytest.approx(2.0, abs=1e-6)


def test_a_pipe_round_a_closed_path_is_a_ring():
    tm = features.pipe(RING, FLAT, 4.0, "hollow", 1.0)
    assert tm.is_watertight
    # Its outline's area times the length round the middle (followed in
    # straight steps, so a little less).
    assert tm.volume == pytest.approx((circle_area(4.0) - circle_area(2.0)) * math.pi * 40, rel=0.01)


def test_a_fitted_pipe_hole_grows_all_round_and_past_its_ends():
    tm = features.pipe(ELBOW, UPRIGHT, 4.0, clearance=0.2)
    assert tm.is_watertight
    assert np.allclose(tm.bounds, [[-2.2, -2.2, -0.2], [30.2, 2.2, 22.2]], atol=1e-3)


@pytest.mark.parametrize("diameter, inside, wall, words", [
    (0.05, "solid", 1.0, "at least 0.1 mm"),
    (4.0, "hollow", 2.0, "fills"),
    (4.0, "hollow", 0.0, "at least 0.05 mm"),
    (4.0, "square", 1.0, "solid or hollow"),
    (30.0, "solid", 1.0, "bends too tightly"),
])
def test_pipes_that_cannot_be_made_are_refused(diameter, inside, wall, words):
    bend = [{"type": "arc", "centre": [0, 0], "radius": 10, "start": 0, "end": 90}]
    with pytest.raises(sketch.SketchError) as err:
        features.pipe(bend, FLAT, diameter, inside, wall)
    assert words in str(err.value)
    assert_plain(str(err.value))


# --- As a part ---------------------------------------------------------------------------


def test_a_pipe_keeps_its_path_and_editable_sizes():
    path = path_sketch()
    made = create.make_pipe(path, 4.0, "hollow", 0.5, hole=True)
    assert made.params["primitive"] == "pipe" and made.name == f"Pipe along {path.name}"
    assert made.params["path_entities"] == ELBOW and np.allclose(made.params["path_frame"], UPRIGHT)
    assert (made.params["diameter"], made.params["inside"], made.params["wall"]) == (4.0, "hollow", 0.5)
    assert made.is_hole and (made.transform == np.eye(4)).all() and not PRIMITIVES["pipe"]["shelf"]
    assert set(parameters.linkable(made)) >= {"diameter", "wall"}
    with pytest.raises(BuildError) as err:
        create.make_pipe(new_primitive("cube"), 4.0)
    assert str(err.value) == create.PIPE_PICK
    with pytest.raises(BuildError) as err:
        create.make_pipe(path, 4.0, "hollow", 3.0)
    assert "fills" in str(err.value)


def test_details_edits_and_scaling_of_a_pipe():
    pipe = create.make_pipe(path_sketch(), 4.0, "hollow", 0.5)
    assert create.edit_refusal(pipe, "diameter", 6.0, None) is None
    assert "fills" in create.edit_refusal(pipe, "wall", 2.5, None)
    [bigger] = modify.scaled([pipe], (2, 2, 2), "centre")
    assert (bigger.params["diameter"], bigger.params["wall"]) == (8.0, 1.0)
    assert shape_geometry(bigger).volume == pytest.approx(shape_geometry(pipe).volume * 8, rel=1e-6)
    with pytest.raises(BuildError) as err:
        modify.scaled([pipe], (1, 1, 2))
    assert "made from a sketch" in str(err.value)


def test_a_pipe_round_trips_through_a_project_file(tmp_path):
    pipe = create.make_pipe(path_sketch(), 4.0, "hollow", 0.5, hole=True)
    file = tmp_path / "pipe.mesh"
    save_project(Scene(shapes=[pipe]), file)
    loaded = load_project(file).shapes[0]
    assert loaded.params == pipe.params and loaded.is_hole
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(pipe).volume)


# --- In the window -----------------------------------------------------------------------


def test_making_a_pipe_is_one_undo_step(window, monkeypatch):
    monkeypatch.setattr(expert_actions, "ask_pipe", lambda parent: {
        "diameter": 4.0, "inside": "hollow", "wall": 0.5, "result": "part", "keep_sketch": False})
    window.add_sketch(ELBOW, UPRIGHT)
    steps = len(window.document._undo)
    window.do_pipe()
    [pipe] = window.document.scene.shapes  # the sketch is used up
    assert pipe.params["primitive"] == "pipe" and window.document.scene.selection == [pipe.id]
    assert len(window.document._undo) == steps + 1
    assert window.inspector.visible_param_fields() == {"diameter", "inside", "wall"}
    window.do_undo()
    [back] = window.document.scene.shapes
    assert back.params["primitive"] == "sketch"


def test_a_pipe_can_keep_its_sketch_and_be_a_hole(window):
    window.add_sketch(ELBOW, UPRIGHT)
    assert window.pipe_selected(4.0, hole=True, keep_sketch=True)
    kinds = sorted(s.params["primitive"] for s in window.document.scene.shapes)
    assert kinds == ["pipe", "sketch"] and window.document.scene.selected()[0].is_hole


def test_a_pipe_needs_one_sketch(window, monkeypatch, warnings):
    monkeypatch.setattr(expert_actions, "ask_pipe", lambda parent: pytest.fail("no form"))
    window.do_pipe()
    window.add_primitive("cube")
    window.do_pipe()
    assert window.statusBar().currentMessage() == create.PIPE_PICK and not warnings


def test_a_refused_pipe_leaves_no_undo_step(window, warnings):
    window.add_sketch(ELBOW, UPRIGHT)
    steps = len(window.document._undo)
    assert not window.pipe_selected(4.0, "hollow", 2.0)
    assert warnings and "fills" in warnings[0] and len(window.document._undo) == steps


def test_pipe_text_is_plain_language(qapp, close_qt_widget):
    dialog = close_qt_widget(FormDialog(None, "Pipe", expert_actions.pipe_fields(), note=expert_actions.PIPE_NOTE))
    for text in dialog.labels():
        assert_plain(text)
    for text in (FIELD_LABELS["inside"], *(label for _, label in features.PIPE_INSIDES),
                 PRIMITIVES["pipe"]["label"], create.PIPE_PICK, *(t.tip for t in TOOLS if t.key == "pipe")):
        assert_plain(text)
