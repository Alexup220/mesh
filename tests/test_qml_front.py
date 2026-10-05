"""The QML front end (mesh/qml_app.py, mesh/bridge.py, mesh/qml/).

These run offscreen like the rest of the suite: they check what the panels
are given and what clicking them does, not pixels.
"""

import re
from pathlib import Path

import numpy as np
import pytest

from mesh import themes, ui_catalog
from mesh.bridge import ICON_DIR, THUMBNAIL_DIR, FormSession
from mesh.settings import Settings

QML_DIR = Path(__file__).resolve().parents[1] / "mesh" / "qml" / "Mesh"
FORBIDDEN = ("boolean", "csg", "manifold", "mesh", "vertex", "vertices", "normal", "offset")


@pytest.fixture
def make(qapp, close_qt_widget, tmp_path):
    from mesh.qml_app import QmlWindow

    def build(settings=None, welcome=False):
        window = QmlWindow(settings, themes_dir=tmp_path / "themes", welcome=welcome)
        return close_qt_widget(window)

    return build


@pytest.fixture
def window(make):
    return make()


def settle(qapp, window, rounds=3):
    for _ in range(rounds):
        qapp.processEvents()
    # Inspector edits sync after a short pause; finish it now.
    if window._edit_timer.isActive():
        window._edit_timer.stop()
        window._finish_edit()


def classic_action_keys(window):
    """Every menu item of the window's own (hidden) menus, by key."""
    keys = []

    def walk(menu, path):
        for action in menu.actions():
            if action.isSeparator():
                continue
            if action.menu() is not None:
                walk(action.menu(), path + [action.text().replace("&", "")])
            else:
                keys.append(ui_catalog.command_key(path, action.text()))

    for top in window.menuBar().actions():
        walk(top.menu(), [top.text().replace("&", "")])
    return keys


# --- loading ------------------------------------------------------------------


def test_the_window_loads_every_panel_with_no_qml_warnings(window, qapp):
    window.show()
    window.set_expert_mode(True)
    for name in themes.BUILTIN:
        window.apply_theme(name)
    window.show_command_palette()
    window.show_theme_editor()
    window.show_welcome()
    settle(qapp, window)
    assert window.qml_warnings == []
    for widget in [window.ribbon, window.status_view, window.mode_view] + [
        dock.widget() for dock in window.docks.values()
    ]:
        assert widget.rootObject() is not None
        assert widget.errors() == []
    for view in window.views:
        assert view.rootObject() is not None
        view.close()


def test_the_layout_matches_the_brief(window):
    from PySide6.QtCore import Qt

    area = {name: window.dockWidgetArea(dock) for name, dock in window.docks.items()}
    assert area["tools"] == area["insert"] == Qt.LeftDockWidgetArea
    assert area["scene"] == area["properties"] == area["history"] == Qt.RightDockWidgetArea
    assert [tab["title"] for tab in window.bridge.ribbon] == ["Create", "Modify", "Inspect", "Export"]
    assert not window.menuBar().isVisible()
    assert window.inspector is not None


# --- commands, icons, thumbnails ----------------------------------------------


def test_every_command_has_an_icon_file(window):
    window.set_expert_mode(True)
    window.bridge.refresh_commands()
    commands = window.bridge.commands
    assert commands
    for key, command in commands.items():
        assert command["icon"], f"{key} has no icon"
        assert (ICON_DIR / f"{command['icon']}.svg").exists(), key
    for name in ui_catalog.icon_names():
        assert (ICON_DIR / f"{name}.svg").exists(), name


def test_every_ribbon_and_palette_entry_is_a_real_command(window):
    window.set_expert_mode(True)
    window.bridge.refresh_commands()
    commands = window.bridge.commands
    for key in ui_catalog.ribbon_keys() + list(ui_catalog.PALETTE):
        if key.endswith(("_", ".")):
            assert any(k.startswith(key) for k in commands), key
        else:
            assert key in commands, key


