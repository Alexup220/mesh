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


def test_measure_text_is_plain_language():
    from mesh.inspect_actions import InspectActions

    for text in (*InspectActions.INSPECT_TOOL_PROMPTS.values(), InspectActions.MEASURE_AGAIN,
                 InspectActions.VOLUME_HINT, *(t.tip for t in TOOLS if t.menu == "inspect"),
                 *(t.label for t in TOOLS if t.menu == "inspect")):
        assert_plain(text)
