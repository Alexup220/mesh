"""Measure Between Faces and Volume and Area (Expert mode's Inspect menu)."""

import numpy as np
import pytest
import trimesh

from mesh import construct, measure
from mesh.builders import BuildError
from mesh.expert import TOOLS
from mesh.scene import new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain


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


# --- Between two faces ------------------------------------------------------------------


def test_two_sides_of_a_box_are_parallel_and_a_box_width_apart():
    box = new_primitive("cube")
    left = measure.clicked(box, face_towards(box, (-1, 0, 0)), (-10, 2, 5))
    right = measure.clicked(box, face_towards(box, (1, 0, 0)), (10, -3, 8))
    assert left.area == pytest.approx(400) and left.facing.tolist() == pytest.approx([-1, 0, 0])
    found = measure.between(left, right)
    assert found.gap == pytest.approx(20) and found.angle == pytest.approx(0)
    assert found.along.tolist() == pytest.approx([20, -5, 3])
    assert found.distance == pytest.approx(np.sqrt(20 ** 2 + 5 ** 2 + 3 ** 2))


def test_the_angle_between_faces_that_meet():
    box = new_primitive("cube")
    top = measure.clicked(box, face_towards(box, (0, 0, 1)), (0, 0, 20))
    side = measure.clicked(box, face_towards(box, (0, -1, 0)), (0, -10, 10))
    found = measure.between(top, side)
    assert found.angle == pytest.approx(90) and found.gap is None
    wedge = new_primitive("wedge")
    tm = shape_geometry(wedge)
    tilted = [f for f in range(len(tm.faces)) if 0.01 < tm.face_normals[f][2] < 0.99]
    slope, bottom = tilted[0], face_towards(wedge, (0, 0, -1))
    found = measure.between(measure.clicked(wedge, slope, tm.triangles_center[slope]),
                            measure.clicked(wedge, bottom, tm.triangles_center[bottom]))
    assert found.angle == pytest.approx(np.degrees(np.arccos(tm.face_normals[slope][2])))
    assert 0 < found.angle < 90


def test_a_click_near_a_corner_measures_from_the_corner():
    box = new_primitive("cube")
    top = face_towards(box, (0, 0, 1))
    a = measure.clicked(box, top, (9.2, 9.4, 20))
    b = measure.clicked(box, top, (-9.5, -9.1, 20))
    assert a.point.tolist() == [10, 10, 20] and b.point.tolist() == [-10, -10, 20]
    assert measure.between(a, b).distance == pytest.approx(np.sqrt(800))


def test_a_round_end_has_a_circle_area():
    cylinder = new_primitive("cylinder")
    end = measure.clicked(cylinder, face_towards(cylinder, (0, 0, 1)), (0, 0, 20))
    assert end.area == pytest.approx(np.pi * 10 ** 2, rel=0.01)


def test_the_description_is_plain_words():
    box = new_primitive("cube")
    left = measure.clicked(box, face_towards(box, (-1, 0, 0)), (-10, 0, 5))
    right = measure.clicked(box, face_towards(box, (1, 0, 0)), (10, 0, 5))
    text = measure.describe(left, right)
    assert "Distance between the points: 20.00 mm" in text
    assert "The faces are parallel, 20.00 mm apart" in text
    assert "First face area: 400.00 mm², second face area: 400.00 mm²" in text
    top = measure.clicked(box, face_towards(box, (0, 0, 1)), (0, 0, 20))
    assert "Angle between the faces: 90.00°" in measure.describe(left, top)
    for line in (text, measure.describe(left, top), measure.describe_face(left)):
        assert_plain(line)


# --- Volume and area --------------------------------------------------------------------


def test_volume_and_area_of_one_part():
    found = measure.amount([new_primitive("cube")])
    assert found.volume == pytest.approx(8000) and found.area == pytest.approx(2400)
    assert found.size.tolist() == pytest.approx([20, 20, 20])


