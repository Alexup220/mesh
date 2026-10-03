"""Every user-facing string added for the modeling tools stays jargon-free.

The forbidden list is the brief's: a beginner never needs these words.
"mesh" is checked as a whole word on the new tool strings; the app's own
name appears elsewhere (the window title, "mesh project" file filters),
which is a name, not jargon, and is not part of this check.
"""

import re

import pytest

FORBIDDEN = ("boolean", "csg", "manifold", "mesh", "vertex", "vertices", "normal", "offset")


def assert_plain(text: str) -> None:
    lowered = text.lower()
    for word in FORBIDDEN:
        assert not re.search(rf"\b{word}", lowered), f"jargon {word!r} in {text!r}"


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def _menu_texts(menu):
    for action in menu.actions():
        if action.menu() is not None:
            yield action.menu().title()
            yield from _menu_texts(action.menu())
        elif not action.isSeparator():
            yield action.text()


def test_every_menu_item_is_plain_language(window):
    texts = []
    for top in window.menuBar().actions():
        texts.append(top.text())
        texts.extend(_menu_texts(top.menu()))
    assert texts
    for text in texts:
        assert_plain(text)


def test_every_inspector_label_is_plain_language():
    from mesh.panels import FIELD_LABELS
    from mesh.scene import FITS

    for text in list(FIELD_LABELS.values()) + list(FITS.values()):
        assert_plain(text)


def test_every_shape_label_and_choice_is_plain_language():
    from mesh.shapes import PRIMITIVES

    for info in PRIMITIVES.values():
        assert_plain(info["label"])
        for choices in info.get("choices", {}).values():
            for _value, label in choices:
                assert_plain(label)


def test_fit_clearance_dialog_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog, fit_clearance_fields
    from mesh.scene import DEFAULT_FIT_CLEARANCES

    dialog = close_qt_widget(
        FormDialog(None, "Fit clearances", fit_clearance_fields(DEFAULT_FIT_CLEARANCES), note="x")
    )
    for text in dialog.labels():
        assert_plain(text)


def test_hardware_names_are_plain_language():
    from mesh import hardware

    for submenu, items in hardware.menu_presets():
        assert_plain(submenu)
        for label, primitive, params in items:
            assert_plain(label)
            assert_plain(hardware.preset_name(primitive, {**{"head": "plain"}, **params}))


def test_tool_prompts_are_plain_language():
    from mesh.app import MeshWindow

    for text in MeshWindow.TOOL_PROMPTS.values():
        assert_plain(text)


@pytest.mark.parametrize("exact", [True, False])
def test_hollow_dialog_is_plain_language(qapp, close_qt_widget, exact):
    from mesh.panels import APPROXIMATE_HOLLOW_NOTE, FormDialog, hollow_fields

    dialog = close_qt_widget(FormDialog(None, "Hollow out", hollow_fields(exact),
                                        note=None if exact else APPROXIMATE_HOLLOW_NOTE))
    for text in dialog.labels():
        assert_plain(text)


def _refusals():
    """Every way the new tools can refuse, as (callable) -- each must raise
    BuildError with a plain-language message."""
    from mesh import builders
    from mesh.scene import new_primitive

    def box():
        return new_primitive("cube")

    def hole():
        s = box()
        s.is_hole = True
        return s

    return [
        lambda: builders.hollow(hole(), 2.0),
        lambda: builders.hollow(box(), 0.0),
        lambda: builders.hollow(box(), 2.0, drain=-1.0),
        lambda: builders.hollow(box(), 30.0),
        lambda: builders.hollow(box(), 2.0, drain=50.0),
        lambda: builders.hollow(new_primitive("cone"), 1.0, open_top=True),
        lambda: builders.hollow(new_primitive("pyramid"), 15.0),
    ]


def test_every_refusal_message_is_plain_language():
    from mesh.builders import BuildError

    for attempt in _refusals():
        with pytest.raises(BuildError) as info:
            attempt()
        assert_plain(str(info.value))
