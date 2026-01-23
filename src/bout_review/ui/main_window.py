from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
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
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.importer import import_media_files
from ..core.models import Note, Project, Segment, generate_id
from ..core.project_io import create_project, load_project, save_project
from ..ffmpeg.exporter import build_timeline, chapter_lines_with_warnings, export_project
from ..utils.config import load_config
from ..utils.timecode import to_timestamp
from .timeline_slider import NoteMarker, SegmentMarker, TimelineSlider


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bout Review")
        self.resize(1100, 720)

        self.config = load_config()
        self.hotkeys = self.config.get("hotkeys", {})
        self.colors = self.config.get("colors", {})
        self.timeline_config = self.config.get("timeline", {})
        self.audio_config = self.config.get("audio", {})
        self.scrub_config = self.config.get("scrub", {})

        self.project: Project | None = None
        self.current_media_id: str | None = None
        self.mark_in_time: float | None = None

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
        self.segment_list = QListWidget()
        self.notes_list = QListWidget()
        self.import_button = QPushButton("Import videos")
        self.import_button.clicked.connect(self._import_videos)
        self.import_button.setEnabled(False)
        self.segment_label = QLabel("Segments (I = Mark In, O = Mark Out)")
        self.mark_in_indicator = QLabel("Mark In: OFF")
        self._set_mark_indicator(False)
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
        self._apply_timeline_config()
        self._sync_hotkey_labels()
        self._sync_mute_action_text()
        self._apply_window_icon()

    # UI setup -----------------------------------------------------------------
    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Videos"))
        left_layout.addWidget(self.video_list)
        left_layout.addWidget(self.import_button)
        left_layout.addWidget(self.segment_label)
        left_layout.addWidget(self.mark_in_indicator)
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
        right_layout.addWidget(self.video_widget, 6)
        right_layout.addWidget(self.position_slider, 0)
        right_layout.addWidget(self.position_label, 0)
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

        new_action = QAction("New Project", self, triggered=self._new_project)
        open_action = QAction("Open Project", self, triggered=self._open_project)
        import_action = QAction("Import Videos", self, triggered=self._import_videos)
        export_action = QAction("Export", self, triggered=self._export)
        open_exports_action = QAction("Open Exports Folder", self, triggered=self._open_exports_folder)
        play_action = QAction("Play/Pause", self, triggered=self._toggle_play)
        self.mute_action = QAction("Mute Audio", self, checkable=True, triggered=self._toggle_mute)
        self.mute_action.setChecked(self.audio.isMuted())
        mark_in_action = QAction("Mark In", self, triggered=self._mark_in)
        mark_out_action = QAction("Mark Out", self, triggered=self._mark_out)
        comment_action = QAction("Add Comment", self, triggered=lambda: self._add_note("comment"))
        chapter_action = QAction("Add Chapter", self, triggered=lambda: self._add_note("chapter"))
        scrub_back_action = QAction("Scrub Back", self, triggered=lambda: self._scrub_seconds(-1))
        scrub_forward_action = QAction("Scrub Forward", self, triggered=lambda: self._scrub_seconds(1))
        scrub_frame_back_action = QAction(
            "Step Frame Back", self, triggered=lambda: self._scrub_frames(-1)
        )
        scrub_frame_forward_action = QAction(
            "Step Frame Forward", self, triggered=lambda: self._scrub_frames(1)
        )

        action_map = {
            "new_project": new_action,
            "open_project": open_action,
            "import_videos": import_action,
            "export": export_action,
            "open_exports": open_exports_action,
            "play_pause": play_action,
            "mute_audio": self.mute_action,
            "mark_in": mark_in_action,
            "mark_out": mark_out_action,
            "add_comment": comment_action,
            "add_chapter": chapter_action,
            "scrub_back": scrub_back_action,
            "scrub_forward": scrub_forward_action,
            "scrub_frame_back": scrub_frame_back_action,
            "scrub_frame_forward": scrub_frame_forward_action,
        }
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

        for action in [
            new_action,
            open_action,
            import_action,
            export_action,
            open_exports_action,
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
        self.video_list.model().rowsMoved.connect(self._on_video_reordered)
        self.segment_list.itemDoubleClicked.connect(self._jump_to_segment)
        self.notes_list.itemDoubleClicked.connect(self._edit_note)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)

    # Project lifecycle --------------------------------------------------------
    def _new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose or create project folder")
        if not directory:
            return
        base_path = Path(directory)
        if base_path.exists() and any(base_path.iterdir()):
            confirm = QMessageBox.question(
                self,
                "Folder not empty",
                f"'{base_path.name}' is not empty. Create project here anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
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
        self._set_mark_indicator(False)
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
        self.mark_in_time = None
        self._set_mark_indicator(False)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.statusBar().showMessage(f"Loaded {media.filename}", 3000)
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
        self._set_mark_indicator(True)
        self._update_timeline_markers()
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
        self._set_mark_indicator(False)
        self._refresh_segments()
        self._update_timeline_markers()
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
        self.project.segments = [s for s in self.project.segments if s.id != segment.id]
        save_project(self.project)
        self._refresh_segments()
        self.statusBar().showMessage("Segment deleted", 2000)

    def _refresh_segments(self) -> None:
        self.segment_list.clear()
        if not self.project:
            return
        segments = sorted(self.project.segments, key=lambda s: s.start)
        for segment in segments:
            start = to_timestamp(segment.start)
            end = to_timestamp(segment.end)
            item = QListWidgetItem(f"{segment.label or segment.id[:5]}  {start} - {end}")
            item.setData(Qt.UserRole, segment.id)
            self.segment_list.addItem(item)
        self._update_timeline_markers()

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
        self._update_timeline_markers()
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
        self._update_timeline_markers()
        self.statusBar().showMessage("Note updated", 1500)

    def _delete_note(self) -> None:
        note = self._selected_note()
        if not note or not self.project:
            QMessageBox.information(self, "No note", "Select a note to delete.")
            return
        self.project.notes = [n for n in self.project.notes if n.id != note.id]
        save_project(self.project)
        self._refresh_notes()
        self._update_timeline_markers()
        self.statusBar().showMessage("Note deleted", 1500)

    def _refresh_notes(self) -> None:
        self.notes_list.clear()
        if not self.project:
            return
        notes = sorted(self.project.notes, key=lambda n: n.timestamp)
        for note in notes:
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

    def _refresh_instructions(self) -> None:
        self.instructions_label.setText(self._instructions_text())

    def _instructions_text(self) -> str:
        def key(name: str, default: str) -> str:
            return self.hotkeys.get(name, default)

        lines = [
            "Quick guide:",
            f"- New/Open project: {key('new_project', 'Ctrl+N')} / {key('open_project', 'Ctrl+O')}",
            f"- Import videos: {key('import_videos', 'Ctrl+I')} (drag to reorder in the list)",
            f"- Play/Pause: {key('play_pause', 'Space')} • Mute: {key('mute_audio', 'M')}",
            f"- Scrub: {key('scrub_back', 'Left')} / {key('scrub_forward', 'Right')} "
            f"({self.scrub_config.get('seconds_step', 1.0)}s)",
            f"- Frame step: {key('scrub_frame_back', 'Shift+Left')} / {key('scrub_frame_forward', 'Shift+Right')} "
            f"({self.scrub_config.get('frames_step', 1)} frame)",
            f"- Mark In/Out: {key('mark_in', 'I')} / {key('mark_out', 'O')}",
            f"- Add Comment/Chapter: {key('add_comment', 'Ctrl+Shift+C')} / {key('add_chapter', 'Ctrl+Shift+H')}",
            "- Double-click a segment to jump to its start; use Edit/Delete buttons for segments and notes.",
            f"- Open exports folder: {key('open_exports', 'Ctrl+Shift+E')}",
            f"- Export: {key('export', 'Ctrl+E')}",
        ]
        return "\n".join(lines)

    def _apply_hotkeys(self, action_map: dict[str, QAction]) -> None:
        for key, action in action_map.items():
            shortcut = self.hotkeys.get(key)
            if shortcut:
                action.setShortcut(shortcut)

    def _apply_tooltips(self, action_map: dict[str, QAction]) -> None:
        descriptions = {
            "new_project": "Create a new project",
            "open_project": "Open an existing project",
            "import_videos": "Import video files into the project",
            "export": "Export highlights and text files",
            "open_exports": "Open the project exports folder",
            "play_pause": "Play or pause the current video",
            "mute_audio": "Toggle audio mute",
            "mark_in": "Set segment start (Mark In)",
            "mark_out": "Set segment end (Mark Out)",
            "add_comment": "Add a comment note at the playhead",
            "add_chapter": "Add a chapter note at the playhead",
            "scrub_back": "Scrub backward by seconds",
            "scrub_forward": "Scrub forward by seconds",
            "scrub_frame_back": "Step backward by frames",
            "scrub_frame_forward": "Step forward by frames",
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
        self.segment_label.setText(f"Segments ({mark_in_key} = Mark In, {mark_out_key} = Mark Out)")
        self._refresh_instructions()

    def _apply_timeline_config(self) -> None:
        show_labels = bool(self.timeline_config.get("show_labels", True))
        label_max = int(self.timeline_config.get("label_max_chars", 12))
        self.position_slider.set_config(self.colors, show_labels, label_max)

    def _sync_mute_action_text(self) -> None:
        self.mute_action.setText("Mute Audio" if not self.audio.isMuted() else "Unmute Audio")

    def _set_mark_indicator(self, active: bool) -> None:
        if active:
            self.mark_in_indicator.setText("Mark In: ON")
            self.mark_in_indicator.setStyleSheet("color: white; background-color: #c0392b; padding: 4px;")
        else:
            self.mark_in_indicator.setText("Mark In: OFF")
            self.mark_in_indicator.setStyleSheet("color: #2c3e50; background-color: #ecf0f1; padding: 4px;")

    def _apply_window_icon(self) -> None:
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "bout_review_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _open_exports_folder(self) -> None:
        if not self.project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        self.project.exports_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.exports_dir)))

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
            NoteMarker(timestamp=n.timestamp, label=n.text or "Chapter")
            for n in sorted(notes, key=lambda n: n.timestamp)
            if n.type == "chapter"
        ]
        comments = [
            NoteMarker(timestamp=n.timestamp, label=n.text or "Comment")
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