def test_overlaps_count_once_and_holes_are_cut_out():
    a, b = new_primitive("cube"), new_primitive("cube")
    b.transform[0, 3] = 10.0
    assert measure.amount([a, b]).volume == pytest.approx(20 * 30 * 20)
    hole = new_primitive("cube")
    hole.is_hole = True
    hole.transform[:3, 3] = (0, 0, 10)
    assert measure.amount([a, hole]).volume == pytest.approx(20 * 20 * 10)


def test_guides_are_left_out_and_holes_alone_are_refused():
    found = measure.amount([new_primitive("cube"), construct.new_point((50, 0, 0))])
    assert found.size.tolist() == pytest.approx([20, 20, 20])
    hole = new_primitive("cube")
    hole.is_hole = True
    with pytest.raises(BuildError) as err:
        measure.amount([hole])
    assert_plain(str(err.value))


def test_a_part_with_gaps_has_no_volume_to_measure(monkeypatch):
    tm = shape_geometry(new_primitive("cube"))
    open_box = trimesh.Trimesh(vertices=tm.vertices, faces=tm.faces[:-2], process=False)
    monkeypatch.setattr(measure.ops, "evaluate", lambda shapes, clearances=None: open_box)
    part = new_primitive("cube")
    with pytest.raises(BuildError) as err:
        measure.amount([part])
    assert str(err.value) == f"{part.name} has gaps, so it has no inside to measure."
    assert_plain(str(err.value))


def test_describing_the_amount():
    found = measure.Amount(8000.0, 2400.0, np.array([20.0, 20.0, 20.0]))
    one = measure.describe_amount(found, 1)
    assert one.startswith("The selected part takes up 8000.00 mm³ (8.00 cm³).")
    assert "Size: 20.00 x 20.00 x 20.00 mm" in one
    assert measure.describe_amount(found, 2).startswith("The 2 selected parts, together, take up")
    assert_plain(one)


def test_the_centre_of_gravity():
    box = new_primitive("cube")  # 20 wide, from 0 up to 20
    assert measure.amount([box]).centre == pytest.approx((0.0, 0.0, 10.0))
    a, b = new_primitive("cube"), new_primitive("cube")
    b.transform[0, 3] = 40.0
    b.params.update(height=40.0)  # twice the first: the middle is two thirds of the way across
    assert measure.amount([a, b]).centre == pytest.approx((80.0 / 3.0, 0.0, 50.0 / 3.0))
    hole = new_primitive("cube")
    hole.is_hole = True
    hole.transform[:3, 3] = (0, 0, 10)  # takes off the top half
    assert measure.amount([new_primitive("cube"), hole]).centre == pytest.approx((0.0, 0.0, 5.0))


def test_the_weight_in_a_chosen_material():
    assert measure.material("pla") == ("PLA", 1.24)
    assert [key for key, _name, _density in measure.MATERIALS] == ["pla", "petg", "abs", "asa", "tpu", "nylon"]
    assert measure.material(measure.TYPED, 2.7) == (None, 2.7)
    for typed in (0.0, -1.0):
        with pytest.raises(BuildError) as err:
            measure.material(measure.TYPED, typed)
        assert str(err.value) == measure.NO_DENSITY
    with pytest.raises(BuildError):
        measure.material("gold")
    found = measure.Amount(8000.0, 2400.0, np.array([20.0, 20.0, 20.0]), np.array([0.0, 0.0, 10.0]))
    assert measure.weight(found, 1.24) == pytest.approx(9.92)


def test_describing_the_centre_of_gravity_and_the_weight():
    found = measure.Amount(8000.0, 2400.0, np.array([20.0, 20.0, 20.0]), np.array([1.5, -2.0, 10.0]))
    lines = measure.describe_amount(found, 1, measure.material("pla")).split("\n")
    assert lines[3] == ("Centre of gravity, the same material all through: left/right 1.50 mm, "
                        "forward/back -2.00 mm, up/down 10.00 mm.")
    assert lines[4] == "Weight, solid PLA (1.24 g/cm³) all through: 9.92 g."
    typed = measure.describe_amount(found, 1, measure.material(measure.TYPED, 2.7))
    assert typed.endswith("Weight, solid at 2.70 g/cm³ all through: 21.60 g.")
    big = measure.Amount(1_000_000.0, 60000.0, np.array([100.0, 100.0, 100.0]), np.zeros(3))
    assert measure.describe_amount(big, 1, ("PETG", 1.27)).endswith(": 1270.00 g (1.270 kg).")
    assert len(measure.describe_amount(found, 1).split("\n")) == 4  # no material, no weight
    for text in (typed, "\n".join(lines), measure.NO_DENSITY):
        assert_plain(text)


