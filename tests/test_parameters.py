"""Named parameters and linked sizes (Expert mode, Phase 5)."""

import json

import numpy as np
import pytest

from mesh import parameter_actions, parameters
from mesh.expert import TOOLS
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

TABLE = [{"name": "width", "formula": "40", "note": ""},
         {"name": "wall", "formula": "2", "note": "thickness"},
         {"name": "inner", "formula": "width - 2 * wall", "note": ""}]


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


# --- Formulas ---------------------------------------------------------------------------


@pytest.mark.parametrize("formula, expected", [
    ("12.5", 12.5), ("width / 2 + wall", 22.0), ("-(wall) ** 2", -4.0), ("2 ^ 3", 8.0),
    ("max(width, 50) - min(1, wall)", 49.0), ("round(sqrt(width))", 6.0),
    ("sin(30) * 10", 5.0), ("pi * 0 + abs(-3)", 3.0), ("width % 7", 5.0),
])
def test_formulas(formula, expected):
    assert parameters.evaluate(formula, {"width": 40.0, "wall": 2.0}) == pytest.approx(expected)


@pytest.mark.parametrize("formula, words", [
    ("widht * 2", "\"widht\", which is not a parameter"),
    ("width / 0", "divides by zero"),
    ("width +", "can't be read as a formula"),
    ("__import__('os')", "can't be read as a formula"),
    ("width.real", "can't be read as a formula"),
    ("'text'", "can't be read as a formula"),
    ("(-8) ** 0.5", "does not come to a number"),
    ("10.0 ** 400", "too big"),
    ("", "can't be empty"),
])
def test_formulas_that_cannot_be_worked_out(formula, words):
    with pytest.raises(parameters.ParameterError) as err:
        parameters.evaluate(formula, {"width": 40.0})
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_parameters_are_worked_out_in_the_order_they_need():
    rows = [TABLE[2], TABLE[0], TABLE[1]]
    assert parameters.values(rows) == {"inner": 36.0, "width": 40.0, "wall": 2.0}
    assert parameters.names_in("inner + width * pi") == {"inner", "width"}


@pytest.mark.parametrize("rows, words", [
    ([{"name": "a", "formula": "b + 1"}, {"name": "b", "formula": "a"}], "need each other"),
    ([{"name": "a", "formula": "a"}], "a → a"),
    ([{"name": "a", "formula": "1"}, {"name": "a", "formula": "2"}], "two parameters called"),
    ([{"name": "2nd", "formula": "1"}], "can't be a parameter name"),
    ([{"name": "sqrt", "formula": "1"}], "already used in formulas"),
])
def test_tables_that_cannot_be_used(rows, words):
    with pytest.raises(parameters.ParameterError) as err:
        parameters.values(rows)
    assert words in str(err.value)


# --- Links ------------------------------------------------------------------------------


def test_what_can_be_linked():
    assert parameters.linkable(new_primitive("cube")) == ["x", "y", "z", "rx", "ry", "rz", "width", "depth",
                                                         "height", "chamfer"]
    assert "size" not in parameters.linkable(new_primitive("screw_hole"))  # a choice, not a number
    from mesh import construct

    assert parameters.linkable(construct.new_point((0, 0, 0))) == ["x", "y", "z", "rx", "ry", "rz"]


def test_links_set_sizes_positions_and_turns():
    box = new_primitive("cube")
    box.links = {"width": "inner", "x": "width / 2", "rz": "45", "chamfer": "wall / 2"}
    changed = parameters.apply_links([box, new_primitive("sphere")], parameters.values(TABLE))
    assert changed == [box]
    assert box.params["width"] == 36 and box.params["chamfer"] == 1
    assert box.transform[0, 3] == 20 and parameters.current(box, "rz") == pytest.approx(45)
    assert parameters.apply_links([box], parameters.values(TABLE)) == []  # nothing new


@pytest.mark.parametrize("links, words", [
    ({"width": "wall - 2"}, "width would be 0"),
    ({"chamfer": "-wall"}, "chamfer would be -2"),
    ({"letter_height": "2"}, "has no letter height"),
    ({"x": "nope"}, "\"nope\", which is not a parameter"),
])
def test_links_that_cannot_be_used(links, words):
    box = new_primitive("cube")
    with pytest.raises(parameters.ParameterError) as err:
        parameters.check_links(box, links, parameters.values(TABLE))
    assert words in str(err.value)
    assert_plain(str(err.value))


CURVES = [{"type": "rectangle", "corner": [0.0, 0.0], "width": 20.0, "height": 10.0},
          {"type": "polygon", "centre": [40.0, 0.0], "sides": 6, "radius": 5.0, "angle": 0.0},
          {"type": "spline", "points": [[0.0, 30.0], [10.0, 40.0], [20.0, 30.0]], "closed": False}]


