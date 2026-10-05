"""The window's Expert mode Inspect menu: section view.

Mixed into MeshWindow through ExpertActions. Inspecting never changes the
scene: no undo step, nothing saved.
"""

import numpy as np

from mesh import construct, sketch
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
