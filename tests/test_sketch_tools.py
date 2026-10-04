"""Sketch tools in the window (Expert mode): the sketch window, adding and
changing sketches with undo, sketching on a face, saving, and sketches
never being printed."""

import json

import numpy as np
import pytest

from mesh import create, ops, sketch, sketch_editor
from mesh.builders import BuildError, hollow, split
from mesh.io_formats import ProjectError, export_scene, load_project, save_project
from mesh.printcheck import check
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

SQUARE = [
    {"type": "line", "start": [0, 0], "end": [10, 0]},
    {"type": "line", "start": [10, 0], "end": [10, 10]},
    {"type": "line", "start": [10, 10], "end": [0, 10]},
    {"type": "line", "start": [0, 10], "end": [0, 0]},
]
CIRCLE = {"type": "circle", "centre": [0, 0], "diameter": 10}


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow(Settings(expert_mode=True)))


@pytest.fixture
def dialog(qapp, close_qt_widget):
    def make(entities=(), guides=()):
        return close_qt_widget(sketch_editor.SketchDialog(None, "Sketch", entities, guides))

    return make


@pytest.fixture
def no_warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    return seen


def scene_json(window):
    return json.dumps(window.document.scene.to_dict(), sort_keys=True)


def sketch_of(entities=SQUARE, frame=None, name="Sketch 1"):
    return create.new_sketch(entities, np.eye(4) if frame is None else frame, name)


# --- The curve forms -----------------------------------------------------------------


@pytest.mark.parametrize("kind", list(sketch_editor.ENTITY_LABELS))
def test_every_curve_form_gives_back_the_curve_it_shows(qapp, close_qt_widget, kind):
    from mesh.panels import FormDialog

    form = close_qt_widget(FormDialog(None, "Curve", sketch_editor.entity_fields(kind)))
    entity = sketch_editor.entity_from_values(kind, form.values())
    assert entity == sketch.clean_entity(sketch_editor.NEW_ENTITIES[kind])
    for text in form.labels():
        assert_plain(text)


