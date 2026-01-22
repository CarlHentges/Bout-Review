from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Iterable

from .models import Project


def ensure_structure(path: Path) -> None:
    (path / "videos").mkdir(parents=True, exist_ok=True)
    (path / "exports").mkdir(parents=True, exist_ok=True)
    (path / "exports" / "clips").mkdir(parents=True, exist_ok=True)
    (path / "exports" / "logs").mkdir(parents=True, exist_ok=True)


def create_project(base_path: Path, name: str | None = None) -> Project:
    base_path.mkdir(parents=True, exist_ok=True)
    ensure_structure(base_path)
    project = Project(base_path=base_path, name=name or base_path.name)
    save_project(project)
    return project


def load_project(base_path: Path) -> Project:
    project_json = base_path / "project.json"
    if not project_json.exists():
        raise FileNotFoundError(f"No project.json found in {base_path}")
    with project_json.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    project = Project.from_dict(base_path, data)
    ensure_structure(base_path)
    return project


def save_project(project: Project) -> None:
    payload = project.to_dict()
    target = project.project_json
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(target.parent), encoding="utf-8"
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp.flush()
    Path(tmp.name).replace(target)


def add_media(project: Project, media_items: Iterable) -> None:
    project.medias.extend(media_items)
    save_project(project)


def upsert_segment(project: Project, segment) -> None:
    project.segments.append(segment)
    save_project(project)


def upsert_note(project: Project, note) -> None:
    project.notes.append(note)
    save_project(project)
