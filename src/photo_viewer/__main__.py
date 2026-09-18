import sys

from PySide6.QtWidgets import QApplication

from photo_viewer.i18n import translator
from photo_viewer.ui.main_window import MainWindow
from photo_viewer.ui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("PhotoViewer")
    app.setApplicationName("PhotoViewer")
    translator.load()
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
