"""Thread (Expert mode's Create menu): modeled screw threads and threaded holes."""

import numpy as np
import pytest
import trimesh

from mesh import construct, create, expert_actions, modify, threads
from mesh.builders import BuildError
from mesh.expert import TOOLS
from mesh.io_formats import load_project, save_project
from mesh.panels import FIELD_LABELS
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from mesh.solids import to_manifold
from test_plain_language import assert_plain

M10 = {"diameter": 10.0, "height": 20.0, "pitch": 1.5, "thread_length": 20.0}


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


def radii_at(tm, z):
    """How far from the middle the surface is, all the way round, at height z."""
    points = trimesh.intersections.mesh_plane(tm, (0, 0, 1), (0, 0, z)).reshape(-1, 3)
    return points, np.hypot(points[:, 0], points[:, 1])


def crest_angle(tm, z):
    points, radius = radii_at(tm, z)
    crest = points[radius > radius.max() - 1e-3].mean(axis=0)  # the middle of the crest
    return np.degrees(np.arctan2(crest[1], crest[0]))


def outside(a, b):
    """How much of `a` is outside `b` (cubic mm)."""
    return (to_manifold(a) - to_manifold(b)).volume()


# --- The thread -------------------------------------------------------------------------


def test_standard_sizes_and_pitches():
    assert threads.standard_size(10) == ("M10", 1.5)
    assert threads.standard_size(3.2) == ("M3", 0.5)
    assert threads.standard_size(19.6) == ("M20", 2.5)
    assert threads.depth(1.5) == pytest.approx(0.8119, abs=1e-4)


def test_a_thread_is_a_closed_part_between_its_two_diameters():
    tm = threads.thread_mesh(M10)
    assert tm.is_watertight
    assert tm.bounds[:, 2].tolist() == pytest.approx([0, 20])
    assert np.ptp(tm.bounds[:, 0]) == pytest.approx(10, abs=1e-4)
    outer, inner = 5.0, 5.0 - threads.depth(1.5)
    # The ISO shape: crest P/8, root P/4, straight flanks between.
    mean_square = outer ** 2 / 8 + inner ** 2 / 4 + 5 / 8 * (outer ** 2 + outer * inner + inner ** 2) / 3
    assert tm.volume == pytest.approx(np.pi * mean_square * 20, rel=0.01)
    _, radius = radii_at(tm, 7.3)
    assert radius.max() == pytest.approx(outer, abs=1e-3) and radius.min() == pytest.approx(inner, abs=0.02)


def test_a_right_hand_thread_climbs_anticlockwise_seen_from_above():
    right = threads.thread_mesh(M10)
    turned = (crest_angle(right, 5.0 + 1.5 / 4) - crest_angle(right, 5.0)) % 360
    assert turned == pytest.approx(90, abs=1)
    left = threads.thread_mesh({**M10, "hand": "left"})
    assert (crest_angle(left, 5.0 + 1.5 / 4) - crest_angle(left, 5.0)) % 360 == pytest.approx(270, abs=1)
    assert left.volume == pytest.approx(right.volume, rel=1e-3)


@pytest.mark.parametrize("end, threaded_at, plain_at", [("top", 15.0, 5.0), ("bottom", 5.0, 15.0)])
def test_part_of_the_height_can_be_threaded(end, threaded_at, plain_at):
    tm = threads.thread_mesh({**M10, "thread_length": 8.0, "end": end})
    assert tm.is_watertight and tm.bounds[:, 2].tolist() == pytest.approx([0, 20])
    _, plain = radii_at(tm, plain_at)
    _, threaded = radii_at(tm, threaded_at)
    assert plain.min() > 4.99 and threaded.min() < 4.3


def test_a_bolt_screws_into_a_threaded_hole_of_its_size():
    bolt = threads.thread_mesh(M10)
    for fit in (0.0, 0.2):
        hole = threads.thread_mesh(M10, fit)
        assert outside(bolt, hole) == pytest.approx(0, abs=1e-6)
    hole = threads.thread_mesh(M10, 0.2)
    assert hole.bounds.ravel().tolist() == pytest.approx([-5.2, -5.2, -0.2, 5.2, 5.2, 20.2], abs=1e-4)
    # The same check catches a bolt that is too fat.
    assert outside(threads.thread_mesh({**M10, "diameter": 10.6}), hole) > 1.0


