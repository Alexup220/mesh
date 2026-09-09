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
from vtkmodules.vtkFiltersSources import vtkPlaneSource
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkPropPicker,
    vtkRenderer,
)

from mesh.scene import Scene
from mesh.shapes import shape_geometry

HOLE_OPACITY = 0.35
BACKGROUND = (0.16, 0.17, 0.20)
GRID_COLOR = (0.32, 0.34, 0.38)

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

    def _render(self) -> None:
        if _headless():
            return
        self._widget.GetRenderWindow().Render()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene: Scene | None = None
        self._actors: dict[str, vtkActor] = {}

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

        self.interactor = self._widget.GetRenderWindow().GetInteractor()
        self.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
        self.interactor.AddObserver("LeftButtonPressEvent", self._on_click)

        self._picker = vtkPropPicker()
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
        grid.PickableOff()
        self.renderer.AddActor(grid)

    def set_scene(self, scene: Scene) -> None:
        self._scene = scene

    def actor_for(self, shape_id: str):
        return self._actors.get(shape_id)

    def refresh(self) -> None:
        if self._scene is None:
            return

        wanted = {s.id for s in self._scene.shapes if s.visible}
        for shape_id in list(self._actors):
            if shape_id not in wanted:
                self.renderer.RemoveActor(self._actors.pop(shape_id))

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
            actor.GetMapper().SetInputData(_to_polydata(shape_geometry(shape)))

            prop = actor.GetProperty()
            prop.SetColor(*_hex_to_rgb(shape.color))
            prop.SetOpacity(HOLE_OPACITY if shape.is_hole else 1.0)
            prop.SetEdgeVisibility(shape.id in selected)
            prop.SetEdgeColor(1.0, 0.85, 0.2)
            prop.SetLineWidth(2.0)

        self._render()

    def _on_click(self, interactor, _event) -> None:
        x, y = interactor.GetEventPosition()
        self._picker.Pick(x, y, 0, self.renderer)
        hit = self._picker.GetActor()
        additive = bool(interactor.GetShiftKey())
        for shape_id, actor in self._actors.items():
            if actor is hit:
                self.picked.emit(shape_id, additive)
                return
        self.picked.emit("", additive)

    def view_preset(self, name: str) -> None:
        if name not in VIEW_PRESETS:
            raise ValueError(f"unknown view {name!r}; expected one of {tuple(VIEW_PRESETS)}")
        self._apply_view(name)
        self._render()

    def frame_selection(self) -> None:
        if self._scene is None:
            return
        chosen = [self._actors[s.id] for s in self._scene.selected() if s.id in self._actors]
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
