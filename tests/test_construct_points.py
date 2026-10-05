"""Construction points (Expert mode's Construct menu)."""

import numpy as np
import pytest

from mesh import construct, construct_actions, guides, modify, pattern_actions
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import is_reference, shape_geometry
from test_plain_language import assert_plain


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow(Settings(expert_mode=True)))


def face_towards(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=np.float64)))


def where(shape):
    return np.round(construct.point_of(shape), 6).tolist()


# --- The guide --------------------------------------------------------------------------


def test_a_point_is_a_guide_drawn_as_a_small_cross():
    guide = construct.new_point((1, 2, 3), "Point 1")
    assert is_reference(guide) and construct.is_guide(guide, "point")
    assert not construct.is_flat_guide(guide) and guide.name == "Point 1"
    assert where(guide) == [1, 2, 3]
    lines = guides.guide_lines("point", guide.params)
    assert [line.tolist() for line in lines] == [[[-2, 0, 0], [2, 0, 0]], [[0, -2, 0], [0, 2, 0]],
                                                  [[0, 0, -2], [0, 0, 2]]]
    bounds = shape_geometry(guide).bounds  # a small ball, so a click can land on it
    assert bounds[0] == pytest.approx([0, 1, 2]) and bounds[1] == pytest.approx([2, 3, 4])


def test_only_a_point_has_a_point_position():
    with pytest.raises(BuildError) as err:
        construct.point_of(new_primitive("cube"))
    assert "is not a point" in str(err.value)


def test_a_point_lands_where_the_face_was_clicked():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    assert where(construct.point_at_spot(box, top, (3, 4, 20))) == [3, 4, 20]
    assert where(construct.point_at_spot(box, top, (3, 4, 25))) == [3, 4, 20]  # kept on the face


def test_a_point_near_a_corner_lands_on_the_corner():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    assert where(construct.point_at_spot(box, top, (9.0, -8.9, 20))) == [10, -10, 20]
    assert where(construct.point_at_spot(box, top, (7.0, -8.9, 20))) == [7, -8.9, 20]


def test_a_point_at_the_middle_of_a_face():
    cylinder = new_primitive("cylinder")
    cylinder.transform[:3, 3] = (5, 6, 0)
    top = face_towards(cylinder, (0, 0, 1))
    assert where(construct.point_at_middle(cylinder, top)) == pytest.approx([5, 6, 20])
    box = new_primitive("cube")
    assert where(construct.point_at_middle(box, face_towards(box, (1, 0, 0)))) == pytest.approx([10, 0, 10])


def test_a_point_needs_a_part_and_a_flat_face():
    with pytest.raises(BuildError) as err:
        construct.point_at_spot(construct.new_point((0, 0, 0)), 0, (0, 0, 0))
    assert "Click a part" in str(err.value)
    with pytest.raises(BuildError):
        construct.point_at_middle(new_primitive("cube"), 10_000)


def test_points_make_planes_and_axes():
    a, b, c = (construct.new_point(p) for p in ((0, 0, 5), (10, 0, 5), (0, 10, 5)))
    origin, normal = construct.plane_of(construct.plane_through_points(*map(construct.point_of, (a, b, c))))
    assert normal.tolist() == [0, 0, 1] and origin[2] == pytest.approx(5)
    point, direction = construct.axis_of(construct.axis_through_points(construct.point_of(a),
                                                                       construct.point_of(b)))
    assert point.tolist() == [5, 0, 5] and direction.tolist() == [1, 0, 0]


def test_split_body_does_not_cut_at_a_point():
    with pytest.raises(BuildError) as err:
        modify.split_body(new_primitive("cube"), construct.new_point((0, 0, 10)))
    assert "not along Point" in str(err.value)
    assert_plain(str(err.value))


# --- In the window ----------------------------------------------------------------------


def add(window, kind):
    window.add_primitive(kind)
    return window.document.scene.shapes[-1]


def test_a_point_at_a_click_is_one_undo_step(window, qapp):
    box = add(window, "cube")
    steps = len(window.document._undo)
    window.do_point_at_spot()
    assert window.tool == "point_spot"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["point_spot"]
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (9.2, 9.1, 20))
    assert window.tool is None
    qapp.processEvents()
    made = window.document.scene.shapes[1]
    assert made.name == "Point 1" and where(made) == [10, 10, 20]
    assert window.document.scene.selection == [made.id] and len(window.document._undo) == steps + 1
    window.do_undo()
    assert len(window.document.scene.shapes) == 1