# --- In the window ----------------------------------------------------------------------


def add(window, kind, x=0.0):
    window.add_primitive(kind)
    shape = window.document.scene.shapes[-1]
    shape.transform[0, 3] = x
    window.sync()
    return shape


def test_measuring_between_two_clicked_faces(window, qapp):
    box = add(window, "cube")
    steps, revision = len(window.document._undo), window.document.revision
    window.do_measure_faces()
    assert window.tool == "measure_faces"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["measure_faces"]
    window._on_surface_picked(box.id, face_towards(box, (-1, 0, 0)), (-10, 0, 5))
    assert window.statusBar().currentMessage() == (
        "Face area: 400.00 mm². " + window.TOOL_PROMPTS["measure_faces_second"])
    window._on_surface_picked(box.id, face_towards(box, (1, 0, 0)), (10, 0, 5))
    qapp.processEvents()
    assert "The faces are parallel, 20.00 mm apart" in window.measure_window.text()
    assert window.measure_window.isVisible() and not window.measure_window.isModal()
    assert window.viewport.measure_actor is not None
    # Still measuring, from a fresh first click; nothing changed.
    assert window.tool == "measure_faces" and window.statusBar().currentMessage() == window.MEASURE_AGAIN
    assert len(window.document._undo) == steps and window.document.revision == revision
    window._on_surface_picked(box.id, face_towards(box, (0, 0, 1)), (0, 0, 20))
    assert window.viewport.measure_actor is None
    window.stop_tool()
    assert window.tool is None


def test_measuring_between_faces_of_two_parts(window, qapp):
    a, b = add(window, "cube"), add(window, "cube", 35.0)
    window.do_measure_faces()
    window._on_surface_picked(a.id, face_towards(a, (1, 0, 0)), (10, 0, 5))
    window._on_surface_picked(b.id, face_towards(b, (-1, 0, 0)), (25, 0, 5))
    qapp.processEvents()
    assert "15.00 mm apart" in window.measure_window.text()


def test_a_click_on_nothing_or_a_guide_keeps_waiting(window):
    window.document.scene.add(construct.new_point((0, 0, 0)))
    window.do_measure_faces()
    window._on_surface_picked("", -1, (0, 0, 0))
    window._on_surface_picked(window.document.scene.shapes[0].id, 0, (0, 0, 0))
    assert window.tool == "measure_faces" and window._construct_picks == []
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["measure_faces"]


def test_volume_and_area_of_the_selected_parts(window, warnings):
    a, b = add(window, "cube"), add(window, "cube", 50.0)
    window.document.scene.select([a.id, b.id])
    steps = len(window.document._undo)
    assert window.measure_selected()
    text = window.measure_window.text()
    assert text.startswith("The 2 selected parts, together, take up 16000.00 mm³")
    assert "Size: 70.00 x 20.00 x 20.00 mm" in text and len(window.document._undo) == steps
    window.document.scene.select([])
    window.do_measure_volume()
    assert window.statusBar().currentMessage() == window.VOLUME_HINT and not warnings


