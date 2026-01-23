from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
import datetime


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def generate_id() -> str:
    return uuid.uuid4().hex


@dataclass
class MediaItem:
    id: str
    filename: str  # stored relative to project/videos
    duration: float
    fps: Optional[float] = None
    rotation_probe: int = 0
    rotation_override: Optional[int] = None
    imported_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaItem":
        return cls(
            id=data["id"],
            filename=data["filename"],
            duration=float(data.get("duration", 0.0)),
            fps=data.get("fps"),
            rotation_probe=int(data.get("rotation_probe", 0)),
            rotation_override=data.get("rotation_override"),
            imported_at=data.get("imported_at", _utc_now_iso()),
        )


@dataclass
class Segment:
    id: str
    media_id: str
    start: float
    end: float
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Segment":
        return cls(
            id=data["id"],
            media_id=data["media_id"],
            start=float(data["start"]),
            end=float(data["end"]),
            label=data.get("label", ""),
        )


@dataclass
class Note:
    id: str
    media_id: str
    timestamp: float
    type: str  # "comment" or "chapter"
    text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Note":
        return cls(
            id=data["id"],
            media_id=data["media_id"],
            timestamp=float(data["timestamp"]),
            type=data["type"],
            text=data.get("text", ""),
        )


@dataclass
class Project:
    base_path: Path
    name: str
    version: int = 1
    created_at: str = field(default_factory=_utc_now_iso)
    medias: List[MediaItem] = field(default_factory=list)
    segments: List[Segment] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)

    @property
    def project_json(self) -> Path:
        return self.base_path / "project.json"

    @property
    def videos_dir(self) -> Path:
        return self.base_path / "videos"

    @property
    def exports_dir(self) -> Path:
        return self.base_path / "exports"

    @property
    def clips_dir(self) -> Path:
        return self.exports_dir / "clips"

    @property
    def logs_dir(self) -> Path:
        return self.exports_dir / "logs"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "name": self.name,
            "medias": [m.to_dict() for m in self.medias],
            "segments": [s.to_dict() for s in self.segments],
            "notes": [n.to_dict() for n in self.notes],
        }

    @classmethod
    def from_dict(cls, base_path: Path, data: Dict[str, Any]) -> "Project":
        return cls(
            base_path=base_path,
            name=data.get("name", base_path.name),
            version=int(data.get("version", 1)),
            created_at=data.get("created_at", _utc_now_iso()),
            medias=[MediaItem.from_dict(m) for m in data.get("medias", [])],
            segments=[Segment.from_dict(s) for s in data.get("segments", [])],
            notes=[Note.from_dict(n) for n in data.get("notes", [])],
        )
