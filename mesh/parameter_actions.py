"""The window's Expert mode named parameters: Change Parameters and Link
Sizes to Parameters (both in the Modify menu).

Mixed into MeshWindow through ExpertActions. The arithmetic is in
mesh.parameters; this is the table window, the link form and the wiring:
check everything first, then change the scene as one undo step.
"""

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from mesh import parameters
from mesh.builders import BuildError
from mesh.history import replayable
from mesh.panels import FIELD_LABELS, run_form
from mesh.shapes import shape_geometry
from mesh.sketch import SketchError
from mesh.threads import ThreadError

PARAMETERS_NOTE = (
    "Name the numbers your design is built from, then link parts' sizes and positions to them "
    "(Modify > Link Sizes to Parameters). A formula can use other parameters, + - * / and "
    "brackets, and min, max, abs, round, sqrt, sin, cos and tan (angles in degrees), for "
    "example: width / 2 + wall. Every linked part follows when you press OK."
)


class ParametersDialog(QDialog):
    """The parameter table: name, formula, what it comes to, and a note."""

    COLUMNS = ("Name", "Number or formula", "Comes to", "Note")

    def __init__(self, parent, rows) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Parameters")
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        self.note = QLabel(PARAMETERS_NOTE, self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        bar = QHBoxLayout()
        self.add_button = QPushButton("Add", self)
        self.add_button.clicked.connect(lambda: self.add_row())
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self.remove_selected)
        bar.addWidget(self.add_button)
        bar.addWidget(self.remove_button)
        bar.addStretch(1)
        layout.addLayout(bar)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for row in rows:
            self.add_row(row["name"], row["formula"], row.get("note", ""))
        self.table.cellChanged.connect(lambda _r, c: self.refresh() if c in (0, 1) else None)
        self.refresh()

    def add_row(self, name: str = "", formula: str = "", note: str = "") -> None:
        if not name:
            taken = {r["name"] for r in self.rows()}
            number = len(taken) + 1
            while f"d{number}" in taken:
                number += 1
            name, formula = f"d{number}", formula or "10"
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, text in enumerate((name, formula, "", note)):
            item = QTableWidgetItem(str(text))
            if column == 2:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.refresh()

    def remove_selected(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self.refresh()

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ""

    def rows(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            name, formula, note = self._text(row, 0), self._text(row, 1), self._text(row, 3)
            if name or formula:
                out.append({"name": name, "formula": formula, "note": note})
        return out

    def problem(self) -> str | None:
        try:
            parameters.values(self.rows())
        except parameters.ParameterError as exc:
            return str(exc)
        return None

    def refresh(self) -> None:
        """Show what each parameter comes to, or "?" where it can't be
        worked out yet."""
        try:
            known = parameters.values(self.rows())
        except parameters.ParameterError:
            known = {}
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            name = self._text(row, 0)
            item = self.table.item(row, 2)
            item.setText(f"{known[name]:g}" if name in known else "?")
        self.table.blockSignals(False)

    def accept(self) -> None:
        problem = self.problem()
        if problem is not None:
            QMessageBox.warning(self, "Cannot use these parameters", problem)
            return
        super().accept()


def ask_parameters(parent, rows) -> list | None:
    dialog = ParametersDialog(parent, rows)
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.rows()
    finally:
        dialog.deleteLater()


def link_fields(shape):
    return [(field, FIELD_LABELS[field], str(shape.links.get(field, "")), {})
            for field in parameters.linkable(shape)]


def link_note(known: dict) -> str:
    listed = ", ".join(f"{name} = {value:g}" for name, value in known.items())
    return (f"Type a formula for each number that should follow your parameters ({listed}); "
            "leave a box empty for a number you set yourself. Typing a number in the Details "
            "panel later ends that link.")


def ask_links(parent, shape, known: dict) -> dict | None:
    return run_form(parent, f"Link Sizes of {shape.name}", link_fields(shape), note=link_note(known))


class ParameterActions:
    """Mixed into MeshWindow through ExpertActions."""

    LINK_NEEDS_ONE = "Select one part (or guide) to link its sizes to parameters."
    LINK_NEEDS_PARAMETERS = "Add parameters first: Modify > Change Parameters."
    LINK_ENDED = "That number no longer follows a parameter."

    def _links_problem(self, shapes, known: dict) -> str | None:
        """Why the parameters `known` can't be applied to (copies of)
        `shapes`, or None. Every linked part is built to be sure."""
        clearances = self.document.scene.fit_clearances
        for shape in shapes:
            if not shape.links:
                continue
            trial = copy.deepcopy(shape)
            try:
                if parameters.apply_links([trial], known):
                    shape_geometry(trial, clearances)
            except parameters.ParameterError as exc:
                return f"{shape.name}: {exc}"
            except (BuildError, SketchError, ThreadError) as exc:
                return f"{shape.name} can't take those numbers. {exc}"
        return None

    def set_parameters(self, rows) -> bool:
        """Replace the parameter table and move every linked part to match.
        One undo step; nothing changes if any part can't follow."""
        scene = self.document.scene
        rows = [{"name": str(r["name"]).strip(), "formula": str(r["formula"]).strip(),
                 "note": str(r.get("note", ""))} for r in rows]
        try:
            known = parameters.values(rows)
        except parameters.ParameterError as exc:
            self._warn("Cannot use these parameters", str(exc))
            return False
        if scene.history is not None:
            # The parameters hold for the whole history: work it all out again.
            return self._rework("Cannot use these parameters", "parameters", self.history_steps(), rows)
        problem = self._links_problem(scene.shapes, known)
        if problem is not None:
            self._warn("Cannot use these parameters", problem)
            return False
        self.document.snapshot("parameters")
        scene.parameters = rows
        parameters.apply_links(scene.shapes, known)
        self.sync()
        return True

    def do_change_parameters(self) -> None:
        rows = ask_parameters(self, self.document.scene.parameters)
        if rows is not None:
            self.set_parameters(rows)

    @replayable()
    def set_links(self, shape_id: str, links: dict) -> bool:
        """Link numbers of one shape to formulas (field -> formula; an empty
        formula ends that link). One undo step."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
        except KeyError:
            return False
        links = {f: str(v).strip() for f, v in links.items() if str(v).strip()}
        known = self._parameter_values()
        trial = copy.deepcopy(shape)
        trial.links = links
        problem = self._links_problem([trial], known)
        if problem is not None:
            self._warn("Cannot link those sizes", problem)
            return False
        self.document.snapshot("link sizes")
        shape.links = links
        parameters.apply_links([shape], known)
        self.sync()
        return True

    def _parameter_values(self) -> dict:
        try:
            return parameters.values(self.document.scene.parameters)
        except parameters.ParameterError:
            return {}

    def do_link_sizes(self) -> None:
        chosen = self._picked()
        if len(chosen) != 1:
            self.statusBar().showMessage(self.LINK_NEEDS_ONE)
            return
        known = self._parameter_values()
        if not known:
            self.statusBar().showMessage(self.LINK_NEEDS_PARAMETERS)
            return
        values = ask_links(self, chosen[0], known)
        if values is not None:
            self.set_links(chosen[0].id, values)

    def _end_link(self, shape, field: str) -> None:
        """A number typed in the Details panel replaces its formula."""
        if field in shape.links:
            del shape.links[field]
            self.statusBar().showMessage(self.LINK_ENDED)
