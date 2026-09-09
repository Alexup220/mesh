"""Visual styling.

VTK and stock Qt both look like 2009 lab software by default. A flat dark
palette with generous hit targets is what stops mesh feeling like one.
"""

STYLESHEET = """
QMainWindow, QWidget { background: #23262b; color: #e6e8ea; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title {
    background: #1b1e22; padding: 8px; font-weight: 600;
}
QPushButton {
    background: #2f343b; border: 1px solid #3d434b; border-radius: 6px;
    padding: 10px 12px; font-size: 13px;
}
QPushButton:hover { background: #3a4049; border-color: #5b8fd4; }
QPushButton:pressed { background: #4a90d9; color: #ffffff; }
QDoubleSpinBox {
    background: #1b1e22; border: 1px solid #3d434b; border-radius: 4px;
    padding: 5px; min-width: 90px;
}
QDoubleSpinBox:focus { border-color: #4a90d9; }
QCheckBox { padding: 6px 0; }
QLabel { color: #a9b1ba; }
QMenuBar, QMenu { background: #1b1e22; }
QMenu::item:selected, QMenuBar::item:selected { background: #4a90d9; }
QStatusBar { background: #1b1e22; color: #cfd6dd; padding: 4px; }
"""


def apply_theme(app) -> None:
    app.setStyleSheet(STYLESHEET)
