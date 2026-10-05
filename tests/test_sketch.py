"""Sketches (Expert mode): curves, outlines, planes, and sketch shapes."""

import math

import numpy as np
import pytest

from mesh import create, sketch
from mesh.builders import BuildError
from mesh.scene import Scene, new_primitive
from mesh.shapes import is_reference, shape_geometry
from test_plain_language import assert_plain

SQUARE = [
    {"type": "line", "start": [0, 0], "end": [10, 0]},
    {"type": "line", "start": [10, 0], "end": [10, 10]},
    {"type": "line", "start": [10, 10], "end": [0, 10]},
    {"type": "line", "start": [0, 10], "end": [0, 0]},
]

EVERY_CURVE = [
    {"type": "line", "start": [0, 0], "end": [20, 0]},
    {"type": "rectangle", "corner": [0, 0], "width": 20, "height": 10},
    {"type": "circle", "centre": [5, 5], "diameter": 4},
    {"type": "arc", "centre": [0, 0], "radius": 10, "start": 0, "end": 90},
    {"type": "polygon", "centre": [0, 0], "sides": 6, "radius": 10, "angle": 0},
    {"type": "spline", "points": [[0, 0], [10, 10], [20, 0]], "closed": False},
]


# --- Checking curves -------------------------------------------------------------


@pytest.mark.parametrize("entity", EVERY_CURVE, ids=lambda e: e["type"])
def test_every_curve_is_cleaned_to_plain_floats(entity):
    cleaned = sketch.clean_entity(entity)
    assert cleaned["type"] == entity["type"]
    assert sketch.clean_entity(cleaned) == cleaned  # cleaning twice changes nothing
    for key, value in cleaned.items():
        if isinstance(value, list) and value and isinstance(value[0], float):
            assert all(type(v) is float for v in value)


@pytest.mark.parametrize("entity, words", [
    ("not a curve", "not a curve"),
    ({"type": "blob"}, "not a curve"),
    ({"type": "line", "start": [0, 0], "end": [0, 0]}, "two different end points"),
    ({"type": "line", "start": [0], "end": [1, 1]}, "two numbers"),
    ({"type": "line", "start": [0, float("nan")], "end": [1, 1]}, "ordinary numbers"),
    ({"type": "rectangle", "corner": [0, 0], "width": 0, "height": 5}, "more than 0"),
    ({"type": "circle", "centre": [0, 0], "diameter": -2}, "more than 0"),
    ({"type": "arc", "centre": [0, 0], "radius": 5, "start": 30, "end": 390}, "whole turn apart"),
    ({"type": "polygon", "centre": [0, 0], "sides": 2, "radius": 5}, "between 3 and 1000"),
    ({"type": "polygon", "centre": [0, 0], "sides": "many", "radius": 5}, "whole number"),
    ({"type": "spline", "points": [[0, 0], [0, 0]]}, "at least 2 different points"),
    ({"type": "spline", "points": [[0, 0], [5, 5], [0, 0]], "closed": True}, "at least 3"),
    ({"type": "spline", "points": "0,0"}, "list of points"),
])
def test_curves_that_cannot_be_drawn_are_refused_plainly(entity, words):
    with pytest.raises(sketch.SketchError) as err:
        sketch.clean_entity(entity)
    assert words in str(err.value)
    assert_plain(str(err.value))


@pytest.mark.parametrize("entity, words", [
    ({"type": "line", "start": [0, 0], "end": [20000, 0]}, "within 10000 mm"),
    ({"type": "circle", "centre": [0, -1e9], "diameter": 4}, "within 10000 mm"),
    ({"type": "rectangle", "corner": [0, 0], "width": 1e6, "height": 5}, "at most 10000 mm"),
    ({"type": "spline", "points": [[0, 0], [5, 5e5]]}, "within 10000 mm"),
])
def test_curves_far_too_big_or_far_away_are_refused(entity, words):
    with pytest.raises(sketch.SketchError) as err:
        sketch.clean_entity(entity)
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_joining_thousands_of_short_lines_is_quick():
    import time

    points = [[10 * math.cos(t), 10 * math.sin(t)] for t in np.linspace(0, 2 * math.pi, 4001)[:-1]]
    lines = [{"type": "line", "start": points[i], "end": points[(i + 1) % len(points)]}
             for i in range(len(points))]
    started = time.perf_counter()
    found = sketch.chains(sketch.clean_entities(lines))
    assert time.perf_counter() - started < 5.0
    assert len(found.loops) == 1


