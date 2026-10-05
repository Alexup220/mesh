"""The history list (Expert mode, Phase 5): recorded, changed, replayed."""

import copy
import json

import numpy as np
import pytest

from mesh import history, history_actions, sketch
from mesh.expert import TOOLS
from mesh.history import HistoryError
from mesh.io_formats import load_project
from mesh.scene import Document, Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

RECT = [{"type": "rectangle", "corner": [0, 0], "width": 20, "height": 10}]
BAND = [{"type": "rectangle", "corner": [5, 0], "width": 5, "height": 20}]
SQUARE = [{"type": "rectangle", "corner": [-2, -2], "width": 4, "height": 4}]
ELBOW = [{"type": "line", "start": [0, 0], "end": [0, 20]}, {"type": "line", "start": [0, 20], "end": [30, 20]}]
LINE = [{"type": "line", "start": [0, 0], "end": [60, 0]}]
BIG = [{"type": "rectangle", "corner": [-10, -10], "width": 20, "height": 20}]
SMALL = [{"type": "rectangle", "corner": [-5, -5], "width": 10, "height": 10}]


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


def face_towards(shape, direction, near=None):
    """A triangle of `shape` facing `direction` (the one nearest `near`)."""
    tm = shape_geometry(shape)
    facing = tm.face_normals @ np.asarray(direction, dtype=np.float64) > 1.0 - 1e-9
    if near is None:
        return int(np.flatnonzero(facing)[0])
    distance = np.linalg.norm(tm.triangles_center - np.asarray(near), axis=1)
    return int(np.flatnonzero(facing)[np.argmin(distance[facing])])


def summary(scene):
    """Each shape's id, name, kind, Hole, bounds and surface area."""
    out = []
    for shape in scene.shapes:
        tm = shape_geometry(shape, scene.fit_clearances)
        out.append((shape.id, shape.name, shape.kind, shape.is_hole, shape.visible, shape.component,
                    np.round(tm.bounds, 3).tolist(), round(float(tm.area), 2)))
    return out + [scene.components]


def add(window, kind="cube", dx=0.0):
    window.add_primitive(kind)
    if dx:
        window.move_copy_selected(dx=dx)
    return window.document.scene.selected()[0]


def add_sketch(window, entities, frame=None, name=None):
    window.add_sketch(entities, np.eye(4) if frame is None else frame, name)
    return window.document.scene.selected()[0]


def pick(window, *shapes):
    window.document.scene.select([s.id for s in shapes])


# --- What a step changed ---------------------------------------------------------------


def test_changes_apply_to_the_scene_before_to_give_the_scene_after():
    a, b = new_primitive("cube"), new_primitive("cylinder")
    before = Scene(shapes=[a, b])
    after = copy.deepcopy(before)
    after.shapes[0].params["width"] = 35.0
    after.shapes[0].transform[0, 3] = 12.0
    after.shapes[0].name = "Lid"
    after.remove([b.id])
    added = new_primitive("sphere")
    after.add(added)
    after.fit_clearances = {"press": 0.1, "snug": 0.3, "loose": 0.4}
    effect = history.changes(before, after)
    assert [d["id"] for d in effect["added"]] == [added.id] and effect["removed"] == [b.id]
    assert set(effect["changed"][a.id]) == {"params", "move", "name"}
    assert effect["changed"][a.id]["params"] == {"width": 35.0}
    assert effect["settings"] == {"fit_clearances": after.fit_clearances}
    assert effect["names"][1:] == ["Lid"]  # the parts made or changed
    json.dumps(effect)  # a project file can hold it
    replayed = copy.deepcopy(before)
    history.apply_changes(replayed, effect)
    assert summary(replayed) == summary(after)
    assert replayed.fit_clearances == after.fit_clearances and replayed.shapes[0].name == "Lid"


def test_a_move_replays_as_a_move_from_wherever_the_part_is():
    box = new_primitive("cube")
    before = Scene(shapes=[box])
    after = copy.deepcopy(before)
    after.shapes[0].transform[1, 3] = 5.0
    effect = history.changes(before, after)
    elsewhere = copy.deepcopy(before)
    elsewhere.shapes[0].transform[0, 3] = 40.0
    history.apply_changes(elsewhere, effect)
    assert np.allclose(elsewhere.shapes[0].transform[:3, 3], [40.0, 5.0, 0.0])


def test_a_dropped_setting_is_dropped_again():
    box = new_primitive("cube")
    box.params["extra"] = 1
    before = Scene(shapes=[box])
    after = copy.deepcopy(before)
    del after.shapes[0].params["extra"]
    effect = history.changes(before, after)
    assert effect["changed"][box.id]["drop"] == ["extra"]
    history.apply_changes(before, effect)
    assert "extra" not in before.shapes[0].params


def test_changes_to_a_part_that_is_gone_are_refused():
    box = new_primitive("cube")
    before = Scene(shapes=[box])
    after = copy.deepcopy(before)
    after.shapes[0].params["width"] = 5.0
    with pytest.raises(HistoryError) as err:
        history.apply_changes(Scene(), history.changes(before, after))
    assert_plain(str(err.value))
    with pytest.raises(HistoryError):
        history.apply_changes(after, history.changes(Scene(), after))  # already there


def test_replayed_parts_get_back_the_ids_later_steps_use():
    scene = Scene(shapes=[new_primitive("cube")])
    before = {s.id for s in scene.shapes}
    made = [new_primitive("cube"), new_primitive("sphere")]
    for shape in made:
        scene.add(shape)
    scene.select([made[1].id])
    history.rename_added(scene, before, ["first", "second"])
    assert [s.id for s in scene.shapes[1:]] == ["first", "second"] and scene.selection == ["second"]