def test_curve_forms_take_numbers_left_of_and_below_the_centre(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    form = close_qt_widget(FormDialog(None, "Curve", sketch_editor.entity_fields("circle")))
    form.widgets["centre_x"].setValue(-25.5)
    form.widgets["centre_y"].setValue(-3.0)
    assert sketch_editor.entity_from_values("circle", form.values())["centre"] == [-25.5, -3.0]


def test_spline_points_are_typed_as_pairs():
    assert sketch_editor.parse_points("0, 0; 10 5;\n20,-1") == [[0, 0], [10, 5], [20, -1]]
    with pytest.raises(sketch.SketchError) as err:
        sketch_editor.parse_points("0, 0; 10")
    assert_plain(str(err.value))


# --- The sketch window -----------------------------------------------------------------


def test_the_sketch_window_needs_a_curve_before_ok(dialog):
    from PySide6.QtWidgets import QDialogButtonBox

    d = dialog()
    ok = d.button_box.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()
    assert "No curves yet" in d.status.text()
    d.add_entity(CIRCLE)
    assert ok.isEnabled()
    assert d.entities() == [sketch.clean_entity(CIRCLE)]
    assert d.status.text().startswith("1 closed outline")


def test_the_status_says_what_the_curves_add_up_to():
    assert "open path" in sketch_editor.status_text(SQUARE[:2])
    assert sketch_editor.status_text(SQUARE).startswith("1 closed outline")
    assert "1 open path" in sketch_editor.status_text(SQUARE + [
        {"type": "line", "start": [50, 0], "end": [60, 0]}])
    branching = SQUARE[:2] + [{"type": "line", "start": [10, 0], "end": [20, 0]}]
    assert "three or more" in sketch_editor.status_text(branching)


def test_curves_are_added_changed_and_removed_through_their_forms(dialog, monkeypatch):
    d = dialog()
    answers = iter([
        {"centre_x": 1.0, "centre_y": 2.0, "diameter": 8.0},
        {"centre_x": 1.0, "centre_y": 2.0, "diameter": 12.0},
    ])
    monkeypatch.setattr(sketch_editor, "run_form", lambda *a, **k: next(answers))
    d.ask_new("circle")
    assert d.entities()[0]["diameter"] == 8.0
    d.list.setCurrentRow(0)
    d.change_chosen()
    assert d.entities()[0]["diameter"] == 12.0
    d.remove_chosen()
    assert d.entities() == []


def test_a_bad_curve_is_refused_and_not_added(dialog, monkeypatch, no_warnings):
    d = dialog()
    monkeypatch.setattr(sketch_editor, "run_form", lambda *a, **k: {
        "points": "0, 0", "closed": False})
    d.ask_new("spline")
    assert d.entities() == []
    assert len(no_warnings) == 1
    assert_plain(no_warnings[0])


def test_cancelling_a_curve_form_adds_nothing(dialog, monkeypatch):
    d = dialog([CIRCLE])
    monkeypatch.setattr(sketch_editor, "run_form", lambda *a, **k: None)
    d.ask_new("line")
    d.list.setCurrentRow(0)
    d.change_chosen()
    assert d.entities() == [sketch.clean_entity(CIRCLE)]


def test_clicking_four_corners_and_the_first_again_draws_a_closed_square(dialog):
    d = dialog()
    d.click_point((0, 0))  # ignored: Draw Lines is off
    assert d.entities() == []
    d.draw_button.click()
    assert d.drawing() and d.status.text() == d.DRAW_PROMPT
    for point in [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]:
        d.click_point(point)
    assert len(d.entities()) == 4
    assert d.drawer.points == []  # closing the outline ends the line
    assert sketch.profile(d.entities()).area() == pytest.approx(100.0)


def test_esc_ends_the_line_then_stops_drawing_and_only_then_closes(dialog):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    d = dialog()
    d.show()
    d.set_drawing(True)
    d.click_point((0, 0))
    d.click_point((5, 0))
    QTest.keyClick(d, Qt.Key_Escape)
    assert d.drawing() and d.drawer.points == [] and len(d.entities()) == 1
    QTest.keyClick(d, Qt.Key_Escape)
    assert not d.drawing() and d.isVisible()
    QTest.keyClick(d, Qt.Key_Escape)
    assert not d.isVisible()


def test_a_face_outline_is_shown_and_can_be_copied_in(dialog):
    outline = np.array([[-10, -10], [10, -10], [10, 10], [-10, 10]], dtype=float)
    d = dialog(guides=[outline])
    assert not d.copy_button.isHidden()
    d.copy_guides()
    assert len(d.entities()) == 4
    assert sketch.profile(d.entities()).area() == pytest.approx(400.0)
    assert dialog().copy_button.isHidden()


def test_clicks_snap_to_curve_ends_then_to_the_grid(dialog):
    d = dialog([{"type": "line", "start": [0, 0], "end": [13.37, 0]}])
    preview = d.preview
    preview.resize(400, 400)
    preview.set_content(d.entities())
    end = preview.to_screen((13.37, 0))
    assert preview.snap(end.x() + 3, end.y() - 2) == [13.37, 0.0]
    far = preview.to_screen((5.2, 7.9))
    step = preview.grid_step()
    x, y = preview.snap(far.x(), far.y())
    assert x == pytest.approx(round(5.2 / step) * step)
    assert y == pytest.approx(round(7.9 / step) * step)


def test_the_preview_draws_without_errors(dialog):
    d = dialog([CIRCLE] + SQUARE, guides=[np.array([[0, 0], [5, 0], [5, 5]], dtype=float)])
    d.set_drawing(True)
    d.click_point((20, 20))
    d.preview.resize(300, 300)
    d.preview.grab()  # runs paintEvent


def test_sketch_window_text_is_plain_language(dialog):
    d = dialog([dict(sketch_editor.NEW_ENTITIES[k]) for k in sketch_editor.ENTITY_LABELS],
               guides=[np.zeros((3, 2))])
    for text in d.labels():
        assert_plain(text)
    for _key, label, _default, options in sketch_editor.sketch_plane_fields():
        assert_plain(label)
        for _value, choice in options.get("choices", []):
            assert_plain(choice)
    for note in sketch_editor.PLANE_NOTES.values():
        assert_plain(note)


# --- Adding and changing sketches in the window ----------------------------------------


def test_add_sketch_is_one_undo_step(window):
    assert window.add_sketch(SQUARE, sketch.named_plane_frame("xz", 4.0))
    shape = window.document.scene.shapes[0]
    assert shape.name == "Sketch 1" and create.is_sketch(shape)
    assert window.document.scene.selection == [shape.id]
    assert np.allclose(shape.transform[:3, 3], [0, -4, 0])
    window.do_undo()
    assert window.document.scene.shapes == []
    window.do_redo()
    assert window.document.scene.shapes[0].params["entities"] == sketch.clean_entities(SQUARE)


def test_a_refused_sketch_leaves_no_undo_step(window, no_warnings):
    assert not window.add_sketch([], np.eye(4))
    assert window.document.scene.shapes == [] and not window.document.can_undo()
    assert no_warnings and "at least one curve" in no_warnings[0]


def test_new_sketch_asks_for_a_plane_then_the_curves(window, monkeypatch):
    seen = {}
    monkeypatch.setattr(sketch_editor, "ask_sketch_plane", lambda parent: {"plane": "yz", "distance": 7.0})

    def edit(parent, title, entities=(), guides=(), note=None):
        seen.update(title=title, note=note)
        return [CIRCLE]

    monkeypatch.setattr(sketch_editor, "edit_sketch", edit)
    window.do_new_sketch()
    shape = window.document.scene.shapes[0]
    assert np.allclose(shape.transform, sketch.named_plane_frame("yz", 7.0))
    assert seen["note"] == sketch_editor.PLANE_NOTES["yz"]
    window.do_new_sketch()
    assert [s.name for s in window.document.scene.shapes] == ["Sketch 1", "Sketch 2"]


@pytest.mark.parametrize("cancel_at", ["plane", "curves"])
def test_cancelling_a_new_sketch_changes_nothing(window, monkeypatch, cancel_at):
    monkeypatch.setattr(sketch_editor, "ask_sketch_plane",
                        lambda parent: None if cancel_at == "plane" else {"plane": "xy", "distance": 0.0})
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: None)
    window.do_new_sketch()
    assert window.document.scene.shapes == [] and not window.document.can_undo()