def test_volume_and_area_weighs_the_parts_as_the_chosen_material(window, warnings, monkeypatch):
    from mesh import inspect_actions

    asked = []
    answers = [None, {"material": "petg", "density": 1.0},
               {"material": measure.TYPED, "density": 2.7}]

    def ask(parent, material, density):
        asked.append((material, density))
        return answers.pop(0)

    monkeypatch.setattr(inspect_actions, "ask_volume", ask)
    box = add(window, "cube")
    window.document.scene.select([])
    window.do_measure_volume()  # nothing selected: not asked
    assert window.statusBar().currentMessage() == window.VOLUME_HINT and asked == []
    window.document.scene.select([box.id])
    steps, revision = len(window.document._undo), window.document.revision
    window.do_measure_volume()  # cancelled
    assert getattr(window, "measure_window", None) is None
    window.do_measure_volume()
    text = window.measure_window.text()
    assert "Centre of gravity, the same material all through: left/right 0.00 mm" in text
    assert text.endswith("Weight, solid PETG (1.27 g/cm³) all through: 10.16 g.")
    window.do_measure_volume()  # the last choice comes up again
    assert asked == [("pla", 1.0), ("pla", 1.0), ("petg", 1.0)]
    assert window.measure_window.text().endswith("Weight, solid at 2.70 g/cm³ all through: 21.60 g.")
    assert len(window.document._undo) == steps and window.document.revision == revision and not warnings
    assert not window.measure_selected(measure.TYPED, 0.0) and warnings == [measure.NO_DENSITY]


def test_the_volume_form_is_plain_language(qapp, close_qt_widget):
    from mesh.inspect_actions import VOLUME_NOTE, volume_fields
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Volume and Area", volume_fields("asa", 2.5), VOLUME_NOTE))
    assert dialog.values() == {"material": "asa", "density": 2.5}
    texts = [VOLUME_NOTE, *dialog.labels()]
    texts += [dialog.widgets["material"].itemText(i) for i in range(dialog.widgets["material"].count())]
    for text in texts:
        assert_plain(text)


def test_a_hole_alone_is_refused(window, warnings):
    hole = add(window, "cube")
    hole.is_hole = True
    window.document.scene.select([hole.id])
    assert not window.measure_selected() and warnings


def test_turning_expert_mode_off_puts_the_measurements_away(window, qapp):
    box = add(window, "cube")
    window.document.scene.select([box.id])
    window.measure_selected()
    window.do_measure_faces()
    window.set_expert_mode(False)
    assert window.tool is None and not window.measure_window.isVisible()


# --- The radius of a round face ----------------------------------------------------------


def strip_towards(shape, direction, clearances=None):
    """A narrow flat strip of a round part facing `direction` (the furthest
    that way, of those facing it), and its middle."""
    tm = shape_geometry(shape, clearances)
    direction = np.asarray(direction, dtype=np.float64)
    facing = tm.face_normals @ direction
    candidates = np.flatnonzero(facing > facing.max() - 1e-6)
    face = int(candidates[np.argmax(tm.triangles_center[candidates] @ direction)])
    return face, tm.triangles_center[face]


def radius_of(shape, direction, clearances=None):
    face, middle = strip_towards(shape, direction, clearances)
    return measure.round_face(shape, face, middle, clearances)


def test_the_radius_of_a_cylinder_a_cone_and_a_ball():
    found = radius_of(new_primitive("cylinder"), (1, 1, 0))  # 20 across
    assert found.text == "Cylinder: this round face is a cylinder, radius 10.00 mm (diameter 20.00 mm)."
    centre, point = found.line  # from the part's middle line out to its true round side
    assert centre[:2] == pytest.approx((0.0, 0.0)) and np.hypot(point[0], point[1]) == pytest.approx(10.0)
    assert point[2] == pytest.approx(centre[2])
    cone = radius_of(new_primitive("cone"), (1, 0, 0.5))  # 20 across at the bottom, 20 high
    assert "a cone, its radius going from 0.00 mm to 10.00 mm, sloping 26.6°" in cone.text
    centre, point = cone.line
    assert np.hypot(point[0], point[1]) == pytest.approx(10.0 * (1 - point[2] / 20.0))
    ball = radius_of(new_primitive("sphere"), (1, -1, 1))
    assert ball.text == "Sphere: this round face is part of a ball, radius 10.00 mm (diameter 20.00 mm)."
    assert np.linalg.norm(ball.line[1] - ball.line[0]) == pytest.approx(10.0)


