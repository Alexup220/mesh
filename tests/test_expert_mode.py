"""Expert mode: off by default, hidden when off, nothing lost when toggled."""

import json

import pytest

from mesh import expert
from mesh.settings import Settings, default_path
from test_plain_language import assert_plain

# What the window shows today with Expert mode off: every visible menu and
# its visible items. The one addition is the switch itself, under Tools.
MENUS_WITH_EXPERT_MODE_OFF = [
    ("&File", ["&Open Project", "&Save Project", "&Add a Model File", "&Save for Printing", "&Quit"]),
    ("&Edit", ["&Undo", "&Redo", "Stop Current Tool", "&Duplicate", "De&lete", "Select &All"]),
    ("&Shape", [
        "&Group", "&Ungroup", "Make &Hole / Solid", "Fit clearances...", "&Lay Flat on a Face",
        "&Place Next Shape on a Face", "Hollow &Out...", "S&plit Part...", "Repeat in a &Row...",
        "Repeat in a &Circle...", "Box with &Lid...", "Add &Text...", "Join", "Cut Out",
        "Keep Overlap", "Mirror along X", "Mirror along Y", "Mirror along Z",
        "Align X min", "Align X center", "Align X max", "Align Y min", "Align Y center",
        "Align Y max", "Align Z min", "Align Z center", "Align Z max",
    ]),
    ("Add hard&ware hole", [
        ("Screw hole (plain)", ["M2", "M2.5", "M3", "M4", "M5", "M6"]),
        ("Screw hole (countersunk)", ["M2", "M2.5", "M3", "M4", "M5", "M6"]),
        ("Screw hole (counterbored)", ["M2", "M2.5", "M3", "M4", "M5", "M6"]),
        ("Nut trap", ["M2", "M2.5", "M3", "M4", "M5", "M6"]),
        ("Heat-set insert pocket", ["M2", "M2.5", "M3", "M4", "M5"]),
        ("Magnet pocket", ["10 × 2 mm", "8 × 2 mm", "6 × 2 mm", "4 × 2 mm"]),
    ]),
    ("&Tools", ["&Measure", "&Expert Mode"]),
    ("&View", ["&Home", "&Front", "&Right", "&Top", "&Zoom to Selection"]),
]


def visible_menus(window):
    def items(menu):
        out = []
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            if action.menu() is not None:
                out.append((action.menu().title(), items(action.menu())))
            else:
                out.append(action.text())
        return out

    return [(a.text(), items(a.menu())) for a in window.menuBar().actions() if a.isVisible()]


@pytest.fixture
def make_window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    def make(settings=None):
        return close_qt_widget(MeshWindow(settings))

    return make


@pytest.fixture
def demo_tool(monkeypatch):
    """One stand-in expert tool, so the switch can be tested on a real menu
    item whatever tools exist."""
    tool = expert.ExpertTool(
        key="demo", menu="modify", label="Demo Tool", tip="Selects everything.",
        handler="do_select_all", shortcut="Ctrl+Alt+J",
    )
    monkeypatch.setattr(expert, "TOOLS", expert.TOOLS + (tool,))
    return tool


def scene_state(window):
    document = window.document
    return json.dumps(document.scene.to_dict(), sort_keys=True), len(document._undo), document.revision


# --- The saved preference -----------------------------------------------------


def test_expert_mode_is_off_by_default():
    assert Settings().expert_mode is False


def test_a_missing_settings_file_means_expert_mode_off(tmp_path):
    assert Settings.load(tmp_path / "nowhere" / "settings.json").expert_mode is False