def test_plain_settings():
    assert history.plain({"a": (1, np.float64(2.5)), "b": np.eye(2)}) == {"a": [1, 2.5], "b": [[1, 0], [0, 1]]}
    with pytest.raises(TypeError):
        history.plain(new_primitive("cube"))


# --- Finding a clicked face again -------------------------------------------------------


def test_a_face_is_found_again_on_a_part_that_grew():
    box = new_primitive("cube")
    index = face_towards(box, (1, 0, 0))
    hint = history.face_hint(box, index, None)
    box.params["width"] = 40.0
    found, moved = history.find_face(box, index, hint, None)
    assert found == index and np.allclose(moved, [10.0, 0.0, 0.0])


def test_a_face_is_found_again_when_the_triangles_changed():
    box = new_primitive("cube")
    index = face_towards(box, (0, 0, 1))
    hint = history.face_hint(box, index, None)
    round_part = new_primitive("cylinder")
    found, _moved = history.find_face(round_part, 0, hint, None)
    tm = shape_geometry(round_part)
    assert tm.face_normals[found] @ np.array([0, 0, 1.0]) > 0.999
    assert tm.triangles_center[found][2] == pytest.approx(tm.bounds[1][2])


def test_a_face_that_is_gone_is_refused():
    box = new_primitive("cube")
    hint = {"centre": [0, 0, 0], "normal": list(np.ones(3) / np.sqrt(3))}
    with pytest.raises(HistoryError) as err:
        history.find_face(box, 0, hint, None)
    assert "no longer on Box" in str(err.value)
    assert_plain(str(err.value))


# --- Recording ---------------------------------------------------------------------------


def test_nothing_is_recorded_until_a_history_is_kept():
    document = Document()
    document.snapshot("add")
    document.scene.add(new_primitive("cube"))
    assert document.scene.history is None


def test_each_snapshot_is_a_step_and_its_changes_are_worked_out_later():
    document = Document()
    document.scene.history = history.start(document.scene)
    document.snapshot("add")
    box = new_primitive("cube")
    document.scene.add(box)
    steps = document.scene.history["steps"]
    assert steps == [{"label": "add", "call": None, "effect": None}]
    document.snapshot("edit")
    box.params["width"] = 30.0
    steps = document.scene.history["steps"]
    assert [d["id"] for d in steps[0]["effect"]["added"]] == [box.id]
    assert steps[0]["effect"]["added"][0]["params"]["width"] == 20.0  # as it was added
    document.settle()
    assert steps[1]["effect"]["changed"][box.id]["params"] == {"width": 30.0}


def test_undo_takes_the_step_off_and_redo_puts_it_back():
    document = Document()
    document.scene.history = history.start(document.scene)
    document.snapshot("add")
    document.scene.add(new_primitive("cube"))
    document.undo()
    assert document.scene.history["steps"] == []
    document.redo()
    steps = document.scene.history["steps"]
    assert len(steps) == 1 and steps[0]["effect"]["added"]


def test_a_history_from_a_file_is_checked():
    assert history.read({"base": {}, "steps": [{"label": "x", "call": None, "effect": None}]})["steps"]
    for broken in (None, [], {"base": {}}, {"base": {}, "steps": [1]},
                   {"base": {}, "steps": [{"call": {"method": 3, "args": {}}}]},
                   {"base": {}, "steps": [{"effect": []}]}):
        assert history.read(broken) is None


# --- In the window -----------------------------------------------------------------------


def test_starting_and_stopping_are_undo_steps_but_not_history_steps(window):
    add(window)
    assert window.start_history() and not window.start_history()
    assert window.statusBar().currentMessage() == window.HISTORY_STARTED
    assert window.history_steps() == []
    base = window.document.scene.history["base"]
    assert len(base["shapes"]) == 1 and "history" not in base
    assert window.stop_history() and window.document.scene.history is None
    window.do_undo()
    assert window.document.scene.history is not None
    window.do_undo()
    assert window.document.scene.history is None and len(window.document.scene.shapes) == 1


def test_a_tool_records_its_call_and_where_its_face_was(window):
    window.start_history()
    box = add(window)
    face = face_towards(box, (0, 0, 1))
    assert window.round_edge(box.id, face, np.array([10.0, 0.0, 20.0]), 3.0)
    steps = window.history_steps()
    assert [s["label"] for s in steps] == ["add", "round edge"]
    call = steps[1]["call"]
    assert call["method"] == "round_edge" and call["picked"] == [box.id]
    assert call["args"] == {"shape_id": box.id, "face_index": face, "point": [10.0, 0.0, 20.0], "radius": 3.0}
    assert np.allclose(call["faces"][0]["normal"], [0, 0, 1])
    assert steps[0]["call"] is None
    assert history.describe(steps[1]).startswith("Round edge: ")


def scenario_extrude(window):
    add_sketch(window, RECT)
    window.extrude_selected(5.0, keep_sketch=True)


def scenario_revolve(window):
    add_sketch(window, BAND)
    window.revolve_selected("y", 270.0)


def scenario_sweep(window):
    add_sketch(window, ELBOW, sketch.named_plane_frame("xz"), "Path")
    add_sketch(window, SQUARE, None, "Outline")
    window.do_select_all()
    window.sweep_selected()


def scenario_loft(window):
    first = add_sketch(window, BIG)
    second = add_sketch(window, SMALL, sketch.named_plane_frame("xy", 15.0))
    pick(window, first, second)
    window.loft_selected()


