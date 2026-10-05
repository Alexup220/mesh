"""The window's Expert mode Inspect menu: section view and measuring.

Mixed into MeshWindow through ExpertActions. Inspecting never changes the
scene: no undo step, nothing saved.
"""

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from mesh import construct, measure, sketch
from mesh.builders import BuildError
from mesh.panels import run_form
from mesh.shapes import is_reference, shape_geometry

DISTANCE = {"min": -10000.0, "max": 10000.0}

SECTION_PLANES = [
    ("xy", "Flat, through the middle of the parts"),
    ("xz", "Upright facing the front, through the middle of the parts"),
    ("yz", "Upright facing the right side, through the middle of the parts"),
]


def section_fields(selected=None):
    planes = ([("selected", f"The selected {selected}")] if selected else []) + SECTION_PLANES
    return [
        ("plane", "Cut along", planes[0][0], {"choices": planes}),
        ("distance", "Move the cut along the way it faces (mm)", 0.0, DISTANCE),
        ("flip", "Show the other side", False, {}),
    ]


SECTION_NOTE = (
    "Shows the parts cut open along a plane: the side the plane faces is hidden and the cut "
    "is drawn in orange. Only the view changes; nothing is cut when you save or print. "
    "Choose Section View again to see the parts whole."
)


def ask_section(parent, selected=None) -> dict | None:
    return run_form(parent, "Section View", section_fields(selected), note=SECTION_NOTE)


