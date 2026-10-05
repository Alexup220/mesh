"""Components (Expert mode, Phase 5): separate parts kept together by name."""

import copy
import json

import numpy as np
import pytest
import trimesh

from mesh import component_actions, components
from mesh.components import ComponentError
from mesh.expert import TOOLS
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
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
    return int(np.flatnonzero(tm.face_normals @ np.asarray(direction, dtype=np.float64) > 1.0 - 1e-9)[0])


def add(window, kind="cube", dx=0.0):
    window.add_primitive(kind)
    if dx:
        window.move_copy_selected(dx=dx)
    return window.document.scene.selected()[0]


def pair(window):
    """Two boxes, side by side, made into one component."""
    first, second = add(window), add(window, "cylinder", dx=40.0)
    window.document.scene.select([first.id, second.id])
    assert window.make_component()
    return first, second, window.document.scene.components[0]


# --- The rules ---------------------------------------------------------------------------


def test_names_count_up_and_must_be_new():
    listed = [{"id": "a", "name": "Component 1"}, {"id": "b", "name": "Component 3"}]
    assert components.next_name(listed) == "Component 2"
    assert components.next_name(listed, "Wheel copy") == "Wheel copy 1"
    assert components.check_name("  Lid   hinge ", listed) == "Lid hinge"
    assert components.check_name("Component 1", listed, own_id="a") == "Component 1"
    for name, words in (("", "needs a name"), ("Component 3", "already a component called"),
                        ("x" * 61, "at most 60")):
        with pytest.raises(ComponentError) as err:
            components.check_name(name, listed)
        assert words in str(err.value)
        assert_plain(str(err.value))


def test_ids_come_from_what_a_component_is_made_of():
    assert components.new_id("a,b", set()) == components.new_id("a,b", set())
    assert components.new_id("a,b", set()) != components.new_id("b,a", set())
    taken = {components.new_id("a,b", set())}
    assert components.new_id("a,b", taken) not in taken


def test_a_component_is_described_by_its_parts():
    box, ball = new_primitive("cube"), new_primitive("sphere")
    box.component = ball.component = "c"
    made = {"id": "c", "name": "Pair"}
    assert components.describe(made, [box, ball]) == "Pair: 2 parts"
    ball.component = ""
    assert components.describe(made, [box, ball]) == "Pair: 1 part"
    box.visible = False
    assert components.describe(made, [box, ball]) == "Pair: 1 part (hidden)"
    assert components.describe(made, []) == "Pair: no parts"


def test_components_from_a_file_are_checked():
    raw = [{"id": "a", "name": "One"}, {"id": "a", "name": "Again"}, {"name": "no id"}, 5, {"id": "b"}]
    assert components.read(raw) == [{"id": "a", "name": "One"}, {"id": "b", "name": "Component"}]
    assert components.read(None) == []


def test_what_replaces_a_components_parts_joins_it():
    box, tool, loose = new_primitive("cube"), new_primitive("sphere"), new_primitive("cone")
    box.component = "c"
    before = Scene(shapes=[box, tool, loose], components=[{"id": "c", "name": "Kit"}])
    after = copy.deepcopy(before)
    after.remove([box.id, tool.id])
    made = new_primitive("cube")
    after.add(made)
    assert components.carry_over(before, after) == [made] and made.component == "c"
    # Parts of two components: nobody can tell which, so neither.
    tool.component = "d"
    before.components.append({"id": "d", "name": "Other"})
    made.component = ""
    assert components.carry_over(before, after) == [] and made.component == ""
    # Nothing replaced: nothing joins.
    assert components.carry_over(after, after) == []


def test_a_copy_is_a_new_component_beside_the_old():
    box = new_primitive("cube")
    box.component = "c"
    listed = [{"id": "c", "name": "Kit"}]
    made, copies = components.copied([box], listed, "c")
    assert made["name"] == "Kit copy 1" and made["id"] != "c"
    assert [s.component for s in copies] == [made["id"]] and copies[0].id != box.id
    assert np.allclose(copies[0].transform[:3, 3], [10.0, 10.0, 0.0])
    with pytest.raises(ComponentError):
        components.copied([], listed, "c")
    with pytest.raises(ComponentError):
        components.copied([box], listed, "gone")


# --- In the window -----------------------------------------------------------------------


def test_new_component_from_the_selection_is_one_undo_step(window):
    first, second = add(window), add(window, dx=40.0)
    window.document.scene.select([first.id, second.id])
    steps = len(window.document._undo)
    assert window.make_component()
    scene = window.document.scene
    assert scene.components[0]["name"] == "Component 1"
    assert {s.component for s in scene.shapes} == {scene.components[0]["id"]}
    assert len(window.document._undo) == steps + 1
    assert window.statusBar().currentMessage() == "Made Component 1 from 2 selected parts."
    window.do_undo()
    assert window.document.scene.components == [] and {s.component for s in window.document.scene.shapes} == {""}


def test_new_component_needs_a_selection_and_a_new_name(window, warnings):
    window.make_component()
    assert window.statusBar().currentMessage() == window.COMPONENT_NEEDS_PARTS
    pair(window)
    add(window)
    assert not window.make_component("Component 1")
    assert warnings and "already a component called" in warnings[0]


