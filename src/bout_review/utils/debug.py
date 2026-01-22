from __future__ import annotations

import os
import sys


def debug_enabled() -> bool:
    return os.getenv("BOUT_REVIEW_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def debug_print(message: str) -> None:
    if debug_enabled():
        print(f"[bout-review debug] {message}", file=sys.stderr)