class InspectActions:
    """Mixed into MeshWindow through ExpertActions."""

    INSPECT_CLICK_TOOLS = ("measure_faces", "measure_radius")
    INSPECT_TOOL_PROMPTS = {
        "measure_faces": "Click a point on a flat face of a part (near a corner, it lands on the "
                         "corner). Esc stops.",
        "measure_faces_second": "Now click a point on the second face.",
        "measure_radius": "Click the round side of a part to see its radius. Esc stops.",
    }
    INSPECT_CLICK_HANDLERS = {
        "measure_faces": "_measure_face_picked",
        "measure_radius": "_measure_radius_picked",
    }
    INSPECT_STAGED = {"measure_faces": ("measure_faces", "measure_faces_second")}

    MEASURE_AGAIN = "Click another face to measure again, Esc to stop."
    VOLUME_HINT = "Select the parts to measure first."

    SECTION_NEEDS_PARTS = "Add a part first, then look inside it with Section View."
    SECTION_ON = "Section view: the parts are shown cut open. Choose Section View again to see them whole."
    SECTION_OFF = "Showing the parts whole again."

    def _parts_middle(self):
        """The middle of the box round every shown part, or None."""
        scene = self.document.scene
        parts = [s for s in scene.shapes if s.visible and not is_reference(s)]
        if not parts:
            return None
        bounds = np.array([shape_geometry(s, scene.fit_clearances).bounds for s in parts])
        return (bounds[:, 0].min(axis=0) + bounds[:, 1].max(axis=0)) / 2.0

    def section_view(self, plane: str, distance: float = 0.0, flip: bool = False, guide=None) -> bool:
        """Show the parts cut along `plane` ("selected" means `guide`, a
        sketch or construction plane; else a SECTION_PLANES key), moved
        `distance` mm along the way it faces. The side it faces is hidden,
        or the other side with `flip`."""
        if plane == "selected":
            origin, normal = construct.plane_of(guide)
        else:
            middle = self._parts_middle()
            if middle is None:
                self.statusBar().showMessage(self.SECTION_NEEDS_PARTS)
                return False
            normal = np.asarray(sketch.PLANES[plane], dtype=np.float64)
            origin = middle
        origin = np.asarray(origin, dtype=np.float64) + normal * float(distance)
        self.viewport.set_section(origin, -normal if flip else normal)
        self.statusBar().showMessage(self.SECTION_ON)
        return True

    def end_section(self) -> None:
        self.viewport.clear_section()
        self.statusBar().showMessage(self.SECTION_OFF)

    def _end_inspecting(self) -> None:
        """Show the parts whole and put the measurements away: Expert mode
        went off, or another project was opened."""
        self.viewport.clear_section()
        if getattr(self, "measure_window", None) is not None:
            self.measure_window.hide()

    def do_section_view(self) -> None:
        if self.viewport.section is not None:
            self.end_section()
            return
        flat = [s for s in self._picked() if construct.is_flat_guide(s)]
        guide = flat[0] if len(flat) == 1 else None
        values = ask_section(self, guide.name if guide is not None else None)
        if values is None:
            return
        self.section_view(values["plane"], values["distance"], values["flip"], guide)

    # --- Measuring -------------------------------------------------------------------

    def _show_measurement(self, title: str, text: str) -> None:
        """The results, in a window that stays open beside the 3D view
        until closed (and can be copied from)."""
        box = getattr(self, "measure_window", None)
        if box is None:
            box = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Close, self)
            box.setWindowModality(Qt.NonModal)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.measure_window = box
        box.setWindowTitle(title)
        box.setText(text)
        box.show()

    def do_measure_faces(self) -> None:
        self._start_construct_tool("measure_faces")

    def _measure_face_picked(self, shape_id: str, face_index: int, point=None) -> None:
        shape = self._clicked_part(shape_id, face_index)
        if shape is None:
            return
        try:
            face = measure.clicked(shape, face_index, point, self.document.scene.fit_clearances)
        except BuildError:
            self.statusBar().showMessage(self._tool_prompt())
            return
        self._construct_picks.append(face)
        if len(self._construct_picks) == 1:
            self.viewport.clear_measure_line()
            self.statusBar().showMessage(f"{measure.describe_face(face)}. {self._tool_prompt()}")
            return
        first, second = self._construct_picks
        self._construct_picks = []
        self.viewport.set_measure_line(first.point, second.point)
        self.statusBar().showMessage(self.MEASURE_AGAIN)
        text = measure.describe(first, second)
        # Once the click is over: a window opened during it would take the
        # mouse button's release.
        QTimer.singleShot(0, lambda: self._show_measurement("Measure Between Faces", text))

    RADIUS_AGAIN = "Click another round side to measure it, Esc to stop."

    def do_measure_radius(self) -> None:
        self._start_construct_tool("measure_radius")

    def _measure_radius_picked(self, shape_id: str, face_index: int, point=None) -> None:
        shape = self._clicked_part(shape_id, face_index)
        if shape is None:
            return
        found = measure.round_face(shape, face_index, point, self.document.scene.fit_clearances)
        if found.line is None:
            self.viewport.clear_measure_line()
        else:
            self.viewport.set_measure_line(*found.line)
        self.statusBar().showMessage(self.RADIUS_AGAIN)
        QTimer.singleShot(0, lambda: self._show_measurement("Radius of a Round Face", found.text))

    def measure_selected(self) -> bool:
        parts = [s for s in self._picked() if not is_reference(s)]
        if not parts:
            self.statusBar().showMessage(self.VOLUME_HINT)
            return False
        found = self._attempt("Cannot measure", lambda: measure.amount(parts, self.document.scene.fit_clearances))
        if found is None:
            return False
        solids = sum(1 for s in parts if not s.is_hole)
        self._show_measurement("Volume and Area", measure.describe_amount(found, solids))
        return True

    def do_measure_volume(self) -> None:
        self.measure_selected()

    GAP_HINT = "Select two parts to measure the shortest distance between them."

    def measure_gap_selected(self) -> bool:
        """The shortest distance between the two selected parts."""
        parts = [s for s in self._picked() if not is_reference(s)]
        if len(parts) != 2:
            self.statusBar().showMessage(self.GAP_HINT)
            return False
        first, second = parts
        found = self._attempt("Cannot measure", lambda: measure.gap(first, second, self.document.scene.fit_clearances))
        if found is None:
            return False
        self._show_measurement("Shortest Distance", measure.describe_gap(first.name, second.name, found))
        return True

    def do_measure_gap(self) -> None:
        self.measure_gap_selected()