def scenario_thread(window):
    add(window, "cylinder")
    window.thread_selected(1.5, 10.0)


def scenario_move_copy(window):
    add(window)
    window.move_copy_selected(5.0, 0.0, 0.0, "z", 30.0, make_copy=True)


def scenario_scale(window):
    add(window)
    window.scale_selected(150.0, stretch_z=50.0)


def two_boxes(window):
    first = add(window)
    second = add(window, dx=10.0)
    pick(window, first, second)
    return first, second


def scenario_combine(window):
    two_boxes(window)
    window.combine_selected(op="difference")


def scenario_split_body(window):
    first, _second = two_boxes(window)
    window.split_body_selected(first.id, keep_tool=True)


def scenario_shell(window):
    box = add(window)
    window.shell_face(box.id, face_towards(box, (0, 0, 1)), 2.0)


def scenario_push_pull(window):
    box = add(window)
    window.push_pull_face(box.id, face_towards(box, (1, 0, 0)), 5.0)


def scenario_round_edge(window):
    box = add(window)
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 3.0)


def scenario_bevel_edge(window):
    box = add(window)
    window.bevel_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 2.0)


def scenario_draft(window):
    add(window)
    window.draft_selected(5.0)


def scenario_rectangular(window):
    add(window)
    window.rectangular_pattern_selected(3, 30.0, "x", 2, 25.0, "y")


def scenario_circular(window):
    add(window)
    window.circular_pattern_selected(4, "z", (40.0, 0.0, 0.0), 360.0)


def scenario_path(window):
    box = add(window)
    path = add_sketch(window, LINE)
    pick(window, box, path)
    window.path_pattern_selected(3)


def scenario_mirror_copy(window):
    add(window, dx=20.0)
    window.mirror_copy_selected("x")


def scenario_mirror_across_face(window):
    first, second = two_boxes(window)
    window.mirror_across_face(second.id, face_towards(second, (1, 0, 0)), [first.id])


def scenario_plane_distance(window):
    window.plane_at_distance_selected("xy", 15.0)


def scenario_plane_face(window):
    box = add(window)
    window.plane_from_face(box.id, face_towards(box, (1, 0, 0)), 5.0)


def scenario_plane_angle(window):
    window.plane_at_angle_selected("z", 30.0)


def scenario_midplane(window):
    box = add(window)
    window.midplane_of_faces((box.id, face_towards(box, (1, 0, 0))), (box.id, face_towards(box, (-1, 0, 0))))


def two_planes(window, second_angle=None):
    window.plane_at_distance_selected("xy", 5.0)
    first = window.document.scene.selected()[0]
    if second_angle is None:
        window.plane_at_distance_selected("xy", 25.0)
    else:
        window.plane_at_angle_selected("z", second_angle)
    pick(window, first, window.document.scene.selected()[0])


def scenario_midplane_of_planes(window):
    two_planes(window)
    window.midplane_selected()


def scenario_axis_two_planes(window):
    two_planes(window, 0.0)
    window.axis_of_two_planes()


def scenario_axis_round(window):
    add(window, "cylinder")
    window.axis_of_round_parts()


def scenario_axis_square(window):
    box = add(window)
    window.axis_square_to(box.id, face_towards(box, (0, 0, 1)), (1.0, 2.0, 20.0))


def scenario_point(window):
    box = add(window)
    window.point_at(box.id, face_towards(box, (0, 0, 1)), (1.0, 2.0, 20.0))


def scenario_delete(window):
    first, _second = two_boxes(window)
    pick(window, first)
    window.do_delete()


def scenario_duplicate(window):
    add(window)
    window.do_duplicate()


def scenario_hole(window):
    add(window)
    window.do_toggle_hole()


def scenario_group(window):
    two_boxes(window)
    window.do_group()


def scenario_boolean(window):
    two_boxes(window)
    window.do_boolean("difference")


def scenario_ungroup(window):
    two_boxes(window)
    window.do_group()
    window.do_ungroup()


def scenario_mirror(window):
    add(window, "cone", dx=15.0)
    window.do_mirror("x")


def scenario_align(window):
    two_boxes(window)
    window.do_align("x", "min")


def scenario_hollow(window):
    add(window)
    window.hollow_selected(2.0)


def scenario_split(window):
    add(window)
    window.split_selected("z", 10.0)


def scenario_repeat_row(window):
    add(window)
    window.repeat_row_selected(3, 25.0)


def scenario_repeat_circle(window):
    add(window)
    window.repeat_circle_selected(4, 30.0, (-30.0, 0.0))


def scenario_links(window):
    window.set_parameters([{"name": "w", "formula": "30", "note": ""}])
    box = add(window)
    window.set_links(box.id, {"width": "w", "x": "w / 2"})


def scenario_details(window):
    box = add(window)
    window._on_edited(box.id, "width", 35.0)
    window._edit_active = False
    window._on_edited(box.id, "x", 12.0)
    window._edit_active = False
    window._on_edited(box.id, "color", "#ff0000")


def scenario_sketch_change(window):
    source = add_sketch(window, RECT)
    window.extrude_selected(5.0)
    part = window.document.scene.selected()[0]
    window.set_sketch_entities(part, BIG)
    assert source.id not in {s.id for s in window.document.scene.shapes}


def scenario_make_component(window):
    two_boxes(window)
    window.make_component()


def scenario_component_tools(window):
    two_boxes(window)
    window.make_component("Pair")
    made = window.document.scene.components[0]["id"]
    window.rename_component(made, "Gearbox")
    window.set_component_shown(made, False)
    window.set_component_shown(made, True)
    window.copy_component(made)
    window.leave_component()
    window.break_apart_component(made)


