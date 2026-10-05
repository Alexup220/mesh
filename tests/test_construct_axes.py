"""Construction axes (Expert mode's Construct menu)."""

import numpy as np
import pytest

from mesh import construct, construct_actions, create, guides, modify, pattern_actions, patterns, sketch
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


def axis(shape):
    point, direction = construct.axis_of(shape)
    return [np.round(point, 6).tolist(), np.round(direction, 6).tolist()]


def middle(shape):
    return np.round(shape_geometry(shape).bounds.mean(axis=0), 6).tolist()


# --- The guide --------------------------------------------------------------------------


def test_an_axis_is_a_guide_drawn_as_a_line_with_an_arrow():
    guide = construct.new_axis((1, 2, 3), (0, 0, 5), 50.0)
    assert is_reference(guide) and construct.is_guide(guide, "axis") and not construct.is_flat_guide(guide)
    assert axis(guide) == [[1, 2, 3], [0, 0, 1]]
    line, arrow = guides.guide_lines("axis", guide.params)
    assert line.tolist() == [[0, 0, -25], [0, 0, 25]] and arrow[1].tolist() == [0, 0, 25]
    assert shape_geometry(guide).bounds[:, 2].tolist() == [-22, 28]  # thick enough to click


@pytest.mark.parametrize("kind", ["cylinder", "cone", "tube", "torus", "sphere", "rounded_cylinder",
                                  "screw_hole", "insert_pocket", "magnet_pocket"])
def test_an_axis_runs_along_the_middle_of_a_round_part(kind):
    part = new_primitive(kind)
    part.transform[:3, 3] = (5, -5, 0)
    made = construct.axis_of_round_part(part)
    point, direction = axis(made)
    assert direction == [0, 0, 1] and point[:2] == [5, -5]
    assert point[2] == pytest.approx(middle(part)[2])


def test_an_axis_follows_a_turned_round_part():
    [lying] = modify.move_copy([new_primitive("cylinder")], axis="x", angle=90.0)
    point, direction = axis(construct.axis_of_round_part(lying))
    assert abs(direction[1]) == pytest.approx(1.0)
    assert point == pytest.approx(middle(lying), abs=1e-6)


def test_a_revolved_part_turns_about_its_own_line():
    outline = create.new_sketch([{"type": "rectangle", "corner": [5, 0], "width": 5, "height": 10}],
                                sketch.plane_frame((0, -1, 0)))
    turned = create.make_revolve(outline, "y")
    point, direction = axis(construct.axis_of_round_part(turned))
    assert point[:2] == [0, 0] and abs(direction[2]) == 1


@pytest.mark.parametrize("make", [lambda: new_primitive("cube"),
                                  lambda: create.new_sketch(SQUARE, np.eye(4))])
def test_only_round_parts_have_an_axis(make):
    with pytest.raises(BuildError) as err:
        construct.axis_of_round_part(make())
    assert "not round about a line" in str(err.value)
    assert_plain(str(err.value))


def test_an_axis_through_two_points_points_from_the_first_to_the_second():
    assert axis(construct.axis_through_points((0, 0, 0), (0, 0, -10))) == [[0, 0, -5], [0, 0, -1]]
    with pytest.raises(BuildError) as err:
        construct.axis_through_points((1, 1, 1), (1, 1, 1))
    assert "on top of each other" in str(err.value)


def test_an_axis_square_to_a_face_goes_through_the_click():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    assert axis(construct.axis_square_to_face(box, top, (3, 4, 20))) == [[3, 4, 20], [0, 0, 1]]
    assert axis(construct.axis_square_to_face(box, top, (9.5, -9.5, 20)))[0] == [10, -10, 20]
    side = face_towards(box, (-1, 0, 0))
    assert axis(construct.axis_square_to_face(box, side, (-10, 0, 5))) == [[-10, 0, 5], [-1, 0, 0]]


def test_an_axis_where_two_planes_meet():
    flat = construct.plane_of(construct.plane_from_named("xy", 5.0))
    upright = construct.plane_of(construct.plane_from_named("yz", 3.0))
    point, direction = axis(construct.axis_where_planes_meet(flat, upright))
    assert point == [3, 0, 5] and abs(direction[1]) == 1
    with pytest.raises(BuildError) as err:
        construct.axis_where_planes_meet(flat, construct.plane_of(construct.plane_from_named("xy", 9.0)))
    assert "parallel" in str(err.value)


def test_a_pattern_goes_round_any_axis():
    box = new_primitive("cube")
    [copy] = patterns.circular_about([box], 2, (0, 0, 30), (1, 0, 0))
    assert middle(copy) == pytest.approx([0, 0, 50])
    tilted = patterns.circular_about([box], 3, (30, 0, 0), (0, 0, 1))
    assert [c.transform for c in tilted] == [pytest.approx(c.transform) for c in
                                            patterns.circular([box], 3, "z", (30, 0, 0))]


