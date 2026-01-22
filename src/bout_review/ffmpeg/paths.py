from __future__ import annotations

import os
from pathlib import Path
import shutil
import imageio_ffmpeg

from ..utils.debug import debug_print


def get_ffmpeg_path() -> Path:
    path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    debug_print(f"Resolved ffmpeg path: {path}")
    return path


def get_ffprobe_path() -> Path:
    # Prefer explicit override
    override = os.getenv("FFPROBE_PATH")
    if override:
        path = Path(override)
        debug_print(f"Resolved ffprobe path (override): {path}")
        return path

    ffmpeg_path = get_ffmpeg_path()
    candidate = ffmpeg_path.with_name("ffprobe")
    if candidate.exists():
        debug_print(f"Resolved ffprobe path (bundle): {candidate}")
        return candidate

    system = shutil.which("ffprobe")
    if system:
        path = Path(system)
        debug_print(f"Resolved ffprobe path (system): {path}")
        return path

    # Last resort: some ffmpeg builds allow `ffmpeg -hide_banner -print_format ...`
    # but we still return a path to keep the call sites consistent.
    debug_print("ffprobe not found; falling back to ffmpeg path (may fail).")
    return ffmpeg_path