def scenario_components_inside_components(window):
    two_boxes(window)
    window.make_component("Pair")
    pair = window.document.scene.components[0]["id"]
    window.document.scene.select([window.document.scene.shapes[0].id])
    window.make_component("Half")
    half = window.document.scene.components[1]["id"]
    window.put_component_inside(half)
    window.put_component_inside(half, pair)
    window.copy_component(pair)
    window.break_apart_component(pair)


def scenario_component_keeps_what_a_tool_makes(window):
    box = add(window)
    window.make_component()
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 3.0)
    assert window.document.scene.shapes[0].component == window.document.scene.components[0]["id"]


SCENARIOS = {name[len("scenario_"):]: fn for name, fn in globals().items() if name.startswith("scenario_")}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_replaying_an_unchanged_history_gives_the_same_project(window, warnings, name):
    window.start_history()
    SCENARIOS[name](window)
    assert not warnings
    steps = window.history_steps()
    assert steps and steps[-1]["effect"] is not None
    replayed = window._replayed(steps)
    assert summary(replayed) == summary(window.document.scene)
    assert [s["label"] for s in replayed.history["steps"]] == [s["label"] for s in steps]


def test_every_tool_in_the_scenarios_is_replayed_as_a_tool(window):
    """The scenarios cover every method marked @replayable."""
    from mesh.app import MeshWindow

    marked = {name for name in dir(MeshWindow) if hasattr(getattr(MeshWindow, name), "replay_faces")}
    import inspect

    source = inspect.getsource(__import__("test_history"))
    assert {name for name in marked if f"window.{name}(" not in source} == set()


def round_then_pattern(window):
    window.start_history()
    box = add(window)
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 2.0)
    window.rectangular_pattern_selected(3, 30.0)
    return window.document.scene


def test_changing_a_step_works_the_later_steps_out_again(window):
    scene = round_then_pattern(window)
    ids = [s.id for s in scene.shapes]
    volumes = [shape_geometry(s).volume for s in scene.shapes]
    assert window.change_history_step(1, {"radius": 6.0})
    scene = window.document.scene
    assert [s.id for s in scene.shapes] == ids
    after = [shape_geometry(s).volume for s in scene.shapes]
    assert all(a < v - 1.0 for a, v in zip(after, volumes))
    assert after == pytest.approx([after[0]] * 3)
    assert scene.history["steps"][1]["call"]["args"]["radius"] == 6.0
    window.do_undo()
    assert [shape_geometry(s).volume for s in window.document.scene.shapes] == pytest.approx(volumes)
    assert window.history_steps()[1]["call"]["args"]["radius"] == 2.0


def test_changing_a_pattern_count_adds_copies(window):
    round_then_pattern(window)
    assert window.change_history_step(2, {"count": 5})
    assert len(window.document.scene.shapes) == 5
    assert window.change_history_step(2, {"count": 2})
    assert len(window.document.scene.shapes) == 2


def test_removing_a_step(window, warnings):
    round_then_pattern(window)
    assert window.remove_history_step(2)
    assert len(window.document.scene.shapes) == 1 and len(window.history_steps()) == 2
    steps = len(window.document._undo)
    assert not window.remove_history_step(0)
    assert warnings and warnings[0].startswith("Step 2 (Round edge: ")
    assert "a part it was used on is no longer there" in warnings[0]
    assert len(window.document._undo) == steps and len(window.history_steps()) == 2
    assert_plain(warnings[0])


def test_skipping_a_step_and_using_it_again(window, warnings):
    round_then_pattern(window)
    steps = len(window.document._undo)
    assert window.skip_history_step(2)
    assert len(window.document.scene.shapes) == 1 and len(window.history_steps()) == 3
    assert window.history_steps()[2]["off"] is True
    assert history.describe(window.history_steps()[2]).endswith(" (skipped)")
    assert not window.skip_history_step(2)
    # A skipped step can still be changed; it stays skipped.
    assert window.change_history_step(2, {"count": 4})
    assert len(window.document.scene.shapes) == 1
    assert window.skip_history_step(2, False)
    assert len(window.document.scene.shapes) == 4 and "off" not in window.history_steps()[2]
    assert not warnings and len(window.document._undo) == steps + 3
    window.do_undo()
    window.do_undo()
    assert len(window.document.scene.shapes) == 1 and window.history_steps()[2]["off"] is True


def test_a_step_a_later_one_needs_cannot_be_skipped(window, warnings):
    scene = round_then_pattern(window)
    before = summary(scene)
    assert not window.skip_history_step(1)
    assert warnings and warnings[0].startswith("Step 3 (Pattern in rows: ")
    assert summary(window.document.scene) == before and "off" not in window.history_steps()[1]
    assert_plain(warnings[0])


def test_a_skipped_step_is_saved_with_the_project(window, tmp_path):
    round_then_pattern(window)
    window.skip_history_step(2)
    file = tmp_path / "skipped.mesh"
    window.save_to(file)
    loaded = load_project(file)
    assert [s.get("off", False) for s in loaded.history["steps"]] == [False, False, True]
    assert history.read({"base": {}, "steps": [{"label": "x", "off": "yes"}]})["steps"][0].get("off") is None
    window.open_from(file)
    assert window.skip_history_step(2, False) and len(window.document.scene.shapes) == 3


