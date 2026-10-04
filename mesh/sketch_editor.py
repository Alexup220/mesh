"""The sketch window (Expert mode): a sketch's curves, typed in millimetres
or clicked into a flat drawing of its plane.

Every curve has a small form of numbers (see entity_fields), and lines can
also be drawn by clicking: each click joins the last point to the new one,
snapped to the grid or to a curve's end. The finished list of curves goes
back to the window, which stores it on a sketch shape (mesh.create).
"""

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mesh import create, sketch
from mesh.panels import run_form

# Any position in a sketch, and any size, in millimetres.
COORD = {"min": -sketch.LIMIT, "max": sketch.LIMIT, "decimals": 3}
SIZE = {"min": sketch.MIN_SIZE, "max": sketch.LIMIT, "decimals": 3}
ANGLE = {"min": -360.0, "max": 360.0, "decimals": 3}

ENTITY_LABELS = {
    "line": "Line",
    "rectangle": "Rectangle",
    "circle": "Circle",
    "arc": "Arc",
    "polygon": "Polygon",
    "spline": "Spline",
}

# What a new curve's form starts with.
NEW_ENTITIES = {
    "line": {"type": "line", "start": [0.0, 0.0], "end": [20.0, 0.0]},
    "rectangle": {"type": "rectangle", "corner": [0.0, 0.0], "width": 20.0, "height": 20.0},
    "circle": {"type": "circle", "centre": [0.0, 0.0], "diameter": 20.0},
    "arc": {"type": "arc", "centre": [0.0, 0.0], "radius": 10.0, "start": 0.0, "end": 90.0},
    "polygon": {"type": "polygon", "centre": [0.0, 0.0], "sides": 6, "radius": 10.0, "angle": 0.0},
    "spline": {"type": "spline", "points": [[0.0, 0.0], [10.0, 10.0], [20.0, 0.0]], "closed": False},
}

SPLINE_POINTS_HELP = "Type the points as pairs of numbers, like 0, 0; 10, 5; 20, 0."


def _xy(prefix: str, label: str, point) -> list:
    return [
        (f"{prefix}x", f"{label} X (mm)", float(point[0]), COORD),
        (f"{prefix}y", f"{label} Y (mm)", float(point[1]), COORD),
    ]


def _number_text(value: float) -> str:
    """A number as short as it can be typed and still read back exactly."""
    short = f"{value:g}"
    return short if float(short) == value else repr(float(value))


def entity_fields(kind: str, entity: dict | None = None) -> list:
    """The form for one curve, filled from `entity` (or a new curve's numbers)."""
    e = entity if entity is not None else NEW_ENTITIES[kind]
    if kind == "line":
        return _xy("start_", "Start", e["start"]) + _xy("end_", "End", e["end"])
    if kind == "rectangle":
        return _xy("corner_", "Corner", e["corner"]) + [
            ("width", "Width (mm)", float(e["width"]), SIZE),
            ("height", "Height (mm)", float(e["height"]), SIZE),
        ]
    if kind == "circle":
        return _xy("centre_", "Centre", e["centre"]) + [
            ("diameter", "Diameter (mm)", float(e["diameter"]), SIZE),
        ]
    if kind == "arc":
        return _xy("centre_", "Centre", e["centre"]) + [
            ("radius", "Radius (mm)", float(e["radius"]), SIZE),
            ("start", "Start angle (degrees)", float(e["start"]), ANGLE),
            ("end", "End angle (degrees)", float(e["end"]), ANGLE),
        ]
    if kind == "polygon":
        return _xy("centre_", "Centre", e["centre"]) + [
            ("sides", "Sides", int(e["sides"]), {"min": 3, "max": 1000}),
            ("radius", "Centre to a corner (mm)", float(e["radius"]), SIZE),
            ("angle", "Turn (degrees)", float(e["angle"]), ANGLE),
        ]
    if kind == "spline":
        points = "; ".join(f"{_number_text(x)}, {_number_text(y)}" for x, y in e["points"])
        return [
            ("points", "Points it passes through", points, {}),
            ("closed", "Close it into a loop", bool(e["closed"]), {}),
        ]
    raise ValueError(f"unknown curve {kind!r}")


