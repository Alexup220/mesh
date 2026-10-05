"""Construction planes (Expert mode's Construct menu)."""

import numpy as np
import pytest

from mesh import construct, construct_actions, guides, modify, sketch, sketch_editor
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import is_reference, shape_geometry
from test_plain_language import assert_plain

SQUARE = [{"type": "rectangle", "corner": [0, 0], "width": 10, "height": 10}]


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


def face_towards(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=np.float64)))


def plane(shape):
    origin, normal = construct.plane_of(shape)
    return [np.round(origin, 6).tolist(), np.round(normal, 6).tolist()]


def box_at(x=0.0, y=0.0, z=0.0):
    box = new_primitive("cube")
    box.transform[:3, 3] = (x, y, z)
    return box


# --- The guide --------------------------------------------------------------------------


def test_a_plane_is_a_guide_drawn_as_a_square_that_faces_its_way():
    guide = construct.new_plane((0, 0, 5), (0, 0, 1), 40.0)
    assert is_reference(guide) and construct.is_guide(guide, "plane") and construct.is_flat_guide(guide)
    assert plane(guide) == [[0, 0, 5], [0, 0, 1]]
    assert shape_geometry(guide).bounds.tolist() == [[-20, -20, 5], [20, 20, 5]]
    square, tick = guides.guide_lines("plane", guide.params)
    assert len(square) == 5 and tick[1].tolist() == [0, 0, 6]  # the tick shows which way it faces


def test_a_plane_turned_in_the_details_panel_moves_with_its_transform():
    guide = construct.new_plane((0, 0, 0), (0, 0, 1))
    guide.transform[:3, 3] = (1, 2, 3)
    guide.transform[:3, :3] = sketch.plane_frame((1, 0, 0))[:3, :3]
    assert plane(guide) == [[1, 2, 3], [1, 0, 0]]


@pytest.mark.parametrize("name, distance, expected", [
    ("xy", 12.5, [[0, 0, 12.5], [0, 0, 1]]),
    ("xz", 15.0, [[0, -15, 0], [0, -1, 0]]),
    ("yz", -5.0, [[-5, 0, 0], [1, 0, 0]]),
])
def test_a_plane_moved_from_the_workplanes_planes(name, distance, expected):
    assert plane(construct.plane_from_named(name, distance)) == expected


def test_a_plane_moved_out_of_a_face_or_into_the_part():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    out = construct.plane_from_face(box, top, 5.0)
    assert plane(out) == [[0, 0, 25], [0, 0, 1]]
    assert out.params["size"] == 30.0  # drawn round the whole face
    assert plane(construct.plane_from_face(box, face_towards(box, (1, 0, 0)), -4.0)) == [[6, 0, 10], [1, 0, 0]]


def test_a_plane_parallel_to_a_sketch_or_another_plane():
    guide = construct.new_plane((0, 0, 0), (1, 0, 0), 80.0)
    guide.transform[:3, 3] = (15, 0, 0)
    assert plane(construct.plane_from_guide(guide, 5.0)) == [[20, 0, 0], [1, 0, 0]]
    drawing = sketch.plane_frame((0, -1, 0), (0, -10, 0))
    from mesh import create

    assert plane(construct.plane_from_guide(create.new_sketch(SQUARE, drawing), 2.0)) == [[0, -12, 0], [0, -1, 0]]


@pytest.mark.parametrize("line, angle, normal", [
    ("x", 90.0, [0, -1, 0]),   # the workplane tipped up to face the front
    ("y", 90.0, [1, 0, 0]),
    ("z", 0.0, [0, -1, 0]),    # around the upright line, 0 faces the front
    ("z", 90.0, [1, 0, 0]),
    ("x", 0.0, [0, 0, 1]),
])
def test_a_plane_at_an_angle_around_a_line(line, angle, normal):
    point, direction = construct.world_line(line)
    made = construct.plane_at_angle(point, direction, angle)
    assert plane(made) == [[0, 0, 0], normal]