def test_moving_a_step(window, warnings):
    window.start_history()
    box = add(window)
    ball = add(window, "sphere")
    # The sphere is still selected when the box's edge is clicked: that
    # doesn't tie the rounding to it.
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 2.0)
    assert window.history_steps()[2]["call"]["picked"] == [ball.id]
    before = summary(window.document.scene)
    steps = len(window.document._undo)
    assert window.move_history_step(2, 1)
    assert [history.describe(s).split(":")[0] for s in window.history_steps()] == ["Add", "Round edge", "Add"]
    # The same parts, the sphere now made last.
    assert sorted(map(repr, summary(window.document.scene))) == sorted(map(repr, before)) and not warnings
    assert window.document.scene.shapes[-1].id == ball.id
    assert len(window.document._undo) == steps + 1
    assert not window.move_history_step(1, 1) and not window.move_history_step(1, 3)
    window.do_undo()
    assert [s["label"] for s in window.history_steps()] == ["add", "add", "round edge"]


def test_a_step_cannot_move_before_the_one_that_makes_its_part(window, warnings):
    scene = round_then_pattern(window)
    before = summary(scene)
    assert not window.move_history_step(2, 1)
    assert warnings and warnings[0].startswith("Step 3 (Pattern in rows: ")
    assert warnings[0].endswith("a part it uses is only made by a later step.")
    assert summary(window.document.scene) == before
    assert [s["label"] for s in window.history_steps()] == ["add", "round edge", "pattern in rows"]
    assert_plain(warnings[0])
    # Moving the step that makes a part after the one that uses it: the
    # user is told about the step that now comes too early.
    assert not window.move_history_step(0, 2)
    assert warnings[-1].startswith("Step 2 (Round edge: ") and warnings[-1].endswith("by a later step.")


def test_a_moved_step_is_saved_with_the_project(window, tmp_path):
    window.start_history()
    add(window)
    add(window, "sphere")
    assert window.move_history_step(1, 0)
    file = tmp_path / "moved.mesh"
    window.save_to(file)
    loaded = load_project(file)
    assert [s["effect"]["names"] for s in loaded.history["steps"]] == [["Sphere"], ["Box"]]


FIELDS = [("radius", "Radius (mm)", 2.0, {"min": 0.1, "max": 100.0}), ("count", "Copies", 3, {"min": 2}),
          ("keep", "Keep it", True, {}), ("axis", "Along", "x", {"choices": [("x", "x")]})]


def test_formulas_in_a_steps_settings_are_worked_out_through_its_form():
    assert [f[0] for f in history.number_fields(FIELDS)] == ["radius", "count"]
    assert history.field_words("Radius (mm)") == "Radius"
    worked = history.formula_values(FIELDS, {"radius": "w / 4", "count": "n + 0.6", "gone": "w"},
                                     {"w": 20.0, "n": 2.0})
    assert worked == {"radius": 5.0, "count": 3} and isinstance(worked["count"], int)
    for formulas, words in (({"radius": "w * 10"}, "Radius would be 200, which it can't be."),
                            ({"count": "1"}, "Copies would be 1, which it can't be."),
                            ({"radius": "q"}, "which is not a parameter")):
        with pytest.raises(history.parameters.ParameterError) as err:
            history.formula_values(FIELDS, formulas, {"w": 20.0})
        assert words in str(err.value)
        assert_plain(str(err.value))


def test_formulas_from_a_file_are_checked():
    raw = {"base": {}, "steps": [{"label": "x", "call": {"method": "m", "args": {}, "formulas": {"a": "w", "b": 3}}},
                                 {"label": "y", "call": {"method": "m", "args": {}, "formulas": "w"}}]}
    steps = history.read(raw)["steps"]
    assert steps[0]["call"]["formulas"] == {"a": "w"} and "formulas" not in steps[1]["call"]


def rounded_box_with(window, formula="w / 4"):
    window.set_parameters([{"name": "w", "formula": "8", "note": ""}])
    window.start_history()
    box = add(window)
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 1.0)
    assert window.set_step_formulas(1, {"radius": formula})
    return window.document.scene


def test_a_steps_setting_can_follow_a_parameter(window, warnings):
    scene = rounded_box_with(window)
    call = window.history_steps()[1]["call"]
    assert call["formulas"] == {"radius": "w / 4"} and call["args"]["radius"] == 2.0
    volume = shape_geometry(scene.shapes[0]).volume
    assert window.set_parameters([{"name": "w", "formula": "12", "note": ""}])
    assert window.history_steps()[1]["call"]["args"]["radius"] == 3.0
    assert shape_geometry(window.document.scene.shapes[0]).volume < volume - 1.0
    assert not warnings
    window.do_undo()
    assert window.history_steps()[1]["call"]["args"]["radius"] == 2.0
    window.do_undo()
    assert "formulas" not in window.history_steps()[1]["call"]


def test_a_count_and_a_point_can_follow_parameters(window):
    window.set_parameters([{"name": "n", "formula": "4", "note": ""}, {"name": "c", "formula": "50", "note": ""}])
    window.start_history()
    add(window)
    window.circular_pattern_selected(3, "z", (100.0, 0.0, 0.0))
    assert window.set_step_formulas(1, {"count": "n", "centre_x": "c * 2 - 40"})
    assert len(window.document.scene.shapes) == 4
    assert window.history_steps()[1]["call"]["args"]["centre"] == [60.0, 0.0, 0.0]
    assert window.set_parameters([{"name": "n", "formula": "2.4", "note": ""}, {"name": "c", "formula": "50", "note": ""}])
    assert len(window.document.scene.shapes) == 2