def test_split_body_does_not_cut_along_an_axis():
    with pytest.raises(BuildError) as err:
        modify.split_body(new_primitive("cube"), construct.new_axis((0, 0, 0), (0, 0, 1)))
    assert "not along Axis" in str(err.value)
    assert_plain(str(err.value))


# --- In the window ----------------------------------------------------------------------


def add(window, kind, x=0.0):
    window.add_primitive(kind)
    shape = window.document.scene.shapes[-1]
    shape.transform[0, 3] = x
    window.sync()
    return shape


def test_axes_through_the_selected_round_parts_are_one_undo_step(window):
    a, b = add(window, "cylinder"), add(window, "cone", 40.0)
    window.document.scene.select([a.id, b.id])
    steps = len(window.document._undo)
    window.do_axis_round_part()
    shapes = window.document.scene.shapes
    assert [s.name for s in shapes[2:]] == ["Axis 1", "Axis 2"] and len(window.document._undo) == steps + 1
    assert window.document.scene.selection == [shapes[2].id, shapes[3].id]
    assert axis(shapes[3])[0][0] == 40
    window.do_undo()
    assert len(window.document.scene.shapes) == 2


def test_a_part_that_is_not_round_is_refused(window, warnings):
    add(window, "cube")
    steps = len(window.document._undo)
    assert not window.axis_of_round_parts()
    assert warnings and "not round" in warnings[0] and len(window.document._undo) == steps
    window.document.scene.select([])
    window.do_axis_round_part()
    assert window.statusBar().currentMessage() == window.AXIS_ROUND_HINT


def test_an_axis_through_two_clicked_points(window, qapp):
    box = add(window, "cube")
    top = face_towards(box, (0, 0, 1))
    window.do_axis_two_points()
    window._on_surface_picked(box.id, top, (-9.6, -9.7, 20))
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["axis_points_second"]
    window._on_surface_picked(box.id, top, (9.8, 9.6, 20))
    assert window.tool is None
    qapp.processEvents()
    point, direction = axis(window.document.scene.shapes[1])
    assert point == [0, 0, 20] and direction == pytest.approx([2 ** -0.5, 2 ** -0.5, 0])


def test_an_axis_square_to_a_clicked_face(window, qapp):
    box = add(window, "cube")
    window.do_axis_square_to_face()
    assert window.tool == "axis_face"
    window._on_surface_picked(box.id, face_towards(box, (0, -1, 0)), (2, -10, 7))
    qapp.processEvents()
    assert axis(window.document.scene.shapes[1]) == [[2, -10, 7], [0, -1, 0]]


def test_an_axis_where_two_selected_planes_meet(window, warnings):
    window.do_axis_two_planes()
    assert window.statusBar().currentMessage() == window.AXIS_PLANES_HINT
    window.plane_at_distance_selected("xz", 4.0)
    window.plane_at_distance_selected("yz", 6.0)
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_axis_two_planes()
    point, direction = axis(window.document.scene.shapes[2])
    assert point == [6, -4, 0] and abs(direction[2]) == 1
    window.plane_at_distance_selected("yz", 9.0)
    window.document.scene.select([window.document.scene.shapes[1].id, window.document.scene.shapes[3].id])
    assert not window.axis_of_two_planes()
    assert warnings and "parallel" in warnings[0]


def test_a_pattern_around_a_selected_axis(window, monkeypatch):
    seen = {}
    monkeypatch.setattr(pattern_actions, "ask_circular_axis", lambda parent, name: seen.update(
        name=name) or {"count": 4, "angle": 360.0})
    box = add(window, "cube")
    window.document.scene.add(construct.new_axis((30, 0, 0), (0, 0, 1), name="Axis 1"))
    window.document.scene.select([box.id, window.document.scene.shapes[1].id])
    window.do_circular_pattern()
    assert seen["name"] == "Axis 1"
    copies = window.document.scene.shapes[2:]
    assert sorted(tuple(middle(c)) for c in copies) == sorted([(30, 30, 10), (60, 0, 10), (30, -30, 10)])


def test_a_plane_at_an_angle_around_a_selected_axis(window, monkeypatch):
    seen = {}
    monkeypatch.setattr(construct_actions, "ask_plane_angle", lambda parent, lines: seen.update(
        lines=lines) or {"line": "selected", "angle": 90.0})
    window.document.scene.add(construct.new_axis((0, 0, 7), (1, 0, 0), name="Axis 1"))
    window.document.scene.select([window.document.scene.shapes[0].id])
    window.do_plane_at_angle()
    assert seen["lines"][0] == ("selected", "The selected Axis 1")
    origin, normal = construct.plane_of(window.document.scene.shapes[1])
    assert origin.tolist() == [0, 0, 7] and normal == pytest.approx([0, -1, 0])


