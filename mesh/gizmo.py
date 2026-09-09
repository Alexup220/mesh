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

from mesh.scene import Shape


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
        self._shape.transform = transform
        self.changed.emit(self._shape.id)