def test_formulas_that_cannot_be_used_change_nothing(window, warnings):
    scene = rounded_box_with(window)
    before = summary(scene)
    assert not window.set_step_formulas(1, {"radius": "depth"})
    assert "\"depth\", which is not a parameter" in warnings[-1]
    assert not window.set_step_formulas(1, {"radius": "w * 3"})  # too big for the box's edge
    assert warnings[-1].startswith("Step 2 (")
    assert not window.set_parameters([{"name": "w", "formula": "100", "note": ""}])
    assert warnings[-1].startswith("Step 2 (") and "Radius would be 25" not in warnings[-1]
    assert summary(window.document.scene) == before
    assert window.history_steps()[1]["call"]["formulas"] == {"radius": "w / 4"}
    for text in warnings:
        assert_plain(text)


def test_a_typed_number_ends_a_formula(window, monkeypatch):
    rounded_box_with(window)
    assert window.set_step_formulas(1, {"radius": "3"})
    call = window.history_steps()[1]["call"]
    assert "formulas" not in call and call["args"]["radius"] == 3.0
    window.set_step_formulas(1, {"radius": "w / 4"})
    # Change... with the number left as it was keeps the formula ...
    monkeypatch.setattr(history_actions, "run_form", lambda *a, **k: {"radius": 2.0})
    window.ask_step_change(1)
    assert window.history_steps()[1]["call"]["formulas"] == {"radius": "w / 4"}
    # ... and a new number ends it.
    monkeypatch.setattr(history_actions, "run_form", lambda *a, **k: {"radius": 1.5})
    assert window.ask_step_change(1)
    call = window.history_steps()[1]["call"]
    assert "formulas" not in call and call["args"]["radius"] == 1.5
    assert window.statusBar().currentMessage() == window.FORMULA_ENDED


def test_formulas_are_saved_with_the_project(window, tmp_path):
    rounded_box_with(window)
    file = tmp_path / "formulas.mesh"
    window.save_to(file)
    assert load_project(file).history["steps"][1]["call"]["formulas"] == {"radius": "w / 4"}
    window.open_from(file)
    assert window.set_parameters([{"name": "w", "formula": "4", "note": ""}])
    assert window.history_steps()[1]["call"]["args"]["radius"] == 1.0


def test_using_parameters_from_the_history_window(window, monkeypatch):
    window.start_history()
    box = add(window)
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 1.0)
    assert not window.ask_step_formulas(1)
    assert window.statusBar().currentMessage() == window.NO_PARAMETERS
    assert not window.ask_step_formulas(0)
    assert window.statusBar().currentMessage() == window.STEP_FIXED
    window.set_parameters([{"name": "w", "formula": "8", "note": ""}])
    seen = {}

    def fake_form(parent, title, fields, note=None):
        seen.update(title=title, fields=fields, note=note)
        return {"radius": "w / 8"}

    monkeypatch.setattr(history_actions, "run_form", fake_form)
    dialog = history_actions.HistoryDialog(window)
    assert not dialog.formulas_button.isHidden()
    dialog.steps.setCurrentRow(1)
    dialog.formulas()
    assert seen["title"] == "Use Parameters in Round an Edge"
    assert seen["fields"] == [("radius", "Radius (mm)", "1", {})]
    assert window.history_steps()[1]["call"]["formulas"] == {"radius": "w / 8"}
    for text in (seen["title"], seen["note"], window.FORMULA_ENDED, window.NO_PARAMETERS,
                 dialog.formulas_button.text()):
        assert_plain(text)
    dialog.deleteLater()


WIDE = [{"type": "rectangle", "corner": [0, 0], "width": 50, "height": 10}]


def sketch_then_extrude(window):
    window.start_history()
    drawn = add_sketch(window, RECT)
    window.extrude_selected(5.0, keep_sketch=True)
    part = window.document.scene.selected()[0]
    assert np.ptp(shape_geometry(part).bounds, axis=0)[0] == pytest.approx(20.0)
    return drawn, part


def test_changing_the_curves_a_step_drew(window, warnings):
    drawn, part = sketch_then_extrude(window)
    found = window.step_sketch(0)
    assert found[0] == drawn.id and found[2][0]["width"] == 20
    assert window.step_sketch(1) is None and window.step_editor(0) is None
    assert window.change_sketch_step(0, WIDE)
    scene = window.document.scene
    assert np.ptp(shape_geometry(scene.get(part.id)).bounds, axis=0)[0] == pytest.approx(50.0)
    assert scene.get(drawn.id).params["entities"][0]["width"] == 50.0
    assert window.history_steps()[0]["effect"]["added"][0]["params"]["entities"][0]["width"] == 50.0
    assert not warnings
    window.do_undo()
    assert np.ptp(shape_geometry(window.document.scene.get(part.id)).bounds, axis=0)[0] == pytest.approx(20.0)


def test_changing_a_change_sketch_step(window):
    drawn, part = sketch_then_extrude(window)
    window.set_sketch_entities(window.document.scene.get(drawn.id), SQUARE)
    assert window.step_sketch(2)[2] == window.document.scene.get(drawn.id).params["entities"]
    # Changing the sketch now leaves the part already made ...
    assert np.ptp(shape_geometry(window.document.scene.get(part.id)).bounds, axis=0)[0] == pytest.approx(20.0)
    # ... changing the step that drew it changes the part too.
    assert window.change_sketch_step(0, WIDE)
    assert np.ptp(shape_geometry(window.document.scene.get(part.id)).bounds, axis=0)[0] == pytest.approx(50.0)
    assert window.change_sketch_step(2, BIG)
    assert window.document.scene.get(drawn.id).params["entities"][0]["corner"] == [-10.0, -10.0]