def test_a_part_threaded_hole_lines_up_with_a_fully_threaded_bolt():
    bolt = threads.thread_mesh({**M10, "height": 12.0, "thread_length": 12.0})
    hole = threads.thread_mesh({**M10, "thread_length": 12.0, "end": "bottom"}, 0.1)
    assert outside(bolt, hole) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("change, words", [
    ({"pitch": 0.1}, "at least 0.2 mm"),
    ({"pitch": 8.0}, "cuts too deep"),
    ({"diameter": 3.0, "pitch": 0.2, "height": 100.0, "thread_length": 100.0}, "more than 150 turns"),
    ({"end": "middle"}, "Choose where"),
])
def test_sizes_that_cannot_make_a_thread_are_refused(change, words):
    with pytest.raises(threads.ThreadError) as err:
        threads.thread_mesh({**M10, **change})
    assert words in str(err.value)
    assert_plain(str(err.value))


# --- Putting a thread on a cylinder -----------------------------------------------------


def test_a_cylinder_becomes_a_thread_and_keeps_everything_else():
    cylinder = new_primitive("cylinder")
    cylinder.transform[:3, 3] = (4, 5, 6)
    cylinder.color, cylinder.is_hole, cylinder.fit = "#123456", True, "snug"
    made = create.threaded(cylinder, 2.5, 50.0, "bottom", "left")
    assert made.params == {"primitive": "thread", "diameter": 20.0, "height": 20.0, "pitch": 2.5,
                           "thread_length": 20.0, "end": "bottom", "hand": "left"}
    assert (made.id, made.name, made.color, made.is_hole, made.fit) == (
        cylinder.id, cylinder.name, "#123456", True, "snug")
    assert (made.transform == cylinder.transform).all()
    assert cylinder.params["primitive"] == "cylinder"  # the original is left alone


def test_only_a_plain_cylinder_takes_a_thread():
    with pytest.raises(BuildError) as err:
        create.threaded(new_primitive("cube"), 1.5, 10.0)
    assert str(err.value) == create.NOT_A_CYLINDER
    chamfered = new_primitive("cylinder")
    chamfered.params["chamfer"] = 1.0
    with pytest.raises(BuildError) as err:
        create.threaded(chamfered, 2.5, 10.0)
    assert "bottom chamfer" in str(err.value)
    with pytest.raises(BuildError) as err:
        create.threaded(new_primitive("cylinder"), 30.0, 10.0)
    assert "cuts too deep" in str(err.value)
    for text in (create.NOT_A_CYLINDER,):
        assert_plain(text)


def test_details_edits_on_a_thread_are_checked():
    thread = create.threaded(new_primitive("cylinder"), 2.5, 20.0)
    assert create.edit_refusal(thread, "pitch", 2.0, None) is None
    assert "cuts too deep" in create.edit_refusal(thread, "pitch", 20.0, None)
    assert create.edit_refusal(thread, "hand", "left", None) is None
    assert create.edit_refusal(new_primitive("cylinder"), "diameter", 0.5, None) is None


def test_scaling_a_thread_keeps_its_pitch_unless_scaled_alike():
    thread = create.threaded(new_primitive("cylinder"), 2.5, 10.0)
    [taller] = modify.scaled([thread], (1, 1, 2))
    assert (taller.params["height"], taller.params["thread_length"], taller.params["pitch"]) == (40, 20, 2.5)
    [bigger] = modify.scaled([thread], (2, 2, 2))
    assert (bigger.params["diameter"], bigger.params["pitch"]) == (40, 5.0)
    with pytest.raises(BuildError) as err:
        modify.scaled([thread], (2, 1, 1))
    assert "is round" in str(err.value)


def test_a_thread_has_an_axis_along_its_middle():
    thread = create.threaded(new_primitive("cylinder"), 2.5, 10.0)
    point, direction = construct.axis_of(construct.axis_of_round_part(thread))
    assert point.tolist() == pytest.approx([0, 0, 10]) and direction.tolist() == [0, 0, 1]