def test_a_point_at_the_middle_of_a_clicked_face(window, qapp):
    cylinder = add(window, "cylinder")
    window.do_point_at_middle()
    assert window.tool == "point_middle"
    window._on_surface_picked(cylinder.id, face_towards(cylinder, (0, 0, -1)), (3, 3, 0))
    qapp.processEvents()
    made = window.document.scene.shapes[1]
    assert where(made) == pytest.approx([0, 0, 0])


def test_clicking_a_guide_keeps_the_tool_waiting(window, qapp):
    window.document.scene.add(construct.new_point((0, 0, 0)))
    window.do_point_at_spot()
    window._on_surface_picked(window.document.scene.shapes[0].id, 0, (0, 0, 0))
    qapp.processEvents()
    assert window.tool == "point_spot" and len(window.document.scene.shapes) == 1


def test_three_selected_points_make_a_plane_at_once(window):
    for p in ((0, 0, 0), (10, 0, 0), (0, 0, 10)):
        window.document.scene.add(construct.new_point(p))
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_plane_through_points()
    assert window.tool is None
    made = window.document.scene.shapes[3]
    origin, normal = construct.plane_of(made)
    assert made.name == "Plane 1" and normal == pytest.approx([0, -1, 0]) and origin[1] == pytest.approx(0)


def test_two_selected_points_make_an_axis_at_once(window):
    window.document.scene.add(construct.new_point((0, 0, 10)))
    window.document.scene.add(construct.new_point((0, 0, 0)))
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_axis_two_points()
    assert window.tool is None
    point, direction = construct.axis_of(window.document.scene.shapes[2])
    assert point.tolist() == [0, 0, 5] and direction.tolist() == [0, 0, -1]  # from the first picked


def test_other_selections_start_the_click_tools(window):
    window.document.scene.add(construct.new_point((0, 0, 0)))
    window.document.scene.select([window.document.scene.shapes[0].id])
    window.do_axis_two_points()
    assert window.tool == "axis_points"
    window.stop_tool()
    window.do_plane_through_points()
    assert window.tool == "plane_points"


def test_a_point_moves_with_the_details_panel(window):
    window.document.scene.add(construct.new_point((0, 0, 0)))
    point = window.document.scene.shapes[0]
    window.document.scene.select([point.id])
    window.sync()
    window.inspector.fields["z"].setValue(12.0)
    assert where(point) == [0, 0, 12]


def test_mirror_does_not_take_a_point_for_a_plane(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: pytest.fail("no form"))
    box = add(window, "cube")
    window.document.scene.add(construct.new_point((0, 0, 0)))
    window.document.scene.select([box.id, window.document.scene.shapes[1].id])
    window.do_mirror_copy()
    assert window.statusBar().currentMessage() == window.MIRROR_HINT


def test_a_point_round_trips_through_a_project_file(tmp_path):
    guide = construct.new_point((1.5, -2, 3), "Point 4")
    file = tmp_path / "guides.mesh"
    save_project(Scene(shapes=[guide]), file)
    loaded = load_project(file).shapes[0]
    assert construct.is_guide(loaded, "point") and where(loaded) == [1.5, -2, 3]
    assert loaded.name == "Point 4"


def test_a_point_at_the_end_of_an_edge_nearer_the_click():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    assert where(construct.point_at_edge_end(box, top, (7, -9.5, 20))) == [10, -10, 20]
    assert where(construct.point_at_edge_end(box, top, (-2, -9.5, 20))) == [-10, -10, 20]
    side = face_towards(box, (1, 0, 0))
    assert where(construct.point_at_edge_end(box, side, (10, 9.5, 4))) == [10, 10, 0]


def test_on_a_round_edge_a_point_goes_on_an_end_of_the_piece_clicked():
    cylinder = new_primitive("cylinder")
    made = where(construct.point_at_edge_end(cylinder, face_towards(cylinder, (0, 0, 1)), (9.9, 0.4, 20)))
    assert np.hypot(made[0], made[1]) == pytest.approx(10.0) and made[2] == 20


