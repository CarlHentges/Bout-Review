#!/usr/bin/env python
from __future__ import annotations

"""
Package the latest PyInstaller build into a zip named for the current platform/arch.

Usage:
    python scripts/package_release.py

Assumes you have already run:
    pyinstaller BoutReview.spec
"""

import platform
import sys
import zipfile
from pathlib import Path
import shutil
import subprocess


def _label_for_platform(system: str) -> str:
    if system == "Darwin":
        return "Mac"
    if system == "Windows":
        return "Windows"
    return "Linux"


def _arch_slug(machine: str) -> str:
    mach = machine.lower()
    if mach in {"x86_64", "amd64"}:
        return "x64"
    if mach in {"aarch64", "arm64"}:
        return "arm64"
    if mach in {"x86", "i386", "i686"}:
        return "x86"
    return mach or "unknown"


def _zip_path(src: Path, dest_zip: Path) -> None:
    if dest_zip.exists():
        dest_zip.unlink()
    # macOS bundles rely on symlinks and resource forks; use ditto to preserve them.
    if sys.platform == "darwin":
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(src),
                str(dest_zip),
            ],
            check=True,
        )
        return

    # Windows/Linux: standard zip
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        if src.is_dir():
            for file in src.rglob("*"):
                if file.is_dir():
                    continue
                arc = Path(src.name) / file.relative_to(src)
                zf.write(file, arcname=str(arc))
        else:
            zf.write(src, arcname=src.name)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    dist_dir = project_root / "dist"
    if not dist_dir.exists():
        print("dist/ not found. Run `pyinstaller BoutReview.spec` first.", file=sys.stderr)
        return 1

    system = platform.system()
    arch = _arch_slug(platform.machine())
    label = _label_for_platform(system)

    if system == "Darwin":
        source = dist_dir / "Bout Review.app"
    else:
        source = dist_dir / "Bout Review"

    if not source.exists():
        print(f"Expected build output not found at: {source}", file=sys.stderr)
        return 1

    zip_name = f"Bout_Review_{label}-{arch}.zip"
    dest = dist_dir / zip_name
    _zip_path(source, dest)
    print(f"Packaged {source.name} -> {dest.relative_to(project_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
