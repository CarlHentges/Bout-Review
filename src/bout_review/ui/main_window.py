from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QObject,
    Signal,
    QThread,
    QEvent,
    QPoint,
    QFileSystemWatcher,
)
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QComboBox,
    QScrollArea,
    QToolButton,
    QWidget,
)

from ..core.importer import import_media_files
from ..core.models import Note, Project, Segment, generate_id
from ..core.project_io import create_project, load_project, save_project
from ..ffmpeg.exporter import (
    build_timeline,
    chapter_lines_with_warnings,
    export_project,
    export_slices,
    ExportResult,
)
from ..utils.config import load_config, config_path
from ..utils.timecode import to_timestamp
from .timeline_slider import NoteMarker, SegmentMarker, TimelineSlider
from .score_tracker import ScoreTrackerWindow
from .strings import AURA_STEP, WARNING_MAP, note_type_label, ui_text
from .theme import GENZ_THEME, gen_z_colors, gen_z_stylesheet


class SegmentDialog(QDialog):
    def __init__(
        self,
        parent,
        title: str,
        start: float,
        end: float,
        label: str,
        speed: float,
        max_duration: float | None,
        gen_z_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.gen_z_mode = bool(gen_z_mode)
        self.setWindowTitle(title)
        self.setModal(True)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.05)
        self.start_spin.setRange(0.0, max(0.0, max_duration or 10_000.0))
        self.start_spin.setValue(max(0.0, start))

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setDecimals(3)
        self.end_spin.setSingleStep(0.05)
        self.end_spin.setRange(0.0, max(0.0, max_duration or 10_000.0))
        self.end_spin.setValue(max(0.0, end))

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setDecimals(3)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setRange(0.1, 8.0)
        self.speed_spin.setValue(max(0.1, speed))

        self.label_edit = QLineEdit(label)

        form = QFormLayout()
        form.addRow(ui_text(self.gen_z_mode, "segment_form_start"), self.start_spin)
        form.addRow(ui_text(self.gen_z_mode, "segment_form_end"), self.end_spin)
        form.addRow(ui_text(self.gen_z_mode, "segment_form_label"), self.label_edit)
        form.addRow(ui_text(self.gen_z_mode, "segment_form_speed"), self.speed_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def accept(self) -> None:
        if self.end_spin.value() <= self.start_spin.value():
            QMessageBox.warning(
                self,
                ui_text(self.gen_z_mode, "dialog_invalid_segment_title"),
                ui_text(self.gen_z_mode, "dialog_invalid_segment_msg"),
            )
            return
        super().accept()

    def values(self) -> tuple[float, float, str, float]:
        return (
            float(self.start_spin.value()),
            float(self.end_spin.value()),
            self.label_edit.text().strip(),
            float(self.speed_spin.value()),
        )


class NoteDialog(QDialog):
    def __init__(
        self,
        parent,
        title: str,
        timestamp: float,
        note_type: str,
        text: str,
        gen_z_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.gen_z_mode = bool(gen_z_mode)
        self.setWindowTitle(title)
        self.setModal(True)

        self.time_spin = QDoubleSpinBox()
        self.time_spin.setDecimals(3)
        self.time_spin.setRange(0.0, 1e9)
        self.time_spin.setSingleStep(0.1)
        self.time_spin.setValue(max(0.0, timestamp))

        self.type_combo = QComboBox()
        self.type_combo.addItem(ui_text(self.gen_z_mode, "note_type_comment"), "comment")
        self.type_combo.addItem(ui_text(self.gen_z_mode, "note_type_chapter"), "chapter")
        idx = self.type_combo.findData(note_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        self.text_edit = QLineEdit(text)

        form = QFormLayout()
        form.addRow(ui_text(self.gen_z_mode, "note_form_timestamp"), self.time_spin)
        form.addRow(ui_text(self.gen_z_mode, "note_form_type"), self.type_combo)
        form.addRow(ui_text(self.gen_z_mode, "note_form_text"), self.text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def values(self) -> tuple[float, str, str]:
        note_type = self.type_combo.currentData()
        if note_type is None:
            note_type = self.type_combo.currentText()
        return (
            float(self.time_spin.value()),
            note_type,
            self.text_edit.text().strip(),
        )


class ToolbarOverflowDialog(QDialog):
    closed = Signal()

    def __init__(self, parent: QWidget, actions: list[QAction], gen_z_mode: bool) -> None:
        super().__init__(parent, Qt.Tool)
        self.setModal(False)
        self.setWindowTitle("Toolbar")

        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(6)

        for action in actions:
            btn = QToolButton(container)
            btn.setDefaultAction(action)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setAutoRaise(False)
            if gen_z_mode:
                btn.setStyleSheet(
                    "background-color: #ff4fd8;"
                    "color: #000000;"
                    "border: 2px solid #000000;"
                    "border-radius: 6px;"
                    "padding: 6px 10px;"
                )
            container_layout.addWidget(btn)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        self.resize(260, 360)
        self.setMinimumSize(220, 220)
        if gen_z_mode:
            self.setStyleSheet(gen_z_stylesheet())

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit()


class ExportWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(ExportResult)
    error = Signal(str)

    def __init__(self, project: Project, slices: list, fast_forward: bool, gap_speed: float) -> None:
        super().__init__()
        self.project = project
        self.slices = slices
        self.fast_forward = fast_forward
        self.gap_speed = gap_speed

    def run(self) -> None:
        try:
            total_steps = len(self.slices) + 2  # clips + concat + text files

            def cb(done: int, msg: str) -> None:
                self.progress.emit(done, msg)

            result = export_project(
                self.project,
                fast_forward_gaps=self.fast_forward,
                gap_speed=self.gap_speed,
                slices=self.slices,
                progress_cb=cb,
                cancel_cb=lambda: self.thread().isInterruptionRequested(),
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.gen_z_mode = bool(self.config.get("gen_z_mode", False))
        self.score_step = AURA_STEP if self.gen_z_mode else 1
        self.setWindowTitle(ui_text(self.gen_z_mode, "window_title"))
        self.resize(1100, 720)
        self.hotkeys = self.config.get("hotkeys", {})
        self.colors = self.config.get("colors", {})
        if self.gen_z_mode:
            self.colors = dict(self.colors) | gen_z_colors()
        self.timeline_config = self.config.get("timeline", {})
        self.audio_config = self.config.get("audio", {})
        self.scrub_config = self.config.get("scrub", {})
        self.export_config = self.config.get("export", {})
        self._config_path = config_path()
        self._config_watcher = QFileSystemWatcher(self)
        self._config_reload_timer = QTimer(self)
        self._config_reload_timer.setSingleShot(True)
        self._config_reload_timer.timeout.connect(self._reload_config)

        self.project: Project | None = None
        self.current_media_id: str | None = None
        self.mark_in_time: float | None = None
        self.score_tracker: ScoreTrackerWindow | None = None
        self.export_gap_ff_enabled: bool = bool(
            self.export_config.get("fast_forward_gaps_enabled", False)
        )
        self.export_gap_speed: float = max(1.0, float(self.export_config.get("gap_speed", 3.0)))
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self._export_total_steps: int = 0
        self._toolbar_actions: list[QAction] = []
        self._toolbar_ext_button: QToolButton | None = None
        self._toolbar_overflow: ToolbarOverflowDialog | None = None
        self._toolbar: QToolBar | None = None
        self._action_map: dict[str, QAction] = {}
        self._last_touch_side: str | None = None
        self._touch_streak: int = 0
        self.video_list_label: QLabel | None = None
        self.gap_speed_label: QLabel | None = None

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(bool(self.audio_config.get("default_muted", True)))
        self.audio.setVolume(float(self.audio_config.get("volume", 0.8)))
        self.player.setAudioOutput(self.audio)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)
        self._scrub_restore_muted = self.audio.isMuted()
        self._scrub_restore_play = False

        self.position_slider = TimelineSlider(Qt.Horizontal)
        self.position_slider.setEnabled(False)
        self.position_label = QLabel("00:00 / 00:00")
        self.gap_ff_button = QPushButton()
        self.gap_ff_button.setCheckable(True)
        self.gap_ff_button.setChecked(self.export_gap_ff_enabled)
        self.gap_ff_button.clicked.connect(self._toggle_gap_fast_forward)
        self.gap_speed_spin = QDoubleSpinBox()
        self.gap_speed_spin.setDecimals(2)
        self.gap_speed_spin.setRange(1.0, 10.0)
        self.gap_speed_spin.setSingleStep(0.25)
        self.gap_speed_spin.setValue(self.export_gap_speed)
        self.gap_speed_spin.valueChanged.connect(self._on_gap_speed_changed)
        self.instructions_label = QLabel()
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setStyleSheet("padding: 8px;")
        self.instructions_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.video_list = QListWidget()
        self.video_list.setDragEnabled(True)
        self.video_list.setAcceptDrops(True)
        self.video_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.video_list.setDefaultDropAction(Qt.MoveAction)
        self.video_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.remove_video_button = QPushButton(self._t("button_remove_video"))
        self.remove_video_button.clicked.connect(self._remove_video)
        self.segment_list = QListWidget()
        self.notes_list = QListWidget()
        self.import_button = QPushButton(self._t("button_import_videos"))
        self.import_button.clicked.connect(self._import_videos)
        self.import_button.setEnabled(False)
        self.segment_label = QLabel(self._t("label_segments", mark_in_key="I", mark_out_key="O"))
        self.mark_in_indicator = QLabel(self._t("mark_indicator_off"))
        self._set_mark_indicator(False)
        self.segment_edit_button = QPushButton(self._t("button_edit_segment"))
        self.segment_delete_button = QPushButton(self._t("button_delete_segment"))
        self.segment_duplicate_button = QPushButton(self._t("button_duplicate_segment"))
        self.segment_edit_button.clicked.connect(self._edit_segment)
        self.segment_delete_button.clicked.connect(self._delete_segment)
        self.segment_duplicate_button.clicked.connect(self._duplicate_segment)
        self.note_label = QLabel(self._t("label_notes"))
        self.note_edit_button = QPushButton(self._t("button_edit_note"))
        self.note_delete_button = QPushButton(self._t("button_delete_note"))
        self.note_edit_button.clicked.connect(self._edit_note)
        self.note_delete_button.clicked.connect(self._delete_note)

        self._build_ui()
        self._build_actions()
        self._connect_signals()
        self._apply_timeline_config()
        self._sync_hotkey_labels()
        self._sync_mute_action_text()
        self.gap_speed_spin.setEnabled(self.export_gap_ff_enabled)
        self._sync_gap_ff_button_text()
        self._apply_window_icon()
        if self.gen_z_mode:
            self._apply_gen_z_theme()
        self._init_config_watcher()

    # UI setup -----------------------------------------------------------------
    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        self.video_list_label = QLabel(self._t("label_videos"))
        left_layout.addWidget(self.video_list_label)
        left_layout.addWidget(self.video_list)
        left_layout.addWidget(self.remove_video_button)
        left_layout.addWidget(self.import_button)
        left_layout.addWidget(self.segment_label)
        left_layout.addWidget(self.mark_in_indicator)
        left_layout.addWidget(self.segment_list)
        segment_buttons = QHBoxLayout()
        segment_buttons.addWidget(self.segment_edit_button)
        segment_buttons.addWidget(self.segment_duplicate_button)
        segment_buttons.addWidget(self.segment_delete_button)
        left_layout.addLayout(segment_buttons)
        left_layout.addWidget(self.note_label)
        left_layout.addWidget(self.notes_list)
        note_buttons = QHBoxLayout()
        note_buttons.addWidget(self.note_edit_button)
        note_buttons.addWidget(self.note_delete_button)
        left_layout.addLayout(note_buttons)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.video_widget, 6)
        right_layout.addWidget(self.position_slider, 0)
        right_layout.addWidget(self.position_label, 0)
        gap_ff_row = QHBoxLayout()
        gap_ff_row.addWidget(self.gap_ff_button)
        self.gap_speed_label = QLabel(self._t("label_gap_speed"))
        gap_ff_row.addWidget(self.gap_speed_label)
        gap_ff_row.addWidget(self.gap_speed_spin)
        gap_ff_row.addStretch()
        right_layout.addLayout(gap_ff_row, 0)
        right_layout.addWidget(self.instructions_label, 1)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 3)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

    def _build_actions(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        new_action = QAction(self._t("action_new_project"), self, triggered=self._new_project)
        open_action = QAction(self._t("action_open_project"), self, triggered=self._open_project)
        import_action = QAction(self._t("action_import_videos"), self, triggered=self._import_videos)
        export_action = QAction(self._t("action_export"), self, triggered=self._export)
        open_exports_action = QAction(
            self._t("action_open_exports"), self, triggered=self._open_exports_folder
        )
        open_config_action = QAction(self._t("action_open_config"), self, triggered=self._open_config_file)
        play_action = QAction(self._t("action_play_pause"), self, triggered=self._toggle_play)
        self.mute_action = QAction(
            self._t("action_mute_audio"), self, checkable=True, triggered=self._toggle_mute
        )
        self.mute_action.setChecked(self.audio.isMuted())
        mark_in_action = QAction(self._t("action_mark_in"), self, triggered=self._mark_in)
        mark_out_action = QAction(self._t("action_mark_out"), self, triggered=self._mark_out)
        comment_action = QAction(
            self._t("action_add_comment"), self, triggered=lambda: self._add_note("comment")
        )
        chapter_action = QAction(
            self._t("action_add_chapter"), self, triggered=lambda: self._add_note("chapter")
        )
        score_action = QAction(self._t("action_score_tracker"), self, triggered=self._open_score_tracker)
        scrub_back_action = QAction(
            self._t("action_scrub_back"), self, triggered=lambda: self._scrub_seconds(-1)
        )
        scrub_forward_action = QAction(
            self._t("action_scrub_forward"), self, triggered=lambda: self._scrub_seconds(1)
        )
        scrub_frame_back_action = QAction(
            self._t("action_scrub_frame_back"), self, triggered=lambda: self._scrub_frames(-1)
        )
        scrub_frame_forward_action = QAction(
            self._t("action_scrub_frame_forward"), self, triggered=lambda: self._scrub_frames(1)
        )

        action_map = {
            "new_project": new_action,
            "open_project": open_action,
            "import_videos": import_action,
            "export": export_action,
            "open_exports": open_exports_action,
            "open_config": open_config_action,
            "play_pause": play_action,
            "mute_audio": self.mute_action,
            "mark_in": mark_in_action,
            "mark_out": mark_out_action,
            "add_comment": comment_action,
            "add_chapter": chapter_action,
            "score_tracker": score_action,
            "scrub_back": scrub_back_action,
            "scrub_forward": scrub_forward_action,
            "scrub_frame_back": scrub_frame_back_action,
            "scrub_frame_forward": scrub_frame_forward_action,
        }
        self._action_map = action_map
        self._apply_hotkeys(action_map)
        self._apply_tooltips(action_map)

        for action in [
            scrub_back_action,
            scrub_forward_action,
            scrub_frame_back_action,
            scrub_frame_forward_action,
        ]:
            action.setShortcutContext(Qt.WindowShortcut)
            self.addAction(action)

        self._toolbar_actions = [
            new_action,
            open_action,
            import_action,
            export_action,
            open_exports_action,
            open_config_action,
            play_action,
            self.mute_action,
            mark_in_action,
            mark_out_action,
            comment_action,
            chapter_action,
            score_action,
        ]
        for action in self._toolbar_actions:
            toolbar.addAction(action)
        QTimer.singleShot(0, self._wire_toolbar_extension_button)

    def _connect_signals(self) -> None:
        self.video_list.itemSelectionChanged.connect(self._on_video_selected)
        self.video_list.model().rowsMoved.connect(self._on_video_reordered)
        self.segment_list.itemDoubleClicked.connect(self._jump_to_segment)
        self.notes_list.itemDoubleClicked.connect(self._edit_note)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._wire_toolbar_extension_button()
        if self._toolbar_overflow and self._toolbar_overflow.isVisible():
            self._position_toolbar_overflow()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._toolbar_ext_button:
            if event.type() == QEvent.MouseButtonPress:
                self._toggle_toolbar_overflow()
                return True
            if event.type() == QEvent.MouseButtonRelease:
                return True
        return super().eventFilter(obj, event)

    def _wire_toolbar_extension_button(self) -> None:
        if not self._toolbar:
            return
        ext_button = self._toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
        if not ext_button or ext_button is self._toolbar_ext_button:
            return
        self._toolbar_ext_button = ext_button
        self._toolbar_ext_button.setCheckable(True)
        self._toolbar_ext_button.installEventFilter(self)

    def _ensure_toolbar_overflow(self) -> ToolbarOverflowDialog:
        if not self._toolbar_overflow:
            self._toolbar_overflow = ToolbarOverflowDialog(
                self, self._toolbar_actions, self.gen_z_mode
            )
            self._toolbar_overflow.closed.connect(self._on_toolbar_overflow_closed)
        return self._toolbar_overflow

    def _toggle_toolbar_overflow(self) -> None:
        panel = self._ensure_toolbar_overflow()
        showing = not panel.isVisible()
        if showing:
            self._position_toolbar_overflow()
            panel.show()
            panel.raise_()
            panel.activateWindow()
        else:
            panel.hide()
        if self._toolbar_ext_button:
            self._toolbar_ext_button.setChecked(showing)

    def _position_toolbar_overflow(self) -> None:
        if not self._toolbar_overflow:
            return
        anchor = self._toolbar_ext_button or self
        size = self._toolbar_overflow.sizeHint()
        anchor_pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        x_offset = max(anchor.width() - size.width(), 0)
        self._toolbar_overflow.move(QPoint(anchor_pos.x() + x_offset, anchor_pos.y()))

    def _on_toolbar_overflow_closed(self) -> None:
        if self._toolbar_ext_button:
            self._toolbar_ext_button.setChecked(False)

    def _init_config_watcher(self) -> None:
        self._config_watcher.fileChanged.connect(self._on_config_path_changed)
        self._config_watcher.directoryChanged.connect(self._on_config_dir_changed)
        self._sync_config_watcher_paths()

    def _sync_config_watcher_paths(self) -> None:
        for path in self._config_watcher.files():
            self._config_watcher.removePath(path)
        for path in self._config_watcher.directories():
            self._config_watcher.removePath(path)
        if self._config_path.parent.exists():
            self._config_watcher.addPath(str(self._config_path.parent))
        if self._config_path.exists():
            self._config_watcher.addPath(str(self._config_path))

    def _ensure_config_file_watched(self) -> None:
        if self._config_path.exists():
            path_str = str(self._config_path)
            if path_str not in self._config_watcher.files():
                self._config_watcher.addPath(path_str)

    def _on_config_path_changed(self, _path: str) -> None:
        self._ensure_config_file_watched()
        self._schedule_config_reload()

    def _on_config_dir_changed(self, _path: str) -> None:
        self._ensure_config_file_watched()
        self._schedule_config_reload()

    def _schedule_config_reload(self) -> None:
        self._config_reload_timer.start(250)

    def _reload_config(self) -> None:
        new_path = config_path()
        if new_path != self._config_path:
            self._config_path = new_path
            self._sync_config_watcher_paths()
        prev_gen_z = self.gen_z_mode
        self.config = load_config()
        self.gen_z_mode = bool(self.config.get("gen_z_mode", False))
        self.score_step = AURA_STEP if self.gen_z_mode else 1
        self.hotkeys = self.config.get("hotkeys", {})
        self.colors = self.config.get("colors", {})
        if self.gen_z_mode:
            self.colors = dict(self.colors) | gen_z_colors()
        self.timeline_config = self.config.get("timeline", {})
        self.audio_config = self.config.get("audio", {})
        self.scrub_config = self.config.get("scrub", {})
        self.export_config = self.config.get("export", {})

        self.audio.setMuted(bool(self.audio_config.get("default_muted", True)))
        self.audio.setVolume(float(self.audio_config.get("volume", 0.8)))

        self.export_gap_ff_enabled = bool(self.export_config.get("fast_forward_gaps_enabled", False))
        self.export_gap_speed = max(1.0, float(self.export_config.get("gap_speed", 3.0)))
        self.gap_ff_button.setChecked(self.export_gap_ff_enabled)
        self.gap_speed_spin.setValue(self.export_gap_speed)
        self.gap_speed_spin.setEnabled(self.export_gap_ff_enabled)

        self._apply_timeline_config()
        if self.gen_z_mode:
            self._apply_gen_z_theme()
        else:
            self._apply_default_theme()

        self._apply_hotkeys(self._action_map)
        self._apply_tooltips(self._action_map)
        self._refresh_ui_texts()

        if prev_gen_z != self.gen_z_mode:
            self._last_touch_side = None
            self._touch_streak = 0
            if self.score_tracker:
                self.score_tracker.close()
                self.score_tracker = None
            if self._toolbar_overflow:
                self._toolbar_overflow.close()
                self._toolbar_overflow = None

    # Project lifecycle --------------------------------------------------------
    def _new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self._t("dialog_choose_project_dir"))
        if not directory:
            return
        base_path = Path(directory)
        if base_path.exists() and any(base_path.iterdir()):
            confirm = QMessageBox.question(
                self,
                self._t("dialog_folder_not_empty_title"),
                self._t("dialog_folder_not_empty_msg", name=base_path.name),
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
        try:
            self.project = create_project(base_path)
        except Exception as exc:
            QMessageBox.critical(self, self._t("dialog_create_project_failed_title"), str(exc))
            return
        self.statusBar().showMessage(
            self._t("status_project_created", directory=directory), 5000
        )
        self._after_project_loaded()

    def _open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self._t("dialog_open_project_dir"))
        if not directory:
            return
        base_path = Path(directory)
        try:
            self.project = load_project(base_path)
        except Exception as exc:
            QMessageBox.critical(self, self._t("dialog_open_project_failed_title"), str(exc))
            return
        self.statusBar().showMessage(self._t("status_project_opened", directory=directory), 5000)
        self._after_project_loaded()

    def _after_project_loaded(self) -> None:
        self.import_button.setEnabled(True)
        self.gap_ff_button.setChecked(self.export_gap_ff_enabled)
        self.gap_speed_spin.setEnabled(self.export_gap_ff_enabled)
        self._sync_gap_ff_button_text()
        self.current_media_id = None
        self.mark_in_time = None
        self._reset_score_tracker()
        self._set_mark_indicator(False)
        self._refresh_video_list()
        self._refresh_segments()
        self._refresh_notes()
        if self.project and self.project.medias:
            self._load_media(self.project.medias[0].id)

    # Video import -------------------------------------------------------------
    def _import_videos(self) -> None:
        if not self.project:
            QMessageBox.information(
                self, self._t("dialog_no_project_title"), self._t("dialog_no_project_msg")
            )
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self._t("dialog_import_videos"),
            "",
            "Videos (*.mp4 *.mov *.mkv *.avi);;All files (*)",
        )
        if not files:
            return
        try:
            imported = import_media_files(self.project, (Path(f) for f in files))
            save_project(self.project)
        except Exception as exc:
            QMessageBox.critical(self, self._t("dialog_import_failed_title"), str(exc))
            return
        self.statusBar().showMessage(
            self._t("status_imported_videos", count=len(imported)), 4000
        )
        self._refresh_video_list()
        if imported and not self.current_media_id:
            self._load_media(imported[0].id)

    # Playback -----------------------------------------------------------------
    def _on_video_selected(self) -> None:
        item = self.video_list.currentItem()
        if not item or not self.project:
            return
        media_id = item.data(Qt.UserRole)
        self._load_media(media_id)

    def _load_media(self, media_id: str) -> None:
        if not self.project:
            return
        media = next((m for m in self.project.medias if m.id == media_id), None)
        if not media:
            return
        path = self.project.videos_dir / media.filename
        self.current_media_id = media_id
        self.mark_in_time = None
        self._set_mark_indicator(False)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.statusBar().showMessage(self._t("status_loaded_media", filename=media.filename), 3000)
        self._update_timeline_markers()

    def _toggle_play(self) -> None:
        if self.player.mediaStatus() == QMediaPlayer.NoMedia:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _toggle_mute(self, checked: bool) -> None:
        self.audio.setMuted(checked)
        self._sync_mute_action_text()
        status = self._t("status_audio_muted") if checked else self._t("status_audio_unmuted")
        self.statusBar().showMessage(status, 2000)

    def _on_position_changed(self, pos_ms: int) -> None:
        if self.position_slider.isSliderDown():
            return
        self.position_slider.setValue(pos_ms)
        total = self.player.duration()
        current_s = pos_ms / 1000 if pos_ms else 0
        total_s = total / 1000 if total else 0
        self.position_label.setText(f"{to_timestamp(current_s)} / {to_timestamp(total_s)}")
        if self.mark_in_time is not None:
            self._update_timeline_markers()

    def _on_duration_changed(self, duration_ms: int) -> None:
        self.position_slider.setEnabled(True)
        self.position_slider.setRange(0, duration_ms)
        self.position_slider.set_duration_seconds(duration_ms / 1000 if duration_ms else 0.0)
        self._update_timeline_markers()

    def _on_slider_moved(self, value: int) -> None:
        self.player.setPosition(value)
        if self.mark_in_time is not None:
            self._update_timeline_markers()

    def _on_slider_pressed(self) -> None:
        self._scrub_restore_muted = self.audio.isMuted()
        self.audio.setMuted(True)
        self._scrub_restore_play = self.player.playbackState() == QMediaPlayer.PlayingState
        if self._scrub_restore_play:
            self.player.pause()

    def _on_slider_released(self) -> None:
        self.audio.setMuted(self._scrub_restore_muted)
        if self._scrub_restore_play:
            self.player.play()

    # Segments -----------------------------------------------------------------
    def _current_time_seconds(self) -> float:
        return max(0.0, self.player.position() / 1000 if self.player.position() else 0.0)

    def _require_media(self) -> bool:
        if not self.project:
            QMessageBox.information(
                self,
                self._t("dialog_no_project_title"),
                self._t("dialog_no_project_msg_alt"),
            )
            return False
        if not self.current_media_id:
            QMessageBox.information(
                self, self._t("dialog_no_video_title"), self._t("dialog_no_video_msg")
            )
            return False
        return True

    def _mark_in(self) -> None:
        if not self._require_media():
            return
        self.mark_in_time = self._current_time_seconds()
        self._set_mark_indicator(True)
        self._update_timeline_markers()
        self.statusBar().showMessage(
            self._t("status_marked_in", time=self.mark_in_time), 2000
        )

    def _mark_out(self) -> None:
        if not self._require_media():
            return
        if self.mark_in_time is None:
            QMessageBox.information(
                self,
                self._t("dialog_no_mark_in_title"),
                self._t("dialog_no_mark_in_msg"),
            )
            return
        end = self._current_time_seconds()
        if end <= self.mark_in_time:
            QMessageBox.warning(
                self,
                self._t("dialog_invalid_segment_title"),
                self._t("dialog_invalid_segment_msg"),
            )
            return
        label = f"E{len(self.project.segments) + 1}"
        segment = Segment(
            id=generate_id(),
            media_id=self.current_media_id,
            start=self.mark_in_time,
            end=end,
            label=label,
        )
        self.project.segments.append(segment)
        save_project(self.project)
        self.mark_in_time = None
        self._set_mark_indicator(False)
        self._refresh_segments()
        self._update_timeline_markers()
        self.statusBar().showMessage(self._t("status_segment_saved", label=label), 2000)

    def _selected_segment(self) -> Segment | None:
        if not self.project:
            return None
        item = self.segment_list.currentItem()
        if not item:
            return None
        seg_id = item.data(Qt.UserRole)
        return next((s for s in self.project.segments if s.id == seg_id), None)

    def _selected_media(self):
        if not self.project:
            return None
        item = self.video_list.currentItem()
        if not item:
            return None
        media_id = item.data(Qt.UserRole)
        return next((m for m in self.project.medias if m.id == media_id), None)

    def _remove_video(self) -> None:
        media = self._selected_media()
        if not media or not self.project:
            QMessageBox.information(
                self, self._t("dialog_no_video_title"), self._t("dialog_no_video_remove_msg")
            )
            return
        confirm = QMessageBox.question(
            self,
            self._t("dialog_remove_video_title"),
            self._t("dialog_remove_video_msg"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        # Remove segments and notes tied to this media
        self.project.segments = [s for s in self.project.segments if s.media_id != media.id]
        self.project.notes = [n for n in self.project.notes if n.media_id != media.id]
        # Remove media entry
        self.project.medias = [m for m in self.project.medias if m.id != media.id]
        # Delete the file if present
        try:
            path = self.project.videos_dir / media.filename
            if path.exists():
                path.unlink()
        except OSError:
            pass
        self.current_media_id = None
        save_project(self.project)
        self._refresh_video_list()
        self._refresh_segments()
        self._refresh_notes()
        self.statusBar().showMessage(self._t("status_video_removed"), 2000)

    def _seek_to(self, seconds: float) -> None:
        duration_ms = self.player.duration()
        target_ms = int(max(0.0, seconds) * 1000)
        if duration_ms:
            target_ms = min(target_ms, duration_ms)
        self.player.setPosition(target_ms)

    def _jump_to_segment(self, item: QListWidgetItem) -> None:
        if not self.project:
            return
        seg_id = item.data(Qt.UserRole)
        segment = next((s for s in self.project.segments if s.id == seg_id), None)
        if not segment:
            return
        if segment.media_id != self.current_media_id:
            self._load_media(segment.media_id)
            QTimer.singleShot(150, lambda: self._seek_to(segment.start))
        else:
            self._seek_to(segment.start)

    def _edit_segment(self) -> None:
        segment = self._selected_segment()
        if not segment or not self.project:
            QMessageBox.information(
                self,
                self._t("dialog_no_segment_title"),
                self._t("dialog_no_segment_msg", action="edit"),
            )
            return
        media = next((m for m in self.project.medias if m.id == segment.media_id), None)
        dlg = SegmentDialog(
            self,
            self._t("dialog_edit_segment_title"),
            start=segment.start,
            end=segment.end,
            label=segment.label,
            speed=float(getattr(segment, "speed", 1.0) or 1.0),
            max_duration=media.duration if media else None,
            gen_z_mode=self.gen_z_mode,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        start, end, label, speed = dlg.values()
        if media and end > media.duration:
            QMessageBox.warning(
                self,
                self._t("dialog_invalid_segment_title"),
                self._t("dialog_invalid_segment_duration_msg"),
            )
            return
        segment.start = start
        segment.end = end
        segment.label = label
        segment.speed = speed
        save_project(self.project)
        self._refresh_segments()
        self.statusBar().showMessage(self._t("status_segment_updated"), 2000)

    def _delete_segment(self) -> None:
        segment = self._selected_segment()
        if not segment or not self.project:
            QMessageBox.information(
                self,
                self._t("dialog_no_segment_title"),
                self._t("dialog_no_segment_msg", action="delete"),
            )
            return
        self.project.segments = [s for s in self.project.segments if s.id != segment.id]
        save_project(self.project)
        self._refresh_segments()
        self.statusBar().showMessage(self._t("status_segment_deleted"), 2000)

    def _duplicate_segment(self) -> None:
        segment = self._selected_segment()
        if not segment or not self.project:
            QMessageBox.information(
                self,
                self._t("dialog_no_segment_title"),
                self._t("dialog_no_segment_msg", action="duplicate"),
            )
            return
        default_speed = float(getattr(segment, "speed", 1.0) or 1.0)
        base_label = segment.label or f"E{len(self.project.segments) + 1}"
        suggested_label = (
            f"{base_label} x{default_speed:g}" if abs(default_speed - 1.0) > 1e-3 else f"{base_label} copy"
        )
        media = next((m for m in self.project.medias if m.id == segment.media_id), None)
        dlg = SegmentDialog(
            self,
            self._t("dialog_duplicate_segment_title"),
            start=segment.start,
            end=segment.end,
            label=suggested_label,
            speed=default_speed,
            max_duration=media.duration if media else None,
            gen_z_mode=self.gen_z_mode,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        start, end, label, speed = dlg.values()
        duplicate = Segment(
            id=generate_id(),
            media_id=segment.media_id,
            start=start,
            end=end,
            label=label.strip(),
            speed=speed,
        )
        self.project.segments.append(duplicate)
        save_project(self.project)
        self._refresh_segments()
        self.statusBar().showMessage(self._t("status_segment_duplicated"), 2000)

    def _refresh_segments(self) -> None:
        self.segment_list.clear()
        if not self.project:
            return
        segments = sorted(self.project.segments, key=lambda s: s.start)
        for segment in segments:
            start = to_timestamp(segment.start)
            end = to_timestamp(segment.end)
            speed = float(getattr(segment, "speed", 1.0) or 1.0)
            speed_suffix = f"  x{speed:g}" if abs(speed - 1.0) > 1e-3 else ""
            item = QListWidgetItem(f"{segment.label or segment.id[:5]}  {start} - {end}{speed_suffix}")
            item.setData(Qt.UserRole, segment.id)
            self.segment_list.addItem(item)
        self._update_timeline_markers()

    # Notes --------------------------------------------------------------------
    def _add_note(self, note_type: str) -> None:
        if note_type not in ("comment", "chapter"):
            return
        if not self._require_media():
            return
        note_label = note_type_label(self.gen_z_mode, note_type)
        text, ok = QInputDialog.getText(
            self,
            self._t("note_new_title", note_type=note_label),
            self._t("note_text_prompt"),
        )
        if not ok:
            return
        note = Note(
            id=generate_id(),
            media_id=self.current_media_id,
            timestamp=self._current_time_seconds(),
            type=note_type,
            text=text.strip(),
        )
        self.project.notes.append(note)
        save_project(self.project)
        self._refresh_notes()
        self._update_timeline_markers()
        status_key = (
            "status_comment_added" if note_type == "comment" else "status_chapter_added"
        )
        self.statusBar().showMessage(self._t(status_key), 1500)

    def _selected_note(self) -> Note | None:
        if not self.project:
            return None
        item = self.notes_list.currentItem()
        if not item:
            return None
        note_id = item.data(Qt.UserRole)
        return next((n for n in self.project.notes if n.id == note_id), None)

    def _edit_note(self) -> None:
        note = self._selected_note()
        if not note or not self.project:
            QMessageBox.information(
                self,
                self._t("dialog_no_note_title"),
                self._t("dialog_no_note_msg", action="edit"),
            )
            return
        dlg = NoteDialog(
            self,
            self._t("note_edit_title"),
            timestamp=note.timestamp,
            note_type=note.type,
            text=note.text,
            gen_z_mode=self.gen_z_mode,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        timestamp, note_type, text = dlg.values()
        note.timestamp = timestamp
        note.type = note_type
        note.text = text
        save_project(self.project)
        self._refresh_notes()
        self._update_timeline_markers()
        self.statusBar().showMessage(self._t("status_note_updated"), 1500)

    def _delete_note(self) -> None:
        note = self._selected_note()
        if not note or not self.project:
            QMessageBox.information(
                self,
                self._t("dialog_no_note_title"),
                self._t("dialog_no_note_msg", action="delete"),
            )
            return
        self.project.notes = [n for n in self.project.notes if n.id != note.id]
        save_project(self.project)
        self._refresh_notes()
        self._update_timeline_markers()
        self.statusBar().showMessage(self._t("status_note_deleted"), 1500)

    # Score tracker -----------------------------------------------------------
    def _open_score_tracker(self) -> None:
        if self.score_tracker:
            self.score_tracker.show()
            self.score_tracker.raise_()
            self.score_tracker.activateWindow()
            return
        self.score_tracker = ScoreTrackerWindow(self, gen_z_mode=self.gen_z_mode)
        self.score_tracker.point_left.connect(self._on_point_left)
        self.score_tracker.point_right.connect(self._on_point_right)
        self.score_tracker.no_point.connect(self._on_no_point)
        self.score_tracker.destroyed.connect(lambda: setattr(self, "score_tracker", None))
        self.score_tracker.show()

    def _reset_score_tracker(self) -> None:
        if self.score_tracker:
            self.score_tracker.reset_scores()
        self._last_touch_side = None
        self._touch_streak = 0

    def _next_aura_gain(self, side: str) -> int:
        base = int(self.score_step)
        if not self.gen_z_mode:
            return base
        if self._last_touch_side == side:
            self._touch_streak += 1
        else:
            self._last_touch_side = side
            self._touch_streak = 1
        multiplier = self.score_tracker.aura_multiplier() if self.score_tracker else 1
        if self._touch_streak > 1:
            return base * max(1, multiplier)
        return base

    def _score_suffix(self) -> str:
        if not self.score_tracker:
            return ""
        left, right = self.score_tracker.scores()
        return self._t("score_suffix", left=left, right=right)

    def _add_quick_comment(self, text: str) -> None:
        if not self._require_media():
            return
        note = Note(
            id=generate_id(),
            media_id=self.current_media_id,
            timestamp=self._current_time_seconds(),
            type="comment",
            text=text.strip(),
        )
        self.project.notes.append(note)
        save_project(self.project)
        self._refresh_notes()
        self._update_timeline_markers()
        self.statusBar().showMessage(self._t("status_comment_added"), 1500)

    def _on_point_left(self) -> None:
        if not self._require_media():
            return
        if not self.score_tracker:
            self._open_score_tracker()
        step = self._next_aura_gain("left")
        if self.score_tracker and self.score_tracker.auto_score_enabled():
            self.score_tracker.increment_left(step)
        suffix = self._score_suffix() if self.score_tracker and self.score_tracker.auto_score_enabled() else ""
        self._add_quick_comment(
            self._t("quick_point_left", step=step, suffix=suffix)
        )

    def _on_point_right(self) -> None:
        if not self._require_media():
            return
        if not self.score_tracker:
            self._open_score_tracker()
        step = self._next_aura_gain("right")
        if self.score_tracker and self.score_tracker.auto_score_enabled():
            self.score_tracker.increment_right(step)
        suffix = self._score_suffix() if self.score_tracker and self.score_tracker.auto_score_enabled() else ""
        self._add_quick_comment(
            self._t("quick_point_right", step=step, suffix=suffix)
        )

    def _on_no_point(self) -> None:
        if not self._require_media():
            return
        if self.gen_z_mode:
            self._last_touch_side = None
            self._touch_streak = 0
        suffix = self._score_suffix() if self.score_tracker else ""
        self._add_quick_comment(self._t("quick_no_point", step=self.score_step, suffix=suffix))

    def _refresh_notes(self) -> None:
        self.notes_list.clear()
        if not self.project:
            return
        notes = sorted(self.project.notes, key=lambda n: n.timestamp)
        for note in notes:
            ts = to_timestamp(note.timestamp)
            label = note_type_label(self.gen_z_mode, note.type)
            item = QListWidgetItem(f"{label:8} {ts}  {note.text}")
            item.setData(Qt.UserRole, note.id)
            self.notes_list.addItem(item)

    # Export -------------------------------------------------------------------
    def _export(self) -> None:
        if not self.project:
            QMessageBox.information(
                self, self._t("dialog_no_project_title"), self._t("dialog_no_project_msg")
            )
            return
        if not self.project.segments:
            QMessageBox.information(
                self, self._t("dialog_no_segments_title"), self._t("dialog_no_segments_msg")
            )
            return
        slices = export_slices(
            self.project, include_gaps=self.export_gap_ff_enabled, gap_speed=self.export_gap_speed
        )
        timeline = build_timeline(slices)
        total_duration = timeline[-1][2] if timeline else 0.0
        _, warnings = chapter_lines_with_warnings(self.project, timeline, total_duration)
        if warnings:
            mapped = self._map_warnings(warnings)
            warning_text = f"{self._t('dialog_chapter_warnings_header')}\n\n"
            warning_text += "\n".join(f"- {w}" for w in mapped)
            warning_text += f"\n\n{self._t('dialog_chapter_warnings_continue')}"
            proceed = QMessageBox.question(
                self, self._t("dialog_chapter_warnings_title"), warning_text, QMessageBox.Yes | QMessageBox.No
            )
            if proceed != QMessageBox.Yes:
                return
        self._export_total_steps = len(slices) + 2
        progress = QProgressDialog(
            self._t("dialog_export_progress_label"),
            self._t("dialog_export_progress_cancel"),
            0,
            self._export_total_steps,
            self,
        )
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self._export_progress = progress

        thread = QThread(self)
        worker = ExportWorker(
            self.project,
            slices,
            self.export_gap_ff_enabled,
            self.export_gap_speed,
        )
        self._export_thread = thread
        self._export_worker = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.run, Qt.QueuedConnection)
        worker.progress.connect(self._on_export_progress, Qt.QueuedConnection)
        worker.finished.connect(self._on_export_finished, Qt.QueuedConnection)
        worker.error.connect(self._on_export_error, Qt.QueuedConnection)
        progress.canceled.connect(lambda: thread.requestInterruption())
        thread.start()

    # Lists --------------------------------------------------------------------
    def _refresh_video_list(self) -> None:
        self.video_list.clear()
        if not self.project:
            return
        for idx, media in enumerate(self.project.medias, start=1):
            item = QListWidgetItem(f"{idx}. {media.filename}")
            item.setData(Qt.UserRole, media.id)
            self.video_list.addItem(item)
        if self.video_list.count() == 0:
            return
        if self.current_media_id:
            for row in range(self.video_list.count()):
                if self.video_list.item(row).data(Qt.UserRole) == self.current_media_id:
                    self.video_list.setCurrentRow(row)
                    break
        else:
            self.video_list.setCurrentRow(0)

    def _on_video_reordered(self, *args) -> None:
        if not self.project:
            return
        order_ids = [self.video_list.item(i).data(Qt.UserRole) for i in range(self.video_list.count())]
        media_lookup = {m.id: m for m in self.project.medias}
        self.project.medias = [media_lookup[mid] for mid in order_ids if mid in media_lookup]
        save_project(self.project)
        self._refresh_video_list()

    def _scrub_seconds(self, direction: int) -> None:
        if not self.project or not self.current_media_id:
            return
        step = float(self.scrub_config.get("seconds_step", 1.0))
        self._seek_to(self._current_time_seconds() + (step * direction))

    def _scrub_frames(self, direction: int) -> None:
        if not self.project or not self.current_media_id:
            return
        frames_step = int(self.scrub_config.get("frames_step", 1))
        seconds = self._frame_step_seconds() * frames_step * direction
        self._seek_to(self._current_time_seconds() + seconds)

    def _frame_step_seconds(self) -> float:
        fallback = float(self.scrub_config.get("frame_fallback_seconds", 0.04))
        if not self.project or not self.current_media_id:
            return fallback
        media = next((m for m in self.project.medias if m.id == self.current_media_id), None)
        if not media or not media.fps:
            return fallback
        if media.fps <= 0:
            return fallback
        return 1.0 / media.fps

    # Utility helpers --------------------------------------------------------
    def _t(self, key: str, **kwargs) -> str:
        return ui_text(self.gen_z_mode, key, **kwargs)

    def _map_warnings(self, warnings: list[str]) -> list[str]:
        if not self.gen_z_mode:
            return warnings
        return [WARNING_MAP.get(warning, warning) for warning in warnings]

    # Export fast-forward gaps -------------------------------------------------
    def _toggle_gap_fast_forward(self, checked: bool | None = None) -> None:
        if checked is None:
            checked = not self.export_gap_ff_enabled
        self.export_gap_ff_enabled = bool(checked)
        self.gap_ff_button.setChecked(self.export_gap_ff_enabled)
        self.gap_speed_spin.setEnabled(self.export_gap_ff_enabled)
        self._sync_gap_ff_button_text()
        status = (
            self._t("status_gap_ff_on", speed=f"{self.export_gap_speed:g}")
            if self.export_gap_ff_enabled
            else self._t("status_gap_ff_off")
        )
        self.statusBar().showMessage(status, 2500)

    def _on_gap_speed_changed(self, value: float) -> None:
        self.export_gap_speed = max(1.0, float(value))
        self._sync_gap_ff_button_text()

    def _sync_gap_ff_button_text(self) -> None:
        state = self._t("gap_state_on") if self.export_gap_ff_enabled else self._t("gap_state_off")
        self.gap_ff_button.setText(
            self._t("gap_ff_button_text", state=state, speed=f"{self.export_gap_speed:g}")
        )

    def _refresh_instructions(self) -> None:
        self.instructions_label.setText(self._instructions_text())

    def _instructions_text(self) -> str:
        def key(name: str, default: str) -> str:
            return self.hotkeys.get(name, default)

        lines = [
            self._t("instructions_header"),
            self._t(
                "instructions_new_open",
                new_key=key("new_project", "Ctrl+N"),
                open_key=key("open_project", "Ctrl+O"),
            ),
            self._t(
                "instructions_import",
                import_key=key("import_videos", "Ctrl+I"),
            ),
            self._t(
                "instructions_play_mute",
                play_key=key("play_pause", "Space"),
                mute_key=key("mute_audio", "M"),
            ),
            self._t("instructions_gap_ff"),
            self._t(
                "instructions_scrub",
                back_key=key("scrub_back", "Left"),
                fwd_key=key("scrub_forward", "Right"),
                seconds_step=self.scrub_config.get("seconds_step", 1.0),
            ),
            self._t(
                "instructions_frame_step",
                back_key=key("scrub_frame_back", "Shift+Left"),
                fwd_key=key("scrub_frame_forward", "Shift+Right"),
                frames_step=self.scrub_config.get("frames_step", 1),
            ),
            self._t(
                "instructions_mark",
                in_key=key("mark_in", "I"),
                out_key=key("mark_out", "O"),
            ),
            self._t(
                "instructions_add_note",
                comment_key=key("add_comment", "Ctrl+Shift+C"),
                chapter_key=key("add_chapter", "Ctrl+Shift+H"),
            ),
            self._t(
                "instructions_score_tracker",
                score_key=key("score_tracker", "Ctrl+Shift+S"),
            ),
            self._t("instructions_double_click"),
            self._t(
                "instructions_open_exports",
                open_exports_key=key("open_exports", "Ctrl+Shift+E"),
            ),
            self._t("instructions_open_config"),
            self._t("instructions_export", export_key=key("export", "Ctrl+E")),
        ]
        return "\n".join(lines)

    # Export callbacks --------------------------------------------------------
    def _cleanup_export_worker(self) -> None:
        if self._export_progress:
            self._export_progress.close()
        if self._export_thread:
            self._export_thread.quit()
            self._export_thread.wait()
        self._export_thread = None
        self._export_worker = None
        self._export_progress = None

    def _on_export_progress(self, done: int, msg: str) -> None:
        if not self._export_progress:
            return
        self._export_progress.setMaximum(self._export_total_steps)
        self._export_progress.setValue(done)
        if msg:
            self._export_progress.setLabelText(f"{self._t('dialog_export_progress_label')} {msg}")

    def _on_export_finished(self, result: ExportResult) -> None:
        save_project(self.project)
        self._cleanup_export_worker()
        lines = [
            self._t("export_summary_highlights", path=result.highlights),
            self._t("export_summary_chapters", path=result.youtube_chapters),
            self._t("export_summary_comments", path=result.comments_timestamps),
            self._t("export_summary_clips", count=len(result.clips)),
        ]
        if self.export_gap_ff_enabled:
            lines.append(self._t("export_summary_gap", speed=f"{self.export_gap_speed:g}"))
        if result.chapter_warnings:
            mapped = self._map_warnings(result.chapter_warnings)
            lines.append("")
            lines.append(self._t("export_summary_warnings"))
            lines.extend(mapped)
        QMessageBox.information(self, self._t("dialog_export_complete_title"), "\n".join(lines))

    def _on_export_error(self, err: str) -> None:
        self._cleanup_export_worker()
        if "cancelled" in err.lower():
            QMessageBox.information(
                self, self._t("dialog_export_cancelled_title"), self._t("dialog_export_cancelled_msg")
            )
        else:
            QMessageBox.critical(self, self._t("dialog_export_failed_title"), err)

    def _apply_hotkeys(self, action_map: dict[str, QAction]) -> None:
        for key, action in action_map.items():
            shortcut = self.hotkeys.get(key, "")
            action.setShortcut(shortcut or "")

    def _apply_tooltips(self, action_map: dict[str, QAction]) -> None:
        descriptions = {
            "new_project": self._t("tooltip_new_project"),
            "open_project": self._t("tooltip_open_project"),
            "import_videos": self._t("tooltip_import_videos"),
            "export": self._t("tooltip_export"),
            "open_exports": self._t("tooltip_open_exports"),
            "open_config": self._t("tooltip_open_config"),
            "play_pause": self._t("tooltip_play_pause"),
            "mute_audio": self._t("tooltip_mute_audio"),
            "mark_in": self._t("tooltip_mark_in"),
            "mark_out": self._t("tooltip_mark_out"),
            "add_comment": self._t("tooltip_add_comment"),
            "add_chapter": self._t("tooltip_add_chapter"),
            "score_tracker": self._t("tooltip_score_tracker"),
            "scrub_back": self._t("tooltip_scrub_back"),
            "scrub_forward": self._t("tooltip_scrub_forward"),
            "scrub_frame_back": self._t("tooltip_scrub_frame_back"),
            "scrub_frame_forward": self._t("tooltip_scrub_frame_forward"),
        }
        for key, action in action_map.items():
            hint = descriptions.get(key, "")
            shortcut = self.hotkeys.get(key, "")
            if shortcut:
                action.setToolTip(f"{hint} ({shortcut})")
            else:
                action.setToolTip(hint)

    def _sync_hotkey_labels(self) -> None:
        mark_in_key = self.hotkeys.get("mark_in", "I")
        mark_out_key = self.hotkeys.get("mark_out", "O")
        self.segment_label.setText(
            self._t("label_segments", mark_in_key=mark_in_key, mark_out_key=mark_out_key)
        )
        self._refresh_instructions()

    def _refresh_ui_texts(self) -> None:
        self.setWindowTitle(self._t("window_title"))
        if self.video_list_label:
            self.video_list_label.setText(self._t("label_videos"))
        self.remove_video_button.setText(self._t("button_remove_video"))
        self.import_button.setText(self._t("button_import_videos"))
        self.segment_edit_button.setText(self._t("button_edit_segment"))
        self.segment_delete_button.setText(self._t("button_delete_segment"))
        self.segment_duplicate_button.setText(self._t("button_duplicate_segment"))
        self.note_label.setText(self._t("label_notes"))
        self.note_edit_button.setText(self._t("button_edit_note"))
        self.note_delete_button.setText(self._t("button_delete_note"))
        if self.gap_speed_label:
            self.gap_speed_label.setText(self._t("label_gap_speed"))

        for key, action in self._action_map.items():
            if key == "mute_audio":
                continue
            action.setText(self._t(f"action_{key}"))
        self._sync_mute_action_text()
        self._sync_hotkey_labels()
        self._sync_gap_ff_button_text()
        self._set_mark_indicator(self.mark_in_time is not None)

    def _apply_timeline_config(self) -> None:
        show_labels = bool(self.timeline_config.get("show_labels", True))
        label_max = int(self.timeline_config.get("label_max_chars", 12))
        self.position_slider.set_config(self.colors, show_labels, label_max)

    def _sync_mute_action_text(self) -> None:
        key = "action_mute_audio" if not self.audio.isMuted() else "action_unmute_audio"
        self.mute_action.setText(self._t(key))

    def _set_mark_indicator(self, active: bool) -> None:
        if active:
            self.mark_in_indicator.setText(self._t("mark_indicator_on"))
        else:
            self.mark_in_indicator.setText(self._t("mark_indicator_off"))
        if self.gen_z_mode:
            bg = GENZ_THEME["pink"] if active else GENZ_THEME["green"]
            self.mark_in_indicator.setStyleSheet(
                f"color: #000000; background-color: {bg}; padding: 4px; border: 2px solid #000000;"
            )
            return
        if active:
            self.mark_in_indicator.setStyleSheet("color: white; background-color: #c0392b; padding: 4px;")
        else:
            self.mark_in_indicator.setStyleSheet("color: #2c3e50; background-color: #ecf0f1; padding: 4px;")

    def _apply_window_icon(self) -> None:
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "bout_review_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _apply_gen_z_theme(self) -> None:
        self.setStyleSheet(gen_z_stylesheet())
        self.instructions_label.setStyleSheet(
            f"padding: 8px; background-color: {GENZ_THEME['green']}; color: #000000;"
            f" border: 2px solid {GENZ_THEME['border']};"
        )
        self.position_label.setStyleSheet(
            f"padding: 4px 8px; background-color: {GENZ_THEME['pink']}; color: #000000;"
            f" border: 2px solid {GENZ_THEME['border']};"
        )

    def _apply_default_theme(self) -> None:
        self.setStyleSheet("")
        self.instructions_label.setStyleSheet("padding: 8px;")
        self.position_label.setStyleSheet("")

    def _open_exports_folder(self) -> None:
        if not self.project:
            QMessageBox.information(
                self, self._t("dialog_no_project_title"), self._t("dialog_no_project_msg")
            )
            return
        self.project.exports_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.exports_dir)))

    def _open_config_file(self) -> None:
        path = config_path()
        if not path.exists():
            load_config()
        if not path.exists():
            QMessageBox.information(
                self,
                self._t("dialog_open_config_failed_title"),
                self._t("dialog_open_config_failed_msg", path=str(path)),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _update_timeline_markers(self) -> None:
        if not self.project or not self.current_media_id:
            self.position_slider.set_markers([], [], [])
            self.position_slider.set_active_segment(None, None)
            return
        segments = [
            SegmentMarker(start=s.start, end=s.end, label=s.label)
            for s in sorted(self.project.segments, key=lambda s: s.start)
            if s.media_id == self.current_media_id
        ]
        notes = [n for n in self.project.notes if n.media_id == self.current_media_id]
        chapters = [
            NoteMarker(timestamp=n.timestamp, label=n.text or self._t("marker_chapter_default"))
            for n in sorted(notes, key=lambda n: n.timestamp)
            if n.type == "chapter"
        ]
        comments = [
            NoteMarker(timestamp=n.timestamp, label=n.text or self._t("marker_comment_default"))
            for n in sorted(notes, key=lambda n: n.timestamp)
            if n.type == "comment"
        ]
        self.position_slider.set_markers(segments, chapters, comments)
        if self.mark_in_time is not None:
            current_time = self._current_time_seconds()
            start = self.mark_in_time
            end = current_time if current_time >= start else start
            self.position_slider.set_active_segment(start, end)
        else:
            self.position_slider.set_active_segment(None, None)
