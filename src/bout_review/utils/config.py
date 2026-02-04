from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "gen_z_mode": False,
    "colors": {
        "segment": "#e74c3c",
        "segment_active": "#f1c40f",
        "chapter": "#3498db",
        "comment": "#2ecc71",
    },
    "hotkeys": {
        "new_project": "Ctrl+N",
        "open_project": "Ctrl+O",
        "import_videos": "Ctrl+I",
        "export": "Ctrl+E",
        "open_exports": "Ctrl+Shift+E",
        "play_pause": "Space",
        "mute_audio": "M",
        "mark_in": "I",
        "mark_out": "O",
        "add_comment": "Ctrl+Shift+C",
        "add_chapter": "Ctrl+Shift+H",
        "score_tracker": "Ctrl+Shift+S",
        "scrub_back": "Left",
        "scrub_forward": "Right",
        "scrub_frame_back": "Shift+Left",
        "scrub_frame_forward": "Shift+Right",
    },
    "audio": {
        "default_muted": True,
        "volume": 0.8,
    },
    "scrub": {
        "seconds_step": 1.0,
        "frames_step": 1,
        "frame_fallback_seconds": 0.04,
    },
    "export": {
        # Render unselected gaps in the highlights at this speed multiplier.
        "fast_forward_gaps_enabled": False,
        "gap_speed": 3.0,
    },
    "timeline": {
        "show_labels": True,
        "label_max_chars": 12,
    },
}


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Bout Review"
    if os.name == "nt":
        appdata = os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Bout Review"
    xdg = os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(xdg) / "bout-review"


def config_path() -> Path:
    override = os.getenv("BOUT_REVIEW_CONFIG")
    if override:
        return Path(override)
    return _default_config_dir() / "bout_review_config.json"


def load_config() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return dict(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_CONFIG)

    if not isinstance(data, dict):
        return dict(DEFAULT_CONFIG)
    merged = _deep_merge(DEFAULT_CONFIG, data)
    if merged != data:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
    return merged