def test_a_ring_and_a_rounded_edge_curve_two_ways():
    ring = radius_of(new_primitive("torus"), (1, 0, 0))  # 20 across, 6 thick
    assert ("Across it, the radius is 3.00 mm, curving round a point 7.00 mm from the part's middle line. "
            "Round that line, where clicked, the radius is ") in ring.text
    assert np.linalg.norm(ring.line[1] - ring.line[0]) == pytest.approx(3.0)
    rounded = new_primitive("rounded_cylinder")  # 20 across, its top edge rounded 3 mm
    found = radius_of(rounded, (1, 0, 1))
    assert "Across it, the radius is 3.00 mm, curving round a point 7.00 mm" in found.text


def test_the_inside_of_a_tube_and_a_fitted_hole():
    tube = new_primitive("tube")  # 20 across with 2 mm walls
    tm = shape_geometry(tube)
    inward = np.column_stack([-tm.triangles_center[:, :2], np.zeros(len(tm.faces))])
    inside = int(np.argmax(np.einsum("ij,ij->i", tm.face_normals, inward)))
    found = measure.round_face(tube, inside, tm.triangles_center[inside])
    assert "a cylinder, radius 8.00 mm (diameter 16.00 mm)" in found.text
    hole = new_primitive("cylinder")
    hole.is_hole, hole.fit = True, "loose"
    fits = {"press": 0.1, "snug": 0.2, "loose": 0.4}
    assert "radius 10.40 mm (diameter 20.80 mm)" in radius_of(hole, (1, 0, 0), fits).text  # as drawn


def test_the_radius_of_a_revolved_part():
    from mesh import create, sketch

    outline = create.new_sketch([{"type": "rectangle", "corner": [5, 0], "width": 5, "height": 10}],
                                sketch.plane_frame((0, -1, 0)))
    turned = create.make_revolve(outline, "y")
    assert "a cylinder, radius 10.00 mm (diameter 20.00 mm)" in radius_of(turned, (1, 0, 0)).text


def test_saying_plainly_when_the_radius_cant_be_told():
    cylinder = new_primitive("cylinder")
    end = measure.round_face(cylinder, face_towards(cylinder, (0, 0, 1)), (0, 0, 20))
    assert end.text == "That face of Cylinder is flat, not round." and end.line is None
    box = measure.round_face(new_primitive("cube"), 0, (0, 0, 0))
    assert "Box is not a cylinder, cone, tube, ring, ball" in box.text and box.line is None
    stretched = new_primitive("cylinder")
    stretched.transform[0, 0] = 2.0
    found = radius_of(stretched, (1, 0, 0))
    assert "is stretched, so its round surfaces can't be told" in found.text and found.line is None
    thread = new_primitive("thread")  # 10 across
    tm = shape_geometry(thread)
    flank = int(np.argmax(np.abs(tm.face_normals[:, 2]) * (np.abs(tm.face_normals[:, 2]) < 0.9)))
    found = measure.round_face(thread, flank, tm.triangles_center[flank])
    assert found.text.endswith("A thread's sloping sides wind round it; its outer diameter is 10.00 mm.")
    for text in (end.text, box.text, found.text):
        assert_plain(text)


def test_measuring_the_radius_of_a_clicked_round_face(window, qapp):
    cylinder = add(window, "cylinder")
    steps, revision = len(window.document._undo), window.document.revision
    window.do_measure_radius()
    assert window.tool == "measure_radius"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["measure_radius"]
    face, middle = strip_towards(cylinder, (0, -1, 0))
    window._on_surface_picked(cylinder.id, face, middle)
    qapp.processEvents()
    assert window.measure_window.text().startswith("Cylinder: this round face is a cylinder, radius 10.00 mm")
    assert window.measure_window.windowTitle() == "Radius of a Round Face"
    assert window.viewport.measure_actor is not None
    # Still measuring; nothing changed.
    assert window.tool == "measure_radius" and window.statusBar().currentMessage() == window.RADIUS_AGAIN
    assert len(window.document._undo) == steps and window.document.revision == revision
    window._on_surface_picked(cylinder.id, face_towards(cylinder, (0, 0, 1)), (0, 0, 20))
    qapp.processEvents()
    assert window.measure_window.text() == "That face of Cylinder is flat, not round."
    assert window.viewport.measure_actor is None
    window._on_surface_picked("", -1, (0, 0, 0))  # nothing there: keeps waiting
    assert window.tool == "measure_radius"
    window.stop_tool()
    assert window.tool is None