def test_a_sketchs_curves_must_be_a_list():
    with pytest.raises(sketch.SketchError):
        sketch.clean_entities({"type": "line"})


def test_spline_points_that_repeat_are_dropped():
    cleaned = sketch.clean_entity(
        {"type": "spline", "points": [[0, 0], [0, 0], [5, 5], [9, 0], [0, 0]], "closed": True}
    )
    assert cleaned["points"] == [[0.0, 0.0], [5.0, 5.0], [9.0, 0.0]]


# --- Curves as straight pieces ---------------------------------------------------


def test_rectangle_is_its_four_corners():
    points, closed = sketch.entity_points(EVERY_CURVE[1])
    assert closed
    assert points.tolist() == [[0, 0], [20, 0], [20, 10], [0, 10]]


def test_circle_is_as_round_as_a_cylinder():
    points, closed = sketch.entity_points(EVERY_CURVE[2])
    assert closed and len(points) == sketch.SEGMENTS
    assert np.allclose(np.linalg.norm(points - [5, 5], axis=1), 2.0)


def test_arc_runs_anticlockwise_from_start_to_end():
    points, closed = sketch.entity_points({"type": "arc", "centre": [0, 0], "radius": 10,
                                           "start": 350, "end": 10})
    assert not closed
    assert np.allclose(points[0], [10 * math.cos(math.radians(350)), 10 * math.sin(math.radians(350))])
    assert np.allclose(points[-1], [10 * math.cos(math.radians(10)), 10 * math.sin(math.radians(10))])
    assert np.all(points[:, 0] > 9.8)  # through angle 0, not the long way round


def test_polygon_corners_sit_on_its_radius():
    points, closed = sketch.entity_points(EVERY_CURVE[4])
    assert closed and len(points) == 6
    assert np.allclose(np.linalg.norm(points, axis=1), 10.0)
    assert np.allclose(points[0], [10, 0])


def test_spline_passes_through_every_point():
    entity = EVERY_CURVE[5]
    points, closed = sketch.entity_points(entity)
    assert not closed
    for p in entity["points"]:
        assert np.min(np.linalg.norm(points - p, axis=1)) < 1e-9
    closed_points, is_closed = sketch.entity_points({**entity, "closed": True})
    assert is_closed and len(closed_points) == 3 * sketch.SPLINE_STEPS


# --- Outlines and paths ------------------------------------------------------------


def test_lines_meeting_end_to_end_close_an_outline_in_any_order_or_direction():
    shuffled = [SQUARE[2], {"type": "line", "start": [10, 0], "end": [0, 0]}, SQUARE[3], SQUARE[1]]
    found = sketch.chains(shuffled)
    assert len(found.loops) == 1 and not found.paths and not found.branching
    assert abs(sketch.signed_area(found.loops[0])) == pytest.approx(100.0)


def test_line_ends_within_the_join_tolerance_meet():
    nearly = [dict(e) for e in SQUARE]
    nearly[3] = {"type": "line", "start": [0, 10], "end": [0.005, 0.0]}
    assert len(sketch.chains(nearly).loops) == 1


def test_an_arc_and_a_line_make_a_d_shape():
    d = [
        {"type": "arc", "centre": [0, 0], "radius": 10, "start": 270, "end": 90},
        {"type": "line", "start": [0, 10], "end": [0, -10]},
    ]
    area = sketch.profile(d).area()
    assert area == pytest.approx(math.pi * 100 / 2, rel=0.01)


def test_open_curves_make_a_path():
    found = sketch.chains(SQUARE[:3])
    assert not found.loops and len(found.paths) == 1
    assert found.paths[0].tolist() == [[0, 0], [10, 0], [10, 10], [0, 10]]


def test_three_ends_at_one_point_is_branching():
    t = SQUARE[:2] + [{"type": "line", "start": [10, 0], "end": [20, 0]}]
    assert sketch.chains(t).branching
    with pytest.raises(sketch.SketchError) as err:
        sketch.profile(t)
    assert_plain(str(err.value))


def test_profile_of_a_rectangle_is_its_area():
    assert sketch.profile([EVERY_CURVE[1]]).area() == pytest.approx(200.0)


