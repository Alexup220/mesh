"""The 3D view: grid, camera, shape actors, and click-to-select.

Holes are drawn translucent. That is the visual half of the Solid/Hole
idea — without it, marking a shape as a hole appears to do nothing.
"""

import numpy as np
import vtkmodules.qt

vtkmodules.qt.PyQtImpl = "PySide6"

# Importing only vtkmodules.vtkRenderingCore (below) gives you the ABSTRACT
# vtkRenderWindow / vtkPolyDataMapper classes: with the monolithic `vtk`
# package this concrete backend is wired up as a side effect of the
# package's own __init__, but with the split `vtkmodules` packages nothing
# registers a concrete OpenGL implementation with VTK's object factory
# unless this module is imported too. Skip it and vtkRenderWindow()
# silently instantiates the do-nothing base class instead of
# vtkXOpenGLRenderWindow: no error, no exception, just a window that
# reports "Not Implemented" for its capabilities and paints nothing --
# not even the background colour -- which is indistinguishable from a
# working renderer pointed at an empty scene. This import must happen
# before any vtkRenderWindow() is constructed.
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersSources import vtkLineSource, vtkPlaneSource
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkCellPicker,
    vtkPolyDataMapper,
    vtkPropPicker,
    vtkRenderer,
)

from mesh import guides
from mesh.scene import Scene
from mesh.shapes import hole_clearance, is_reference, shape_geometry
from mesh.sketch import sketch_lines

HOLE_OPACITY = 0.35
BACKGROUND = (0.16, 0.17, 0.20)
GRID_COLOR = (0.50, 0.53, 0.58)
MEASURE_COLOR = (1.0, 0.85, 0.2)
MEASURE_LINE_WIDTH = 4.0  # pixels
SELECTED_COLOR = (1.0, 0.85, 0.2)
# A guide (a sketch) is its curves, drawn as lines, over a faint shading of
# the area its closed outlines fill.
GUIDE_FILL_OPACITY = 0.18
GUIDE_LINE_WIDTH = 2.0
GUIDE_SELECTED_LINE_WIDTH = 3.5

