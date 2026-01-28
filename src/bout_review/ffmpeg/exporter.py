from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
import sys

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


@dataclass
class ExportSlice:
    media_id: str
    start: float
    end: float
    speed: float
    label: str
    is_gap: bool


def _log_command(log_path: Path, cmd: List[str], result: subprocess.CompletedProcess) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(" ".join(cmd) + "\n")
        if result.stdout:
            fh.write(result.stdout)
        if result.stderr:
            fh.write(result.stderr)
        fh.write("\n")


def _log_text(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")


def _debug_enabled() -> bool:
    return os.getenv("BOUT_REVIEW_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def _no_window_kwargs() -> dict:
    """On Windows, suppress console windows for ffmpeg child processes."""
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "startupinfo": startupinfo,
        }
    return {}


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


def _build_vf(rotation: int, speed: float = 1.0) -> str:
    filters = []
    if speed and abs(speed - 1.0) > 1e-3:
        filters.append(f"setpts=PTS/{speed:.6f}")
    rot = _rotation_filter(rotation)
    if rot:
        filters.append(rot)
    filters.append(_scale_filter())
    return ",".join(filters)


def _atempo_filters(speed: float) -> str:
    """Return a comma-separated chain of atempo filters that approximate `speed`.

    ffmpeg's atempo supports factors between 0.5 and 2.0, so we decompose larger/smaller
    values into a product of supported chunks (e.g., 4.0 -> 2.0,2.0; 0.25 -> 0.5,0.5).
    """
    if speed <= 0:
        return ""
    factors = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-4:
        factors.append(remaining)
    if not factors:
        return ""
    return ",".join(f"atempo={f:.6f}" for f in factors)


def build_timeline(slices: List[ExportSlice]) -> List[Tuple[ExportSlice, float, float]]:
    timeline = []
    offset = 0.0
    for slc in slices:
        speed = max(0.001, float(getattr(slc, "speed", 1.0) or 1.0))
        duration = max(0.0, slc.end - slc.start) / speed
        timeline.append((slc, offset, offset + duration))
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


def export_slices(project: Project, include_gaps: bool, gap_speed: float) -> List[ExportSlice]:
    ordered_segments = _ordered_segments(project)
    by_media: Dict[str, List[Segment]] = {}
    for seg in ordered_segments:
        by_media.setdefault(seg.media_id, []).append(seg)

    slices: List[ExportSlice] = []
    for media in project.medias:
        duration = float(media.duration or 0.0)
        segs = by_media.get(media.id, [])
        cursor = 0.0
        for seg in segs:
            if include_gaps and seg.start > cursor:
                slices.append(
                    ExportSlice(
                        media_id=media.id,
                        start=cursor,
                        end=seg.start,
                        speed=gap_speed,
                        label="Gap",
                        is_gap=True,
                    )
                )
            slices.append(
                ExportSlice(
                    media_id=media.id,
                    start=seg.start,
                    end=seg.end,
                    speed=max(0.001, float(getattr(seg, "speed", 1.0) or 1.0)),
                    label=seg.label or "",
                    is_gap=False,
                )
            )
            cursor = max(cursor, seg.end)
        if include_gaps and duration > cursor:
            slices.append(
                ExportSlice(
                    media_id=media.id,
                    start=cursor,
                    end=duration,
                    speed=gap_speed,
                    label="Gap",
                    is_gap=True,
                )
            )
    return slices


def _map_to_highlight(note: Note, timeline: List[Tuple[ExportSlice, float, float]]) -> float | None:
    for slc, start_out, end_out in timeline:
        if slc.media_id != note.media_id:
            continue
        if slc.start <= note.timestamp <= slc.end:
            speed = max(0.001, float(getattr(slc, "speed", 1.0) or 1.0))
            return start_out + (note.timestamp - slc.start) / speed
    return None


def _render_clip(
    ffmpeg: Path,
    source: Path,
    start: float,
    end: float,
    rotation: int,
    speed: float,
    output: Path,
    log_path: Path,
) -> Path:
    start = max(0.0, start)
    duration = max(0.0, end - start)
    speed = max(0.001, speed)
    effective_duration = duration / speed if speed > 0 else duration
    vf = _build_vf(rotation, speed)
    atempo_chain = _atempo_filters(speed)
    if _debug_enabled():
        _log_text(
            log_path,
            f"[clip] src={source.name} start={start:.3f}s end={end:.3f}s dur={duration:.3f}s "
            f"speed={speed:.3f} effective_dur={effective_duration:.3f}s vf='{vf}' af='{atempo_chain or 'none'}'",
        )
    cmd = [
        str(ffmpeg),
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{effective_duration:.3f}",
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
        "-fflags",
        "+genpts",
    ]
    if atempo_chain:
        cmd += ["-af", atempo_chain]
    cmd += [
        "-reset_timestamps",
        "1",
        "-avoid_negative_ts",
        "1",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, **_no_window_kwargs())
    _log_command(log_path, cmd, result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for clip {output.name}: {result.stderr}")
    return output


def _concat_highlight(ffmpeg: Path, clip_paths: List[Path], output: Path, log_path: Path) -> Path:
    if _debug_enabled():
        _log_text(
            log_path,
            "[concat] clips="
            + ", ".join(f"{clip.name}" for clip in clip_paths),
        )
    input_args: List[str] = []
    filter_parts: List[str] = []
    for idx, clip in enumerate(clip_paths):
        input_args += ["-i", str(clip)]
        filter_parts.append(f"[{idx}:v]setpts=PTS-STARTPTS[v{idx}]")
        filter_parts.append(f"[{idx}:a]asetpts=PTS-STARTPTS[a{idx}]")
    concat_inputs = "".join(f"[v{idx}][a{idx}]" for idx in range(len(clip_paths)))
    filter_parts.append(f"{concat_inputs}concat=n={len(clip_paths)}:v=1:a=1[v][a]")
    filter_complex = ";".join(filter_parts)
    cmd = [
        str(ffmpeg),
        "-y",
        "-fflags",
        "+genpts",
        *input_args,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-r",
        "60",
        "-fps_mode",
        "cfr",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, **_no_window_kwargs())
    _log_command(log_path, cmd, result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr}")
    return output


def _write_text(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def chapter_lines_with_warnings(
    project: Project, timeline: List[Tuple[ExportSlice, float, float]], total_duration: float
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


def _comment_lines(project: Project, timeline: List[Tuple[ExportSlice, float, float]]) -> List[str]:
    lines: List[str] = []
    for note in project.notes:
        if note.type != "comment":
            continue
        mapped = _map_to_highlight(note, timeline)
        if mapped is None:
            continue
        lines.append(f"{to_timestamp(mapped)} {note.text.strip()}")
    return lines


def export_project(project: Project, fast_forward_gaps: bool = False, gap_speed: float = 3.0) -> ExportResult:
    ordered_segments = _ordered_segments(project)
    if not ordered_segments:
        raise ValueError("No segments to export. Mark keep ranges before exporting.")
    gap_speed = max(1.0, float(gap_speed))
    media_lookup: Dict[str, str] = {m.id: m.filename for m in project.medias}
    rotation_lookup: Dict[str, int] = {
        m.id: m.rotation_override if m.rotation_override is not None else m.rotation_probe
        for m in project.medias
    }

    slices = export_slices(project, include_gaps=fast_forward_gaps, gap_speed=gap_speed)

    ffmpeg = get_ffmpeg_path()
    project.exports_dir.mkdir(parents=True, exist_ok=True)
    project.clips_dir.mkdir(parents=True, exist_ok=True)
    project.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = project.logs_dir / "ffmpeg_export.log"

    if _debug_enabled():
        _log_text(
            log_path,
            "[slices]"
            + " | ".join(
                f"{idx}:{'gap' if slc.is_gap else (slc.label or 'seg')} media={slc.media_id[:6]} start={slc.start:.3f} end={slc.end:.3f} speed={slc.speed}"
                for idx, slc in enumerate(slices, start=1)
            ),
        )

    clip_paths: List[Path] = []
    gap_count = 0
    for idx, slc in enumerate(slices, start=1):
        if slc.end <= slc.start:
            raise ValueError(f"Slice {idx} has non-positive duration.")
        filename = media_lookup.get(slc.media_id)
        if not filename:
            raise ValueError(f"Slice {idx} references missing media {slc.media_id}")
        src = project.videos_dir / filename
        if not src.exists():
            raise FileNotFoundError(f"Media file missing: {src}")
        if slc.is_gap:
            gap_count += 1
            label = _safe_label(f"gap_{gap_count}", f"GAP{gap_count}")
        else:
            label = _safe_label(slc.label, f"E{idx}")
        dest = project.clips_dir / f"{label}.mp4"
        rotation = rotation_lookup.get(slc.media_id, 0)
        clip = _render_clip(
            ffmpeg=ffmpeg,
            source=src,
            start=slc.start,
            end=slc.end,
            rotation=rotation,
            speed=max(0.05, float(getattr(slc, "speed", 1.0) or 1.0)),
            output=dest,
            log_path=log_path,
        )
        clip_paths.append(clip)

    highlights_path = project.exports_dir / "highlights.mp4"
    _concat_highlight(ffmpeg, clip_paths, highlights_path, log_path)

    timeline = build_timeline(slices)
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