def test_a_midplane_between_parallel_faces_is_halfway_across():
    box = new_primitive("cube")
    left = construct.face_of(box, face_towards(box, (-1, 0, 0)))
    right = construct.face_of(box, face_towards(box, (1, 0, 0)))
    origin, normal = plane(construct.midplane(left[:2], right[:2]))
    assert origin == [0, 0, 10] and abs(normal[0]) == 1
    low, high = box_at(), box_at(40.0, 0.0, 20.0)
    a = construct.face_of(low, face_towards(low, (0, 0, 1)))
    b = construct.face_of(high, face_towards(high, (0, 0, 1)))
    assert plane(construct.midplane(a[:2], b[:2])) == [[20, 0, 30], [0, 0, 1]]


def test_a_midplane_between_faces_at_an_angle_mirrors_one_onto_the_other():
    wedge = new_primitive("wedge")
    slope = construct.face_of(wedge, face_towards(wedge, (1, 0, 1)))
    bottom = construct.face_of(wedge, face_towards(wedge, (0, 0, -1)))
    origin, normal = construct.plane_of(construct.midplane(slope[:2], bottom[:2]))
    reflect = np.eye(3) - 2.0 * np.outer(normal, normal)
    mirrored_point = slope[0] - 2.0 * float((slope[0] - origin) @ normal) * normal
    assert float((mirrored_point - bottom[0]) @ bottom[1]) == pytest.approx(0.0, abs=1e-9)
    assert reflect @ slope[1] == pytest.approx(bottom[1])


def test_a_plane_through_three_points_faces_up_or_to_the_front():
    origin, normal = construct.plane_of(construct.plane_through_points((0, 0, 3), (0, 10, 3), (10, 0, 3)))
    assert origin == pytest.approx([10 / 3, 10 / 3, 3]) and normal == pytest.approx([0, 0, 1])
    upright = construct.plane_through_points((0, 0, 0), (0, 0, 10), (10, 0, 0))
    assert plane(upright)[1] == [0, -1, 0]


@pytest.mark.parametrize("points", [
    [(0, 0, 0), (10, 0, 0), (20, 0, 0)],
    [(1, 1, 1), (1, 1, 1), (5, 5, 5)],
])
def test_points_in_a_line_dont_fix_a_plane(points):
    with pytest.raises(BuildError) as err:
        construct.plane_through_points(*points)
    assert "in one line" in str(err.value)
    assert_plain(str(err.value))


def test_a_click_near_a_corner_lands_on_the_corner():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    assert construct.spot(box, top, (9.2, 8.9, 20.0)).tolist() == [10, 10, 20]
    assert construct.spot(box, top, (3.0, 4.0, 20.3)).tolist() == [3, 4, 20]


def test_a_guide_is_not_a_face_to_build_on():
    guide = construct.new_plane((0, 0, 0), (0, 0, 1))
    for tool in (lambda: construct.plane_from_face(guide, 0), lambda: construct.spot(guide, 0, (0, 0, 0))):
        with pytest.raises(BuildError):
            tool()


def test_a_construction_plane_splits_a_part():
    pieces = modify.split_body(new_primitive("cube"), construct.plane_from_named("xy", 5.0))
    assert sorted(round(shape_geometry(p).volume) for p in pieces) == [2000, 6000]


def test_a_construction_plane_is_never_a_part():
    with pytest.raises(BuildError) as err:
        modify.split_body(construct.plane_from_named("xy"), new_primitive("cube"))
    assert "construction plane is a guide" in str(err.value)
    assert_plain(str(err.value))


# --- In the window ----------------------------------------------------------------------


def add_box(window, x=0.0):
    window.add_primitive("cube")
    box = window.document.scene.shapes[-1]
    box.transform[0, 3] = x
    window.sync()
    return box