def test_curves_a_later_step_cannot_use_are_refused(window, warnings):
    _drawn, part = sketch_then_extrude(window)
    before = summary(window.document.scene)
    assert not window.change_sketch_step(0, LINE)  # no closed outline to extrude
    assert warnings and warnings[-1].startswith("Step 2 (")
    assert not window.change_sketch_step(0, [{"type": "circle", "centre": [0, 0], "diameter": -1}])
    assert "diameter" in warnings[-1]
    assert summary(window.document.scene) == before
    for text in warnings:
        assert_plain(text)


def test_change_in_the_history_window_opens_the_sketch(window, monkeypatch):
    from mesh import sketch_editor

    _drawn, part = sketch_then_extrude(window)
    seen = {}

    def fake_sketch(parent, title, entities=(), guides=(), note=None):
        seen.update(title=title, entities=entities, note=note)
        return WIDE

    monkeypatch.setattr(sketch_editor, "edit_sketch", fake_sketch)
    assert window.ask_step_change(0)
    assert seen["title"] == "Change Sketch 1" and seen["entities"][0]["width"] == 20
    assert np.ptp(shape_geometry(window.document.scene.get(part.id)).bounds, axis=0)[0] == pytest.approx(50.0)
    assert_plain(seen["note"])


def test_using_a_step_on_other_parts(window, warnings):
    window.start_history()
    first = add(window)
    second = add(window, "sphere")
    window.document.scene.select([first.id])
    window.rectangular_pattern_selected(3, 30.0)
    assert {s.name for s in window.document.scene.shapes} == {"Box", "Sphere"} and len(window.document.scene.shapes) == 4
    steps = len(window.document._undo)
    assert window.retarget_history_step(2, [second.id])
    names = [s.name for s in window.document.scene.shapes]
    assert names.count("Sphere") == 3 and names.count("Box") == 1
    assert window.history_steps()[2]["call"]["picked"] == [second.id]
    assert len(window.document._undo) == steps + 1 and not warnings
    assert not window.retarget_history_step(2, [second.id])  # nothing new
    window.do_undo()
    assert [s.name for s in window.document.scene.shapes].count("Box") == 3


def test_a_step_cannot_be_used_on_parts_it_cannot_reach(window, warnings):
    window.start_history()
    box = add(window)
    window.rectangular_pattern_selected(2, 30.0)
    later = add(window, "sphere")
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 2.0)
    before = summary(window.document.scene)
    assert not window.retarget_history_step(1, [later.id])
    assert warnings and warnings[-1].endswith("a part it uses is only made by a later step.")
    assert not window.retarget_history_step(1, [])
    assert window.statusBar().currentMessage() == window.STEP_NEEDS_PARTS
    assert not window.retarget_history_step(3, [later.id])  # used on a clicked face
    assert window.statusBar().currentMessage() == window.STEP_NAMES_ITS_PARTS
    assert summary(window.document.scene) == before
    for text in (*warnings, window.STEP_NEEDS_PARTS, window.STEP_NAMES_ITS_PARTS):
        assert_plain(text)


def test_use_on_selection_in_the_history_window(window):
    window.start_history()
    first = add(window)
    second = add(window, "sphere")
    window.document.scene.select([first.id])
    window.rectangular_pattern_selected(2, 30.0)
    window.document.scene.select([second.id])
    dialog = history_actions.HistoryDialog(window)
    assert not dialog.retarget_button.isHidden()
    dialog.steps.setCurrentRow(2)
    dialog.retarget()
    assert dialog.steps.item(2).text() == "3. Pattern in rows: Sphere"
    dialog.deleteLater()


def test_a_change_that_cannot_be_worked_out_changes_nothing(window, warnings):
    scene = round_then_pattern(window)
    before = summary(scene)
    steps = len(window.document._undo)
    assert not window.change_history_step(1, {"radius": 30.0})
    assert warnings and warnings[0].startswith("Step 2 (")
    assert summary(window.document.scene) == before and len(window.document._undo) == steps
    assert window.history_steps()[1]["call"]["args"]["radius"] == 2.0


def test_a_step_with_no_settings_cannot_be_changed(window):
    window.start_history()
    add(window)
    assert not window.change_history_step(0, {"width": 3.0})
    assert window.step_editor(0) is None
    assert not window.ask_step_change(0)
    assert window.statusBar().currentMessage() == window.STEP_FIXED


def test_new_parameters_work_the_whole_history_out_again(window):
    window.set_parameters([{"name": "w", "formula": "40", "note": ""}])
    window.start_history()
    box = add(window)
    window.set_links(box.id, {"width": "w"})
    window.round_edge(box.id, face_towards(box, (1, 0, 0)), (20.0, 0.0, 20.0), 3.0)
    window.rectangular_pattern_selected(2, 80.0)
    assert window.set_parameters([{"name": "w", "formula": "60", "note": ""}])
    scene = window.document.scene
    assert len(scene.shapes) == 2 and scene.parameters[0]["formula"] == "60"
    for shape in scene.shapes:
        size = np.ptp(shape_geometry(shape).bounds, axis=0)
        assert size[0] == pytest.approx(60.0)
    assert len(window.history_steps()) == 4  # changing parameters is not a step
    window.do_undo()
    assert np.ptp(shape_geometry(window.document.scene.shapes[0]).bounds, axis=0)[0] == pytest.approx(40.0)


def test_parameters_that_break_a_later_step_are_refused(window, warnings):
    window.set_parameters([{"name": "w", "formula": "40", "note": ""}])
    window.start_history()
    box = add(window)
    window.set_links(box.id, {"height": "w"})
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 40.0), 8.0)
    assert not window.set_parameters([{"name": "w", "formula": "5", "note": ""}])
    assert warnings and "Step 3 (" in warnings[0]
    assert window.document.scene.parameters[0]["formula"] == "40"