def test_a_sketchs_curves_can_be_linked():
    from mesh import create

    drawn = create.new_sketch(CURVES, np.eye(4))
    fields = parameters.linkable(drawn)
    assert fields[:6] == ["x", "y", "z", "rx", "ry", "rz"]
    assert {"curve1.corner.x", "curve1.width", "curve2.sides", "curve2.angle", "curve3.points.2.y"} <= set(fields)
    assert "curve3.closed" not in fields
    assert parameters.field_words("curve3.points.2.y") == "curve 3 point 2 Y"
    assert parameters.curve_label(drawn, "curve1.corner.x") == "Curve 1 (rectangle): corner X (mm)"
    assert parameters.curve_label(drawn, "curve2.angle") == "Curve 2 (polygon): turn (degrees)"
    drawn.links = {"curve1.width": "width", "curve2.sides": "wall * 2.2", "curve3.points.2.y": "inner"}
    assert parameters.apply_links([drawn], parameters.values(TABLE)) == [drawn]
    rect, polygon, spline = drawn.params["entities"]
    assert rect["width"] == 40.0 and polygon["sides"] == 4 and spline["points"][1] == [10.0, 36.0]
    assert CURVES[0]["width"] == 20.0  # the curves given are not changed
    assert parameters.current(drawn, "curve2.sides") == 4


@pytest.mark.parametrize("links, words", [
    ({"curve1.width": "wall - 2"}, "curve 1 width would be 0"),
    ({"curve2.sides": "wall"}, "curve 2 sides would be 2"),
    ({"curve4.width": "2"}, "has no curve 4 width"),
])
def test_curve_links_that_cannot_be_used(links, words):
    from mesh import create

    drawn = create.new_sketch(CURVES, np.eye(4))
    with pytest.raises(parameters.ParameterError) as err:
        parameters.check_links(drawn, links, parameters.values(TABLE))
    assert words in str(err.value)
    assert_plain(str(err.value))


def test_a_curve_a_sketch_cannot_draw_is_refused():
    from mesh import create

    drawn = create.new_sketch([{"type": "line", "start": [0.0, 0.0], "end": [10.0, 0.0]}], np.eye(4))
    drawn.links = {"curve1.end.x": "wall - 2"}
    with pytest.raises(parameters.ParameterError) as err:
        parameters.apply_links([drawn], parameters.values(TABLE))
    assert "curve 1 can't take 0 there" in str(err.value)
    assert_plain(str(err.value))


def test_users_of_a_parameter():
    a, b = new_primitive("cube"), new_primitive("cube")
    a.links = {"width": "inner + 1"}
    b.links = {"x": "wall"}
    assert parameters.users([a, b], "inner") == [a]


def test_parameters_and_links_round_trip_and_mark_the_file(tmp_path):
    box = new_primitive("cube")
    box.links = {"width": "inner"}
    file = tmp_path / "linked.mesh"
    save_project(Scene(shapes=[box], parameters=[dict(r) for r in TABLE]), file)
    assert json.loads(file.read_text())["format_version"] == 2
    loaded = load_project(file)
    assert loaded.parameters == TABLE and loaded.shapes[0].links == {"width": "inner"}
    plain = tmp_path / "plain.mesh"
    save_project(Scene(shapes=[new_primitive("cube")]), plain)
    document = json.loads(plain.read_text())
    assert document["format_version"] == 1 and "parameters" not in document["scene"]
    assert "links" not in document["scene"]["shapes"][0]


def test_a_newer_project_file_is_refused(tmp_path):
    from mesh.io_formats import ProjectError

    file = tmp_path / "future.mesh"
    file.write_text(json.dumps({"format_version": 3, "scene": {"shapes": []}}))
    with pytest.raises(ProjectError) as err:
        load_project(file)
    assert "newer version of mesh" in str(err.value)


# --- In the window ----------------------------------------------------------------------


def add_box(window):
    window.add_primitive("cube")
    return window.document.scene.shapes[-1]


def test_changing_parameters_moves_linked_parts_in_one_undo_step(window):
    box = add_box(window)
    assert window.set_parameters(TABLE)
    assert window.set_links(box.id, {"width": "inner", "height": "wall * 5", "depth": ""})
    assert box.links == {"width": "inner", "height": "wall * 5"}
    assert (box.params["width"], box.params["height"], box.params["depth"]) == (36, 10, 20)
    steps = len(window.document._undo)
    assert window.set_parameters([{**TABLE[0], "formula": "60"}, *TABLE[1:]])
    assert box.params["width"] == 56 and len(window.document._undo) == steps + 1
    assert shape_geometry(box).extents.tolist() == pytest.approx([56, 20, 10])
    window.do_undo()
    assert window.document.scene.shapes[0].params["width"] == 36
    assert window.document.scene.parameters == TABLE