def test_change_sketch_is_one_undo_step(window, monkeypatch):
    window.add_sketch(SQUARE, np.eye(4))
    shape = window.document.scene.shapes[0]
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: [CIRCLE])
    window.do_edit_sketch()
    assert shape.params["entities"] == [sketch.clean_entity(CIRCLE)]
    window.do_undo()
    assert window.document.scene.shapes[0].params["entities"] == sketch.clean_entities(SQUARE)


def test_change_sketch_without_changes_takes_no_undo_step(window, monkeypatch):
    window.add_sketch(SQUARE, np.eye(4))
    steps = len(window.document._undo)
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: list(SQUARE))
    window.do_edit_sketch()
    assert len(window.document._undo) == steps


def test_change_sketch_needs_one_sketch_selected(window, monkeypatch):
    called = []
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: called.append(1))
    window.add_primitive("cube")
    window.do_edit_sketch()
    assert not called
    assert window.statusBar().currentMessage() == "Select one sketch to change its curves."


# --- Sketching on a face ------------------------------------------------------------------


def _top_face(window, shape):
    tm = shape_geometry(shape, window.document.scene.fit_clearances)
    return int(np.argmax(tm.face_normals[:, 2]))


def test_sketch_on_a_face_needs_a_part(window):
    window.do_sketch_on_face()
    assert window.tool is None
    window.add_sketch(SQUARE, np.eye(4))
    window.do_sketch_on_face()
    assert window.tool is None
    assert "Add a part first" in window.statusBar().currentMessage()