def test_an_outline_inside_another_is_a_hole():
    washer = [
        {"type": "circle", "centre": [0, 0], "diameter": 20},
        {"type": "circle", "centre": [0, 0], "diameter": 10},
    ]
    ring = sketch.profile(washer).area()
    outer = sketch.profile(washer[:1]).area()
    inner = sketch.profile(washer[1:]).area()
    assert ring == pytest.approx(outer - inner)
    island = washer + [{"type": "circle", "centre": [0, 0], "diameter": 4}]
    assert sketch.profile(island).area() == pytest.approx(ring + sketch.profile(island[2:]).area())


def test_profile_without_a_closed_outline_says_so():
    with pytest.raises(sketch.SketchError) as err:
        sketch.profile(SQUARE[:3])
    assert "no closed outline" in str(err.value)
    assert_plain(str(err.value))


def test_single_path_takes_one_open_path_or_one_outline():
    path, closed = sketch.single_path(SQUARE[:3])
    assert not closed and len(path) == 4
    loop, closed = sketch.single_path(SQUARE)
    assert closed and len(loop) == 4
    with pytest.raises(sketch.SketchError) as err:
        sketch.single_path(SQUARE[:1] + [{"type": "line", "start": [50, 50], "end": [60, 60]}])
    assert_plain(str(err.value))


# --- Planes ------------------------------------------------------------------------


@pytest.mark.parametrize("normal", [(0, 0, 1), (0, -1, 0), (1, 0, 0), (1, 1, 1), (0, 0, -1), (-1, 0, 0)])
def test_plane_frames_are_square_and_face_their_direction(normal):
    frame = sketch.plane_frame(normal, (3, 4, 5))
    rotation = frame[:3, :3]
    assert np.allclose(rotation.T @ rotation, np.eye(3))
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    n = np.asarray(normal, dtype=float) / np.linalg.norm(normal)
    assert np.allclose(frame[:3, 2], n)
    # The origin is on the plane, nearest the world origin.
    assert np.allclose(frame[:3, 3], np.dot([3, 4, 5], n) * n)


def test_the_workplane_frame_is_the_worlds_own():
    assert np.allclose(sketch.named_plane_frame("xy"), np.eye(4))


def test_upright_planes_read_as_seen_from_the_front_and_right():
    front = sketch.named_plane_frame("xz", 5.0)
    assert np.allclose(front[:3, 0], [1, 0, 0]) and np.allclose(front[:3, 1], [0, 0, 1])
    assert np.allclose(front[:3, 3], [0, -5, 0])
    right = sketch.named_plane_frame("yz")
    assert np.allclose(right[:3, 0], [0, 1, 0]) and np.allclose(right[:3, 1], [0, 0, 1])
    with pytest.raises(ValueError):
        sketch.named_plane_frame("sideways")
    with pytest.raises(sketch.SketchError):
        sketch.plane_frame((0, 0, 0))


@pytest.mark.parametrize("normal, across", [
    ((0, 1, 0), (-1, 0, 0)),     # the back, seen from behind
    ((-1, 0, 0), (0, -1, 0)),    # the left side, seen from the left
    ((1, 1, 0), (-0.5**0.5, 0.5**0.5, 0)),
])
def test_every_upright_face_reads_upright_as_seen_from_outside(normal, across):
    frame = sketch.plane_frame(normal)
    assert np.allclose(frame[:3, 1], [0, 0, 1])
    assert np.allclose(frame[:3, 0], across)


def test_sketch_and_world_points_convert_both_ways():
    frame = sketch.plane_frame((1, 2, 3), (4, 5, 6))
    flat = np.array([[0, 0], [1.5, -2], [10, 7]])
    assert np.allclose(sketch.to_sketch(frame, sketch.to_world(frame, flat)), flat)


# --- How a sketch is drawn and measured ---------------------------------------------


def test_sketch_geometry_fills_outlines_and_spans_open_curves():
    entities = [EVERY_CURVE[1], {"type": "line", "start": [0, 0], "end": [0, -15]}]
    tm = sketch.sketch_geometry(entities)
    assert np.allclose(tm.bounds, [[0, -15, 0], [20, 10, 0]])
    assert tm.area == pytest.approx(200.0)


def test_an_empty_sketch_still_has_geometry():
    tm = sketch.sketch_geometry([])
    assert len(tm.faces) == 1 and tm.area == 0


def test_sketch_lines_close_closed_curves():
    lines = sketch.sketch_lines([EVERY_CURVE[1], EVERY_CURVE[0]])
    assert np.allclose(lines[0][0], lines[0][-1]) and len(lines[0]) == 5
    assert len(lines[1]) == 2