def test_a_plane_from_the_form_is_one_undo_step_and_numbered(window, monkeypatch):
    monkeypatch.setattr(construct_actions, "ask_plane_distance", lambda parent, selected: {
        "source": "xz", "distance": 20.0})
    steps = len(window.document._undo)
    window.do_plane_at_distance()
    window.do_plane_at_distance()
    shapes = window.document.scene.shapes
    assert [s.name for s in shapes] == ["Plane 1", "Plane 2"] and len(window.document._undo) == steps + 2
    assert plane(shapes[1]) == [[0, -20, 0], [0, -1, 0]] and window.document.scene.selection == [shapes[1].id]
    window.do_undo()
    assert [s.name for s in window.document.scene.shapes] == ["Plane 1"]


def test_a_plane_from_a_clicked_face(window, monkeypatch, qapp):
    seen = {}
    monkeypatch.setattr(construct_actions, "ask_plane_distance", lambda parent, selected: seen.update(
        selected=selected) or {"source": "face", "distance": 5.0})
    box = add_box(window)
    window.do_plane_at_distance()
    assert window.tool == "plane_face" and seen["selected"] is None
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (0, 0, 20))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()  # added once the click is over
    assert plane(window.document.scene.shapes[1]) == [[0, 0, 25], [0, 0, 1]]
    assert len(window.document._undo) == steps + 1


def test_the_form_offers_a_selected_sketch_or_plane(window, monkeypatch):
    seen = {}
    monkeypatch.setattr(construct_actions, "ask_plane_distance", lambda parent, selected: seen.update(
        selected=selected) or {"source": "selected", "distance": 3.0})
    window.add_sketch(SQUARE, sketch.plane_frame((1, 0, 0), (10, 0, 0)))
    window.do_plane_at_distance()
    assert seen["selected"] == "Sketch 1"
    assert plane(window.document.scene.shapes[1]) == [[13, 0, 0], [1, 0, 0]]


def test_a_plane_at_an_angle_from_the_form(window, monkeypatch):
    monkeypatch.setattr(construct_actions, "ask_plane_angle", lambda parent, lines: {"line": "y", "angle": 90.0})
    window.do_plane_at_angle()
    assert plane(window.document.scene.shapes[0]) == [[0, 0, 0], [1, 0, 0]]


def test_a_midplane_of_two_clicked_faces(window, qapp):
    box = add_box(window, 30.0)
    window.do_midplane()
    assert window.tool == "midplane"
    window._on_surface_picked(box.id, face_towards(box, (-1, 0, 0)), (20, 0, 10))
    assert window.tool == "midplane"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["midplane_second"]
    window._on_surface_picked(box.id, face_towards(box, (1, 0, 0)), (40, 0, 10))
    assert window.tool is None
    qapp.processEvents()
    origin, normal = plane(window.document.scene.shapes[1])
    assert origin == [30, 0, 10] and abs(normal[0]) == 1


def test_a_midplane_of_two_selected_planes_needs_no_clicks(window):
    window.plane_at_distance_selected("xy", 0.0)
    window.plane_at_distance_selected("xy", 30.0)
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_midplane()
    assert window.tool is None
    assert plane(window.document.scene.shapes[2]) == [[0, 0, 15], [0, 0, 1]]


def test_a_plane_through_three_clicked_points(window, qapp):
    box = add_box(window)
    top = face_towards(box, (0, 0, 1))
    front = face_towards(box, (0, -1, 0))
    window.do_plane_through_points()
    window._on_surface_picked(box.id, top, (-9.5, -9.5, 20))   # lands on the corner
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["plane_points_second"]
    window._on_surface_picked(box.id, top, (9.6, 9.5, 20))
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["plane_points_third"]
    window._on_surface_picked(box.id, front, (9.5, -10, 0.4))
    qapp.processEvents()
    origin, normal = construct.plane_of(window.document.scene.shapes[1])
    # Through the corners (-10, -10, 20), (10, 10, 20) and (10, -10, 0).
    for corner in ((-10, -10, 20), (10, 10, 20), (10, -10, 0)):
        assert float((np.asarray(corner) - origin) @ normal) == pytest.approx(0.0, abs=1e-9)