# --- The length of an edge ---------------------------------------------------------------


def test_the_length_of_a_straight_edge():
    box = new_primitive("cube")
    box.params.update(width=30.0)
    top = face_towards(box, (0, 0, 1))
    found = construct.edge_at(box, top, (3, -9.5, 20))  # by the front edge of the top
    assert measure.describe_edge(box.name, found) == "Box: this edge is 30.00 mm long."
    side = face_towards(box, (1, 0, 0))
    upright = construct.edge_at(box, side, (15, 9.5, 4))
    assert measure.describe_edge("Box", upright) == "Box: this edge is 20.00 mm long."


def test_a_round_edge_gives_the_piece_clicked_and_all_the_way_round():
    cylinder = new_primitive("cylinder")  # 20 across
    found = construct.edge_at(cylinder, face_towards(cylinder, (0, 0, 1)), (9.9, 0.4, 20.0))
    text = measure.describe_edge(cylinder.name, found)
    lines = text.split("\n")
    assert lines[0] == f"Cylinder: the straight stretch of the edge clicked is {found.length:.2f} mm long."
    assert found.length < 1.0
    assert lines[1] == f"The edge goes on all the way round: {found.run_length:.2f} mm round."
    assert found.run_length == pytest.approx(2 * np.pi * 10, rel=1e-3) and found.run_length < 2 * np.pi * 10
    assert lines[2] == measure.EDGE_NOTE
    assert_plain(text)


def test_an_edge_that_goes_on_round_a_curve():
    from mesh import ops

    cut = new_primitive("cube")
    cut.is_hole = True
    cut.params.update(width=30.0, height=30.0)
    cut.transform[:3, 3] = (0.0, 10.0, -5.0)  # takes off the back half, top to bottom
    half = ops.make_group([new_primitive("cylinder"), cut])  # half a cylinder, 20 across
    tm = shape_geometry(half)
    top = int(np.flatnonzero(tm.face_normals[:, 2] > 0.999)[0])
    straight = construct.edge_at(half, top, (2.0, -0.2, 20.0))  # by the cut edge, straight across
    assert measure.describe_edge(half.name, straight) == f"{half.name}: this edge is 20.00 mm long."
    curve = construct.edge_at(half, top, (0.0, -9.8, 20.0))  # by the round edge, at its front
    assert not curve.closed and not curve.straight
    lines = measure.describe_edge(half.name, curve).split("\n")
    assert lines[1] == f"The edge goes on round its curves: {curve.run_length:.2f} mm long in all."
    assert curve.run_length == pytest.approx(np.pi * 10, rel=1e-3)


def test_measuring_the_length_of_a_clicked_edge(window, qapp):
    box = add(window, "cube")
    window.add_primitive("sphere")
    ball = window.document.scene.shapes[-1]
    steps, revision = len(window.document._undo), window.document.revision
    window.do_measure_edge()
    assert window.tool == "measure_edge"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["measure_edge"]
    window._on_surface_picked(ball.id, 0, shape_geometry(ball).triangles_center[0])
    assert window.tool == "measure_edge" and "no sharp edge" in window.statusBar().currentMessage()
    window._on_surface_picked(box.id, face_towards(box, (0, -1, 0)), (-9.6, -10, 7))
    qapp.processEvents()
    assert window.measure_window.text() == "Box: this edge is 20.00 mm long."
    assert window.measure_window.windowTitle() == "Length of an Edge"
    assert window.viewport.measure_actor is not None
    # Still measuring; nothing changed.
    assert window.tool == "measure_edge" and window.statusBar().currentMessage() == window.EDGE_AGAIN
    assert len(window.document._undo) == steps and window.document.revision == revision
    window.stop_tool()
    assert window.tool is None


# --- The shortest distance between two parts ---------------------------------------------


def at(kind, x=0.0, y=0.0, z=0.0):
    shape = new_primitive(kind)
    shape.transform[:3, 3] = (x, y, z)
    return shape


