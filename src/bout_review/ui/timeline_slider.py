from __future__ import annotations

from dataclasses import dataclass
from typing import List

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


@dataclass
class SegmentMarker:
    start: float
    end: float
    label: str


@dataclass
class NoteMarker:
    timestamp: float
    label: str


class TimelineSlider(QSlider):
    def __init__(self, orientation: Qt.Orientation = Qt.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)
        self._duration_seconds = 0.0
        self._segments: List[SegmentMarker] = []
        self._chapters: List[NoteMarker] = []
        self._comments: List[NoteMarker] = []
        self._active_segment: tuple[float, float] | None = None
        self._colors = {
            "segment": "#e74c3c",
            "segment_active": "#f1c40f",
            "chapter": "#3498db",
            "comment": "#2ecc71",
        }
        self._show_labels = True
        self._label_max_chars = 12

    def set_duration_seconds(self, seconds: float) -> None:
        self._duration_seconds = max(0.0, float(seconds))
        self.update()

    def set_markers(
        self,
        segments: List[SegmentMarker],
        chapters: List[NoteMarker],
        comments: List[NoteMarker],
    ) -> None:
        self._segments = segments
        self._chapters = chapters
        self._comments = comments
        self.update()

    def set_active_segment(self, start: float | None, end: float | None) -> None:
        if start is None or end is None:
            self._active_segment = None
        else:
            self._active_segment = (float(start), float(end))
        self.update()

    def set_config(self, colors: dict, show_labels: bool, label_max_chars: int) -> None:
        self._colors = dict(self._colors) | colors
        self._show_labels = bool(show_labels)
        self._label_max_chars = max(4, int(label_max_chars))
        self.update()

    def mousePressEvent(self, event) -> None:
        """Allow jumping the playhead by clicking anywhere on the groove, not just dragging the handle."""
        if event.button() == Qt.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            evt_point = event.position().toPoint() if hasattr(event, "position") else event.pos()
            handle = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            if not handle.contains(evt_point):
                groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
                if groove.contains(evt_point) and groove.width() > 0 and groove.height() > 0:
                    if self.orientation() == Qt.Horizontal:
                        pos = event.position().x() if hasattr(event, "position") else event.x()
                        span = groove.width()
                        offset = pos - groove.x()
                    else:
                        pos = event.position().y() if hasattr(event, "position") else event.y()
                        span = groove.height()
                        offset = pos - groove.y()
                    offset = max(0, min(span, offset))
                    value = QStyle.sliderValueFromPosition(
                        self.minimum(),
                        self.maximum(),
                        int(offset),
                        span,
                        opt.upsideDown,
                    )
                    self.setSliderDown(True)
                    self.sliderPressed.emit()
                    self.setValue(value)
                    self.sliderMoved.emit(value)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._duration_seconds <= 0:
            return
        if not (self._segments or self._chapters or self._comments or self._active_segment):
            return

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        if groove.width() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        total = self._duration_seconds

        def x_from_time(seconds: float) -> int:
            return groove.x() + int((seconds / total) * groove.width())

        # Segments as colored overlays on the groove
        segment_color = QColor(self._colors.get("segment", "#e74c3c"))
        segment_color.setAlpha(120)
        seg_height = max(4, groove.height() // 2)
        seg_y = groove.center().y() - seg_height // 2
        for seg in self._segments:
            x1 = x_from_time(max(0.0, seg.start))
            x2 = x_from_time(max(seg.start, seg.end))
            width = max(1, x2 - x1)
            painter.fillRect(QRect(x1, seg_y, width, seg_height), segment_color)

        if self._active_segment:
            active_start, active_end = self._active_segment
            active_color = QColor(self._colors.get("segment_active", "#f1c40f"))
            active_color.setAlpha(200)
            x1 = x_from_time(max(0.0, min(active_start, active_end)))
            x2 = x_from_time(max(active_start, active_end))
            width = x2 - x1
            if width < 4:
                x1 = max(groove.x(), x1 - 2)
                width = 4
            painter.fillRect(QRect(x1, seg_y - 1, width, seg_height + 2), active_color)

        # Chapter markers
        chapter_color = QColor(self._colors.get("chapter", "#3498db"))
        comment_color = QColor(self._colors.get("comment", "#2ecc71"))
        fm = QFontMetrics(self.font())

        def draw_marker(marker: NoteMarker, color: QColor, y_offset: int) -> None:
            x = x_from_time(max(0.0, marker.timestamp))
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.drawLine(x, groove.top(), x, groove.bottom())
            if self._show_labels and marker.label:
                text = marker.label[: self._label_max_chars]
                text_width = fm.horizontalAdvance(text)
                text_x = max(0, min(x + 2, self.width() - text_width - 2))
                painter.drawText(text_x, groove.top() - y_offset, text)

        for chapter in self._chapters:
            draw_marker(chapter, chapter_color, 4)
        for comment in self._comments:
            draw_marker(comment, comment_color, -12)
