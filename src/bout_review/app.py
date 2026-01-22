import sys
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


def main() -> None:
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("Bout-Review")
    win.setCentralWidget(QLabel("Bout-Review is running."))
    win.resize(600, 300)
    win.show()
    raise SystemExit(app.exec())
