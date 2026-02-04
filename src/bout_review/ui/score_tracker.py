from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .strings import AURA_STEP, ui_text

class ScoreTrackerWindow(QWidget):
    point_left = Signal()
    point_right = Signal()
    no_point = Signal()

    def __init__(self, parent=None, gen_z_mode: bool = False) -> None:
        super().__init__(parent, Qt.Window)
        self.gen_z_mode = bool(gen_z_mode)
        self.score_step = AURA_STEP if self.gen_z_mode else 1
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowTitle(ui_text(self.gen_z_mode, "score_tracker_title"))

        self.left_label = QLabel(ui_text(self.gen_z_mode, "score_left_label"))
        self.right_label = QLabel(ui_text(self.gen_z_mode, "score_right_label"))
        self.score_label = QLabel(ui_text(self.gen_z_mode, "score_label"))

        self.left_score_box = QSpinBox()
        self.left_score_box.setRange(0, 99999 if self.gen_z_mode else 999)
        self.left_score_box.setSingleStep(self.score_step)
        if self.gen_z_mode:
            self.left_score_box.setSuffix(" aura")
        self.left_score_box.setAlignment(Qt.AlignCenter)
        self.left_score_box.setStyleSheet("font-size: 18px; padding: 6px;")
        self.left_score_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.right_score_box = QSpinBox()
        self.right_score_box.setRange(0, 99999 if self.gen_z_mode else 999)
        self.right_score_box.setSingleStep(self.score_step)
        if self.gen_z_mode:
            self.right_score_box.setSuffix(" aura")
        self.right_score_box.setAlignment(Qt.AlignCenter)
        self.right_score_box.setStyleSheet("font-size: 18px; padding: 6px;")
        self.right_score_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.enable_score = QCheckBox(ui_text(self.gen_z_mode, "score_enable"))
        self.enable_score.setChecked(True)

        self.point_left_btn = QPushButton(
            ui_text(self.gen_z_mode, "score_point_left", step=self.score_step)
        )
        self.point_right_btn = QPushButton(
            ui_text(self.gen_z_mode, "score_point_right", step=self.score_step)
        )
        self.no_point_btn = QPushButton(ui_text(self.gen_z_mode, "score_no_point"))

        self.point_left_btn.clicked.connect(self.point_left.emit)
        self.point_right_btn.clicked.connect(self.point_right.emit)
        self.no_point_btn.clicked.connect(self.no_point.emit)

        grid = QGridLayout()
        grid.addWidget(self.left_label, 0, 0)
        grid.addWidget(self.score_label, 0, 1)
        grid.addWidget(self.right_label, 0, 2)
        grid.addWidget(self.left_score_box, 1, 0)
        grid.addWidget(self.enable_score, 1, 1, alignment=Qt.AlignCenter)
        grid.addWidget(self.right_score_box, 1, 2)

        buttons = QHBoxLayout()
        buttons.addWidget(self.point_left_btn)
        buttons.addWidget(self.no_point_btn)
        buttons.addWidget(self.point_right_btn)

        root = QVBoxLayout()
        root.addLayout(grid)
        root.addLayout(buttons)
        root.addStretch(1)
        self.setLayout(root)
        self.setFixedWidth(360)

    def reset_scores(self) -> None:
        self.left_score_box.setValue(0)
        self.right_score_box.setValue(0)

    def increment_left(self) -> None:
        self.left_score_box.setValue(self.left_score_box.value() + self.score_step)

    def increment_right(self) -> None:
        self.right_score_box.setValue(self.right_score_box.value() + self.score_step)

    def auto_score_enabled(self) -> bool:
        return self.enable_score.isChecked()

    def scores(self) -> tuple[int, int]:
        return self.left_score_box.value(), self.right_score_box.value()
