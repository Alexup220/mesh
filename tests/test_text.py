"""Text: raised (solid) or engraved (Hole), from the bundled font."""

from pathlib import Path

import numpy as np
import pytest

import mesh
from mesh import text
from mesh.ops import evaluate
from mesh.scene import DEFAULT_FIT_CLEARANCES, new_primitive
from mesh.shapes import PRIMITIVES, shape_geometry, shelf_primitives
from mesh.solids import to_manifold


def test_font_is_bundled_inside_the_package():
    package = Path(mesh.__file__).resolve().parent
    assert text.FONT_PATH.is_file()
    assert package in text.FONT_PATH.parents
    assert (package / "fonts" / "LICENSE_DEJAVU").is_file()


def test_same_text_gives_the_same_solid_everywhere():
    """A fixed reference volume: the font ships with mesh and nothing reads
    system fonts, so this number is the same on every machine."""
    assert np.isclose(text.text_mesh("Hello", 10.0, 2.0).volume, 215.92956935921612, rtol=1e-6)


@pytest.mark.parametrize("words", ["H", "Hello", "Ag%&é 123", "Off-by-one!"])
def test_text_is_watertight_and_rests_on_the_plane(words):
    tm = text.text_mesh(words, 8.0, 1.5)
    assert tm.is_watertight
    assert np.isclose(tm.bounds[0][2], 0.0) and np.isclose(tm.bounds[1][2], 1.5)
    assert np.allclose(tm.bounds.mean(axis=0)[:2], (0.0, 0.0), atol=1e-9)


def test_letter_height_is_the_height_of_a_capital():
    tm = text.text_mesh("H", 12.0, 2.0)
    assert np.isclose(tm.bounds[1][1] - tm.bounds[0][1], 12.0, atol=1e-6)


def test_letters_keep_their_holes():
    assert to_manifold(text.text_mesh("O", 10.0, 2.0)).genus() == 1
    assert to_manifold(text.text_mesh("B", 10.0, 2.0)).genus() == 2


def test_clearance_grows_each_letter_outward():
    tm = text.text_mesh("H", 10.0, 2.0, clearance=0.2)
    assert tm.is_watertight
    assert np.isclose(tm.bounds[1][1] - tm.bounds[0][1], 10.4, atol=1e-6)
    assert np.allclose(tm.bounds[:, 2], (-0.2, 2.2))


def test_blank_text_is_refused():
    with pytest.raises(ValueError):
        text.text_mesh("   ", 10.0, 2.0)


def test_text_is_a_menu_primitive_with_numeric_sizes():
    assert "text" in PRIMITIVES and "text" not in shelf_primitives()
    assert PRIMITIVES["text"]["defaults"] == {"text": "Text", "letter_height": 10.0, "depth": 2.0}


def test_engraved_text_cuts_a_watertight_part():
    plate = new_primitive("cube")
    plate.params.update(width=60.0, depth=20.0, height=5.0)
    words = new_primitive("text")
    words.params.update(text="mesh", letter_height=8.0, depth=1.0)
    words.is_hole, words.fit = True, "exact"
    words.transform[2, 3] = 4.0  # 1 mm into the top
    result = evaluate([plate, words], clearances=dict(DEFAULT_FIT_CLEARANCES))
    assert result.is_watertight
    assert np.isclose(6000.0 - result.volume, shape_geometry(words).volume, rtol=1e-4)


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


@pytest.mark.parametrize("engraved", [False, True])
def test_add_text_is_one_undo_step(window, engraved):
    depth = len(window.document._undo)
    assert window.add_text("Hi there", 6.0, 1.0, engraved=engraved) is True
    shape = window.document.scene.shapes[0]
    assert shape.is_hole is engraved
    assert shape.params["text"] == "Hi there"
    assert len(window.document._undo) == depth + 1
    assert shape_geometry(shape).is_watertight


def test_blank_text_adds_nothing_and_no_undo_step(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    depth = len(window.document._undo)
    assert window.add_text("  ") is False
    assert window.document.scene.shapes == [] and len(window.document._undo) == depth
    assert seen == ["Type some text first."]


def test_inspector_edits_the_words(window):
    window.add_text("abc")
    shape = window.document.scene.shapes[0]
    box = window.inspector.text_boxes["text"]
    assert box.text() == "abc"
    before = shape_geometry(shape).volume

    box.setText("abcdef")
    box.editingFinished.emit()
    window._finish_edit()
    assert shape.params["text"] == "abcdef"
    assert shape_geometry(shape).volume > before

    depth = len(window.document._undo)
    box.setText("   ")
    box.editingFinished.emit()
    assert shape.params["text"] == "abcdef"  # blank text is ignored
    assert len(window.document._undo) == depth


def test_dialog_values_reach_add_text(window, monkeypatch):
    from mesh import panels

    monkeypatch.setattr(panels, "run_form", lambda *a, **k: {
        "text": "Lid", "letter_height": 5.0, "depth": 0.6, "style": "engraved",
    })
    window.do_add_text()
    shape = window.document.scene.shapes[0]
    assert shape.is_hole and shape.params["letter_height"] == 5.0
