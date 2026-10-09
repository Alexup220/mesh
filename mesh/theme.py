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


def stylesheet_for(tokens: dict) -> str:
    """The widgets the QML front end still shows (dock titles, message
    boxes, file and colour choosers, the sketch window) in a theme's
    colours (see mesh.themes)."""
    t = tokens
    return f"""
QMainWindow, QDialog, QMessageBox, QWidget {{ background: {t['background']}; color: {t['text']}; }}
QMainWindow::separator {{ background: {t['border']}; width: 3px; height: 3px; }}
QMainWindow::separator:hover {{ background: {t['accent']}; }}
QDockWidget {{ color: {t['text']}; }}
QDockWidget::title {{
    background: {t['panel']}; padding: 6px 8px; font-weight: 600;
    border-bottom: 1px solid {t['border']};
}}
QToolBar {{ background: {t['panel']}; border: none; padding: 0; spacing: 0; }}
QTabBar::tab {{
    background: {t['panel']}; color: {t['text']}; padding: 6px 12px;
    border: 1px solid {t['border']}; border-bottom: none;
}}
QTabBar::tab:selected {{ border-top: 2px solid {t['accent']}; }}
QTabBar::tab:hover {{ background: {t['background']}; }}
QPushButton {{
    background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 6px;
    padding: 8px 12px; color: {t['text']};
}}
QPushButton:hover {{ border-color: {t['accent']}; }}
QPushButton:pressed, QPushButton:checked {{ background: {t['accent']}; }}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QListWidget {{
    background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 4px;
    padding: 4px; color: {t['text']};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
QMenu {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; }}
QMenu::item:selected {{ background: {t['accent']}; }}
QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; }}
QLabel {{ color: {t['text']}; background: transparent; }}
"""