@pytest.mark.parametrize("entity", EVERY_CURVE, ids=lambda e: e["type"])
def test_every_curve_is_described_in_plain_words(entity):
    text = sketch.describe(entity)
    assert text and "{" not in text
    assert_plain(text)


# --- Sketch shapes -----------------------------------------------------------------


def test_new_sketch_holds_its_curves_and_its_plane():
    frame = sketch.named_plane_frame("xz", 2.0)
    shape = create.new_sketch(SQUARE, frame, "Sketch 1")
    assert shape.kind == "primitive" and shape.params["primitive"] == "sketch"
    assert shape.params["entities"] == sketch.clean_entities(SQUARE)
    assert np.allclose(shape.transform, frame)
    assert shape.color == create.SKETCH_COLOR
    assert is_reference(shape) and create.is_sketch(shape)
    assert not is_reference(new_primitive("cube"))


def test_new_sketch_refuses_no_curves_and_bad_curves():
    with pytest.raises(BuildError) as err:
        create.new_sketch([], np.eye(4))
    assert_plain(str(err.value))
    with pytest.raises(BuildError):
        create.new_sketch([{"type": "circle", "centre": [0, 0], "diameter": 0}], np.eye(4))
    with pytest.raises(ValueError):
        create.new_sketch(SQUARE, np.eye(3))


def test_sketch_names_count_up():
    scene = Scene()
    assert create.next_sketch_name(scene.shapes) == "Sketch 1"
    scene.add(create.new_sketch(SQUARE, np.eye(4), "Sketch 1"))
    scene.add(create.new_sketch(SQUARE, np.eye(4), "Sketch 7"))
    scene.add(new_primitive("cube", name="Sketch of a box"))
    assert create.next_sketch_name(scene.shapes) == "Sketch 8"


def test_with_entities_changes_a_copy():
    shape = create.new_sketch(SQUARE, np.eye(4))
    changed = create.with_entities(shape, [EVERY_CURVE[2]])
    assert changed.id == shape.id
    assert changed.params["entities"] == [sketch.clean_entity(EVERY_CURVE[2])]
    assert shape.params["entities"] == sketch.clean_entities(SQUARE)
    with pytest.raises(BuildError):
        create.with_entities(shape, [])
    with pytest.raises(BuildError):
        create.with_entities(new_primitive("cube"), SQUARE)


def test_a_sketch_shape_is_placed_by_its_plane():
    shape = create.new_sketch([EVERY_CURVE[1]], sketch.named_plane_frame("xz", 3.0))
    tm = shape_geometry(shape)
    assert np.allclose(tm.bounds, [[0, -3, 0], [20, -3, 10]])


# --- Sketches on a face --------------------------------------------------------------


def _face_facing(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=float)))


def test_a_box_top_face_gives_its_plane_and_outline():
    box = new_primitive("cube")
    frame, outlines = create.face_plane(box, _face_facing(box, (0, 0, 1)))
    assert np.allclose(frame[:3, 2], [0, 0, 1]) and np.allclose(frame[:3, 3], [0, 0, 20])
    assert len(outlines) == 1
    assert abs(sketch.signed_area(outlines[0])) == pytest.approx(400.0)
    traced = create.outline_entities(outlines)
    assert len(traced) == 4
    assert sketch.profile(traced).area() == pytest.approx(400.0)


def test_a_box_side_face_is_upright():
    box = new_primitive("cube")
    frame, outlines = create.face_plane(box, _face_facing(box, (1, 0, 0)))
    assert np.allclose(frame[:3, 2], [1, 0, 0])
    assert np.allclose(frame[:3, 3], [10, 0, 0])
    assert abs(sketch.signed_area(outlines[0])) == pytest.approx(400.0)


def test_a_cylinder_end_is_one_round_face():
    cylinder = new_primitive("cylinder")
    frame, outlines = create.face_plane(cylinder, _face_facing(cylinder, (0, 0, 1)))
    assert len(outlines) == 1 and len(outlines[0]) == 64


def test_a_face_of_a_moved_part_follows_the_part():
    box = new_primitive("cube")
    box.transform[:3, 3] = [100, 0, 5]
    frame, outlines = create.face_plane(box, _face_facing(box, (0, 0, 1)))
    assert np.allclose(frame[:3, 3], [0, 0, 25])
    world = sketch.to_world(frame, outlines[0])
    assert np.allclose(world.mean(axis=0), [100, 0, 25])
