from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, List

from .models import MediaItem, generate_id, Project
from ..ffmpeg.probe import probe_media


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
    videos_dir.mkdir(parents=True, exist_ok=True)
    imported: List[MediaItem] = []
    for src in files:
        dest = _unique_destination(videos_dir, src)
        shutil.copy2(src, dest)
        metadata = probe_media(dest)
        item = MediaItem(
            id=generate_id(),
            filename=dest.name,
            duration=metadata.duration,
            rotation_probe=metadata.rotation,
        )
        imported.append(item)
    project.medias.extend(imported)
    return imported
