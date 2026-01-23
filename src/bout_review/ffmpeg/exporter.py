from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .paths import get_ffmpeg_path
from ..core.models import Note, Project, Segment
from ..utils.timecode import to_timestamp


EXPORT_RESOLUTION = (1920, 1080)


@dataclass
class ExportResult:
    highlights: Path
    clips: List[Path]
    youtube_chapters: Path
    comments_timestamps: Path
    chapter_warnings: List[str]


def _log_command(log_path: Path, cmd: List[str], result: subprocess.CompletedProcess) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(" ".join(cmd) + "\n")
        if result.stdout:
            fh.write(result.stdout)
        if result.stderr:
            fh.write(result.stderr)
        fh.write("\n")


def _rotation_filter(rotation: int) -> str:
    rotation = rotation % 360
    if rotation == 90:
        return "transpose=1"
    if rotation == 180:
        return "transpose=1,transpose=1"
    if rotation == 270:
        return "transpose=2"
    return ""


def _scale_filter() -> str:
    w, h = EXPORT_RESOLUTION
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"


def _build_vf(rotation: int) -> str:
    filters = []
    rot = _rotation_filter(rotation)
    if rot:
        filters.append(rot)
    filters.append(_scale_filter())
    return ",".join(filters)


def build_timeline(segments: List[Segment]) -> List[Tuple[Segment, float, float]]:
    timeline = []
    offset = 0.0
    for seg in segments:
        duration = max(0.0, seg.end - seg.start)
        timeline.append((seg, offset, offset + duration))
        offset += duration
    return timeline


def _safe_label(label: str, fallback: str) -> str:
    candidate = label.strip() or fallback
    candidate = re.sub(r"[^\w.\-]+", "_", candidate)
    candidate = candidate.strip("_") or fallback
    return candidate


def _ordered_segments(project: Project) -> List[Segment]:
    order = {m.id: idx for idx, m in enumerate(project.medias)}
    return sorted(
        project.segments,
        key=lambda s: (order.get(s.media_id, 10**9), s.start, s.end),
    )


def _map_to_highlight(note: Note, timeline: List[Tuple[Segment, float, float]]) -> float | None:
    for seg, start_out, end_out in timeline:
        if seg.media_id != note.media_id:
            continue
        if seg.start <= note.timestamp <= seg.end:
            return start_out + (note.timestamp - seg.start)
    return None


def _render_clip(
    ffmpeg: Path,
    source: Path,
    start: float,
    end: float,
    rotation: int,
    output: Path,
    log_path: Path,
) -> Path:
    start = max(0.0, start)
    duration = max(0.0, end - start)
    vf = _build_vf(rotation)
    cmd = [
        str(ffmpeg),
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    _log_command(log_path, cmd, result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for clip {output.name}: {result.stderr}")
    return output


def _concat_highlight(ffmpeg: Path, clip_paths: List[Path], output: Path, log_path: Path) -> Path:
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tmp:
        for clip in clip_paths:
            safe_path = clip.as_posix().replace("'", "'\\''")
            tmp.write(f"file '{safe_path}'\n")
        list_path = Path(tmp.name)
    cmd = [
        str(ffmpeg),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    _log_command(log_path, cmd, result)
    list_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr}")
    return output


def _write_text(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def chapter_lines_with_warnings(
    project: Project, timeline: List[Tuple[Segment, float, float]], total_duration: float
) -> tuple[List[str], List[str]]:
    chapters: List[Tuple[float, str]] = []
    warnings: List[str] = []
    for note in project.notes:
        if note.type != "chapter":
            continue
        mapped = _map_to_highlight(note, timeline)
        if mapped is None:
            continue
        label = note.text.strip() or "Chapter"
        chapters.append((mapped, label))

    chapters.sort(key=lambda x: x[0])

    if not chapters or chapters[0][0] > 0:
        chapters.insert(0, (0.0, "Start"))

    if len(chapters) < 3:
        warnings.append("YouTube requires at least 3 chapter timestamps.")

    for idx in range(len(chapters) - 1):
        delta = chapters[idx + 1][0] - chapters[idx][0]
        if delta < 10:
            warnings.append("Some chapters are less than 10 seconds apart.")
            break

    if chapters and total_duration - chapters[-1][0] < 10:
        warnings.append("Last chapter is within 10 seconds of the end.")

    return [f"{to_timestamp(ts)} {label}" for ts, label in chapters], warnings


def _comment_lines(project: Project, timeline: List[Tuple[Segment, float, float]]) -> List[str]:
    lines: List[str] = []
    for note in project.notes:
        if note.type != "comment":
            continue
        mapped = _map_to_highlight(note, timeline)
        if mapped is None:
            continue
        lines.append(f"{to_timestamp(mapped)} {note.text.strip()}")
    return lines


def export_project(project: Project) -> ExportResult:
    ordered_segments = _ordered_segments(project)
    if not ordered_segments:
        raise ValueError("No segments to export. Mark keep ranges before exporting.")
    media_lookup: Dict[str, str] = {m.id: m.filename for m in project.medias}
    rotation_lookup: Dict[str, int] = {
        m.id: m.rotation_override if m.rotation_override is not None else m.rotation_probe
        for m in project.medias
    }

    ffmpeg = get_ffmpeg_path()
    project.exports_dir.mkdir(parents=True, exist_ok=True)
    project.clips_dir.mkdir(parents=True, exist_ok=True)
    project.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = project.logs_dir / "ffmpeg_export.log"

    clip_paths: List[Path] = []
    for idx, segment in enumerate(ordered_segments, start=1):
        if segment.end <= segment.start:
            raise ValueError(f"Segment {segment.id} has non-positive duration.")
        filename = media_lookup.get(segment.media_id)
        if not filename:
            raise ValueError(f"Segment {segment.id} references missing media {segment.media_id}")
        src = project.videos_dir / filename
        if not src.exists():
            raise FileNotFoundError(f"Media file missing: {src}")
        label = _safe_label(segment.label, f"E{idx}")
        dest = project.clips_dir / f"{label}.mp4"
        rotation = rotation_lookup.get(segment.media_id, 0)
        clip = _render_clip(
            ffmpeg=ffmpeg,
            source=src,
            start=segment.start,
            end=segment.end,
            rotation=rotation,
            output=dest,
            log_path=log_path,
        )
        clip_paths.append(clip)

    highlights_path = project.exports_dir / "highlights.mp4"
    _concat_highlight(ffmpeg, clip_paths, highlights_path, log_path)

    timeline = build_timeline(ordered_segments)
    total_duration = timeline[-1][2] if timeline else 0.0

    chapters_path = project.exports_dir / "youtube_chapters.txt"
    chapter_lines, chapter_warnings = chapter_lines_with_warnings(project, timeline, total_duration)
    _write_text(chapters_path, chapter_lines)

    comments_path = project.exports_dir / "comments_timestamps.txt"
    comment_lines = _comment_lines(project, timeline)
    if comment_lines:
        _write_text(comments_path, comment_lines)
    else:
        comments_path.touch(exist_ok=True)

    return ExportResult(
        highlights=highlights_path,
        clips=clip_paths,
        youtube_chapters=chapters_path,
        comments_timestamps=comments_path,
        chapter_warnings=chapter_warnings,
    )