def test_a_point_at_the_end_of_a_clicked_edge_is_one_undo_step(window, qapp, tmp_path):
    box = add(window, "cube")
    window.do_point_at_edge_end()
    assert window.tool == "point_edge"
    steps = len(window.document._undo)
    window._on_surface_picked(box.id, face_towards(box, (0, -1, 0)), (9.6, -10, 13))
    assert window.tool is None
    qapp.processEvents()
    made = window.document.scene.shapes[1]
    assert made.name == "Point 1" and where(made) == [10, -10, 20]
    assert len(window.document._undo) == steps + 1
    file = tmp_path / "end.mesh"
    save_project(window.document.scene, file)
    assert where(load_project(file).shapes[1]) == [10, -10, 20]
    window.do_undo()
    assert len(window.document.scene.shapes) == 1


def test_a_point_where_three_planes_meet():
    flat = construct.plane_of(construct.plane_from_named("xy", 5.0))
    front = construct.plane_of(construct.plane_from_named("xz", 3.0))  # faces the front, 3 mm forward
    side = construct.plane_of(construct.plane_from_named("yz", -2.0))
    assert where(construct.point_where_planes_meet(flat, front, side)) == [-2, -3, 5]
    tilted = construct.plane_of(construct.plane_at_angle((0, 0, 0), (0, 0, 1), 45.0))
    assert where(construct.point_where_planes_meet(flat, side, tilted)) == pytest.approx([-2, -2, 5])
    for planes in ((flat, front, construct.plane_of(construct.plane_from_named("xy", 9.0))),
                   (front, side, construct.plane_of(construct.plane_at_angle((0, 0, 0), (0, 0, 1), 10.0)))):
        with pytest.raises(BuildError) as err:  # two parallel; all three through one upright line
            construct.point_where_planes_meet(*planes)
        assert "don't meet at a single point" in str(err.value)
        assert_plain(str(err.value))


def test_a_point_where_an_axis_meets_a_plane():
    line = construct.axis_of(construct.axis_through_points((0, 0, 0), (10, 10, 10)))
    flat = construct.plane_of(construct.plane_from_named("xy", 4.0))
    assert where(construct.point_where_axis_meets_plane(line, flat)) == pytest.approx([4, 4, 4])
    upright = construct.axis_of(construct.new_axis((1, 2, 3), (0, 0, 1)))
    with pytest.raises(BuildError) as err:
        construct.point_where_axis_meets_plane(upright, construct.plane_of(construct.plane_from_named("yz", 0.0)))
    assert "runs alongside the plane" in str(err.value)
    assert_plain(str(err.value))


def test_points_where_selected_guides_meet_are_one_undo_step_each(window, tmp_path):
    window.do_point_three_planes()
    assert window.statusBar().currentMessage() == window.POINT_PLANES_HINT
    for name, distance in (("xy", 5.0), ("xz", 3.0), ("yz", -2.0)):
        window.plane_at_distance_selected(name, distance)
    scene = window.document.scene
    scene.select([s.id for s in scene.shapes])
    steps = len(window.document._undo)
    window.do_point_three_planes()
    made = scene.shapes[3]
    assert made.name == "Point 1" and where(made) == [-2, -3, 5] and len(window.document._undo) == steps + 1
    scene.add(construct.new_axis((0, 0, 0), (1, 1, 1), name="Axis 1"))
    window.do_point_axis_plane()
    assert window.statusBar().currentMessage() == window.POINT_AXIS_HINT
    scene.select([scene.shapes[4].id, scene.shapes[0].id])
    window.do_point_axis_plane()
    assert where(scene.shapes[5]) == pytest.approx([5, 5, 5])
    file = tmp_path / "meet.mesh"
    save_project(scene, file)
    assert where(load_project(file).shapes[5]) == pytest.approx([5, 5, 5])
    window.do_undo()
    assert len(window.document.scene.shapes) == 5


def test_point_text_is_plain_language():
    prompts = construct_actions.ConstructActions.CONSTRUCT_TOOL_PROMPTS
    for key in ("point_spot", "point_middle", "point_edge", "axis_edge"):
        assert_plain(prompts[key])
    assert_plain(construct_actions.ConstructActions.POINT_PLANES_HINT)
    assert_plain(construct_actions.ConstructActions.POINT_AXIS_HINT)