def test_a_thread_round_trips_through_a_project_file(tmp_path):
    thread = create.threaded(new_primitive("cylinder"), 2.5, 12.0, "bottom", "left")
    file = tmp_path / "bolt.mesh"
    save_project(Scene(shapes=[thread]), file)
    loaded = load_project(file).shapes[0]
    assert loaded.params == thread.params
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(thread).volume)


# --- In the window ----------------------------------------------------------------------


def test_threading_the_selected_cylinder_is_one_undo_step(window, monkeypatch):
    seen = {}
    monkeypatch.setattr(expert_actions, "ask_thread", lambda parent, height, standard, pitch: seen.update(
        height=height, standard=standard, pitch=pitch) or {"pitch": pitch, "length": 12.0, "end": "top",
                                                           "hand": "right"})
    window.add_primitive("cylinder")
    cylinder = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    window.do_thread()
    assert seen == {"height": 20.0, "standard": "M20", "pitch": 2.5}
    assert cylinder.params["primitive"] == "thread" and cylinder.params["thread_length"] == 12.0
    assert len(window.document._undo) == steps + 1
    assert window.inspector.visible_param_fields() >= {"pitch", "thread_length", "end", "hand"}
    window.do_undo()
    assert window.document.scene.shapes[0].params["primitive"] == "cylinder"


def test_a_threaded_hole_is_cut_at_its_fit(window):
    window.add_primitive("cylinder")
    hole = window.document.scene.shapes[0]
    hole.is_hole, hole.fit = True, "snug"
    assert window.thread_selected(2.5, 20.0)
    clearance = window.document.scene.fit_clearances["snug"]
    tm = shape_geometry(hole, window.document.scene.fit_clearances)
    assert np.ptp(tm.bounds[:, 2]) == pytest.approx(20 + 2 * clearance, abs=1e-4)


def test_nothing_to_thread(window, monkeypatch, warnings):
    monkeypatch.setattr(expert_actions, "ask_thread", lambda *a: pytest.fail("no form"))
    window.do_thread()
    window.add_primitive("cube")
    window.do_thread()
    assert window.statusBar().currentMessage() == create.NOT_A_CYLINDER and not warnings


def test_a_refused_thread_leaves_no_undo_step(window, warnings):
    window.add_primitive("cylinder")
    steps = len(window.document._undo)
    assert not window.thread_selected(30.0, 10.0)
    assert warnings and "cuts too deep" in warnings[0] and len(window.document._undo) == steps
    assert window.document.scene.shapes[0].params["primitive"] == "cylinder"


def test_a_details_edit_that_cannot_make_a_thread_is_refused(window, warnings):
    window.add_primitive("cylinder")
    thread = window.document.scene.shapes[0]
    window.thread_selected(2.5, 20.0)
    window._on_edited(thread.id, "pitch", 20.0)
    assert warnings and "cuts too deep" in warnings[0] and thread.params["pitch"] == 2.5
    window._on_edited(thread.id, "pitch", 2.0)
    assert thread.params["pitch"] == 2.0


def test_thread_text_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Thread", expert_actions.thread_fields(20.0, 2.5),
                                        note=expert_actions.thread_note("M20", 2.5)))
    for text in dialog.labels():
        assert_plain(text)
    for text in (*(FIELD_LABELS[f] for f in ("pitch", "thread_length", "end", "hand")),
                 *(label for _, label in threads.ENDS + threads.HANDS),
                 *(t.tip for t in TOOLS if t.key == "thread")):
        assert_plain(text)


# --- Several starts ---------------------------------------------------------------------


def crest_angles(tm, z):
    points, radius = radii_at(tm, z)
    crest = points[radius > radius.max() - 1e-3]
    return np.degrees(np.arctan2(crest[:, 1], crest[:, 0])) % 360