def test_a_history_is_saved_and_opened_with_the_project(window, tmp_path):
    round_then_pattern(window)
    file = tmp_path / "kept.mesh"
    window.save_to(file)
    document = json.loads(file.read_text())
    assert document["format_version"] == 2 and len(document["scene"]["history"]["steps"]) == 3
    window.open_from(file)
    assert [s["label"] for s in window.history_steps()] == ["add", "round edge", "pattern in rows"]
    assert window.change_history_step(1, {"radius": 4.0})
    loaded = load_project(file)
    assert loaded.history["steps"][1]["call"]["args"]["radius"] == 2.0


def test_the_history_window(window, monkeypatch):
    dialog = history_actions.HistoryDialog(window)
    assert dialog.note.text() == history_actions.NOT_KEPT_NOTE and dialog.steps.count() == 0
    assert not dialog.change_button.isEnabled()
    dialog.start()
    assert window.document.scene.history is not None
    assert dialog.note.text() == history_actions.HISTORY_NOTE
    box = add(window)
    window.round_edge(box.id, face_towards(box, (0, 0, 1)), (10.0, 0.0, 20.0), 2.0)
    dialog.refresh()
    assert [dialog.steps.item(i).text() for i in range(2)] == ["1. Add: Box", f"2. Round edge: {window.document.scene.shapes[0].name}"]
    seen = {}

    def fake_form(parent, title, fields, note=None):
        seen.update(title=title, fields=fields)
        return {"radius": 5.0}

    monkeypatch.setattr(history_actions, "run_form", fake_form)
    dialog.steps.setCurrentRow(1)
    dialog.change()
    assert seen["title"] == "Change Round an Edge" and seen["fields"][0][2] == 2.0
    assert window.history_steps()[1]["call"]["args"]["radius"] == 5.0
    dialog.steps.setCurrentRow(1)
    assert dialog.skip_button.text() == "Skip"
    dialog.skip()
    assert dialog.steps.item(1).text().endswith(" (skipped)") and dialog.skip_button.text() == "Use Again"
    dialog.skip()
    assert not dialog.steps.item(1).text().endswith(" (skipped)") and dialog.skip_button.text() == "Skip"
    dialog.remove()
    assert dialog.steps.count() == 1
    dialog.stop()
    assert window.document.scene.history is None and dialog.steps.count() == 0
    dialog.deleteLater()


def test_moving_steps_in_the_history_window(window):
    dialog = history_actions.HistoryDialog(window)
    dialog.start()
    assert not dialog.up_button.isEnabled()
    add(window)
    add(window, "sphere")
    dialog.refresh()
    assert dialog.up_button.isEnabled() and dialog.down_button.isEnabled()
    dialog.steps.setCurrentRow(1)
    dialog.move(-1)
    assert [dialog.steps.item(i).text() for i in range(2)] == ["1. Add: Sphere", "2. Add: Box"]
    assert dialog.steps.currentRow() == 0
    dialog.move(-1)  # already first: nothing moves
    dialog.move(1)
    assert [dialog.steps.item(i).text() for i in range(2)] == ["1. Add: Box", "2. Add: Sphere"]
    dialog.deleteLater()


SAMPLE_ARGS = {
    "distance": 5.0, "side": "one", "hole": False, "keep_sketch": False, "axis": "z", "angle": 30.0,
    "pitch": 1.5, "length": 10.0, "end": "top", "hand": "right", "dx": 1.0, "dy": 0.0, "dz": 0.0,
    "make_copy": False, "size": 100.0, "stretch_x": 100.0, "stretch_y": 100.0, "stretch_z": 100.0,
    "about": "base", "op": "union", "keep_tools": False, "keep_tool": False, "wall": 2.0, "far_side": False,
    "radius": 2.0, "count": 3, "spacing": 10.0, "count2": 1, "spacing2": 30.0, "axis2": "y",
    "centre": [0.0, 0.0, 0.0], "follow": False, "plane": "x", "open_top": False, "drain": 0.0,
    "pegs": False, "peg_diameter": 4.0,
}


@pytest.mark.parametrize("method", sorted(history_actions.editors()))
def test_each_step_form_is_the_tools_own_and_gives_settings_back(qapp, close_qt_widget, method):
    from mesh.app import MeshWindow
    from mesh.panels import FormDialog

    assert hasattr(getattr(MeshWindow, method), "replay_faces")
    title, fields, back = history_actions.editors()[method]
    form = close_qt_widget(FormDialog(None, f"Change {title}", fields(SAMPLE_ARGS), note=history_actions.STEP_NOTE))
    for text in form.labels():
        assert_plain(text)
    settings = back(form.values(), SAMPLE_ARGS)
    import inspect

    accepted = inspect.signature(getattr(MeshWindow, method)).parameters
    assert set(settings) <= set(accepted)


def test_history_text_is_plain_language(window):
    labels = ["", "add", "edit", "union", "difference", "intersection", "hole", "push/pull",
              "fit clearances", "round edge", "pattern in rows", "keep a history"]
    for text in (history_actions.HISTORY_NOTE, history_actions.NOT_KEPT_NOTE, history_actions.STEP_NOTE,
                 window.HISTORY_STARTED, window.HISTORY_STOPPED, window.STEP_FIXED,
                 *(history.label_words(label) for label in labels),
                 *(t.tip for t in TOOLS if t.key == "history")):
        assert_plain(text)