@pytest.mark.parametrize("content", [
    "", "not json", "[]", "{}", '{"expert_mode": "yes"}', '{"expert_mode": 1}',
    '{"expert_mode": false}', '{"expert_mode": null}',
])
def test_anything_but_an_exact_true_means_expert_mode_off(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert Settings.load(path).expert_mode is False


def test_settings_save_and_load(tmp_path):
    path = tmp_path / "config" / "mesh" / "settings.json"
    settings = Settings.load(path)
    settings.expert_mode = True
    assert settings.save() is True
    assert json.loads(path.read_text()) == {"expert_mode": True}
    assert Settings.load(path).expert_mode is True
    assert not path.with_name("settings.json.tmp").exists()


def test_settings_without_a_path_save_nothing():
    assert Settings(expert_mode=True).save() is False


def test_settings_that_cannot_be_written_report_it(tmp_path):
    blocker = tmp_path / "not a folder"
    blocker.write_text("")
    settings = Settings(expert_mode=True, path=blocker / "settings.json")
    assert settings.save() is False


def test_settings_live_in_the_users_config_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_path() == tmp_path / "mesh" / "settings.json"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_path() == tmp_path / ".config" / "mesh" / "settings.json"


# --- Off by default, and the app as it was ------------------------------------


def test_a_fresh_window_starts_with_expert_mode_off(make_window):
    window = make_window()
    assert window.settings.expert_mode is False
    assert window.act_expert.isChecked() is False


def test_a_fresh_install_starts_with_expert_mode_off(qapp, close_qt_widget, tmp_path, monkeypatch):
    from mesh.app import make_window

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    window = close_qt_widget(make_window())
    assert window.settings.expert_mode is False
    assert window.settings.path == tmp_path / "mesh" / "settings.json"


def test_with_expert_mode_off_the_menus_are_exactly_as_before(make_window):
    assert visible_menus(make_window()) == MENUS_WITH_EXPERT_MODE_OFF


def test_with_expert_mode_off_the_rest_of_the_window_is_as_before(make_window):
    from PySide6.QtWidgets import QDockWidget, QToolBar

    from mesh.shapes import shelf_primitives

    window = make_window()
    assert [d.windowTitle() for d in window.findChildren(QDockWidget)] == ["Shapes", "Details"]
    assert list(window.shelf.buttons) == shelf_primitives()
    assert shelf_primitives() == [
        "cube", "sphere", "cylinder", "cone", "torus", "tube", "wedge", "pyramid",
        "rounded_box", "rounded_cylinder",
    ]
    bar = window.findChildren(QToolBar)[0]
    assert [a.text() for a in bar.actions() if not a.isSeparator()] == [
        "&Undo", "&Redo", "&Group", "&Ungroup", "&Duplicate", "De&lete",
        "&Home", "&Top", "&Front", "&Right",
    ]
    assert window.expert_badge.isHidden()


def test_with_expert_mode_off_expert_tools_are_hidden_and_their_shortcuts_dead(make_window, demo_tool):
    window = make_window()
    action = window.expert_actions["demo"]
    assert action.isVisible() is False and action.isEnabled() is False
    for menu in window.expert_menus.values():
        assert menu.menuAction().isVisible() is False
    assert visible_menus(window) == MENUS_WITH_EXPERT_MODE_OFF

    window.add_primitive("cube")
    window.document.scene.select([])
    action.trigger()  # what its shortcut would do: nothing, while disabled
    assert window.document.scene.selection == []


# --- Turning it on and off -------------------------------------------------------


def test_turning_expert_mode_on_shows_the_expert_tools(make_window, demo_tool):
    window = make_window()
    window.act_expert.trigger()
    assert window.settings.expert_mode is True
    action = window.expert_actions["demo"]
    assert action.isVisible() and action.isEnabled()
    assert action.toolTip() == "Selects everything."
    assert window.expert_menus["modify"].menuAction().isVisible()
    assert not window.expert_badge.isHidden()

    window.add_primitive("cube")
    window.document.scene.select([])
    action.trigger()
    assert window.document.scene.selection == [window.document.scene.shapes[0].id]


def test_expert_menus_sit_before_view_and_empty_ones_stay_hidden(make_window, demo_tool):
    window = make_window()
    window.set_expert_mode(True)
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles[-1] == "&View"
    assert titles[-1 - len(expert.MENUS):-1] == [title for _key, title in expert.MENUS]
    for key, menu in window.expert_menus.items():
        assert menu.menuAction().isVisible() == bool(expert.tools_in(key))


def test_turning_expert_mode_off_again_restores_the_menus(make_window, demo_tool):
    window = make_window()
    window.set_expert_mode(True)
    window.set_expert_mode(False)
    assert window.act_expert.isChecked() is False
    assert visible_menus(window) == MENUS_WITH_EXPERT_MODE_OFF
    assert window.expert_actions["demo"].isEnabled() is False
    assert window.expert_badge.isHidden()


def test_toggling_expert_mode_changes_nothing_in_the_model(make_window):
    window = make_window()
    window.add_primitive("cube")
    window.add_primitive("sphere")
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_group()
    window.add_primitive("cylinder")
    window.do_toggle_hole()
    before = scene_state(window)
    actors = set(window.viewport._actors)

    for on in (True, False, True, False):
        window.set_expert_mode(on)
        assert scene_state(window) == before
        assert set(window.viewport._actors) == actors

    window.do_undo()  # the undo history is the one from before the toggles
    assert window.document.scene.shapes[-1].is_hole is False


def test_expert_mode_is_remembered_for_next_time(make_window, tmp_path):
    path = tmp_path / "settings.json"
    window = make_window(Settings.load(path))
    window.act_expert.trigger()
    assert json.loads(path.read_text()) == {"expert_mode": True}

    again = make_window(Settings.load(path))
    assert again.settings.expert_mode is True and again.act_expert.isChecked()

    again.act_expert.trigger()
    assert make_window(Settings.load(path)).settings.expert_mode is False


def test_a_setting_that_cannot_be_saved_still_switches_and_says_so(make_window, tmp_path):
    blocker = tmp_path / "not a folder"
    blocker.write_text("")
    window = make_window(Settings(path=blocker / "settings.json"))
    window.set_expert_mode(True)
    assert window.settings.expert_mode is True and window.act_expert.isChecked()
    assert window.statusBar().currentMessage() == window.EXPERT_NOT_SAVED


@pytest.mark.parametrize("on", [False, True])
def test_opening_a_project_leaves_expert_mode_as_it_was(make_window, tmp_path, on):
    path = tmp_path / "part.mesh"
    writer = make_window()
    writer.add_primitive("cube")
    writer.save_to(path)

    window = make_window(Settings(expert_mode=on))
    window.open_from(path)
    assert window.settings.expert_mode is on
    assert window.act_expert.isChecked() is on
    assert "expert" not in path.read_text().lower()


# --- The tool list ---------------------------------------------------------------


def test_every_expert_tool_is_listed_once_with_a_known_menu_and_a_real_handler():
    from mesh.app import MeshWindow

    keys = [tool.key for tool in expert.TOOLS]
    assert len(keys) == len(set(keys))
    menus = {key for key, _title in expert.MENUS}
    for tool in expert.TOOLS:
        assert tool.menu in menus
        assert callable(getattr(MeshWindow, tool.handler, None)), tool.handler
        assert tool.label.strip() and tool.tip.strip()


def test_every_expert_tool_has_a_menu_item(make_window):
    window = make_window()
    assert set(window.expert_actions) == {tool.key for tool in expert.TOOLS}
    for tool in expert.TOOLS:
        assert window.expert_actions[tool.key] in window.expert_menus[tool.menu].actions()


def test_expert_shortcuts_do_not_clash_with_each_other_or_the_app(make_window):
    window = make_window()
    window.set_expert_mode(True)
    expert_ids = {id(a) for a in window.expert_actions.values()}
    others = {a.shortcut().toString() for a in window.actions()
              if id(a) not in expert_ids and not a.shortcut().isEmpty()}
    seen = set()
    for tool in expert.TOOLS:
        if tool.shortcut:
            shortcut = window.expert_actions[tool.key].shortcut().toString()
            assert shortcut not in others and shortcut not in seen, shortcut
            seen.add(shortcut)


def test_expert_text_is_plain_language(make_window):
    window = make_window()
    for _key, title in expert.MENUS:
        assert_plain(title)
    for tool in expert.TOOLS:
        assert_plain(tool.label)
        assert_plain(tool.tip)
    assert_plain(window.act_expert.text())
    assert_plain(window.EXPERT_TIP)
    assert_plain(window.EXPERT_NOT_SAVED)
    assert_plain(window.expert_badge.text())