def test_every_pre_existing_command_is_reachable_from_the_new_menus(window):
    window.set_expert_mode(True)
    window.bridge.refresh_commands()

    def keys(entries):
        for entry in entries:
            if entry["type"] == "action":
                yield entry["key"]
            elif entry["type"] == "menu":
                yield from keys(entry["entries"])

    reachable = {k for menu in window.bridge.menus for k in keys(menu["entries"])}
    classic = classic_action_keys(window)
    assert len(classic) > 140
    assert set(classic) <= reachable


def test_expert_tools_are_hidden_from_the_ribbon_and_menus_when_off(window):
    bridge = window.bridge
    on_ribbon = lambda: {i.get("key") for t in bridge.ribbon for g in t["groups"] for i in g["items"]}  # noqa: E731
    assert "create.extrude" not in on_ribbon()
    assert "Sketch" not in [m["title"] for m in bridge.menus]
    window.set_expert_mode(True)
    bridge.refresh_commands()
    assert "create.extrude" in on_ribbon()
    assert "Sketch" in [m["title"] for m in bridge.menus]
    assert bridge.expertMode
    window.set_expert_mode(False)
    bridge.refresh_commands()
    assert "create.extrude" not in on_ribbon()


def test_shortcuts_are_shown_with_their_commands(window):
    commands = window.bridge.commands
    assert commands["edit.undo"]["shortcut"] == "Ctrl+Z"
    assert commands["shape.group"]["shortcut"] == "Ctrl+G"
    assert commands["view.search_commands"]["shortcut"] == "Ctrl+K"
    assert commands["tools.measure"]["checkable"]


def test_triggering_a_command_runs_it(window):
    window.bridge.insert("shape:cube")
    window.bridge.insert("shape:sphere")
    window.bridge.trigger("edit.select_all")
    assert len(window.document.scene.selection) == 2
    window.bridge.trigger("tools.measure")
    assert window.tool == "measure"
    assert window.bridge.mode == "Measure"
    window.bridge.refresh_commands()
    assert window.bridge.commands["tools.measure"]["checked"]
    window.bridge.trigger("edit.stop_current_tool")
    assert window.tool is None
    assert window.bridge.mode == "Select"


def test_a_hidden_command_does_nothing(window):
    window.bridge.trigger("create.extrude")
    window.bridge.trigger("no.such.command")
    assert window.document.undo_labels == []


# --- Insert panel ----------------------------------------------------------------


def test_every_insert_item_has_a_thumbnail(window):
    items = window.bridge.insertItems
    assert {item["key"] for item in items} >= {f"shape:{k}" for k in ("cube", "sphere", "cylinder", "cone", "torus")}
    for item in items:
        assert (THUMBNAIL_DIR / f"{item['thumbnail']}.svg").exists(), item["key"]
        assert item["thumbnailUrl"].startswith("file://")


@pytest.mark.parametrize("key", [i["key"] for i in ui_catalog.insert_items() if not i["command"]])
def test_clicking_a_thumbnail_adds_it_to_the_scene_and_outliner(window, key):
    bridge = window.bridge
    bridge.insert(key)
    scene = window.document.scene
    assert len(scene.shapes) == 1
    assert window.document.undo_labels == ["add"]
    assert [row["id"] for row in bridge.outliner] == [scene.shapes[0].id]
    assert bridge.outliner[0]["selected"]
    if key.startswith("hardware:"):
        assert scene.shapes[0].is_hole
        assert bridge.outliner[0]["hole"]


def test_the_ready_made_thumbnails_ask_for_their_numbers_first(window, monkeypatch):
    asked = []

    def answer(title, fields, note=None):
        asked.append(title)
        return {"text": "Hi", "letter_height": 8.0, "depth": 1.5, "style": "raised"}

    monkeypatch.setattr(window, "ask_form", answer)
    window.bridge.insert("command:shape.add_text")
    assert asked == ["Add text"]
    assert window.document.scene.shapes[0].params["text"] == "Hi"


