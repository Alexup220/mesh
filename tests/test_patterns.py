"""Repeat in a row / in a circle."""

import numpy as np
import pytest

from mesh.builders import BuildError, repeat_circle, repeat_row
from mesh.ops import evaluate
from mesh.scene import DEFAULT_FIT_CLEARANCES, euler_from_transform, new_primitive
from mesh.shapes import shape_geometry


def centre(shape):
    return shape_geometry(shape).bounds.mean(axis=0)


def hole():
    s = new_primitive("cylinder")
    s.params.update(diameter=4.0, height=10.0)
    s.is_hole, s.fit = True, "snug"
    return s


def test_row_makes_count_minus_one_copies_spaced_along_x():
    part = hole()
    copies = repeat_row(part, 4, 12.5, "x")
    assert len(copies) == 3
    xs = [centre(c)[0] for c in copies]
    assert np.allclose(xs, [12.5, 25.0, 37.5])
    assert all(np.isclose(centre(c)[1], 0.0) for c in copies)


def test_row_along_y():
    copies = repeat_row(new_primitive("cube"), 3, 30.0, "y")
    assert np.allclose([centre(c)[1] for c in copies], [30.0, 60.0])


def test_copies_are_independent_and_keep_hole_and_fit():
    part = hole()
    copies = repeat_row(part, 3, 10.0)
    ids = {part.id} | {c.id for c in copies}
    assert len(ids) == 3
    for c in copies:
        assert c.is_hole and c.fit == "snug"
        assert c.params is not part.params and c.transform is not part.transform
    copies[0].params["diameter"] = 99.0
    copies[0].transform[0, 3] = 500.0
    assert part.params["diameter"] == 4.0 and copies[1].params["diameter"] == 4.0
    assert copies[1].transform[0, 3] == 20.0


def test_full_circle_spaces_copies_evenly_and_turns_them():
    part = new_primitive("cube")
    part.params.update(width=4.0, depth=2.0, height=2.0)
    part.transform[:3, 3] = [40.0, 0.0, 0.0]
    transform, copies = repeat_circle(part, 4, 30.0, (10.0, 0.0), 360.0)
    assert np.allclose(transform[:3, 3], (40.0, 0.0, 0.0))  # already on the circle
    centres = [centre(c)[:2] for c in copies]
    assert np.allclose(centres, [(10.0, 30.0), (-20.0, 0.0), (10.0, -30.0)], atol=1e-9)
    assert np.isclose(euler_from_transform(copies[0].transform)[2], 90.0)


def test_partial_circle_puts_the_ends_that_far_apart():
    part = new_primitive("sphere")
    part.transform[:3, 3] = [20.0, 0.0, 0.0]
    _t, copies = repeat_circle(part, 3, 20.0, (0.0, 0.0), 90.0)
    angles = [np.degrees(np.arctan2(*centre(c)[1::-1])) for c in copies]
    assert np.allclose(angles, [45.0, 90.0], atol=1e-9)


def test_original_moves_onto_the_circle_at_its_own_direction():
    part = new_primitive("cube")
    part.transform[:3, 3] = [0.0, 5.0, 0.0]
    transform, copies = repeat_circle(part, 2, 25.0, (0.0, 0.0), 360.0)
    assert np.allclose(transform[:2, 3], (0.0, 25.0))
    assert np.allclose(centre(copies[0])[:2], (0.0, -25.0), atol=1e-9)
    # repeat_circle itself changes nothing.
    assert np.allclose(part.transform[:2, 3], (0.0, 5.0))


def test_circle_of_holes_cuts_a_watertight_part():
    plate = new_primitive("cylinder")
    plate.params.update(diameter=60.0, height=3.0)
    h = hole()
    h.transform[:3, 3] = [20.0, 0.0, -2.0]
    transform, copies = repeat_circle(h, 6, 20.0, (0.0, 0.0))
    h.transform = transform
    result = evaluate([plate, h] + copies, clearances=dict(DEFAULT_FIT_CLEARANCES))
    assert result.is_watertight
    removed = shape_geometry(plate).volume - result.volume
    assert np.isclose(removed, 6 * np.pi * 2.2**2 * 3.0, rtol=5e-3)


@pytest.mark.parametrize("call", [
    lambda s: repeat_row(s, 1, 10.0),
    lambda s: repeat_row(s, 3, 0.0),
    lambda s: repeat_row(s, 10_000, 1.0),
    lambda s: repeat_circle(s, 3, 0.0, (0, 0)),
    lambda s: repeat_circle(s, 3, 10.0, (0, 0), 0.0),
    lambda s: repeat_circle(s, 3, 10.0, (0, 0), 400.0),
])
def test_bad_patterns_are_refused(call):
    with pytest.raises(BuildError):
        call(new_primitive("cube"))


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_row_in_the_window_is_one_undo_step(window):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.repeat_row_selected(5, 25.0, "x") is True
    scene = window.document.scene
    assert len(scene.shapes) == 5 and len(scene.selection) == 5
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert len(window.document.scene.shapes) == 1


def test_circle_in_the_window_is_one_undo_step_including_the_move(window):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.repeat_circle_selected(6, 30.0, (0.0, 0.0), 360.0) is True
    scene = window.document.scene
    assert len(scene.shapes) == 6
    assert np.isclose(scene.shapes[0].transform[0, 3], 30.0)
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert np.allclose(window.document.scene.shapes[0].transform, np.eye(4))


def test_a_refused_pattern_leaves_no_undo_step(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.repeat_row_selected(1, 25.0) is False
    assert window.repeat_circle_selected(3, -5.0, (0, 0)) is False
    assert len(window.document._undo) == depth
    assert len(window.document.scene.shapes) == 1


def test_circle_dialog_defaults_keep_the_part_in_place(window, monkeypatch):
    from mesh import panels

    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    shape.transform[:3, 3] = [50.0, 7.0, 0.0]

    def accept_defaults(parent, title, fields, note=None):
        return {key: default for key, _label, default, _o in fields}

    monkeypatch.setattr(panels, "run_form", accept_defaults)
    window.do_repeat_circle()
    assert len(window.document.scene.shapes) == 6
    assert np.allclose(window.document.scene.get(shape.id).transform[:3, 3], (50.0, 7.0, 0.0))
