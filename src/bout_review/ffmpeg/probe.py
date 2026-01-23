from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .paths import get_ffmpeg_path, get_ffprobe_path
from ..utils.debug import debug_print


@dataclass
class MediaMetadata:
    duration: float
    rotation: int
    fps: float | None = None


def _run_ffprobe(path: Path) -> dict:
    ffprobe = get_ffprobe_path()
    cmd = [
        str(ffprobe),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    debug_print(f"Running ffprobe command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffprobe executable not found; set FFPROBE_PATH or ensure ffprobe is installed"
        ) from exc
    except subprocess.CalledProcessError as exc:
        debug_print(f"ffprobe return code: {exc.returncode}")
        if exc.stdout:
            debug_print(f"ffprobe stdout: {exc.stdout.strip()}")
        if exc.stderr:
            debug_print(f"ffprobe stderr: {exc.stderr.strip()}")
        raise RuntimeError(f"ffprobe failed: {exc.stderr}") from exc
    debug_print(f"ffprobe stdout length: {len(result.stdout)}")
    return json.loads(result.stdout)


def _parse_duration_from_text(text: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _parse_frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        try:
            num, den = value.split("/", 1)
            num_f = float(num)
            den_f = float(den)
            if den_f == 0:
                return None
            return num_f / den_f
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def _normalize_rotation(value: float) -> int:
    rounded = int(round(value / 90.0) * 90)
    return rounded % 360


def _parse_rotation_from_text(text: str) -> int:
    for line in text.splitlines():
        rotate_match = re.search(r"rotate\s*:\s*([-\d.]+)", line)
        if rotate_match:
            try:
                return _normalize_rotation(float(rotate_match.group(1)))
            except ValueError:
                continue
        display_match = re.search(r"rotation of\s*([-\d.]+)\s*degrees", line)
        if display_match:
            try:
                return _normalize_rotation(float(display_match.group(1)))
            except ValueError:
                continue
    return 0


def _parse_fps_from_text(text: str) -> float | None:
    match = re.search(r",\s*([\d.]+)\s*fps", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _run_ffmpeg_probe(path: Path) -> MediaMetadata:
    ffmpeg = get_ffmpeg_path()
    cmd = [str(ffmpeg), "-hide_banner", "-i", str(path)]
    debug_print(f"Running ffmpeg fallback probe: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr or ""
    if stderr:
        preview = "\n".join(stderr.splitlines()[:20])
        debug_print(f"ffmpeg stderr preview:\n{preview}")
    duration = _parse_duration_from_text(stderr)
    rotation = _parse_rotation_from_text(stderr)
    fps = _parse_fps_from_text(stderr)
    if duration is None:
        raise RuntimeError("Could not parse duration from ffmpeg output.")
    debug_print(f"ffmpeg fallback duration: {duration:.3f}s rotation: {rotation}")
    return MediaMetadata(duration=duration, rotation=rotation, fps=fps)


def _extract_rotation(stream: dict) -> int:
    tags = stream.get("tags", {}) or {}
    if "rotate" in tags:
        try:
            return int(tags["rotate"])
        except ValueError:
            pass
    side_data = stream.get("side_data_list") or []
    for entry in side_data:
        if entry.get("rotation") is not None:
            try:
                return int(entry["rotation"])
            except (TypeError, ValueError):
                continue
    return 0


def probe_media(path: Path) -> MediaMetadata:
    try:
        data = _run_ffprobe(path)
    except RuntimeError as exc:
        debug_print(f"ffprobe failed; attempting ffmpeg fallback. Reason: {exc}")
        return _run_ffmpeg_probe(path)

    duration = 0.0
    if data.get("format", {}).get("duration"):
        try:
            duration = float(data["format"]["duration"])
        except ValueError:
            duration = 0.0
    video_stream: Optional[dict] = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break
    rotation = _extract_rotation(video_stream) if video_stream else 0
    fps = None
    if video_stream:
        fps = _parse_frame_rate(video_stream.get("avg_frame_rate"))
        if fps is None:
            fps = _parse_frame_rate(video_stream.get("r_frame_rate"))
    return MediaMetadata(duration=duration, rotation=rotation, fps=fps)