def test_a_change_no_linked_part_can_take_is_refused(window, warnings):
    box = add_box(window)
    window.set_parameters(TABLE)
    window.set_links(box.id, {"width": "inner"})
    steps = len(window.document._undo)
    assert not window.set_parameters([{**TABLE[0], "formula": "4"}, *TABLE[1:]])
    assert warnings and warnings[-1].startswith("Box:") and "width would be 0" in warnings[-1]
    assert not window.set_parameters([TABLE[0], TABLE[1]])  # "inner" is still used
    assert "\"inner\", which is not a parameter" in warnings[-1]
    assert len(window.document._undo) == steps and window.document.scene.parameters == TABLE


def test_a_thread_pitch_that_cannot_be_built_is_refused(window, warnings):
    window.add_primitive("cylinder")
    cylinder = window.document.scene.shapes[0]
    window.thread_selected(2.5, 20.0)
    window.set_parameters([{"name": "p", "formula": "2"}])
    window.set_links(cylinder.id, {"pitch": "p"})
    assert not window.set_parameters([{"name": "p", "formula": "20"}])
    assert "can't take those numbers" in warnings[-1] and cylinder.params["pitch"] == 2


def test_typing_a_number_in_details_ends_the_link(window):
    box = add_box(window)
    window.set_parameters(TABLE)
    window.set_links(box.id, {"width": "inner", "x": "wall"})
    window.document.scene.select([box.id])
    window.sync()
    box_field = window.inspector.fields["width"]
    assert "inner" in box_field.toolTip() and window.inspector.field_labels["width"].font().italic()
    box_field.setValue(25.0)
    assert box.params["width"] == 25 and box.links == {"x": "wall"}
    window._finish_edit()
    assert box_field.toolTip() == "" and not window.inspector.field_labels["width"].font().italic()
    assert window.statusBar().currentMessage() == window.LINK_ENDED
    window._finish_edit()
    assert window.statusBar().currentMessage() != window.LINK_ENDED  # said once
    window.set_parameters([{**TABLE[0], "formula": "80"}, *TABLE[1:]])
    assert box.params["width"] == 25  # no longer follows


def test_linked_copies_follow_too(window):
    box = add_box(window)
    window.set_parameters(TABLE)
    window.set_links(box.id, {"width": "width"})
    window.document.scene.select([box.id])
    window.rectangular_pattern_selected(3, 50.0, "x")
    window.set_parameters([{**TABLE[0], "formula": "30"}, *TABLE[1:]])
    assert [s.params["width"] for s in window.document.scene.shapes] == [30, 30, 30]


def test_the_change_parameters_window(window, qapp, monkeypatch, warnings):
    dialog = parameter_actions.ParametersDialog(window, TABLE)
    assert dialog.table.item(2, 2).text() == "36"
    dialog.table.item(0, 1).setText("50")
    assert dialog.table.item(2, 2).text() == "46"
    dialog.add_row()
    assert dialog.rows()[-1] == {"name": "d4", "formula": "10", "note": ""}
    dialog.table.item(3, 1).setText("inner + nothing")
    assert dialog.table.item(3, 2).text() == "?"
    dialog.accept()
    assert warnings and "\"nothing\"" in warnings[0] and dialog.result() == 0
    dialog.table.selectRow(3)
    dialog.remove_selected()
    assert [r["name"] for r in dialog.rows()] == ["width", "wall", "inner"]
    dialog.deleteLater()
    monkeypatch.setattr(parameter_actions, "ask_parameters", lambda parent, rows: rows + [
        {"name": "gap", "formula": "0.2", "note": ""}])
    window.do_change_parameters()
    assert [r["name"] for r in window.document.scene.parameters] == ["gap"]


def test_linking_through_the_form(window, monkeypatch):
    seen = {}
    box = add_box(window)
    window.document.scene.select([])
    window.do_link_sizes()
    assert window.statusBar().currentMessage() == window.LINK_NEEDS_ONE
    window.document.scene.select([box.id])
    window.do_link_sizes()
    assert window.statusBar().currentMessage() == window.LINK_NEEDS_PARAMETERS
    window.set_parameters(TABLE)
    window.document.scene.select([box.id])
    monkeypatch.setattr(parameter_actions, "ask_links", lambda parent, shape, known: seen.update(
        shape=shape.name, known=known) or {"height": "wall * 3"})
    window.do_link_sizes()
    assert seen["known"]["inner"] == 36 and box.params["height"] == 6