def test_mirror_does_not_take_an_axis_for_a_plane(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: pytest.fail("no form"))
    box = add(window, "cube")
    window.document.scene.add(construct.new_axis((0, 0, 0), (0, 0, 1)))
    window.document.scene.select([box.id, window.document.scene.shapes[1].id])
    window.do_mirror_copy()
    assert window.statusBar().currentMessage() == window.MIRROR_HINT


def test_an_axis_round_trips_through_a_project_file(tmp_path):
    guide = construct.axis_through_points((1, 2, 3), (4, 6, 3))
    file = tmp_path / "guides.mesh"
    save_project(Scene(shapes=[guide]), file)
    loaded = load_project(file).shapes[0]
    assert construct.is_guide(loaded, "axis") and axis(loaded) == axis(guide)
    assert loaded.params == guide.params


# --- Along a clicked edge -----------------------------------------------------------------


def test_an_axis_along_the_edge_nearest_the_click():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    made = construct.axis_along_edge(box, top, (3, -9.5, 20))  # by the front edge of the top
    assert axis(made) == [[0, -10, 20], [1, 0, 0]] and made.params["length"] == 60.0
    side = face_towards(box, (1, 0, 0))
    assert axis(construct.axis_along_edge(box, side, (10, 9.5, 4)))[1] == [0, 0, 1]  # pointing up


def test_an_edge_split_in_pieces_is_one_straight_edge():
    from mesh import ops

    left, right = new_primitive("cube"), new_primitive("cube")
    right.transform[0, 3] = 20.0
    joined = ops.make_group([left, right])  # one 40 mm long box, its long edges in two pieces
    tm = shape_geometry(joined)
    top = int(np.flatnonzero(tm.face_normals[:, 2] > 0.999)[0])
    edge = construct.edge_at(joined, top, (25.0, -9.8, 20.0))
    assert sorted([edge.start[0], edge.end[0]]) == [-10, 30] and edge.straight
    assert axis(construct.axis_along_edge(joined, top, (25.0, -9.8, 20.0))) == [[10, -10, 20], [1, 0, 0]]


def test_on_a_round_edge_the_axis_runs_along_the_piece_clicked():
    cylinder = new_primitive("cylinder")
    top = face_towards(cylinder, (0, 0, 1))
    edge = construct.edge_at(cylinder, top, (9.9, 0.4, 20.0))
    assert edge.closed and not edge.straight
    assert edge.run_length == pytest.approx(2 * np.pi * 10, rel=1e-3)
    point, direction = axis(construct.axis_along_edge(cylinder, top, (9.9, 0.4, 20.0)))
    assert direction[2] == 0 and np.hypot(point[0], point[1]) == pytest.approx(10 * np.cos(np.pi / 64))
    assert point[2] == 20


def test_an_edge_needs_a_sharp_edge_on_a_part():
    with pytest.raises(BuildError) as err:
        construct.axis_along_edge(new_primitive("sphere"), 0, (0, 0, 0))
    assert "no sharp edge" in str(err.value)
    assert_plain(str(err.value))
    with pytest.raises(BuildError):
        construct.axis_along_edge(construct.new_point((0, 0, 0)), 0, (0, 0, 0))


def test_an_axis_along_a_clicked_edge_is_one_undo_step(window, qapp, tmp_path):
    box = add(window, "cube")
    window.add_primitive("sphere")
    ball = window.document.scene.shapes[-1]
    window.do_axis_along_edge()
    assert window.tool == "axis_edge"
    steps = len(window.document._undo)
    window._on_surface_picked(ball.id, 0, shape_geometry(ball).triangles_center[0])
    assert window.tool == "axis_edge" and "no sharp edge" in window.statusBar().currentMessage()
    window._on_surface_picked(box.id, face_towards(box, (0, -1, 0)), (-9.6, -10, 7))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()
    made = window.document.scene.shapes[2]
    assert made.name == "Axis 1" and axis(made) == [[-10, -10, 10], [0, 0, 1]]
    assert len(window.document._undo) == steps + 1
    file = tmp_path / "edge.mesh"
    save_project(window.document.scene, file)
    assert axis(load_project(file).shapes[2]) == axis(made)
    window.do_undo()
    assert len(window.document.scene.shapes) == 2


def test_axis_text_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Pattern Around a Line", pattern_actions.circular_axis_fields(),
                                        note=pattern_actions.circular_axis_note("Axis 1")))
    for text in dialog.labels():
        assert_plain(text)
    for text in (construct_actions.ConstructActions.AXIS_ROUND_HINT,
                 construct_actions.ConstructActions.AXIS_PLANES_HINT, construct.NOT_ROUND):
        assert_plain(text)