def test_sketch_on_a_face_draws_on_the_clicked_face(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    window.do_sketch_on_face()
    assert window.tool == "sketch_face"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["sketch_face"]
    steps = len(window.document._undo)

    seen = {}

    def edit(parent, title, entities=(), guides=(), note=None):
        seen.update(title=title, guides=guides)
        return [CIRCLE]

    monkeypatch.setattr(sketch_editor, "edit_sketch", edit)
    window._on_surface_picked(box.id, _top_face(window, box), (0, 0, 20))
    assert window.tool is None
    assert len(window.document._undo) == steps  # the click itself changes nothing
    qapp.processEvents()  # the sketch window opens once the click is over
    assert seen["title"] == f"Sketch on a face of {box.name}"
    assert len(seen["guides"]) == 1
    sketch_shape = window.document.scene.shapes[-1]
    assert create.is_sketch(sketch_shape)
    assert np.allclose(sketch_shape.transform[:3, 3], [0, 0, 20])
    assert len(window.document._undo) == steps + 1


def test_a_missed_click_keeps_waiting_for_a_face(window):
    window.add_primitive("cube")
    window.do_sketch_on_face()
    window._on_surface_picked("", -1, (0, 0, 0))
    assert window.tool == "sketch_face"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["sketch_face"]


def test_cancelling_the_face_sketch_window_adds_nothing(window, monkeypatch, qapp):
    window.add_primitive("cube")
    box = window.document.scene.shapes[0]
    monkeypatch.setattr(sketch_editor, "edit_sketch", lambda *a, **k: None)
    window.do_sketch_on_face()
    window._on_surface_picked(box.id, _top_face(window, box), (0, 0, 20))
    qapp.processEvents()
    assert len(window.document.scene.shapes) == 1


def test_esc_and_turning_expert_mode_off_stop_sketch_on_face(window):
    window.add_primitive("cube")
    window.do_sketch_on_face()
    window.stop_tool()
    assert window.tool is None
    window.do_sketch_on_face()
    window.set_expert_mode(False)
    assert window.tool is None and window.viewport.pick_mode is None


# --- How sketches look and behave in the window ---------------------------------------


def test_a_sketch_is_drawn_as_lines_over_faint_shading(window):
    from mesh.viewport import GUIDE_FILL_OPACITY, GUIDE_LINE_WIDTH, GUIDE_SELECTED_LINE_WIDTH

    window.add_sketch(SQUARE, np.eye(4))
    shape = window.document.scene.shapes[0]
    viewport = window.viewport
    outline = viewport.outline_for(shape.id)
    assert outline is not None
    assert outline.GetMapper().GetInput().GetNumberOfLines() == 4
    assert viewport.actor_for(shape.id).GetProperty().GetOpacity() == pytest.approx(GUIDE_FILL_OPACITY)
    assert outline.GetProperty().GetLineWidth() == pytest.approx(GUIDE_SELECTED_LINE_WIDTH)
    assert viewport._shape_hit(outline) == shape.id
    window.document.scene.select([])
    window.sync()
    assert outline.GetProperty().GetLineWidth() == pytest.approx(GUIDE_LINE_WIDTH)
    window.document.scene.select([shape.id])
    window.do_delete()
    assert viewport.outline_for(shape.id) is None


def test_a_sketch_has_no_drag_handles_and_no_solid_or_hole_rows(window):
    window.add_sketch(SQUARE, np.eye(4))
    assert not window.gizmo._widget.GetEnabled()
    inspector = window.inspector
    assert not inspector._layout.isRowVisible(inspector._hole_row)
    assert not inspector._layout.isRowVisible(inspector._fit_row)
    assert inspector.visible_param_fields() == set()
    window.add_primitive("cube")
    assert window.gizmo._widget.GetEnabled()
    assert inspector._layout.isRowVisible(inspector._hole_row)


def test_sketches_stay_when_expert_mode_is_off(window):
    window.add_sketch(SQUARE, np.eye(4))
    before = scene_json(window)
    window.set_expert_mode(False)
    assert scene_json(window) == before
    shape = window.document.scene.shapes[0]
    assert window.viewport.outline_for(shape.id) is not None
    window.document.scene.select([shape.id])
    window.sync()
    assert window.inspector.isEnabled()  # it can still be moved and turned


def test_sketches_save_and_open_with_the_project(window, tmp_path, qapp, close_qt_widget):
    from mesh.app import MeshWindow

    window.add_primitive("cube")
    window.add_sketch(SQUARE + [CIRCLE], sketch.named_plane_frame("xz", 2.5), "Sketch 4")
    path = tmp_path / "sketched.mesh"
    window.save_to(path)

    again = close_qt_widget(MeshWindow())
    again.open_from(path)
    original = window.document.scene.shapes[1]
    loaded = again.document.scene.get(original.id)
    assert loaded.name == "Sketch 4"
    assert loaded.params == original.params
    assert np.allclose(loaded.transform, original.transform)
    assert again.viewport.outline_for(loaded.id) is not None
    assert json.loads(path.read_text())["format_version"] == 1


# --- Never printed ------------------------------------------------------------------------


def scene_with_box_and_sketch():
    scene = Scene()
    scene.add(new_primitive("cube"))
    # A big sketch well outside the box: if it counted, the size would grow.
    scene.add(sketch_of([{"type": "rectangle", "corner": [100, 100], "width": 50, "height": 50}]))
    return scene


def test_sketches_are_left_out_of_the_printed_model(tmp_path):
    scene = scene_with_box_and_sketch()
    result = ops.evaluate(scene.shapes)
    assert np.allclose(result.bounds, [[-10, -10, 0], [10, 10, 20]])
    report = check(scene)
    assert report.size_mm == pytest.approx((20, 20, 20))
    path = tmp_path / "out.stl"
    export_scene(scene, path)
    import trimesh

    assert np.allclose(trimesh.load(path).bounds, [[-10, -10, 0], [10, 10, 20]])


def test_a_scene_of_only_sketches_has_nothing_to_print(tmp_path):
    scene = Scene()
    scene.add(sketch_of())
    assert check(scene).empty
    with pytest.raises(ProjectError):
        export_scene(scene, tmp_path / "out.stl")


def test_grouping_or_joining_leaves_sketches_out():
    scene = scene_with_box_and_sketch()
    group = ops.make_group(scene.shapes)
    assert np.allclose(shape_geometry(group).bounds, [[-10, -10, 0], [10, 10, 20]])
    assert [c.name for c in ops.ungroup(group)] == [s.name for s in scene.shapes]
    joined = ops.boolean(scene.shapes, "union")
    assert np.allclose(joined.bounds, [[-10, -10, 0], [10, 10, 20]])


def test_hollow_and_split_refuse_a_sketch_plainly():
    shape = sketch_of()
    for attempt in (lambda: hollow(shape, 2.0), lambda: split(shape, "z", 0.0)):
        with pytest.raises(BuildError) as err:
            attempt()
        assert "sketch is a flat drawing" in str(err.value)
        assert_plain(str(err.value))


def test_a_sketch_round_trips_through_a_project_file(tmp_path):
    scene = Scene()
    shape = sketch_of(SQUARE + [{"type": "spline", "points": [[0, 0], [3, 4], [8, 1]], "closed": True}],
                      sketch.plane_frame((1, 1, 0), (5, 5, 5)))
    scene.add(shape)
    path = tmp_path / "sketch.mesh"
    save_project(scene, path)
    loaded = load_project(path).get(shape.id)
    assert loaded.params == shape.params
    assert np.allclose(loaded.transform, shape.transform)
    assert np.allclose(shape_geometry(loaded).vertices, shape_geometry(shape).vertices)
