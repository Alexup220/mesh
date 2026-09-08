import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
