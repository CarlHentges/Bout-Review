from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import imageio_ffmpeg
import subprocess

from ..utils.debug import debug_print
from ..utils.config import config_path


def _user_bin_dir() -> Path:
    return config_path().parent / "bin"


def _is_in_app_bundle(path: Path) -> bool:
    parts = path.parts
    return "Contents" in parts and "Applications" in parts


def _ensure_executable_copy(src: Path, name: str) -> Path:
    if not src.exists():
        raise FileNotFoundError(src)
    dest_dir = _user_bin_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    try:
        if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(src, dest)
        dest.chmod(0o755)
        if sys.platform == "darwin":
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", str(dest)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return dest
    except OSError as exc:
        debug_print(f"Failed to copy bundled binary to user bin: {exc}")
        raise


def _should_copy(candidate: Path) -> bool:
    if sys.platform == "darwin" and "AppTranslocation" in str(candidate):
        return True
    if _is_in_app_bundle(candidate):
        return True
    return not os.access(candidate, os.X_OK)


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
        candidates.append(exe_dir.parent / "Frameworks" / name)
        # Some PyInstaller layouts place binaries in a subfolder matching the dest name.
        candidates.append(exe_dir / "ffmpeg" / name)
        candidates.append(exe_dir.parent / "Resources" / "ffmpeg" / name)
        if sys.platform == "win32":
            # Try .exe variants explicitly
            exe_variants = []
            for cand in list(candidates):
                if cand.suffix.lower() != ".exe":
                    exe_variants.append(cand.with_suffix(".exe"))
            candidates.extend(exe_variants)
        for candidate in candidates:
            if candidate.exists():
                if _should_copy(candidate):
                    try:
                        copied = _ensure_executable_copy(candidate, name)
                        debug_print(f"Using copied bundled binary for {name}: {copied}")
                        return copied
                    except OSError:
                        debug_print(
                            f"Bundled binary not usable and copy failed for {name}: {candidate}"
                        )
                        return None
                debug_print(f"Resolved bundled binary for {name}: {candidate}")
                return candidate
    return None


def get_ffmpeg_path() -> Path:
    bundled = _bundled_binary("ffmpeg")
    if bundled:
        return bundled
    path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if getattr(sys, "frozen", False) and _should_copy(path):
        copied = _ensure_executable_copy(path, "ffmpeg")
        return copied
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
