"""The drag handles around the selected shape.

vtkBoxWidget2 provides move, scale, and rotate handles in one widget, so
the beginner never has to pick a tool mode first.
"""

import numpy as np
import vtkmodules.qt

vtkmodules.qt.PyQtImpl = "PySide6"

from PySide6.QtCore import QObject, Signal
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkInteractionWidgets import vtkBoxRepresentation, vtkBoxWidget2

from mesh.scene import Shape, _signed_scale

# Which size params a corner-handle scale drag should grow, per axis of
# the gizmo's local box (x, y, z). "radial" params (diameter, wall
# thickness) are driven by the average of the two horizontal axes, since
# a round primitive has no separate X/Y size to keep distinct.
_PRIMITIVE_SCALE_TARGETS = {
    "cube": {"width": "x", "depth": "y", "height": "z"},
    "wedge": {"width": "x", "depth": "y", "height": "z"},
    "pyramid": {"width": "x", "depth": "y", "height": "z"},
    "cylinder": {"diameter": "radial", "height": "z"},
    "cone": {"diameter": "radial", "height": "z"},
    "sphere": {"diameter": "average"},
    "torus": {"diameter": "radial", "thickness": "average"},
    "tube": {"diameter": "radial", "wall": "radial", "height": "z"},
    # The rounding radius keeps its size: it is a detail, not a dimension.
    "rounded_box": {"width": "x", "depth": "y", "height": "z"},
    "rounded_cylinder": {"diameter": "radial", "height": "z"},
    "text": {"letter_height": "radial", "depth": "z"},
    # Hardware holes keep their standard sizes; only how deep they go (and
    # a magnet pocket's size, which is the magnet's own) follows a drag.
    "screw_hole": {"depth": "z"},
    "nut_trap": {"depth": "z"},
    "magnet_pocket": {"diameter": "radial", "depth": "z"},
}


class Gizmo(QObject):
    changing = Signal()
    changed = Signal(str)

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        self.viewport = viewport
        self.snap_mm = 1.0
        self._shape: Shape | None = None
        self._base: np.ndarray | None = None

        self._representation = vtkBoxRepresentation()
        self._representation.SetPlaceFactor(1.0)
        self._representation.HandlesOn()

        self._widget = vtkBoxWidget2()
        self._widget.SetRepresentation(self._representation)
        self._widget.SetInteractor(viewport.interactor)
        self._widget.RotationEnabledOn()
        self._widget.ScalingEnabledOn()
        self._widget.TranslationEnabledOn()
        self._widget.Off()

        self._widget.AddObserver("StartInteractionEvent", self._on_start)
        self._widget.AddObserver("EndInteractionEvent", self._on_end)

    @property
    def attached_id(self) -> str | None:
        return self._shape.id if self._shape else None

    def attach(self, shape: Shape | None) -> None:
        self._shape = shape
        if shape is None:
            self._widget.Off()
            self._base = None
            return

        actor = self.viewport.actor_for(shape.id)
        if actor is None:
            self._widget.Off()
            self._base = None
            return

        self._base = np.asarray(shape.transform, dtype=np.float64).copy()
        self._representation.PlaceWidget(actor.GetBounds())
        self._widget.On()

    def _snap(self, value: float) -> float:
        if not self.snap_mm:
            return float(value)
        return round(float(value) / self.snap_mm) * self.snap_mm

    def _on_start(self, *_args) -> None:
        self.changing.emit()

    def _on_end(self, *_args) -> None:
        transform = vtkTransform()
        self._representation.GetTransform(transform)
        matrix = transform.GetMatrix()
        delta = np.array(
            [[matrix.GetElement(r, c) for c in range(4)] for r in range(4)],
            dtype=np.float64,
        )
        self._apply(delta @ (self._base if self._base is not None else np.eye(4)))

    def _apply(self, transform: np.ndarray) -> None:
        """Write a new transform onto the attached shape, snapping position."""
        if self._shape is None:
            return
        transform = np.asarray(transform, dtype=np.float64).copy()
        for axis in range(3):
            transform[axis, 3] = self._snap(transform[axis, 3])

        if self._shape.kind == "primitive":
            transform = self._bake_scale(self._shape, transform)

        self._shape.transform = transform
        self.changed.emit(self._shape.id)

    def _bake_scale(self, shape: Shape, transform: np.ndarray) -> np.ndarray:
        """Fold a corner-handle scale into the shape's size params instead
        of leaving it in the transform.

        gizmo writes scale straight into the transform, while the
        Inspector's size fields read from shape.params -- after a
        corner-handle drag those two disagreed (a 20mm cube dragged to
        40mm still showed "20.00" in the inspector, and typing 30 there
        then produced 60mm). Baking the scale into params here, and
        resetting the transform's rotation block back to unit scale, keeps
        params the single source of truth for a primitive's size, exactly
        like every other numeric-inspector field.

        Imported and group shapes have no size params to bake into, so
        their scale is left in the transform untouched (see the `kind ==
        "primitive"` guard in _apply above).
        """
        r = transform[:3, :3]
        scale = _signed_scale(r)
        magnitude = np.abs(scale)
        sx, sy, sz = magnitude

        primitive = shape.params.get("primitive")
        targets = _PRIMITIVE_SCALE_TARGETS.get(primitive, {})
        radial = (sx + sy) / 2.0
        average = (sx + sy + sz) / 3.0
        factors = {"x": sx, "y": sy, "z": sz, "radial": radial, "average": average}

        for param, axis_key in targets.items():
            if param in shape.params:
                shape.params[param] = float(shape.params[param]) * factors[axis_key]

        # Divide by magnitude only (not the signed scale) so a mirrored
        # shape's reflection survives: the sign that made det(r) negative
        # stays on this column instead of being thrown away with the
        # magnitude baked into params.
        out = transform.copy()
        out[:3, :3] = r / magnitude
        return out
