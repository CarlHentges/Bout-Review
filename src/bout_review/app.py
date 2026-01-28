from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Bout Review")
    app.setApplicationDisplayName("Bout Review")
    app.setApplicationVersion("1.3.0")
    icon_path = Path(__file__).resolve().parent / "assets" / "bout_review_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
