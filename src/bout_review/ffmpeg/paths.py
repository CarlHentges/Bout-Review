from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import imageio_ffmpeg

from ..utils.debug import debug_print


def _bundled_binary(name: str) -> Path | None:
    if getattr(sys, "frozen", False):
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / name)
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / name)
        # macOS .app layout: Contents/MacOS (exe) and Contents/Resources (data)
        candidates.append(exe_dir.parent / "Resources" / name)
        for candidate in candidates:
            if candidate.exists():
                debug_print(f"Resolved bundled binary for {name}: {candidate}")
                return candidate
    return None


def get_ffmpeg_path() -> Path:
    bundled = _bundled_binary("ffmpeg")
    if bundled:
        return bundled
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

    bundled = _bundled_binary("ffprobe")
    if bundled:
        return bundled

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