def test_three_points_in_a_line_are_refused_and_change_nothing(window, warnings, qapp):
    box = add_box(window)
    top = face_towards(box, (0, 0, 1))
    steps = len(window.document._undo)
    window.do_plane_through_points()
    for x in (-5.0, 0.0, 5.0):
        window._on_surface_picked(box.id, top, (x, 0.0, 20.0))
    qapp.processEvents()
    assert warnings and "in one line" in warnings[0]
    assert len(window.document.scene.shapes) == 1 and len(window.document._undo) == steps


def test_clicks_off_a_part_or_on_a_guide_keep_waiting(window):
    add_box(window)
    window.add_sketch(SQUARE, np.eye(4))
    window.do_midplane()
    window._on_surface_picked("", -1, (0, 0, 0))
    window._on_surface_picked(window.document.scene.shapes[1].id, 0, (0, 0, 0))
    assert window.tool == "midplane" and not window._construct_picks
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["midplane"]


def test_esc_and_turning_expert_mode_off_stop_the_construct_tools(window):
    box = add_box(window)
    window.do_plane_through_points()
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (0, 0, 20))
    window.stop_tool()
    assert window.tool is None
    window.do_plane_through_points()
    assert window._construct_picks == []  # a fresh start
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["plane_points"]
    window.set_expert_mode(False)
    assert window.tool is None


def test_new_sketch_draws_straight_onto_a_selected_plane(window, monkeypatch):
    monkeypatch.setattr(sketch_editor, "ask_sketch_plane", lambda parent: pytest.fail("no plane form"))
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda parent, title, **k: SQUARE)
    window.plane_at_distance_selected("yz", 25.0)
    window.do_new_sketch()
    drawn = window.document.scene.shapes[1]
    assert drawn.params["primitive"] == "sketch"
    assert plane(drawn)[1] == [1, 0, 0] and drawn.transform[0, 3] == pytest.approx(25.0)


def test_mirror_and_split_body_take_a_selected_plane(window):
    box = add_box(window, 20.0)
    window.plane_at_distance_selected("yz", 40.0)
    guide = window.document.scene.shapes[1]
    window.document.scene.select([box.id, guide.id])
    assert window.mirror_copy_selected()
    mirrored = window.document.scene.shapes[2]
    assert np.round(shape_geometry(mirrored).bounds.mean(axis=0), 6).tolist() == [60, 0, 10]
    window.plane_at_distance_selected("xy", 5.0)
    window.document.scene.select([box.id, window.document.scene.shapes[-1].id])
    assert window.split_body_selected()
    assert sum(1 for s in window.document.scene.shapes if s.name.startswith("Box (piece")) == 2


def test_a_plane_round_trips_through_a_project_file(tmp_path):
    guide = construct.plane_through_points((0, 0, 0), (10, 0, 5), (0, 10, 0))
    file = tmp_path / "guides.mesh"
    save_project(Scene(shapes=[guide, new_primitive("cube")]), file)
    loaded = load_project(file).shapes[0]
    assert is_reference(loaded) and construct.is_guide(loaded, "plane")
    assert loaded.transform == pytest.approx(guide.transform) and loaded.params == guide.params


def test_plane_forms_and_prompts_are_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    forms = [
        ("Plane at a Distance", construct_actions.plane_distance_fields("Sketch 1"), construct_actions.PLANE_DISTANCE_NOTE),
        ("Plane at an Angle", construct_actions.plane_angle_fields(construct.WORLD_LINES), construct_actions.PLANE_ANGLE_NOTE),
    ]
    for title, fields, note in forms:
        dialog = close_qt_widget(FormDialog(None, title, fields, note=note))
        for text in dialog.labels():
            assert_plain(text)
    for text in construct_actions.ConstructActions.CONSTRUCT_TOOL_PROMPTS.values():
        assert_plain(text)
    assert_plain(construct_actions.ConstructActions.MIDPLANE_HINT)