@pytest.mark.parametrize("starts", [2, 3, 4])
def test_several_starts_run_side_by_side_evenly_round(starts):
    tm = threads.thread_mesh({**M10, "starts": starts})
    assert tm.is_watertight and tm.bounds[:, 2].tolist() == pytest.approx([0, 20])
    # The same ridges, as much thread: the pitch is still ridge to ridge.
    assert tm.volume == pytest.approx(threads.thread_mesh(M10).volume, rel=0.01)
    # A crest every 1/starts of a turn round.
    angles = crest_angles(tm, 7.3)
    for k in range(starts):
        target = (angles[0] + 360.0 * k / starts) % 360
        assert np.min(np.abs((angles - target + 180) % 360 - 180)) < 6
    # Each thread rises the pitch times the starts in one turn (its lead):
    # a quarter of the pitch higher, the crests have turned anticlockwise
    # by a quarter turn divided by the starts.
    shifted = (crest_angles(tm, 5.0) + 90.0 / starts) % 360
    high = crest_angles(tm, 5.0 + 1.5 / 4)
    for a in shifted:
        assert np.min(np.abs((high - a + 180) % 360 - 180)) < 3


def test_a_two_start_bolt_screws_into_a_two_start_hole_but_not_a_one_start_one():
    bolt = threads.thread_mesh({**M10, "starts": 2})
    for fit in (0.0, 0.2):
        assert outside(bolt, threads.thread_mesh({**M10, "starts": 2}, fit)) == pytest.approx(0, abs=1e-6)
    assert outside(threads.thread_mesh(M10), threads.thread_mesh({**M10, "starts": 2}, 0.2)) > 1.0
    part = threads.thread_mesh({**M10, "starts": 2, "thread_length": 12.0, "end": "bottom"}, 0.1)
    short = threads.thread_mesh({**M10, "starts": 2, "height": 12.0, "thread_length": 12.0})
    assert outside(short, part) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("starts, words", [
    (0, "1 to 4 starts"), (5, "1 to 4 starts"), (1.5, "whole number"),
])
def test_starts_that_cannot_make_a_thread_are_refused(starts, words):
    with pytest.raises(threads.ThreadError) as err:
        threads.thread_mesh({**M10, "starts": starts})
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_several_starts_count_towards_the_most_turns():
    long = {"diameter": 10.0, "pitch": 1.0, "height": 100.0, "thread_length": 100.0}
    assert threads.thread_mesh(long).is_watertight
    with pytest.raises(threads.ThreadError) as err:
        threads.thread_mesh({**long, "starts": 2})
    assert "counting each start" in str(err.value)
    assert_plain(str(err.value))


def test_a_thread_made_before_starts_existed_has_one():
    assert threads.thread_mesh(M10).volume == pytest.approx(threads.thread_mesh({**M10, "starts": 1}).volume)
    assert "starts" not in create.threaded(new_primitive("cylinder"), 2.5, 20.0).params
    made = create.threaded(new_primitive("cylinder"), 2.5, 20.0, starts=3)
    assert made.params["starts"] == 3


def test_a_several_start_thread_round_trips_through_a_project_file(tmp_path):
    thread = create.threaded(new_primitive("cylinder"), 2.5, 12.0, starts=2)
    file = tmp_path / "two.mesh"
    save_project(Scene(shapes=[thread]), file)
    loaded = load_project(file).shapes[0]
    assert loaded.params == thread.params
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(thread).volume)


def test_starts_in_the_form_and_the_details_panel(window, monkeypatch, warnings):
    monkeypatch.setattr(expert_actions, "ask_thread", lambda parent, height, standard, pitch: {
        "pitch": pitch, "length": 20.0, "end": "top", "hand": "right", "starts": 2})
    window.add_primitive("cylinder")
    thread = window.document.scene.shapes[0]
    steps = len(window.document._undo)
    window.do_thread()
    assert thread.params["starts"] == 2 and len(window.document._undo) == steps + 1
    assert "starts" in window.inspector.visible_param_fields()
    assert window.inspector.field_value("starts") == 2
    window._on_edited(thread.id, "starts", 4.0)
    window._finish_edit()
    assert thread.params["starts"] == 4
    window._on_edited(thread.id, "starts", 2.5)
    assert thread.params["starts"] == 4 and warnings and "whole number" in warnings[0]
    window.do_undo()
    assert window.document.scene.shapes[0].params["starts"] == 2
    window.do_undo()
    assert window.document.scene.shapes[0].params["primitive"] == "cylinder"


def test_a_one_start_thread_shows_one_start_in_the_details_panel(window):
    window.add_primitive("cylinder")
    window.thread_selected(2.5, 20.0)
    assert window.inspector.field_value("starts") == 1
    assert_plain(FIELD_LABELS["starts"])