def _as_shown(default, options: dict):
    """What a form field shows for `default`: a number box keeps it within
    its range and rounds it to its decimals (see mesh.panels.FormDialog)."""
    if isinstance(default, bool) or not isinstance(default, (int, float)):
        return default
    if isinstance(default, int):
        return min(max(default, int(options.get("min", 0))), int(options.get("max", 1000)))
    value = min(max(default, float(options.get("min", 0.0))), float(options.get("max", 10000.0)))
    return round(value, int(options.get("decimals", 2)))


def keep_untouched(fields, values: dict) -> dict:
    """A form's values, with every field still showing what it was given
    back exactly as it was: the form's rounding and range must not change a
    curve just because its form was opened."""
    out = dict(values)
    for key, _label, default, options in fields:
        shown = _as_shown(default, options or {})
        if values.get(key) == shown or (
                isinstance(shown, float) and abs(values.get(key, math.inf) - shown) < 1e-9):
            out[key] = default
    return out


def parse_points(text: str) -> list:
    """"0, 0; 10, 5" -> [[0, 0], [10, 5]]."""
    points = []
    for pair in text.replace("\n", ";").split(";"):
        if not pair.strip():
            continue
        parts = pair.replace(" ", ",").split(",")
        numbers = [p for p in parts if p.strip()]
        try:
            x, y = (float(v) for v in numbers)
        except ValueError as exc:
            raise sketch.SketchError(SPLINE_POINTS_HELP) from exc
        points.append([x, y])
    return points


def entity_from_values(kind: str, values: dict) -> dict:
    """A checked curve from a filled-in form. Raises SketchError."""

    def xy(prefix):
        return [values[f"{prefix}x"], values[f"{prefix}y"]]

    if kind == "line":
        entity = {"type": "line", "start": xy("start_"), "end": xy("end_")}
    elif kind == "rectangle":
        entity = {"type": "rectangle", "corner": xy("corner_"),
                  "width": values["width"], "height": values["height"]}
    elif kind == "circle":
        entity = {"type": "circle", "centre": xy("centre_"), "diameter": values["diameter"]}
    elif kind == "arc":
        entity = {"type": "arc", "centre": xy("centre_"), "radius": values["radius"],
                  "start": values["start"], "end": values["end"]}
    elif kind == "polygon":
        entity = {"type": "polygon", "centre": xy("centre_"), "sides": values["sides"],
                  "radius": values["radius"], "angle": values["angle"]}
    elif kind == "spline":
        entity = {"type": "spline", "points": parse_points(values["points"]),
                  "closed": values["closed"]}
    else:
        raise ValueError(f"unknown curve {kind!r}")
    return sketch.clean_entity(entity)