def test_dropping_a_thumbnail_puts_the_shape_where_it_lands(window):
    window.bridge.insert_at("shape:cylinder", (12.5, -7.0))
    shape = window.document.scene.shapes[0]
    assert shape.transform[0, 3] == pytest.approx(12.5)
    assert shape.transform[1, 3] == pytest.approx(-7.0)
    assert window.document.undo_labels == ["add"]


def test_the_workplane_point_is_on_the_plane_under_the_view_centre(window):
    window.resize(1200, 800)
    widget = window.viewport._widget
    widget.resize(800, 600)
    window.viewport.view_preset("top")
    point = window.viewport.workplane_point(400, 300)
    assert point is not None
    focal = window.viewport.renderer.GetActiveCamera().GetFocalPoint()
    assert point == pytest.approx((focal[0], focal[1]), abs=1.0)


# --- outliner and properties ----------------------------------------------------------


def test_outliner_click_selects_and_ctrl_click_adds(window):
    bridge = window.bridge
    bridge.insert("shape:cube")
    bridge.insert("shape:sphere")
    first, second = (row["id"] for row in bridge.outliner)
    bridge.select(first, False)
    assert window.document.scene.selection == [first]
    bridge.select(second, True)
    assert set(window.document.scene.selection) == {first, second}
    assert bridge.selectedCount == 2
    assert bridge.properties == []


def test_properties_show_the_selected_shapes_own_fields(window):
    bridge = window.bridge
    bridge.insert("shape:cylinder")
    fields = [row["field"] for row in bridge.properties]
    assert fields[:3] == ["x", "y", "z"]
    assert {"diameter", "height", "chamfer", "rx", "ry", "rz", "color", "is_hole"} <= set(fields)
    assert "width" not in fields
    assert bridge.selectedName == "Cylinder"


def test_typing_a_size_changes_the_part_in_one_undo_step(window, qapp):
    bridge = window.bridge
    bridge.insert("shape:cube")
    bridge.setField("width", 42.0)
    bridge.setField("depth", 13.0)
    settle(qapp, window)
    shape = window.document.scene.shapes[0]
    assert (shape.params["width"], shape.params["depth"]) == (42.0, 13.0)
    assert window.document.undo_labels == ["add", "edit"]
    assert {r["field"]: r["value"] for r in bridge.properties}["width"] == 42.0


def test_a_choice_a_text_a_colour_and_the_hole_box_go_through(window, qapp):
    bridge = window.bridge
    bridge.insert("hardware:nut_trap")
    bridge.setField("size", "M5")
    bridge.setField("color", "#FF0000")
    bridge.setField("fit", "loose")
    settle(qapp, window)
    shape = window.document.scene.shapes[0]
    assert (shape.params["size"], shape.color, shape.fit) == ("M5", "#ff0000", "loose")
    bridge.setField("is_hole", False)
    settle(qapp, window)
    assert not shape.is_hole
    assert "fit" not in [row["field"] for row in bridge.properties]


def test_a_bad_colour_changes_nothing(window, qapp):
    window.bridge.insert("shape:cube")
    window.bridge.setField("color", "blue")
    settle(qapp, window)
    assert window.document.undo_labels == ["add"]


def test_turning_a_part_goes_into_its_transform(window, qapp):
    window.bridge.insert("shape:cube")
    window.bridge.setField("rz", 30.0)
    settle(qapp, window)
    transform = window.document.scene.shapes[0].transform
    assert np.degrees(np.arctan2(transform[1, 0], transform[0, 0])) == pytest.approx(30.0)


# --- history -------------------------------------------------------------------------------


def test_history_lists_steps_and_jumps_back_and_forward(window):
    bridge = window.bridge
    for kind in ("cube", "sphere", "cone"):
        bridge.insert(f"shape:{kind}")
    assert [row["label"] for row in bridge.history] == ["Start", "Add", "Add", "Add"]
    assert bridge.history[-1]["state"] == "current"
    bridge.undoTo(1)
    assert len(window.document.scene.shapes) == 1
    assert [row["state"] for row in bridge.history] == ["done", "current", "undone", "undone"]
    bridge.undoTo(3)
    assert len(window.document.scene.shapes) == 3
    bridge.undoTo(0)
    assert window.document.scene.shapes == []
    assert bridge.history[0]["state"] == "current"


