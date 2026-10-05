import json

import pytest

from mesh import themes
from mesh.scene import Document, new_primitive
from mesh.settings import Settings


def test_six_built_in_themes_each_set_every_token():
    assert list(themes.BUILTIN) == [
        "Dark", "Light", "Fusion Grey", "Midnight Blue", "High Contrast", "Solarized",
    ]
    for name, colors in themes.BUILTIN.items():
        assert themes.clean_colors(colors) == colors, name


def test_every_token_has_a_label():
    assert set(themes.TOKEN_LABELS) == set(themes.TOKENS)
    assert set(themes.TOKENS) == {
        "background", "panel", "text", "accent", "border", "viewport", "grid", "selection",
    }


def test_a_saved_theme_loads_back(tmp_path):
    colors = dict(themes.BUILTIN["Light"], accent="#ABCDEF")
    path = themes.save_custom("  My theme ", colors, tmp_path)
    assert path.parent == tmp_path
    assert json.loads(path.read_text())["name"] == "My theme"
    loaded = themes.load_custom(tmp_path)
    assert loaded == {"My theme": dict(colors, accent="#abcdef")}
    assert list(themes.all_themes(tmp_path))[-1] == "My theme"


@pytest.mark.parametrize("name, colors, problem", [
    ("", None, "name"),
    ("x" * 41, None, "characters"),
    ("Dark", None, "built-in"),
    ("Mine", {"background": "red"}, "#1a2b3c"),
])
def test_a_theme_that_cannot_be_saved_says_why_and_writes_nothing(tmp_path, name, colors, problem):
    with pytest.raises(themes.ThemeError, match=problem):
        themes.save_custom(name, colors or dict(themes.BUILTIN["Dark"]), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_damaged_theme_files_are_skipped(tmp_path):
    (tmp_path / "a.json").write_text("not json")
    (tmp_path / "b.json").write_text(json.dumps({"name": "Half", "colors": {"text": "#ffffff"}}))
    (tmp_path / "c.json").write_text(json.dumps({"name": "Light", "colors": themes.BUILTIN["Dark"]}))
    (tmp_path / "d.json").write_text(json.dumps(["list"]))
    assert themes.load_custom(tmp_path) == {}
    assert themes.load_custom(tmp_path / "missing") == {}


def test_theme_and_layout_round_trip_in_settings(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings.load(path)
    assert (settings.theme, settings.layout) == ("Dark", "")
    settings.theme, settings.layout = "Solarized", "abc|def"
    assert settings.save()
    again = Settings.load(path)
    assert (again.theme, again.layout, again.expert_mode) == ("Solarized", "abc|def", False)


def test_settings_file_without_a_theme_is_written_as_before(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings.load(path)
    settings.expert_mode = True
    settings.save()
    assert json.loads(path.read_text()) == {"expert_mode": True}


@pytest.mark.parametrize("raw", ['{"theme": 3, "layout": []}', '{"theme": "  "}'])
def test_odd_theme_or_layout_values_fall_back(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(raw)
    settings = Settings.load(path)
    assert (settings.theme, settings.layout) == ("Dark", "")


def test_document_keeps_a_label_per_undo_and_redo_step():
    document = Document()
    for label in ("add", "group", "delete"):
        document.snapshot(label)
        document.scene.add(new_primitive("cube"))
    assert document.undo_labels == ["add", "group", "delete"]
    document.undo()
    document.undo()
    assert document.undo_labels == ["add"]
    assert document.redo_labels == ["delete", "group"]
    document.redo()
    assert document.undo_labels == ["add", "group"]
    document.snapshot("move")
    assert document.undo_labels == ["add", "group", "move"]
    assert document.redo_labels == []
