"""The tool dialogs: an explanatory note above the form is shown in full.

On a real desktop the Hollow out note showed only two of its four lines:
a word-wrapped label spanning a form row is not given the height its
wrapped text needs. The note now sits above the form with a fixed
narrowest width and at least the height all its lines need at that width.
"""

import pytest

LONG_NOTE = (
    "This shape is hollowed out approximately: the inside follows the outside "
    "at about the wall thickness you choose, with slightly rounded inside "
    "corners. Boxes, cylinders and spheres hollow out exactly. This sentence "
    "is here to make the note wrap onto several lines."
)


@pytest.fixture
def dialog(qapp, close_qt_widget):
    from mesh.panels import FormDialog, hollow_fields

    return close_qt_widget(FormDialog(None, "Hollow out", hollow_fields(False), note=LONG_NOTE))


def _all_lines_fit(label) -> bool:
    return label.height() >= label.heightForWidth(label.width())


def test_the_note_shows_every_line_when_the_dialog_opens(qapp, dialog):
    dialog.show()
    qapp.processEvents()
    assert dialog.note.isVisible()
    assert _all_lines_fit(dialog.note)


def test_the_note_keeps_every_line_when_the_dialog_is_shrunk(qapp, dialog):
    dialog.show()
    qapp.processEvents()
    dialog.resize(1, 1)
    qapp.processEvents()
    assert _all_lines_fit(dialog.note)


def test_the_note_sits_above_the_fields(qapp, dialog):
    from PySide6.QtCore import QPoint

    dialog.show()
    qapp.processEvents()
    first_field = next(iter(dialog.widgets.values()))
    note_bottom = dialog.note.mapTo(dialog, QPoint(0, dialog.note.height())).y()
    assert note_bottom <= first_field.mapTo(dialog, QPoint(0, 0)).y()


def test_a_dialog_without_a_note_still_reads_back_its_values(qapp, close_qt_widget):
    from mesh.panels import FormDialog, hollow_fields

    dialog = close_qt_widget(FormDialog(None, "Hollow out", hollow_fields(True)))
    assert dialog.note is None
    assert dialog.values() == {"wall": 2.0, "open_top": False, "drain": 0.0}