# --- status line ----------------------------------------------------------------------------


def test_the_status_line_follows_the_window(window):
    window.bridge.insert("shape:cube")
    assert "ready to print" in window.bridge.status
    assert not window.bridge.statusWarning
    window.start_lay_flat()
    assert window.bridge.status == window.TOOL_PROMPTS["lay_flat"]
    assert window.bridge.toolActive


# --- themes ------------------------------------------------------------------------------------


def _viewport_background(window):
    return tuple(round(v, 3) for v in window.viewport.renderer.GetBackground())


def _hex(color):
    return tuple(round(int(color[i:i + 2], 16) / 255.0, 3) for i in (1, 3, 5))


@pytest.mark.parametrize("name", list(themes.BUILTIN))
def test_each_built_in_theme_switches_live(window, name):
    window.apply_theme(name)
    singleton = window.engine.singletonInstance("Mesh", "Theme")
    assert singleton.property("tokens") == themes.BUILTIN[name]
    assert window.bridge.themeName == name
    assert _viewport_background(window) == _hex(themes.BUILTIN[name]["viewport"])
    checked = [a.text() for a in window.theme_menu.actions() if a.isChecked()]
    assert checked == [name]


def test_the_chosen_theme_is_remembered(make, tmp_path):
    settings = Settings.load(tmp_path / "settings.json")
    first = make(settings)
    first.apply_theme("Solarized")
    assert Settings.load(tmp_path / "settings.json").theme == "Solarized"
    second = make(Settings.load(tmp_path / "settings.json"))
    assert second.bridge.themeName == "Solarized"


def test_a_custom_theme_saved_in_the_editor_survives_a_restart(make, tmp_path):
    settings = Settings.load(tmp_path / "settings.json")
    window = make(settings)
    colors = dict(themes.BUILTIN["Light"], accent="#aa3366")
    window.bridge.previewTheme(colors)
    assert window.engine.singletonInstance("Mesh", "Theme").property("tokens")["accent"] == "#aa3366"
    assert window.bridge.saveTheme("Berry", colors) == ""
    assert (tmp_path / "themes" / "berry.json").exists()
    assert window.bridge.themeName == "Berry"
    assert "Berry" in [a.text() for a in window.theme_menu.actions()]
    assert "view.theme.berry" in window.bridge.commands

    again = make(Settings.load(tmp_path / "settings.json"))
    assert again.bridge.themeName == "Berry"
    assert again.engine.singletonInstance("Mesh", "Theme").property("tokens") == colors


def test_the_theme_editor_refuses_a_bad_theme_and_cancel_puts_the_theme_back(window, tmp_path):
    assert "built-in" in window.bridge.saveTheme("Dark", dict(themes.BUILTIN["Light"]))
    assert "name" in window.bridge.saveTheme("", dict(themes.BUILTIN["Light"]))
    window.bridge.previewTheme(dict(themes.BUILTIN["Light"]))
    window.bridge.endPreview()
    assert window.bridge.tokens == themes.BUILTIN["Dark"]
    assert _viewport_background(window) == _hex(themes.BUILTIN["Dark"]["viewport"])
    assert not (tmp_path / "themes").exists() or not list((tmp_path / "themes").iterdir())


# --- layout and welcome ---------------------------------------------------------------------------


def test_the_panel_layout_is_kept_between_runs(make, tmp_path, qapp):
    settings = Settings.load(tmp_path / "settings.json")
    window = make(settings)
    window.show()
    window.docks["history"].close()
    window.close()
    saved = Settings.load(tmp_path / "settings.json")
    assert "|" in saved.layout
    again = make(saved)
    again.show()
    qapp.processEvents()
    assert not again.docks["history"].isVisible()
    assert again.docks["properties"].isVisible()