def status_text(entities) -> str:
    """What the sketch's curves add up to, in plain words."""
    if not entities:
        return "No curves yet. Add one with the buttons, or turn on Draw Lines and click."
    found = sketch.chains(entities)
    if found.branching:
        return ("Some curves meet three or more at one point, so the outline is unclear. "
                "Draw each outline as one closed loop.")
    loops = sum(1 for loop in found.loops if abs(sketch.signed_area(loop)) > sketch.MIN_SIZE**2)
    paths = len(found.paths)

    def count(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"

    if loops and not paths:
        return f"{count(loops, 'closed outline')}, ready to make a part from."
    if loops:
        return (f"{count(loops, 'closed outline')} and {count(paths, 'open path')}. "
                "Only closed outlines give a part its shape.")
    return (f"{count(paths, 'open path')} and no closed outline yet. A path can guide a "
            "Sweep; a part's shape needs a closed outline (join curve ends, or add a closed curve).")


class LineDrawer:
    """Click-to-draw lines. Each click adds a point and a line from the
    point before it; clicking the first point again closes the outline and
    starts afresh."""

    def __init__(self) -> None:
        self.points: list[list[float]] = []

    def click(self, point) -> list[dict]:
        """The line (if any) this click draws."""
        point = [float(point[0]), float(point[1])]
        if not self.points:
            self.points = [point]
            return []
        last = self.points[-1]
        if math.dist(last, point) < sketch.MIN_SIZE:
            return []
        if len(self.points) >= 2 and math.dist(self.points[-2], point) <= sketch.JOIN_TOLERANCE:
            return []  # straight back over the line just drawn
        line = {"type": "line", "start": list(last), "end": point}
        if len(self.points) >= 3 and math.dist(self.points[0], point) <= sketch.JOIN_TOLERANCE:
            self.points = []
        else:
            self.points.append(point)
        return [line]

    def finish(self) -> None:
        self.points = []


def _curve_ends(entities) -> list:
    """The points a click snaps to: line, arc and spline ends and corners,
    circle and polygon centres."""
    out = []
    for e in entities:
        kind = e["type"]
        if kind == "line":
            out += [e["start"], e["end"]]
        elif kind == "spline":
            out += list(e["points"])
        elif kind == "arc":
            points, _closed = sketch.entity_points(e)
            out += [list(points[0]), list(points[-1]), e["centre"]]
        elif kind in ("circle", "polygon"):
            out.append(e["centre"])
            if kind == "polygon":
                points, _closed = sketch.entity_points(e)
                out += [list(p) for p in points]
        elif kind == "rectangle":
            points, _closed = sketch.entity_points(e)
            out += [list(p) for p in points]
    return out


class SketchPreview(QWidget):
    """A flat drawing of the sketch: grid, axes, the filled outline, every
    curve, and (when sketching on a face) that face's outline, dashed."""

    clicked = Signal(float, float)   # a snapped point, in sketch millimetres
    finished = Signal()              # right click: end the line being drawn

    SNAP_PIXELS = 10
    # The drawing first shows at least this many mm across; the mouse wheel
    # zooms by ZOOM_STEP a notch, between SPANS.
    FIRST_SPAN = 100.0
    ZOOM_STEP = 1.25
    SPANS = (1.0, 100000.0)
    BACKGROUND = QColor("#1b1e22")
    GRID = QColor("#2c3138")
    X_AXIS = QColor("#d9534f")
    Y_AXIS = QColor("#5cb85c")
    CURVE = QColor(create.SKETCH_COLOR)
    CHOSEN = QColor("#ffd933")
    GUIDE = QColor("#9aa3ad")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(440, 440)
        self.setMouseTracking(True)
        self.entities: list[dict] = []
        self.guides: list[np.ndarray] = []
        self.chain: list = []
        self.chosen: int | None = None
        self.drawing = False
        self._hover = None
        self._centre = np.zeros(2)
        self._span = self.FIRST_SPAN
        self._fitted = False

    def set_content(self, entities, guides=None, chain=None, chosen=None) -> None:
        self.entities = list(entities)
        if guides is not None:
            self.guides = [np.asarray(g, dtype=np.float64) for g in guides]
        self.chain = list(chain or [])
        self.chosen = chosen
        # Fitted once; after that the view only grows when something is
        # out of sight, so a click never moves the drawing under the mouse.
        self._fit(grow_only=self._fitted)
        self._fitted = True
        self.update()

    # --- Where things are on screen ---------------------------------------------

    def _fit(self, grow_only: bool = False) -> None:
        points = [np.zeros((1, 2))]
        points += [line for line in sketch.sketch_lines(self.entities)]
        points += list(self.guides)
        if self.chain:
            points.append(np.asarray(self.chain))
        everything = np.vstack(points)
        low, high = everything.min(axis=0), everything.max(axis=0)
        if grow_only:
            view_low, view_high = self._centre - self._span / 2.0, self._centre + self._span / 2.0
            if np.all(low >= view_low) and np.all(high <= view_high):
                return
            low, high = np.minimum(low, view_low), np.maximum(high, view_high)
        self._centre = (low + high) / 2.0
        self._span = min(max(float((high - low).max()) * 1.25, self.FIRST_SPAN), self.SPANS[1])

    def zoom(self, notches: float, x: float, y: float) -> None:
        """Zoom in (notches > 0) or out, keeping the point under (x, y)
        pixels where it is."""
        before = self.to_sketch(x, y)
        low, high = self.SPANS
        self._span = min(max(self._span / self.ZOOM_STEP ** notches, low), high)
        self._centre = self._centre + (before - self.to_sketch(x, y))
        self.update()

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120.0
        if notches:
            self.zoom(notches, event.position().x(), event.position().y())

    def _scale(self) -> float:
        return min(self.width(), self.height()) / self._span

    def to_screen(self, point) -> QPointF:
        s = self._scale()
        return QPointF(self.width() / 2.0 + (point[0] - self._centre[0]) * s,
                       self.height() / 2.0 - (point[1] - self._centre[1]) * s)

    def to_sketch(self, x: float, y: float) -> np.ndarray:
        s = self._scale()
        return np.array([self._centre[0] + (x - self.width() / 2.0) / s,
                         self._centre[1] - (y - self.height() / 2.0) / s])

    def grid_step(self) -> float | None:
        """The grid's spacing (mm): a round number at least 12 pixels apart;
        None (no grid) when zoomed out so far that none is."""
        s = self._scale()
        for step in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000):
            if step * s >= 12:
                return float(step)
        return None

    def snap(self, x: float, y: float) -> list:
        """The sketch point a click at (x, y) pixels means: a curve's end
        when one is near, else the nearest grid point."""
        s = self._scale()
        raw = self.to_sketch(x, y)
        ends = _curve_ends(self.entities) + list(self.chain)
        if ends:
            ends = np.asarray(ends, dtype=np.float64)
            distance = np.linalg.norm(ends - raw, axis=1)
            nearest = int(np.argmin(distance))
            if distance[nearest] * s <= self.SNAP_PIXELS:
                return [float(v) for v in ends[nearest]]
        step = self.grid_step() or 1.0
        return [round(float(v) / step) * step for v in raw]

    # --- Mouse ---------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if not self.drawing:
            return
        if event.button() == Qt.RightButton:
            self.finished.emit()
            return
        if event.button() == Qt.LeftButton:
            x, y = self.snap(event.position().x(), event.position().y())
            self.clicked.emit(x, y)

    def mouseMoveEvent(self, event) -> None:
        if self.drawing:
            self._hover = self.snap(event.position().x(), event.position().y())
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hover = None
        self.update()

    # --- Drawing ---------------------------------------------------------------------

    def _polyline(self, painter, points, closed=False) -> None:
        polygon = QPolygonF([self.to_screen(p) for p in points])
        if closed:
            painter.drawPolygon(polygon)
        else:
            painter.drawPolyline(polygon)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.BACKGROUND)

        step = self.grid_step()
        low = self.to_sketch(0, self.height())
        high = self.to_sketch(self.width(), 0)
        painter.setPen(QPen(self.GRID, 1))
        if step is not None:
            for i in range(int(math.floor(low[0] / step)), int(math.ceil(high[0] / step)) + 1):
                x = self.to_screen((i * step, 0)).x()
                painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            for j in range(int(math.floor(low[1] / step)), int(math.ceil(high[1] / step)) + 1):
                y = self.to_screen((0, j * step)).y()
                painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
        origin = self.to_screen((0, 0))
        painter.setPen(QPen(self.X_AXIS, 1.5))
        painter.drawLine(QPointF(0, origin.y()), QPointF(self.width(), origin.y()))
        painter.setPen(QPen(self.Y_AXIS, 1.5))
        painter.drawLine(QPointF(origin.x(), 0), QPointF(origin.x(), self.height()))

        if self.guides:
            pen = QPen(self.GUIDE, 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for loop in self.guides:
                self._polyline(painter, loop, closed=True)

        try:
            area = sketch.profile(self.entities)
        except sketch.SketchError:
            area = None
        if area is not None:
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for polygon in area.to_polygons():
                path.addPolygon(QPolygonF([self.to_screen(p) for p in polygon]))
                path.closeSubpath()
            fill = QColor(self.CURVE)
            fill.setAlpha(60)
            painter.fillPath(path, fill)

        painter.setBrush(Qt.NoBrush)
        for index, line in enumerate(sketch.sketch_lines(self.entities)):
            chosen = index == self.chosen
            painter.setPen(QPen(self.CHOSEN if chosen else self.CURVE, 3.0 if chosen else 2.0))
            self._polyline(painter, line)

        if self.chain:
            painter.setPen(QPen(self.CHOSEN, 1.5))
            painter.setBrush(self.CHOSEN)
            for point in self.chain:
                painter.drawEllipse(self.to_screen(point), 3, 3)
            if self._hover is not None:
                painter.setPen(QPen(self.CHOSEN, 1.5, Qt.DashLine))
                painter.drawLine(self.to_screen(self.chain[-1]), self.to_screen(self._hover))
        if self.drawing and self._hover is not None:
            painter.setPen(QPen(self.CHOSEN, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(self.to_screen(self._hover), 5, 5)
        painter.end()


class SketchDialog(QDialog):
    """The sketch window: the drawing on the left, its curves on the right."""

    NOTE = (
        "Sizes are in millimetres. X runs to the right and Y runs up, seen from "
        "the side the plane faces. Closed curves make the outline a part is made "
        "from; a closed curve inside another cuts a hole in it. Turn the mouse "
        "wheel over the drawing to zoom."
    )
    DRAW_PROMPT = (
        "Click to place points: each click draws a line from the last point. Click the "
        "first point again to close the outline. Right-click or press Esc to stop the line."
    )

    def __init__(self, parent, title: str, entities=(), guides=(), note: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._entities = sketch.clean_entities(list(entities))
        self.guides = [np.asarray(g, dtype=np.float64) for g in guides]
        self.drawer = LineDrawer()

        outer = QHBoxLayout(self)
        self.preview = SketchPreview(self)
        self.preview.clicked.connect(self._on_preview_click)
        self.preview.finished.connect(self.finish_line)
        outer.addWidget(self.preview, 1)

        side = QVBoxLayout()
        outer.addLayout(side)
        self.note = QLabel(note + " " + self.NOTE if note else self.NOTE, self)
        self.note.setWordWrap(True)
        self.note.setMinimumWidth(320)
        side.addWidget(self.note)

        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(lambda _row: self._chosen_changed())
        self.list.itemDoubleClicked.connect(lambda _item: self.change_chosen())
        side.addWidget(self.list, 1)

        buttons = QGridLayout()
        side.addLayout(buttons)
        self.draw_button = QPushButton("Draw Lines", self)
        self.draw_button.setCheckable(True)
        self.draw_button.toggled.connect(self.set_drawing)
        buttons.addWidget(self.draw_button, 0, 0, 1, 2)
        self.add_buttons: dict[str, QPushButton] = {}
        for index, (kind, label) in enumerate(ENTITY_LABELS.items()):
            button = QPushButton(f"{label}...", self)
            button.clicked.connect(lambda _c=False, k=kind: self.ask_new(k))
            buttons.addWidget(button, 1 + index // 2, index % 2)
            self.add_buttons[kind] = button
        row = 1 + (len(ENTITY_LABELS) + 1) // 2
        self.change_button = QPushButton("Change...", self)
        self.change_button.clicked.connect(self.change_chosen)
        buttons.addWidget(self.change_button, row, 0)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self.remove_chosen)
        buttons.addWidget(self.remove_button, row, 1)
        self.copy_button = QPushButton("Copy the Face's Outline", self)
        self.copy_button.setToolTip("Add the clicked face's edges as lines, to trace or change.")
        self.copy_button.clicked.connect(self.copy_guides)
        self.copy_button.setVisible(bool(self.guides))
        buttons.addWidget(self.copy_button, row + 1, 0, 1, 2)

        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(320)
        side.addWidget(self.status)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        side.addWidget(self.button_box)

        self._refresh()

    # --- The curves ---------------------------------------------------------------

    def entities(self) -> list[dict]:
        return [dict(e) for e in self._entities]

    def add_entity(self, entity) -> None:
        self._entities.append(sketch.clean_entity(entity))
        self._refresh(chosen=len(self._entities) - 1)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Cannot draw that", text)

    def _ask(self, kind: str, entity=None):
        """Run a curve's form; the checked curve, or None."""
        verb = "Change" if entity is not None else "Add"
        name = ENTITY_LABELS[kind].lower()
        article = "an" if name[0] in "aeiou" else "a"
        fields = entity_fields(kind, entity)
        values = run_form(self, f"{verb} {article} {name}", fields,
                          note=SPLINE_POINTS_HELP if kind == "spline" else None)
        if values is None:
            return None
        if entity is not None:
            values = keep_untouched(fields, values)
        try:
            return entity_from_values(kind, values)
        except sketch.SketchError as exc:
            self._warn(str(exc))
            return None

    def ask_new(self, kind: str) -> None:
        self.set_drawing(False)
        entity = self._ask(kind)
        if entity is not None:
            self.add_entity(entity)

    def chosen_row(self) -> int | None:
        row = self.list.currentRow()
        return row if 0 <= row < len(self._entities) else None

    def change_chosen(self) -> None:
        row = self.chosen_row()
        if row is None:
            return
        self.drawer.finish()
        old = self._entities[row]
        entity = self._ask(old["type"], old)
        if entity is not None:
            self._entities[row] = entity
            self._refresh(chosen=row)

    def remove_chosen(self) -> None:
        row = self.chosen_row()
        if row is None:
            return
        self.drawer.finish()
        del self._entities[row]
        self._refresh(chosen=min(row, len(self._entities) - 1) if self._entities else None)

    def copy_guides(self) -> None:
        """Add the face's edges as lines; any already there are not added twice."""
        self.drawer.finish()
        for entity in create.outline_entities(self.guides):
            if entity not in self._entities:
                self._entities.append(entity)
        self._refresh(chosen=len(self._entities) - 1)

    # --- Drawing lines by clicking -------------------------------------------------

    def set_drawing(self, on: bool) -> None:
        on = bool(on)
        self.drawer.finish()
        self.preview.drawing = on
        if self.draw_button.isChecked() != on:
            self.draw_button.blockSignals(True)
            self.draw_button.setChecked(on)
            self.draw_button.blockSignals(False)
        self._refresh(chosen=self.chosen_row())

    def drawing(self) -> bool:
        return self.preview.drawing

    def _on_preview_click(self, x: float, y: float) -> None:
        self.click_point((x, y))

    def click_point(self, point) -> None:
        """A click in the drawing while Draw Lines is on (snapped already)."""
        if not self.drawing():
            return
        new = self.drawer.click(point)
        for entity in new:
            self._entities.append(sketch.clean_entity(entity))
        self._refresh(chosen=len(self._entities) - 1 if new else self.chosen_row())

    def finish_line(self) -> None:
        self.drawer.finish()
        self._refresh(chosen=self.chosen_row())

    def keyPressEvent(self, event) -> None:
        # Esc ends the line being drawn, then stops drawing; it closes the
        # window only when nothing is being drawn.
        if event.key() == Qt.Key_Escape and self.drawing():
            if self.drawer.points:
                self.finish_line()
            else:
                self.set_drawing(False)
            return
        super().keyPressEvent(event)

    # --- Showing it --------------------------------------------------------------------

    def _refresh(self, chosen: int | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for entity in self._entities:
            self.list.addItem(sketch.describe(entity))
        if chosen is not None and 0 <= chosen < len(self._entities):
            self.list.setCurrentRow(chosen)
        self.list.blockSignals(False)
        self.status.setText(self.DRAW_PROMPT if self.drawing() else status_text(self._entities))
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(bool(self._entities))
        self._chosen_changed()

    def _chosen_changed(self) -> None:
        has_chosen = self.chosen_row() is not None
        self.change_button.setEnabled(has_chosen)
        self.remove_button.setEnabled(has_chosen)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.preview.set_content(self._entities, self.guides, self.drawer.points, self.chosen_row())

    def labels(self) -> list[str]:
        """Every piece of text this window shows (for the plain-language tests)."""
        texts = [self.windowTitle(), self.note.text(), self.status.text(), self.DRAW_PROMPT]
        for button in self.findChildren(QPushButton):
            texts += [button.text(), button.toolTip()]
        texts += [self.list.item(i).text() for i in range(self.list.count())]
        return texts


def edit_sketch(parent, title: str, entities=(), guides=(), note: str | None = None):
    """Show the sketch window; the curves drawn, or None if cancelled."""
    dialog = SketchDialog(parent, title, entities, guides, note)
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.entities()
    finally:
        dialog.deleteLater()


# --- Where a new sketch goes -----------------------------------------------------------

PLANE_CHOICES = [
    ("xy", "The workplane (flat, facing up)"),
    ("xz", "Upright, facing the front"),
    ("yz", "Upright, facing the right side"),
]
PLANE_NOTES = {
    "xy": "Drawn on the workplane: X is left to right, Y is front to back.",
    "xz": "Drawn upright, seen from the front: X is left to right, Y is height.",
    "yz": "Drawn upright, seen from the right: X is front to back, Y is height.",
}


def sketch_plane_fields():
    return [
        ("plane", "Draw on", "xy", {"choices": PLANE_CHOICES}),
        ("distance", "Move the plane forward along the way it faces (mm)", 0.0, COORD),
    ]


def ask_sketch_plane(parent) -> dict | None:
    return run_form(parent, "New sketch", sketch_plane_fields(),
                    note="Choose the flat plane to draw on. You can move or turn the sketch later.")
