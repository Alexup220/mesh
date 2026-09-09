import os

import pytest

# Force (not setdefault) offscreen: some dev machines export
# QT_QPA_PLATFORM=wayland;xcb globally (Hyprland does), which already
# "counts" as set and would silently defeat setdefault, leaving the suite
# running against a real windowing platform. mesh/viewport.py imports
# vtkmodules.vtkRenderingOpenGL2 so the viewport can actually render in the
# real app; that backend talks to X11 directly through the native window
# id Qt hands it, and under any platform other than offscreen/xcb that id
# doesn't point at a usable window, which segfaults the moment a test
# calls Render() (see Viewport._render / _headless in mesh/viewport.py).
# The suite only exercises scene/selection logic, never pixels, so it
# must run under a platform with no real window at all.
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def close_qt_widget(qapp):
    """Register widgets for explicit teardown after the test.

    Without this, QVTKRenderWindowInteractor widgets built during a test are
    left for the garbage collector and get reaped in a half-finalized state
    at interpreter shutdown, each printing a ~981-frame RecursionError
    traceback. Registering a widget here closes it, schedules its deletion,
    and flushes the event queue so Qt actually releases it while the test
    result is still clean. Any fixture that constructs a QWidget (Viewport
    and friends in Tasks 11-14) should route it through this instead of
    returning a bare constructor.
    """
    widgets = []

    def register(widget):
        widgets.append(widget)
        return widget

    yield register

    for widget in widgets:
        widget.close()
        widget.deleteLater()
    qapp.processEvents()