def test_a_part_moves_to_the_newer_component(window):
    first, second, _old = pair(window)
    window.document.scene.select([second.id])
    window.make_component("Wheel")
    scene = window.document.scene
    assert first.component == scene.components[0]["id"] and second.component == scene.components[1]["id"]


def test_select_whole_component(window):
    first, second, _made = pair(window)
    loose = add(window, dx=-40.0)
    window.document.scene.select([second.id])
    window.do_select_component()
    assert window.document.scene.selection == [second.id, first.id]
    window.document.scene.select([loose.id])
    window.do_select_component()
    assert window.statusBar().currentMessage() == window.NOT_IN_A_COMPONENT


def test_take_out_rename_hide_and_break_apart(window, warnings):
    first, second, made = pair(window)
    window.document.scene.select([second.id])
    assert window.leave_component() and second.component == ""
    assert not window.leave_component()
    assert window.rename_component(made["id"], " Gear  box ")
    assert window.document.scene.components[0]["name"] == "Gear box"
    assert not window.rename_component(made["id"], "")
    assert warnings and "needs a name" in warnings[0]
    assert window.set_component_shown(made["id"], False) and not first.visible
    assert not window.set_component_shown(made["id"], False)
    assert window.set_component_shown(made["id"], True) and first.visible
    assert window.break_apart_component(made["id"])
    assert window.document.scene.components == [] and first.component == ""
    assert not window.break_apart_component(made["id"])


def test_copy_component(window):
    _first, _second, made = pair(window)
    assert window.copy_component(made["id"])
    scene = window.document.scene
    assert len(scene.shapes) == 4 and scene.components[1]["name"] == "Component 1 copy 1"
    assert {s.id for s in scene.selected()} == {s.id for s in scene.shapes[2:]}
    assert all(s.component == scene.components[1]["id"] for s in scene.shapes[2:])


def test_a_tool_on_a_components_part_keeps_it_in(window):
    first, _second, made = pair(window)
    window.round_edge(first.id, face_towards(first, (0, 0, 1)), (10.0, 0.0, 20.0), 3.0)
    window.document.scene.select([window.document.scene.shapes[-1].id, window.document.scene.shapes[0].id])
    window.do_group()
    scene = window.document.scene
    assert len(scene.shapes) == 1 and scene.shapes[0].component == made["id"]
    window.do_ungroup()
    assert all(s.component == made["id"] for s in window.document.scene.shapes)


def test_save_one_component_for_printing(window, tmp_path):
    first, _second, made = pair(window)
    add(window, dx=-60.0)
    window.set_component_shown(made["id"], False)
    file = tmp_path / "kit.stl"
    window.export_component(made["id"], file)
    saved = trimesh.load(file)
    assert saved.bounds[0][0] == pytest.approx(-10.0, abs=0.01)
    assert saved.bounds[1][0] == pytest.approx(50.0, abs=0.01)


def test_components_are_saved_with_the_project(tmp_path):
    box = new_primitive("cube")
    box.component = "c"
    scene = Scene(shapes=[box], components=[{"id": "c", "name": "Kit"}])
    file = tmp_path / "kit.mesh"
    save_project(scene, file)
    document = json.loads(file.read_text())
    assert document["format_version"] == 2 and document["scene"]["components"] == [{"id": "c", "name": "Kit"}]
    loaded = load_project(file)
    assert loaded.components == scene.components and loaded.shapes[0].component == "c"
    plain = tmp_path / "plain.mesh"
    save_project(Scene(shapes=[new_primitive("cube")]), plain)
    assert "components" not in json.loads(plain.read_text())["scene"]


def test_the_components_window(window, monkeypatch, tmp_path):
    window.do_components()
    assert window.statusBar().currentMessage() == window.NO_COMPONENTS
    first, _second, made = pair(window)
    dialog = component_actions.ComponentsDialog(window)
    assert [dialog.items.item(i).text() for i in range(dialog.items.count())] == ["Component 1: 2 parts"]
    monkeypatch.setattr(component_actions, "run_form", lambda *a, **k: {"name": "Kit"})
    dialog.act("rename")
    dialog.act("show")
    assert dialog.items.item(0).text() == "Kit: 2 parts (hidden)"
    dialog.act("show")
    window.document.scene.select([])
    dialog.act("select")
    assert len(window.document.scene.selection) == 2
    dialog.act("copy")
    assert dialog.items.count() == 2
    dialog.items.setCurrentRow(0)
    file = tmp_path / "kit.stl"
    monkeypatch.setattr(component_actions.QFileDialog, "getSaveFileName", lambda *a, **k: (str(file), ""))
    dialog.act("save")
    assert file.exists() and window.statusBar().currentMessage() == "Saved kit.stl"
    dialog.act("break")
    assert [dialog.items.item(i).text() for i in range(dialog.items.count())] == ["Kit copy 1: 2 parts"]
    dialog.deleteLater()


def test_component_text_is_plain_language(window):
    for text in (component_actions.COMPONENTS_NOTE, component_actions.NEW_COMPONENT_NOTE,
                 window.COMPONENT_NEEDS_PARTS, window.NOT_IN_A_COMPONENT, window.NO_COMPONENTS,
                 *(t.tip for t in TOOLS if t.menu == "assemble"), *(t.label for t in TOOLS if t.menu == "assemble")):
        assert_plain(text)