RECT = [{"type": "rectangle", "corner": [0.0, 0.0], "width": 20.0, "height": 10.0},
        {"type": "circle", "centre": [10.0, 5.0], "diameter": 4.0}]


def drawn_sketch(window):
    window.add_sketch(RECT, np.eye(4))
    return window.document.scene.selected()[0]


def test_a_part_made_from_a_sketch_follows_its_linked_curves(window, tmp_path):
    window.set_parameters(TABLE)
    drawn = drawn_sketch(window)
    window.extrude_selected(5.0)
    part = window.document.scene.selected()[0]
    assert window.set_links(part.id, {"curve1.width": "width", "curve2.diameter": "wall * 3"})
    assert part.params["entities"][0]["width"] == 40.0
    volume = shape_geometry(part).volume
    assert volume == pytest.approx((40 * 10 - np.pi * 9) * 5, rel=0.01)
    window.set_parameters([{**TABLE[0], "formula": "30"}, *TABLE[1:]])
    assert shape_geometry(part).volume == pytest.approx((30 * 10 - np.pi * 9) * 5, rel=0.01)
    window.do_undo()
    assert window.document.scene.get(part.id).params["entities"][0]["width"] == 40.0
    file = tmp_path / "curves.mesh"
    window.save_to(file)
    loaded = load_project(file).get(part.id)
    assert loaded.links == {"curve1.width": "width", "curve2.diameter": "wall * 3"}
    assert drawn.id not in {s.id for s in window.document.scene.shapes}


def test_change_sketch_ends_the_links_of_numbers_typed_over(window):
    window.set_parameters(TABLE)
    drawn = drawn_sketch(window)
    assert window.set_links(drawn.id, {"curve1.width": "width", "curve1.height": "inner / 4",
                                       "curve2.diameter": "wall"})
    entities = [dict(e) for e in drawn.params["entities"]]
    entities[0] = {**entities[0], "width": 25.0}  # typed over
    assert window.set_sketch_entities(drawn, entities)
    assert drawn.links == {"curve1.height": "inner / 4", "curve2.diameter": "wall"}
    assert window.statusBar().currentMessage() == window.LINK_ENDED
    # Taking the circle out ends its link too.
    assert window.set_sketch_entities(drawn, entities[:1])
    assert drawn.links == {"curve1.height": "inner / 4"}
    window.do_undo()
    window.do_undo()
    assert window.document.scene.get(drawn.id).links["curve1.width"] == "width"


def test_with_a_history_parts_follow_their_sketchs_linked_curves(window):
    window.set_parameters(TABLE)
    window.start_history()
    drawn = drawn_sketch(window)
    window.set_links(drawn.id, {"curve1.width": "width"})
    window.extrude_selected(5.0, keep_sketch=True)
    part = window.document.scene.selected()[0]
    assert np.ptp(shape_geometry(part).bounds, axis=0)[0] == pytest.approx(40.0)
    assert window.set_parameters([{**TABLE[0], "formula": "60"}, *TABLE[1:]])
    part = window.document.scene.get(part.id)
    assert np.ptp(shape_geometry(part).bounds, axis=0)[0] == pytest.approx(60.0)


def test_curve_labels_in_the_link_form(qapp, close_qt_widget):
    from mesh import create
    from mesh.panels import FormDialog

    drawn = create.new_sketch(CURVES, np.eye(4))
    fields = parameter_actions.link_fields(drawn)
    labels = {key: label for key, label, _value, _options in fields}
    assert labels["curve1.width"] == "Curve 1 (rectangle): width (mm)"
    assert labels["curve3.points.1.x"] == "Curve 3 (spline): point 1 X (mm)"
    assert labels["x"] == "Left / right (mm)"
    dialog = close_qt_widget(FormDialog(None, "Link Sizes of Sketch", fields, note=parameter_actions.link_note({})))
    for text in dialog.labels():
        assert_plain(text)


def test_parameter_text_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    box = new_primitive("cube")
    box.links = {"width": "inner"}
    dialog = close_qt_widget(FormDialog(None, "Link Sizes of Box", parameter_actions.link_fields(box),
                                        note=parameter_actions.link_note({"width": 40.0})))
    for text in dialog.labels():
        assert_plain(text)
    assert dialog.values()["width"] == "inner" and dialog.values()["height"] == ""
    actions = parameter_actions.ParameterActions
    for text in (parameter_actions.PARAMETERS_NOTE, *parameter_actions.ParametersDialog.COLUMNS,
                 actions.LINK_NEEDS_ONE, actions.LINK_NEEDS_PARAMETERS, actions.LINK_ENDED,
                 *(t.tip for t in TOOLS if t.key in ("parameters", "link_sizes"))):
        assert_plain(text)
    assert np.isfinite(parameters.values(TABLE)["inner"])