def test_the_welcome_screen_shows_on_the_first_start_only(make, tmp_path, qapp):
    settings = Settings.load(tmp_path / "settings.json")
    first = make(settings, welcome=None)
    qapp.processEvents()
    assert [v.title() for v in first.views] == ["Welcome to mesh"]
    first.close()
    second = make(Settings.load(tmp_path / "settings.json"), welcome=None)
    qapp.processEvents()
    assert second.views == []


# --- forms -------------------------------------------------------------------------------------------


def test_form_answers_keep_each_fields_type_and_range():
    from mesh import panels

    session = FormSession("Repeat in a row", panels.repeat_row_fields(), None)
    values = session.values_from({"count": "7.6", "spacing": -5, "axis": "q"})
    assert values == {"count": 8, "spacing": 0.1, "axis": "x"}
    session = FormSession("Hollow out", panels.hollow_fields(True), None)
    assert session.values_from({"open_top": 1})["open_top"] is True
    kinds = {row["key"]: row["kind"] for row in session.fields}
    assert kinds["wall"] == "number"


def test_a_tool_asks_its_numbers_in_the_qml_form(window, qapp):
    from PySide6.QtCore import QTimer

    window.show()
    window.bridge.insert("shape:cube")

    def answer():
        forms = [v for v in window.views if v.title() == "Repeat in a row"]
        if not forms:  # not open yet
            QTimer.singleShot(20, answer)
            return
        forms[-1].rootObject().property("session").accept({"count": 4, "spacing": 30.0, "axis": "y"})

    QTimer.singleShot(0, answer)
    window.do_repeat_row()
    assert len(window.document.scene.shapes) == 4
    assert window.document.undo_labels == ["add", "repeat in a row"]
    assert window.qml_warnings == []


def test_closing_the_form_cancels_it(window, qapp):
    from PySide6.QtCore import QTimer

    window.show()
    window.bridge.insert("shape:cube")
    QTimer.singleShot(50, lambda: window.views[-1].close())
    window.do_repeat_row()
    assert len(window.document.scene.shapes) == 1


# --- words ----------------------------------------------------------------------------------------------


def _qml_strings():
    for path in QML_DIR.glob("*.qml"):
        for text in re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', path.read_text()):
            if " " in text.strip() and not text.startswith(("image:", "file:", "#")):
                yield text


def assert_plain(text):
    lowered = text.lower().replace("welcome to mesh", "welcome")
    for word in FORBIDDEN:
        assert not re.search(rf"\b{word}", lowered), f"jargon {word!r} in {text!r}"


def test_every_new_word_on_screen_is_plain_language(window):
    texts = list(_qml_strings())
    assert texts
    texts += list(themes.TOKEN_LABELS.values()) + list(themes.BUILTIN)
    texts += [item["label"] for item in ui_catalog.insert_items()]
    texts += [dock.windowTitle() for dock in window.docks.values()]
    texts += [c["label"] for c in window.bridge.commands.values()]
    texts += [title for title, _e, groups in ui_catalog.RIBBON] + [
        g for _t, _e, groups in ui_catalog.RIBBON for g, _i in groups
    ]
    for text in texts:
        assert_plain(text)


def test_the_classic_window_is_still_there():
    from mesh import app

    assert "--classic" in Path(app.__file__).read_text()




def test_a_menu_has_its_items_before_its_window_opens(window, qapp):
    """A menu's own window keeps the size it opened with, so items made
    after it opens left it one item tall on a real screen."""
    from PySide6.QtCore import QMetaObject, Q_RETURN_ARG, QUrl
    from PySide6.QtQml import QQmlComponent

    component = QQmlComponent(window.engine)
    component.setData(
        b"import QtQuick\nimport Mesh\nItem {\n"
        b"  MeshMenu { id: m; entries: bridge.menus[0].entries }\n"
        b"  function countAtOpen() { m.openBuilt(); var seen = m.count; m.close(); return seen }\n}",
        QUrl())
    root = component.create()
    assert root is not None, component.errorString()
    seen = QMetaObject.invokeMethod(root, "countAtOpen", Q_RETURN_ARG("QVariant"))
    root.deleteLater()
    assert seen > 1
