"""The side panels: what you can add, and the exact numbers for what you picked.

The inspector is what separates a toy from a tool. Every gesture in the
viewport has a typeable millimetre equivalent here.
"""

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mesh.features import END_SCALE_LIMITS, TAPER_LIMIT, TWIST_LIMIT
from mesh.scene import DEFAULT_COLOR, DEFAULT_FIT, FITS, Shape, euler_from_transform
from mesh.shapes import PRIMITIVES, is_reference, shelf_primitives
from mesh.text import has_letters

POSITION_FIELDS = ("x", "y", "z")
ROTATION_FIELDS = ("rx", "ry", "rz")

def _param_fields() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Every parameter that appears in any primitive's defaults (see
    mesh.shapes.PRIMITIVES), split by the kind of control it needs:
    numbers get a spin box, params with "choices" a drop-down, and any
    other text a text box. Which ones are shown for a given shape is
    decided at display time, from that shape's own primitive kind -- not
    every shape has every field, and imported/group shapes have none."""
    numeric, choice, text = [], [], []
    for info in PRIMITIVES.values():
        choices = info.get("choices", {})
        for key, default in info["defaults"].items():
            if key in numeric or key in choice or key in text:
                continue
            if key in choices:
                choice.append(key)
            elif isinstance(default, str):
                text.append(key)
            else:
                numeric.append(key)
    return tuple(numeric), tuple(choice), tuple(text)


SIZE_FIELDS, CHOICE_FIELDS, TEXT_FIELDS = _param_fields()

# Size fields that may legitimately be zero (a chamfer or rounding of 0
# means "none"); every other size must stay positive.
ZERO_ALLOWED = ("radius", "chamfer")

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
    "color": "Colour",
    "fit": "Fit",
    "radius": "Rounding radius (mm)",
    "chamfer": "Bottom chamfer (mm)",
    "text": "Text",
    "letter_height": "Letter height (mm)",
    "size": "Size",
    "head": "Screw head",
    "distance": "Distance (mm)",
    "side": "Direction",
    "angle": "Angle (degrees)",
    "taper": "Sides slope in (degrees)",
    "twist": "Twist along the path (degrees)",
    "end_scale": "Size at the far end (%)",
    "pitch": "Thread pitch (mm per turn)",
    "thread_length": "Threaded length (mm)",
    "end": "Thread starts",
    "hand": "Thread turns",
}


class ShapeShelf(QWidget):
    primitive_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setAlignment(Qt.AlignTop)
        self.buttons: dict[str, QPushButton] = {}

        for index, kind in enumerate(shelf_primitives()):
            button = QPushButton(PRIMITIVES[kind]["label"], self)
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
        self.field_labels: dict[str, QLabel] = {}
        self._rows: dict[str, int] = {}

        for field in POSITION_FIELDS + SIZE_FIELDS + ROTATION_FIELDS:
            box = QDoubleSpinBox(self)
            box.setDecimals(2)
            box.setSingleStep(1.0)
            if field in ROTATION_FIELDS:
                box.setRange(-360.0, 360.0)
            elif field == "angle":
                # How far a Revolve turns: at most one whole turn.
                box.setRange(0.1, 360.0)
            elif field == "taper":
                # How far an Extrusion's sides slope in (out, below 0).
                box.setRange(-TAPER_LIMIT, TAPER_LIMIT)
            elif field == "twist":
                # How far a Sweep turns along its path, either way.
                box.setRange(-TWIST_LIMIT, TWIST_LIMIT)
            elif field == "end_scale":
                box.setRange(*END_SCALE_LIMITS)
            elif field in SIZE_FIELDS:
                box.setRange(0.0 if field in ZERO_ALLOWED else 0.1, 10000.0)
            else:
                box.setRange(-10000.0, 10000.0)
            box.valueChanged.connect(lambda value, f=field: self._emit(f, value))
            label = QLabel(FIELD_LABELS[field])
            layout.addRow(label, box)
            self.field_labels[field] = label
            self.fields[field] = box
            self._rows[field] = layout.rowCount() - 1

        self._layout = layout

        # Non-numeric params: a drop-down per choice field (its items are
        # filled from the shown primitive's own choices), a text box per
        # text field.
        self.choice_boxes: dict[str, QComboBox] = {}
        for field in CHOICE_FIELDS:
            combo = QComboBox(self)
            combo.currentIndexChanged.connect(
                lambda _i, f=field, c=combo: self._emit(f, c.currentData())
            )
            layout.addRow(QLabel(FIELD_LABELS[field]), combo)
            self.choice_boxes[field] = combo
            self._rows[field] = layout.rowCount() - 1
        self.text_boxes: dict[str, QLineEdit] = {}
        for field in TEXT_FIELDS:
            line = QLineEdit(self)
            # Emit once the user is done typing, not per keystroke: half-typed
            # text is not worth rebuilding geometry for.
            line.editingFinished.connect(lambda f=field, w=line: self._emit_text(f, w))
            layout.addRow(QLabel(FIELD_LABELS[field]), line)
            self.text_boxes[field] = line
            self._rows[field] = layout.rowCount() - 1

        self.color_button = QPushButton(self)
        self.color_button.setFixedHeight(28)
        self.color_button.clicked.connect(self._pick_color)
        layout.addRow(QLabel(FIELD_LABELS["color"]), self.color_button)

        self.hole_box = QCheckBox("Make this a hole", self)
        self.hole_box.toggled.connect(lambda value: self._emit("is_hole", value))
        layout.addRow(self.hole_box)
        self._hole_row = layout.rowCount() - 1

        # How snugly the hole fits what goes into it. Only meaningful for a
        # Hole, so the row is hidden for solids (see show_shape).
        self.fit_box = QComboBox(self)
        for key, label in FITS.items():
            self.fit_box.addItem(label, key)
        self.fit_box.currentIndexChanged.connect(
            lambda _i: self._emit("fit", self.fit_box.currentData())
        )
        layout.addRow(QLabel(FIELD_LABELS["fit"]), self.fit_box)
        self._fit_row = layout.rowCount() - 1

        self.show_shape(None)

    def _emit(self, field: str, value) -> None:
        if self._loading or self._shape is None:
            return
        self.edited.emit(self._shape.id, field, value)

    def _emit_text(self, field: str, widget: QLineEdit) -> None:
        if self._shape is None or self._loading:
            return
        value = widget.text()
        if field == "text" and not has_letters(value):
            # Nothing that would draw: put the part's own text back.
            widget.setText(str(self._shape.params.get(field, "")))
            return
        if value.strip() and value != self._shape.params.get(field):
            self._emit(field, value)

    def _set_color_swatch(self, color: str) -> None:
        self.color_button.setStyleSheet(f"background-color: {color}; border: 1px solid #3d434b;")
        self.color_button.setText(color)

    def _pick_color(self) -> None:
        if self._shape is None:
            return
        current = QColor(self._shape.color)
        chosen = QColorDialog.getColor(current, self, "Choose a colour")
        if not chosen.isValid():
            return
        hex_color = chosen.name(QColor.HexRgb).lower()
        self._set_color_swatch(hex_color)
        self._emit("color", hex_color)

    def field_value(self, field: str):
        if field == "is_hole":
            return self.hole_box.isChecked()
        if field == "color":
            return self.color_button.text()
        if field == "fit":
            return self.fit_box.currentData()
        if field in self.choice_boxes:
            return self.choice_boxes[field].currentData()
        if field in self.text_boxes:
            return self.text_boxes[field].text()
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

    def _choices(self, shape: Shape) -> dict:
        info = PRIMITIVES.get(shape.params.get("primitive")) if shape.kind == "primitive" else None
        return info.get("choices", {}) if info else {}

    def visible_param_fields(self) -> set[str]:
        """The shape params this inspector is currently showing a control for."""
        return {
            field
            for field in SIZE_FIELDS + CHOICE_FIELDS + TEXT_FIELDS
            if self._layout.isRowVisible(self._rows[field])
        }

    def show_shape(self, shape: Shape | None) -> None:
        self._shape = shape
        self.setEnabled(shape is not None)
        if shape is None:
            # Nothing selected: show only the rows every shape has. Listing
            # every possible size field made the panel wide enough to
            # squeeze the 3D view.
            for field in SIZE_FIELDS + CHOICE_FIELDS + TEXT_FIELDS:
                self._layout.setRowVisible(self._rows[field], False)
            self._layout.setRowVisible(self._fit_row, False)
            # Hidden while a sketch was shown; every part has it.
            self._layout.setRowVisible(self._hole_row, True)
            self._show_links({})
            return

        self._loading = True
        try:
            transform = np.asarray(shape.transform, dtype=np.float64)
            for axis, field in enumerate(POSITION_FIELDS):
                self.fields[field].setValue(float(transform[axis, 3]))

            active = self._active_size_fields(shape)
            # A number a part made before it existed lacks means its default.
            defaults = PRIMITIVES[shape.params["primitive"]]["defaults"] if active else {}
            for field in SIZE_FIELDS:
                self._layout.setRowVisible(self._rows[field], field in active)
                if field in active:
                    self.fields[field].setValue(float(shape.params.get(field, defaults.get(field, 0.0))))
            choices = self._choices(shape)
            for field, combo in self.choice_boxes.items():
                shown = field in active
                self._layout.setRowVisible(self._rows[field], shown)
                combo.clear()
                if shown:
                    for value, label in choices.get(field, []):
                        combo.addItem(label, value)
                    combo.setCurrentIndex(max(combo.findData(shape.params.get(field, defaults.get(field))), 0))
            for field, line in self.text_boxes.items():
                shown = field in active
                self._layout.setRowVisible(self._rows[field], shown)
                line.setText(str(shape.params.get(field, "")) if shown else "")

            # Rotation is authoritative in the transform, not in params:
            # shape_geometry() never reads rotation from params, so reading
            # it from there would show angles that do nothing when typed.
            rx, ry, rz = euler_from_transform(transform)
            for field, value in zip(ROTATION_FIELDS, (rx, ry, rz)):
                self.fields[field].setValue(float(value))

            # A guide (a sketch) is never printed, so solid or hole means
            # nothing for it.
            guide = is_reference(shape)
            self.hole_box.setChecked(bool(shape.is_hole))
            self._layout.setRowVisible(self._hole_row, not guide)
            self._layout.setRowVisible(self._fit_row, bool(shape.is_hole) and not guide)
            index = self.fit_box.findData(getattr(shape, "fit", DEFAULT_FIT))
            self.fit_box.setCurrentIndex(max(index, 0))
            self._set_color_swatch(shape.color or DEFAULT_COLOR)
            self._show_links(getattr(shape, "links", None) or {})
        finally:
            self._loading = False

    LINKED_TIP = "Follows the formula {formula} (Modify > Change Parameters). Typing a number ends the link."

    def _show_links(self, links: dict) -> None:
        """A number that follows a parameter's formula is shown in italics,
        with the formula in its tooltip (Expert mode)."""
        for field, box in self.fields.items():
            formula = links.get(field)
            tip = self.LINKED_TIP.format(formula=formula) if formula else ""
            box.setToolTip(tip)
            label = self.field_labels[field]
            label.setToolTip(tip)
            font = label.font()
            font.setItalic(bool(formula))
            label.setFont(font)


class FormDialog(QDialog):
    """A small form of named fields with OK / Cancel.

    `fields` is a list of (key, label, default, options) tuples:
    - a float default makes a millimetre spin box; options may hold
      "min", "max", "decimals", "step";
    - an int default makes a whole-number spin box ("min", "max");
    - a bool default makes a check box;
    - a str default with options["choices"] = [(value, label), ...] makes a
      drop-down; any other str default makes a text box.
    Every tool dialog (fits, hollow out, split, patterns, box with lid, text)
    is one of these, so the tests can drive them through `values()`.
    """

    NOTE_WIDTH = 380

    def __init__(self, parent, title: str, fields, note: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.widgets: dict[str, QWidget] = {}
        outer = QVBoxLayout(self)
        if note:
            # A word-wrapped label is not reliably given the height its
            # wrapped lines need (inside a form row it showed half the
            # note). So it sits above the form, never narrower than
            # NOTE_WIDTH, and never shorter than its lines at that width.
            self.note = QLabel(note, self)
            self.note.setWordWrap(True)
            self.note.setMinimumWidth(self.NOTE_WIDTH)
            self.note.ensurePolished()
            self.note.setMinimumHeight(self.note.heightForWidth(self.NOTE_WIDTH))
            outer.addWidget(self.note)
        else:
            self.note = None
        layout = QFormLayout()
        outer.addLayout(layout)
        for key, label, default, options in fields:
            options = options or {}
            if isinstance(default, bool):
                widget = QCheckBox(label, self)
                widget.setChecked(default)
                layout.addRow(widget)
            else:
                if isinstance(default, int):
                    widget = QSpinBox(self)
                    widget.setRange(int(options.get("min", 0)), int(options.get("max", 1000)))
                    widget.setValue(default)
                elif isinstance(default, float):
                    widget = QDoubleSpinBox(self)
                    widget.setDecimals(int(options.get("decimals", 2)))
                    widget.setSingleStep(float(options.get("step", 1.0)))
                    widget.setRange(float(options.get("min", 0.0)), float(options.get("max", 10000.0)))
                    widget.setValue(default)
                elif "choices" in options:
                    widget = QComboBox(self)
                    for value, text in options["choices"]:
                        widget.addItem(text, value)
                    widget.setCurrentIndex(max(widget.findData(default), 0))
                else:
                    widget = QLineEdit(default, self)
                layout.addRow(QLabel(label, self), widget)
            self.widgets[key] = widget
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def values(self) -> dict:
        out = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                out[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                out[key] = widget.value()
            elif isinstance(widget, QComboBox):
                out[key] = widget.currentData()
            else:
                out[key] = widget.text()
        return out

    def labels(self) -> list[str]:
        """Every piece of text this dialog shows (for the plain-language tests)."""
        texts = [self.windowTitle()]
        if self.note is not None:
            texts.append(self.note.text())
        for label in self.findChildren(QLabel):
            texts.append(label.text())
        for widget in self.widgets.values():
            if isinstance(widget, QCheckBox):
                texts.append(widget.text())
            elif isinstance(widget, QComboBox):
                texts.extend(widget.itemText(i) for i in range(widget.count()))
        return texts


def run_form(parent, title: str, fields, note: str | None = None) -> dict | None:
    """Show a FormDialog; return its values, or None if cancelled."""
    dialog = FormDialog(parent, title, fields, note)
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.values()
    finally:
        dialog.deleteLater()


def fit_clearance_fields(current: dict):
    return [
        (key, f"{FITS[key]} clearance per side (mm)", float(current[key]),
         {"min": 0.0, "max": 2.0, "decimals": 2, "step": 0.05})
        for key in current
    ]


def ask_fit_clearances(parent, current: dict) -> dict | None:
    return run_form(
        parent,
        "Fit clearances",
        fit_clearance_fields(current),
        note="Extra room added on every side of a Hole, so parts slide in after printing.",
    )


APPROXIMATE_HOLLOW_NOTE = (
    "This shape is hollowed out approximately: the wall follows the outside "
    "evenly, but may come out a little thinner in places than the number "
    "you type. Boxes, cylinders and spheres are hollowed out exactly."
)


def hollow_fields(exact: bool):
    fields = [("wall", "Wall thickness (mm)", 2.0, {"min": 0.1, "max": 100.0})]
    if exact:
        fields.append(("open_top", "Open top", False, None))
    fields.append(("drain", "Drain hole (mm, 0 for none)", 0.0, {"min": 0.0, "max": 100.0}))
    return fields


def ask_hollow(parent, exact: bool) -> dict | None:
    return run_form(
        parent, "Hollow out", hollow_fields(exact),
        note=None if exact else APPROXIMATE_HOLLOW_NOTE,
    )


SPLIT_DIRECTIONS = [
    ("z", "Flat, at a height"),
    ("x", "Upright, left from right"),
    ("y", "Upright, front from back"),
]


def split_fields(size: tuple[float, float, float]):
    return [
        ("axis", "Cut", "z", {"choices": SPLIT_DIRECTIONS}),
        ("distance", "Cut this far in from the bottom, left or front (mm)",
         round(size[2] / 2.0, 2), {"min": 0.0, "max": 10000.0}),
        ("pegs", "Add alignment pegs", False, None),
        ("peg_diameter", "Peg size (mm)", 4.0, {"min": 1.0, "max": 50.0}),
    ]


def split_note(size: tuple[float, float, float]) -> str:
    return (
        f"This part is {size[0]:.1f} mm left to right, {size[1]:.1f} mm front to back "
        f"and {size[2]:.1f} mm tall. Both halves are laid out side by side, ready to print."
    )


def ask_split(parent, size: tuple[float, float, float]) -> dict | None:
    return run_form(parent, "Split part", split_fields(size), note=split_note(size))


ROW_DIRECTIONS = [("x", "Left to right (X)"), ("y", "Front to back (Y)")]


def repeat_row_fields():
    return [
        ("count", "How many in total", 3, {"min": 2, "max": 500}),
        ("spacing", "Spacing, centre to centre (mm)", 25.0, {"min": 0.1}),
        ("axis", "Direction", "x", {"choices": ROW_DIRECTIONS}),
    ]


def ask_repeat_row(parent) -> dict | None:
    return run_form(parent, "Repeat in a row", repeat_row_fields())


def repeat_circle_fields(part_centre: tuple[float, float], radius: float = 30.0):
    # By default the circle's centre sits `radius` to the left of the part,
    # so the part is already on the circle and stays put.
    return [
        ("count", "How many in total", 6, {"min": 2, "max": 500}),
        ("radius", "Radius (mm)", radius, {"min": 0.1}),
        ("angle", "Angle to fill (degrees, 360 for a full circle)", 360.0,
         {"min": 1.0, "max": 360.0}),
        ("centre_x", "Circle centre, left / right (mm)", round(part_centre[0] - radius, 2),
         {"min": -10000.0}),
        ("centre_y", "Circle centre, forward / back (mm)", round(part_centre[1], 2),
         {"min": -10000.0}),
    ]


def ask_repeat_circle(parent, part_centre: tuple[float, float]) -> dict | None:
    return run_form(
        parent, "Repeat in a circle", repeat_circle_fields(part_centre),
        note="Copies go round a vertical line through the circle centre.",
    )


def box_with_lid_fields():
    return [
        ("width", "Outside width (mm)", 60.0, {"min": 5.0}),
        ("depth", "Outside depth (mm)", 40.0, {"min": 5.0}),
        ("height", "Outside height, lid on (mm)", 30.0, {"min": 5.0}),
        ("wall", "Wall thickness (mm)", 2.0, {"min": 0.4, "max": 50.0}),
        ("lid_height", "Lid height (mm)", 6.0, {"min": 0.4}),
        ("fit", "Lid fit", "snug", {"choices": list(FITS.items())}),
    ]


def ask_box_with_lid(parent) -> dict | None:
    return run_form(
        parent, "Box with lid", box_with_lid_fields(),
        note="Makes a box and a lid that drops onto it, side by side and ready to print.",
    )


TEXT_STYLES = [("raised", "Raised (stands up)"), ("engraved", "Engraved (cut in, as a Hole)")]


def text_fields():
    return [
        ("text", "Text", "Hello", None),
        ("letter_height", "Letter height (mm)", 10.0, {"min": 1.0, "max": 500.0}),
        ("depth", "Depth (mm)", 2.0, {"min": 0.2, "max": 100.0}),
        ("style", "Style", "raised", {"choices": TEXT_STYLES}),
    ]


def ask_text(parent) -> dict | None:
    return run_form(parent, "Add text", text_fields())