def test_the_shortest_distance_between_two_parts():
    found = measure.gap(at("cube"), at("cube", 35.0))
    assert found.distance == pytest.approx(15.0) and not found.overlap
    corner = measure.gap(at("cube"), at("cube", 30.0, 30.0, 30.0))  # corner to corner
    assert corner.distance == pytest.approx(np.sqrt(3 * 10.0 ** 2))
    ball = measure.gap(at("cube"), at("sphere", 0.0, 0.0, 25.0))  # the ball's bottom is 5 above the box
    assert ball.distance == pytest.approx(5.0, abs=0.05)


def test_parts_that_touch_or_overlap_have_no_gap():
    touching = measure.gap(at("cube"), at("cube", 20.0))
    assert touching.distance == pytest.approx(0.0) and not touching.overlap
    inside = at("cube", 0.0, 0.0, 5.0)
    inside.params.update(width=4.0, depth=4.0, height=4.0)
    for other in (at("cube", 10.0), inside):
        found = measure.gap(at("cube"), other)
        assert found.overlap and found.distance == 0.0


def test_a_fitted_hole_is_measured_as_drawn():
    hole = at("cube", 35.0)
    hole.is_hole, hole.fit = True, "loose"
    assert measure.gap(at("cube"), hole, {"press": 0.1, "snug": 0.2, "loose": 0.4}).distance == pytest.approx(14.6)


def test_the_distance_needs_two_closed_parts(monkeypatch):
    box = at("cube")
    for other, expected in ((construct.new_point((50, 0, 0)), "is a guide, not a part"),
                            (box, "two different parts")):
        with pytest.raises(BuildError) as err:
            measure.gap(box, other)
        assert expected in str(err.value)
        assert_plain(str(err.value))
    tm = shape_geometry(box)
    open_box = trimesh.Trimesh(vertices=tm.vertices, faces=tm.faces[:-2], process=False)
    monkeypatch.setattr(measure, "shape_geometry", lambda shape, clearances=None: open_box)
    with pytest.raises(BuildError) as err:
        measure.gap(box, at("cube", 50.0))
    assert str(err.value) == f"{box.name} has gaps in its surface, so the distance to it can't be measured."


def test_describing_the_distance():
    text = measure.describe_gap("Box 1", "Box 2", measure.Gap(15.0, False))
    assert text.startswith("Shortest distance between Box 1 and Box 2: 15.00 mm.")
    assert "touch" in measure.describe_gap("A", "B", measure.Gap(0.0, False))
    assert "overlap" in measure.describe_gap("A", "B", measure.Gap(0.0, True))
    for found in (measure.Gap(15.0, False), measure.Gap(0.0, False), measure.Gap(0.0, True)):
        assert_plain(measure.describe_gap("Box 1", "Box 2", found))


def test_the_shortest_distance_between_the_selected_parts(window, warnings):
    a, b = add(window, "cube"), add(window, "cube", 32.0)
    window.do_measure_gap()
    assert window.statusBar().currentMessage() == window.GAP_HINT
    window.document.scene.select([a.id, b.id])
    steps, revision = len(window.document._undo), window.document.revision
    window.do_measure_gap()
    assert window.measure_window.text().startswith(f"Shortest distance between {a.name} and {b.name}: 12.00 mm.")
    assert window.measure_window.windowTitle() == "Shortest Distance"
    assert len(window.document._undo) == steps and window.document.revision == revision and not warnings


def test_measure_text_is_plain_language():
    from mesh.inspect_actions import InspectActions

    for text in (*InspectActions.INSPECT_TOOL_PROMPTS.values(), InspectActions.MEASURE_AGAIN,
                 InspectActions.VOLUME_HINT, InspectActions.GAP_HINT, InspectActions.RADIUS_AGAIN,
                 InspectActions.EDGE_AGAIN, measure.EDGE_NOTE, measure.GAP_NOTE, measure.OPEN_SURFACE,
                 *(t.tip for t in TOOLS if t.menu == "inspect"),
                 *(t.label for t in TOOLS if t.menu == "inspect")):
        assert_plain(text)
