"""The side panels: what you can add, and the exact numbers for what you picked.

The inspector is what separates a toy from a tool. Every gesture in the
viewport has a typeable millimetre equivalent here.
"""

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from mesh.scene import Shape, euler_from_transform
from mesh.shapes import PRIMITIVES

POSITION_FIELDS = ("x", "y", "z")
ROTATION_FIELDS = ("rx", "ry", "rz")

# Every size parameter that appears in any primitive's defaults (see
# mesh.shapes.PRIMITIVES). Which of these are shown for a given shape is
# decided at display time, from that shape's own primitive kind -- not
# every shape has every field, and imported/group shapes have none.
SIZE_FIELDS = ("width", "depth", "height", "diameter", "thickness", "wall")

FIELD_LABELS = {
    "x": "Left / right (mm)",
    "y": "Forward / back (mm)",
    "z": "Height above plane (mm)",
    "width": "Width (mm)",
    "depth": "Depth (mm)",
    "height": "Height (mm)",
    "diameter": "Diameter (mm)",
    "thickness": "Thickness (mm)",
    "wall": "Wall thickness (mm)",
    "rx": "Tilt X (degrees)",
    "ry": "Tilt Y (degrees)",
    "rz": "Turn (degrees)",
}


class ShapeShelf(QWidget):
    primitive_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setAlignment(Qt.AlignTop)
        self.buttons: dict[str, QPushButton] = {}

        for index, (kind, info) in enumerate(PRIMITIVES.items()):
            button = QPushButton(info["label"], self)
            button.setMinimumHeight(48)
            button.clicked.connect(lambda _checked=False, k=kind: self.primitive_requested.emit(k))
            layout.addWidget(button, index // 2, index % 2)
            self.buttons[kind] = button


class Inspector(QWidget):
    edited = Signal(str, str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shape: Shape | None = None
        self._loading = False

        layout = QFormLayout(self)
        self.fields: dict[str, QDoubleSpinBox] = {}
        self._rows: dict[str, int] = {}

        for field in POSITION_FIELDS + SIZE_FIELDS + ROTATION_FIELDS:
            box = QDoubleSpinBox(self)
            box.setDecimals(2)
            box.setSingleStep(1.0)
            if field in ROTATION_FIELDS:
                box.setRange(-360.0, 360.0)
            elif field in SIZE_FIELDS:
                box.setRange(0.1, 10000.0)
            else:
                box.setRange(-10000.0, 10000.0)
            box.valueChanged.connect(lambda value, f=field: self._emit(f, value))
            layout.addRow(QLabel(FIELD_LABELS[field]), box)
            self.fields[field] = box
            self._rows[field] = layout.rowCount() - 1

        self._layout = layout
        self.hole_box = QCheckBox("Make this a hole", self)
        self.hole_box.toggled.connect(lambda value: self._emit("is_hole", value))
        layout.addRow(self.hole_box)

        self.setEnabled(False)

    def _emit(self, field: str, value) -> None:
        if self._loading or self._shape is None:
            return
        self.edited.emit(self._shape.id, field, value)

    def field_value(self, field: str):
        if field == "is_hole":
            return self.hole_box.isChecked()
        return self.fields[field].value()

    def _active_size_fields(self, shape: Shape) -> tuple[str, ...]:
        """The real size parameters for this shape, or none for shapes that
        don't have any (imported models, groups) -- there is no plain-language
        substitute for a fallback number that edits nothing."""
        if shape.kind != "primitive":
            return ()
        primitive = shape.params.get("primitive")
        info = PRIMITIVES.get(primitive)
        if info is None:
            return ()
        return tuple(info["defaults"].keys())

    def show_shape(self, shape: Shape | None) -> None:
        self._shape = shape
        self.setEnabled(shape is not None)
        if shape is None:
            return

        self._loading = True
        try:
            transform = np.asarray(shape.transform, dtype=np.float64)
            for axis, field in enumerate(POSITION_FIELDS):
                self.fields[field].setValue(float(transform[axis, 3]))

            active = self._active_size_fields(shape)
            for field in SIZE_FIELDS:
                self._layout.setRowVisible(self._rows[field], field in active)
                if field in active:
                    self.fields[field].setValue(float(shape.params.get(field, 0.0)))

            # Rotation is authoritative in the transform, not in params:
            # shape_geometry() never reads rotation from params, so reading
            # it from there would show angles that do nothing when typed.
            rx, ry, rz = euler_from_transform(transform)
            for field, value in zip(ROTATION_FIELDS, (rx, ry, rz)):
                self.fields[field].setValue(float(value))

            self.hole_box.setChecked(bool(shape.is_hole))
        finally:
            self._loading = False
