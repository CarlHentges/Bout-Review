from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, List

from .models import MediaItem, generate_id, Project
from ..ffmpeg.probe import probe_media


def _ensure_writable_directory(path: Path) -> None:
    """Attempt to write a zero-byte temp file to confirm directory permissions."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        probe_path = path / ".write_test.tmp"
        with probe_path.open("wb") as fh:
            fh.write(b"")
        probe_path.unlink(missing_ok=True)
    except Exception as exc:
        raise PermissionError(
            f"Cannot write to project folder '{path}'. Choose a writable location (e.g., Documents)."
        ) from exc


def _unique_destination(videos_dir: Path, src: Path) -> Path:
    base = src.stem
    suffix = src.suffix
    candidate = videos_dir / f"{base}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = videos_dir / f"{base}_{counter}{suffix}"
        counter += 1
    return candidate


def import_media_files(project: Project, files: Iterable[Path]) -> List[MediaItem]:
    videos_dir = project.videos_dir
    _ensure_writable_directory(videos_dir)
    imported: List[MediaItem] = []
    for src in files:
        dest = _unique_destination(videos_dir, src)
        try:
            shutil.copy2(src, dest)
        except PermissionError as exc:
            raise PermissionError(
                f"Access denied while copying '{src}' into project folder '{dest}'. "
                "Choose a writable project location (e.g., inside Documents) and avoid Program Files or other protected folders."
            ) from exc
        except OSError as exc:
            raise OSError(f"Failed to copy '{src}' to '{dest}': {exc}") from exc
        metadata = probe_media(dest)
        item = MediaItem(
            id=generate_id(),
            filename=dest.name,
            duration=metadata.duration,
            fps=metadata.fps,
            rotation_probe=metadata.rotation,
        )
        imported.append(item)
    project.medias.extend(imported)
    return imported
