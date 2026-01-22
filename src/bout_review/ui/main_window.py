from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.importer import import_media_files
from ..core.models import Note, Project, Segment, generate_id
from ..core.project_io import create_project, load_project, save_project
from ..ffmpeg.exporter import build_timeline, chapter_lines_with_warnings, export_project
from ..utils.timecode import to_timestamp


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bout-Review")
        self.resize(1100, 720)

        self.project: Project | None = None
        self.current_media_id: str | None = None
        self.mark_in_time: float | None = None

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setEnabled(False)
        self.position_label = QLabel("00:00 / 00:00")

        self.video_list = QListWidget()
        self.segment_list = QListWidget()
        self.notes_list = QListWidget()
        self.import_button = QPushButton("Import videos")
        self.import_button.clicked.connect(self._import_videos)
        self.import_button.setEnabled(False)
        self.segment_label = QLabel("Segments (I = Mark In, O = Mark Out)")
        self.segment_edit_button = QPushButton("Edit segment")
        self.segment_delete_button = QPushButton("Delete segment")
        self.segment_edit_button.clicked.connect(self._edit_segment)
        self.segment_delete_button.clicked.connect(self._delete_segment)
        self.note_label = QLabel("Notes")
        self.note_edit_button = QPushButton("Edit note")
        self.note_delete_button = QPushButton("Delete note")
        self.note_edit_button.clicked.connect(self._edit_note)
        self.note_delete_button.clicked.connect(self._delete_note)

        self._build_ui()
        self._build_actions()
        self._connect_signals()

    # UI setup -----------------------------------------------------------------
    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Videos"))
        left_layout.addWidget(self.video_list)
        left_layout.addWidget(self.import_button)
        left_layout.addWidget(self.segment_label)
        left_layout.addWidget(self.segment_list)
        segment_buttons = QHBoxLayout()
        segment_buttons.addWidget(self.segment_edit_button)
        segment_buttons.addWidget(self.segment_delete_button)
        left_layout.addLayout(segment_buttons)
        left_layout.addWidget(self.note_label)
        left_layout.addWidget(self.notes_list)
        note_buttons = QHBoxLayout()
        note_buttons.addWidget(self.note_edit_button)
        note_buttons.addWidget(self.note_delete_button)
        left_layout.addLayout(note_buttons)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.video_widget)
        right_layout.addWidget(self.position_slider)
        right_layout.addWidget(self.position_label)

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

        new_action = QAction("New Project", self, triggered=self._new_project, shortcut="Ctrl+N")
        open_action = QAction("Open Project", self, triggered=self._open_project, shortcut="Ctrl+O")
        import_action = QAction("Import Videos", self, triggered=self._import_videos, shortcut="Ctrl+I")
        export_action = QAction("Export", self, triggered=self._export, shortcut="Ctrl+E")
        play_action = QAction("Play/Pause", self, triggered=self._toggle_play, shortcut="Space")
        self.mute_action = QAction("Mute Audio", self, checkable=True, triggered=self._toggle_mute)
        self.mute_action.setChecked(True)
        mark_in_action = QAction("Mark In", self, triggered=self._mark_in, shortcut="I")
        mark_out_action = QAction("Mark Out", self, triggered=self._mark_out, shortcut="O")
        comment_action = QAction("Add Comment", self, triggered=lambda: self._add_note("comment"), shortcut="Ctrl+Shift+C")
        chapter_action = QAction("Add Chapter", self, triggered=lambda: self._add_note("chapter"), shortcut="Ctrl+Shift+H")

        for action in [
            new_action,
            open_action,
            import_action,
            export_action,
            play_action,
            self.mute_action,
            mark_in_action,
            mark_out_action,
            comment_action,
            chapter_action,
        ]:
            toolbar.addAction(action)

    def _connect_signals(self) -> None:
        self.video_list.itemSelectionChanged.connect(self._on_video_selected)
        self.segment_list.itemDoubleClicked.connect(self._jump_to_segment)
        self.notes_list.itemDoubleClicked.connect(self._edit_note)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)

    # Project lifecycle --------------------------------------------------------
    def _new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose or create project folder")
        if not directory:
            return
        base_path = Path(directory)
        try:
            self.project = create_project(base_path)
        except Exception as exc:
            QMessageBox.critical(self, "Create project failed", str(exc))
            return
        self.statusBar().showMessage(f"Project created at {directory}", 5000)
        self._after_project_loaded()

    def _open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open project folder")
        if not directory:
            return
        base_path = Path(directory)
        try:
            self.project = load_project(base_path)
        except Exception as exc:
            QMessageBox.critical(self, "Open project failed", str(exc))
            return
        self.statusBar().showMessage(f"Project opened from {directory}", 5000)
        self._after_project_loaded()

    def _after_project_loaded(self) -> None:
        self.import_button.setEnabled(True)
        self.current_media_id = None
        self.mark_in_time = None
        self._refresh_video_list()
        self._refresh_segments()
        self._refresh_notes()
        if self.project and self.project.medias:
            self._load_media(self.project.medias[0].id)

    # Video import -------------------------------------------------------------
    def _import_videos(self) -> None:
        if not self.project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import video files",
            "",
            "Videos (*.mp4 *.mov *.mkv *.avi);;All files (*)",
        )
        if not files:
            return
        try:
            imported = import_media_files(self.project, (Path(f) for f in files))
            save_project(self.project)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.statusBar().showMessage(f"Imported {len(imported)} video(s)", 4000)
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
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.statusBar().showMessage(f"Loaded {media.filename}", 3000)

    def _toggle_play(self) -> None:
        if self.player.mediaStatus() == QMediaPlayer.NoMedia:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _toggle_mute(self, checked: bool) -> None:
        self.audio.setMuted(checked)
        status = "Audio muted" if checked else "Audio unmuted"
        self.statusBar().showMessage(status, 2000)

    def _on_position_changed(self, pos_ms: int) -> None:
        if self.position_slider.isSliderDown():
            return
        self.position_slider.setValue(pos_ms)
        total = self.player.duration()
        current_s = pos_ms / 1000 if pos_ms else 0
        total_s = total / 1000 if total else 0
        self.position_label.setText(f"{to_timestamp(current_s)} / {to_timestamp(total_s)}")

    def _on_duration_changed(self, duration_ms: int) -> None:
        self.position_slider.setEnabled(True)
        self.position_slider.setRange(0, duration_ms)

    def _on_slider_moved(self, value: int) -> None:
        self.player.setPosition(value)

    # Segments -----------------------------------------------------------------
    def _current_time_seconds(self) -> float:
        return max(0.0, self.player.position() / 1000 if self.player.position() else 0.0)

    def _require_media(self) -> bool:
        if not self.project:
            QMessageBox.information(self, "No project", "Open or create a project first.")
            return False
        if not self.current_media_id:
            QMessageBox.information(self, "No video", "Import and select a video to continue.")
            return False
        return True

    def _mark_in(self) -> None:
        if not self._require_media():
            return
        self.mark_in_time = self._current_time_seconds()
        self.statusBar().showMessage(f"Marked in at {self.mark_in_time:.2f}s", 2000)

    def _mark_out(self) -> None:
        if not self._require_media():
            return
        if self.mark_in_time is None:
            QMessageBox.information(self, "No mark in", "Press I to set a start before marking out.")
            return
        end = self._current_time_seconds()
        if end <= self.mark_in_time:
            QMessageBox.warning(self, "Invalid segment", "End must be after start.")
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
        self._refresh_segments()
        self.statusBar().showMessage(f"Segment {label} saved", 2000)

    def _selected_segment(self) -> Segment | None:
        if not self.project:
            return None
        item = self.segment_list.currentItem()
        if not item:
            return None
        seg_id = item.data(Qt.UserRole)
        return next((s for s in self.project.segments if s.id == seg_id), None)

    def _seek_to(self, seconds: float) -> None:
        self.player.setPosition(int(seconds * 1000))

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
            QMessageBox.information(self, "No segment", "Select a segment to edit.")
            return
        start, ok = QInputDialog.getDouble(
            self, "Edit segment", "Start time (seconds):", value=segment.start, min=0.0, decimals=3
        )
        if not ok:
            return
        end, ok = QInputDialog.getDouble(
            self, "Edit segment", "End time (seconds):", value=segment.end, min=0.0, decimals=3
        )
        if not ok:
            return
        if end <= start:
            QMessageBox.warning(self, "Invalid segment", "End must be after start.")
            return
        label, ok = QInputDialog.getText(self, "Edit segment", "Label:", text=segment.label)
        if not ok:
            return
        media = next((m for m in self.project.medias if m.id == segment.media_id), None)
        if media and end > media.duration:
            QMessageBox.warning(
                self, "Invalid segment", "End time exceeds media duration. Adjust and try again."
            )
            return
        segment.start = start
        segment.end = end
        segment.label = label.strip()
        save_project(self.project)
        self._refresh_segments()
        self.statusBar().showMessage("Segment updated", 2000)

    def _delete_segment(self) -> None:
        segment = self._selected_segment()
        if not segment or not self.project:
            QMessageBox.information(self, "No segment", "Select a segment to delete.")
            return
        confirm = QMessageBox.question(
            self, "Delete segment", "Delete the selected segment?", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        self.project.segments = [s for s in self.project.segments if s.id != segment.id]
        save_project(self.project)
        self._refresh_segments()
        self.statusBar().showMessage("Segment deleted", 2000)

    def _refresh_segments(self) -> None:
        self.segment_list.clear()
        if not self.project:
            return
        for segment in self.project.segments:
            start = to_timestamp(segment.start)
            end = to_timestamp(segment.end)
            item = QListWidgetItem(f"{segment.label or segment.id[:5]}  {start} - {end}")
            item.setData(Qt.UserRole, segment.id)
            self.segment_list.addItem(item)

    # Notes --------------------------------------------------------------------
    def _add_note(self, note_type: str) -> None:
        if note_type not in ("comment", "chapter"):
            return
        if not self._require_media():
            return
        text, ok = QInputDialog.getText(self, f"New {note_type}", "Note text:")
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
        self.statusBar().showMessage(f"{note_type.capitalize()} added", 1500)

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
            QMessageBox.information(self, "No note", "Select a note to edit.")
            return
        timestamp, ok = QInputDialog.getDouble(
            self, "Edit note", "Timestamp (seconds):", value=note.timestamp, min=0.0, decimals=3
        )
        if not ok:
            return
        text, ok = QInputDialog.getText(self, "Edit note", "Note text:", text=note.text)
        if not ok:
            return
        note.timestamp = timestamp
        note.text = text.strip()
        save_project(self.project)
        self._refresh_notes()
        self.statusBar().showMessage("Note updated", 1500)

    def _delete_note(self) -> None:
        note = self._selected_note()
        if not note or not self.project:
            QMessageBox.information(self, "No note", "Select a note to delete.")
            return
        confirm = QMessageBox.question(
            self, "Delete note", "Delete the selected note?", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        self.project.notes = [n for n in self.project.notes if n.id != note.id]
        save_project(self.project)
        self._refresh_notes()
        self.statusBar().showMessage("Note deleted", 1500)

    def _refresh_notes(self) -> None:
        self.notes_list.clear()
        if not self.project:
            return
        for note in self.project.notes:
            ts = to_timestamp(note.timestamp)
            item = QListWidgetItem(f"{note.type:8} {ts}  {note.text}")
            item.setData(Qt.UserRole, note.id)
            self.notes_list.addItem(item)

    # Export -------------------------------------------------------------------
    def _export(self) -> None:
        if not self.project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        if not self.project.segments:
            QMessageBox.information(self, "No segments", "Mark keep ranges before exporting.")
            return
        timeline = build_timeline(self.project.segments)
        total_duration = timeline[-1][2] if timeline else 0.0
        _, warnings = chapter_lines_with_warnings(self.project, timeline, total_duration)
        if warnings:
            warning_text = "Chapters do not meet YouTube requirements:\n\n"
            warning_text += "\n".join(f"- {w}" for w in warnings)
            warning_text += "\n\nContinue export anyway?"
            proceed = QMessageBox.question(
                self, "Chapter warnings", warning_text, QMessageBox.Yes | QMessageBox.No
            )
            if proceed != QMessageBox.Yes:
                return
        try:
            result = export_project(self.project)
            save_project(self.project)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        message = (
            f"Highlights: {result.highlights}\n"
            f"Chapters: {result.youtube_chapters}\n"
            f"Comments: {result.comments_timestamps}\n"
            f"Clips: {len(result.clips)} saved"
        )
        if result.chapter_warnings:
            message += "\n\nChapter warnings:\n" + "\n".join(result.chapter_warnings)
        QMessageBox.information(self, "Export complete", message)

    # Lists --------------------------------------------------------------------
    def _refresh_video_list(self) -> None:
        self.video_list.clear()
        if not self.project:
            return
        for media in self.project.medias:
            item = QListWidgetItem(media.filename)
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