VIEW_PRESETS = {
    "home": ((1.0, -1.0, 0.8), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
}


def _to_polydata(tm) -> vtkPolyData:
    points = vtkPoints()
    for vertex in tm.vertices:
        points.InsertNextPoint(*vertex)
    cells = vtkCellArray()
    for face in tm.faces:
        cells.InsertNextCell(3)
        for index in face:
            cells.InsertCellPoint(int(index))
    poly = vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(cells)
    return poly


def _lines_polydata(lines) -> vtkPolyData:
    """World-space polylines (a list of (N, 3) arrays) as VTK lines."""
    points = vtkPoints()
    cells = vtkCellArray()
    for line in lines:
        start = points.GetNumberOfPoints()
        for point in line:
            points.InsertNextPoint(*(float(v) for v in point))
        cells.InsertNextCell(len(line))
        for index in range(len(line)):
            cells.InsertCellPoint(start + index)
    poly = vtkPolyData()
    poly.SetPoints(points)
    poly.SetLines(cells)
    return poly


def _guide_lines(shape) -> list:
    """A guide's curves (a sketch's) or lines (a construction guide's) as
    world-space polylines."""
    transform = np.asarray(shape.transform, dtype=np.float64)
    kind = shape.params.get("primitive")
    if kind == "sketch":
        local = [np.column_stack([line, np.zeros(len(line))])
                 for line in sketch_lines(shape.params.get("entities", []))]
    else:
        local = guides.guide_lines(kind, shape.params)
    return [(np.column_stack([line, np.ones(len(line))]) @ transform.T)[:, :3] for line in local]


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _headless() -> bool:
    """True under the test suite's Qt "offscreen" platform.

    vtkXOpenGLRenderWindow (see the vtkRenderingOpenGL2 import above) talks
    to X11 directly through the native window id Qt hands it. Under the
    real "xcb" platform that id is a real X window and this works; under
    "offscreen" (what tests/conftest.py selects, precisely so the suite
    needs no display) there is no real X window behind that id, and
    Render() segfaults trying to use it. Tests exercise scene/selection
    logic, not pixels, so skipping the actual Render() call under
    "offscreen" keeps that logic exercised without touching X11 at all.
    """
    app = QApplication.instance()
    return app is not None and app.platformName() == "offscreen"


class Viewport(QWidget):
    picked = Signal(str, bool)
    # (shape id or "", triangle index or -1, world point (x, y, z)) -- sent
    # instead of `picked` while a surface tool (Lay flat, Place on face,
    # Measure) is waiting for a click on a part.
    surface_picked = Signal(str, int, object)

    def _render(self) -> None:
        if _headless():
            return
        self._widget.GetRenderWindow().Render()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene: Scene | None = None
        self._actors: dict[str, vtkActor] = {}
        # A guide's (sketch's) curves, drawn as lines beside its shading.
        self._outlines: dict[str, vtkActor] = {}
        # What each actor's polydata was last built from. shape_geometry()
        # runs a per-vertex Python loop to build a vtkPolyData -- rebuilding
        # every actor on every refresh() call (e.g. once per keystroke while
        # editing a field on a DIFFERENT shape) is wasted work when a
        # shape's own parameters and transform have not changed since the
        # last rebuild.
        self._geometry_keys: dict[str, tuple] = {}

        # QVTKRenderWindowInteractor is a "native"/foreign-window widget
        # (WA_PaintOnScreen); Qt's layout engine treats its sizeHint()
        # (400x400) as authoritative unless it is explicitly told to claim
        # all remaining space. Both of the following are required: the
        # Expanding size policy on this container so QMainWindow's central
        # widget actually grows to the full central area, and the stretch
        # factor on addWidget so the child widget is stretched to fill this
        # container rather than sitting at its sizeHint in a corner.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._widget = QVTKRenderWindowInteractor(self)
        self._widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._widget, 1)

        self.renderer = vtkRenderer()
        self.renderer.SetBackground(*BACKGROUND)
        self._widget.GetRenderWindow().AddRenderer(self.renderer)

        # A second layer drawn on top of the parts, sharing their camera,
        # for the Measure line. Its two points are on a part's surface, so
        # the line lies on or inside the part: in the parts' own layer it
        # was hidden inside them or fought with the surface down to a 1 px
        # sliver.
        window = self._widget.GetRenderWindow()
        window.SetNumberOfLayers(2)
        self.overlay = vtkRenderer()
        self.overlay.SetLayer(1)
        self.overlay.InteractiveOff()
        self.overlay.SetActiveCamera(self.renderer.GetActiveCamera())
        window.AddRenderer(self.overlay)

        self.interactor = self._widget.GetRenderWindow().GetInteractor()
        self.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
        self.interactor.AddObserver("LeftButtonPressEvent", self._on_click)

        self._picker = vtkPropPicker()
        self._cell_picker = vtkCellPicker()
        self._cell_picker.SetTolerance(0.0005)
        # None for normal click-to-select; any other value means the next
        # click on a part is reported through surface_picked instead.
        self.pick_mode: str | None = None
        # The Measure tool's line between its two clicked points, or None.
        self.measure_actor: vtkActor | None = None
        self._add_grid()
        # Position the camera now, but do NOT call Render() here: the
        # widget's native window is not mapped yet (this runs during
        # MeshWindow.__init__, well before show()/start()). VTK creates its
        # OpenGL context/framebuffer on first Render(); doing that against
        # an unmapped, zero-size native window leaves VTK permanently
        # rendering into a dead surface, which shows up as a solid black
        # viewport forever after — the window manager background colour
        # never even gets a chance to be cleared onto it. The real first
        # Render() happens in start(), after show() and Initialize().
        self._apply_view("home")

    def _apply_view(self, name: str) -> None:
        direction, up = VIEW_PRESETS[name]
        camera = self.renderer.GetActiveCamera()
        camera.SetFocalPoint(0.0, 0.0, 0.0)
        camera.SetPosition(*(np.array(direction) * 200.0))
        camera.SetViewUp(*up)
        self.renderer.ResetCamera()

    def _add_grid(self) -> None:
        plane = vtkPlaneSource()
        plane.SetOrigin(-110.0, -110.0, 0.0)
        plane.SetPoint1(110.0, -110.0, 0.0)
        plane.SetPoint2(-110.0, 110.0, 0.0)
        plane.SetResolution(22, 22)
        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(plane.GetOutputPort())
        grid = vtkActor()
        grid.SetMapper(mapper)
        grid.GetProperty().SetRepresentationToWireframe()
        grid.GetProperty().SetColor(*GRID_COLOR)
        grid.GetProperty().SetLineWidth(1.25)
        grid.PickableOff()
        self.renderer.AddActor(grid)

    def set_scene(self, scene: Scene) -> None:
        self._scene = scene

    def actor_for(self, shape_id: str):
        return self._actors.get(shape_id)

    def _geometry_key(self, shape) -> tuple:
        """A cheap fingerprint of everything that changes a shape's
        triangles: its kind, its params, and its transform. Two calls with
        an equal key are guaranteed to produce the same polydata."""
        transform = np.asarray(shape.transform, dtype=np.float64)
        clearance = hole_clearance(shape, self._clearances())
        return (shape.kind, repr(shape.params), transform.tobytes(), clearance)

    def _clearances(self) -> dict | None:
        return getattr(self._scene, "fit_clearances", None)

    def refresh(self) -> None:
        if self._scene is None:
            return

        wanted = {s.id for s in self._scene.shapes if s.visible}
        for shape_id in list(self._actors):
            if shape_id not in wanted:
                self.renderer.RemoveActor(self._actors.pop(shape_id))
                self._geometry_keys.pop(shape_id, None)
        guides = {s.id for s in self._scene.shapes if s.visible and is_reference(s)}
        for shape_id in list(self._outlines):
            if shape_id not in guides:
                self.renderer.RemoveActor(self._outlines.pop(shape_id))

        selected = set(self._scene.selection)
        for shape in self._scene.shapes:
            if not shape.visible:
                continue
            actor = self._actors.get(shape.id)
            if actor is None:
                actor = vtkActor()
                actor.SetMapper(vtkPolyDataMapper())
                self._actors[shape.id] = actor
                self.renderer.AddActor(actor)

            key = self._geometry_key(shape)
            changed = self._geometry_keys.get(shape.id) != key
            if changed:
                actor.GetMapper().SetInputData(
                    _to_polydata(shape_geometry(shape, self._clearances()))
                )
                self._geometry_keys[shape.id] = key

            if is_reference(shape):
                self._refresh_guide(shape, actor, shape.id in selected, changed)
                continue

            prop = actor.GetProperty()
            prop.SetColor(*_hex_to_rgb(shape.color))
            prop.SetOpacity(HOLE_OPACITY if shape.is_hole else 1.0)
            prop.SetEdgeVisibility(shape.id in selected)
            prop.SetEdgeColor(1.0, 0.85, 0.2)
            prop.SetLineWidth(2.0)

        self._render()

    def _refresh_guide(self, shape, shading: vtkActor, selected: bool, changed: bool) -> None:
        """A guide is faint shading plus its curves as lines, yellow and
        thicker while selected."""
        color = _hex_to_rgb(shape.color)
        prop = shading.GetProperty()
        prop.SetColor(*color)
        prop.SetOpacity(GUIDE_FILL_OPACITY)
        prop.SetEdgeVisibility(False)
        prop.LightingOff()
        outline = self._outlines.get(shape.id)
        if outline is None:
            outline = vtkActor()
            outline.SetMapper(vtkPolyDataMapper())
            outline.GetProperty().LightingOff()
            self._outlines[shape.id] = outline
            self.renderer.AddActor(outline)
            changed = True
        if changed:
            outline.GetMapper().SetInputData(_lines_polydata(_guide_lines(shape)))
        line = outline.GetProperty()
        line.SetColor(*(SELECTED_COLOR if selected else color))
        line.SetLineWidth(GUIDE_SELECTED_LINE_WIDTH if selected else GUIDE_LINE_WIDTH)

    def outline_for(self, shape_id: str):
        """A guide's line actor (its curves), or None."""
        return self._outlines.get(shape_id)

    def _shape_hit(self, actor) -> str | None:
        for shape_id, candidate in self._actors.items():
            if candidate is actor:
                return shape_id
        for shape_id, candidate in self._outlines.items():
            if candidate is actor:
                return shape_id
        return None

    def end_drag(self) -> None:
        """Forget a mouse button held down in the 3D view, before a window
        opens on top of it and takes the button's release."""
        self.interactor.GetInteractorStyle().OnLeftButtonUp()

    def set_pick_mode(self, mode: str | None) -> None:
        self.pick_mode = mode

    def _on_click(self, interactor, _event) -> None:
        x, y = interactor.GetEventPosition()
        if self.pick_mode is not None:
            self._on_surface_click(x, y)
            return
        self._picker.Pick(x, y, 0, self.renderer)
        hit = self._picker.GetActor()
        additive = bool(interactor.GetShiftKey())
        shape_id = self._shape_hit(hit) if hit is not None else None
        self.picked.emit(shape_id or "", additive)

    def _on_surface_click(self, x: int, y: int) -> None:
        self._cell_picker.Pick(x, y, 0, self.renderer)
        hit = self._cell_picker.GetActor()
        point = tuple(float(v) for v in self._cell_picker.GetPickPosition())
        for shape_id, actor in self._actors.items():
            if actor is hit:
                self.surface_picked.emit(shape_id, int(self._cell_picker.GetCellId()), point)
                return
        self.surface_picked.emit("", -1, point)

    def set_measure_line(self, a, b) -> None:
        """Draw (or move) the Measure tool's line from a to b."""
        if self.measure_actor is None:
            self._measure_source = vtkLineSource()
            mapper = vtkPolyDataMapper()
            mapper.SetInputConnection(self._measure_source.GetOutputPort())
            actor = vtkActor()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(*MEASURE_COLOR)
            # Drawn as a flat-coloured tube a few pixels wide: plain wide
            # lines are not supported by every graphics driver.
            prop.SetLineWidth(MEASURE_LINE_WIDTH)
            prop.SetRenderLinesAsTubes(True)
            prop.LightingOff()
            actor.PickableOff()
            self.overlay.AddActor(actor)
            self.measure_actor = actor
        self._measure_source.SetPoint1(*(float(v) for v in a))
        self._measure_source.SetPoint2(*(float(v) for v in b))
        self._measure_source.Update()
        self._render()

    def clear_measure_line(self) -> None:
        if self.measure_actor is not None:
            self.overlay.RemoveActor(self.measure_actor)
            self.measure_actor = None
            self._render()

    def view_preset(self, name: str) -> None:
        if name not in VIEW_PRESETS:
            raise ValueError(f"unknown view {name!r}; expected one of {tuple(VIEW_PRESETS)}")
        self._apply_view(name)
        self._render()

    def frame_selection(self) -> None:
        if self._scene is None:
            return
        chosen = [self._outlines.get(s.id) or self._actors[s.id]
                  for s in self._scene.selected() if s.id in self._actors]
        if not chosen:
            self.renderer.ResetCamera()
        else:
            bounds = np.array([a.GetBounds() for a in chosen])
            self.renderer.ResetCamera(
                bounds[:, 0].min(), bounds[:, 1].max(),
                bounds[:, 2].min(), bounds[:, 3].max(),
                bounds[:, 4].min(), bounds[:, 5].max(),
            )
        self._render()

    def start(self) -> None:
        """Call once after the window is shown."""
        if _headless():
            return
        self.interactor.Initialize()
        # First real Render(): the native window is mapped now, so VTK can
        # create a valid OpenGL context/framebuffer against it. See the
        # comment in __init__ for why this must not happen any earlier.
        self._render()
