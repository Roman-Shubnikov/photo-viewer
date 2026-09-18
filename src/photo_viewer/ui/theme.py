from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BACKGROUND = QColor("#121316")
SURFACE = QColor("#1c1e23")
TEXT = QColor("#e8e9ec")
MUTED = QColor("#8b8f98")
ACCENT = QColor("#4c8dff")
PLACEHOLDER = QColor("#25272d")

_STYLESHEET = """
QToolBar { background: #1c1e23; border: none; padding: 6px; spacing: 8px; }
QToolButton { color: #e8e9ec; padding: 6px 12px; border-radius: 6px; }
QToolButton:hover { background: #2a2d34; }
QMenu { background: #1c1e23; color: #e8e9ec; border: 1px solid #343841; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 4px; }
QMenu::item:selected { background: #2a2d34; }
QSlider::groove:horizontal { height: 4px; background: #343841; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4c8dff; border-radius: 2px; }
QSlider::handle:horizontal { background: #e8e9ec; width: 12px; margin: -4px 0; border-radius: 6px; }
QListView { background: #121316; border: none; outline: none; }
QStatusBar { background: #1c1e23; color: #8b8f98; }
QPushButton { background: #2a2d34; color: #e8e9ec; border: none; border-radius: 6px; padding: 8px 16px; }
QPushButton:hover { background: #343841; }
QPushButton:disabled { color: #6a6e77; }
QPushButton#primary { background: #4c8dff; color: white; }
QPushButton#primary:hover { background: #6aa0ff; }
QPushButton#primary:disabled { background: #2f4670; color: #9aa7bf; }
QLineEdit { background: #25272d; color: #e8e9ec; border: 1px solid #343841; border-radius: 6px; padding: 6px 8px; }
QProgressBar { background: #25272d; border: none; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #4c8dff; border-radius: 4px; }
QLabel#muted { color: #8b8f98; }
QLabel#error { color: #ff7a7a; }
QLabel#warning { color: #ffc35c; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, SURFACE)
    palette.setColor(QPalette.ColorRole.WindowText, TEXT)
    palette.setColor(QPalette.ColorRole.Base, BACKGROUND)
    palette.setColor(QPalette.ColorRole.Text, TEXT)
    palette.setColor(QPalette.ColorRole.Button, SURFACE)
    palette.setColor(QPalette.ColorRole.ButtonText, TEXT)
    palette.setColor(QPalette.ColorRole.Highlight, ACCENT)
    app.setPalette(palette)
    app.setStyleSheet(_STYLESHEET)
