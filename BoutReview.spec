# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


spec_path = Path(globals().get("__file__", Path.cwd())).resolve()
project_root = spec_path.parent if spec_path.is_file() else spec_path
src_root = project_root / "src"

icon_icns = src_root / "bout_review" / "assets" / "bout_review_icon.icns"
icon_png = src_root / "bout_review" / "assets" / "bout_review_icon.png"


def _ensure_icns(png_path: Path, icns_path: Path) -> Path | None:
    if icns_path.exists():
        return icns_path
    # Try Pillow if available
    try:
        from PIL import Image  # type: ignore

        img = Image.open(png_path)
        img.save(icns_path)
        if icns_path.exists():
            return icns_path
    except Exception:
        pass

    # Fall back to macOS tools: sips + iconutil
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            iconset_dir = Path(tmpdir) / "BoutReview.iconset"
            iconset_dir.mkdir(parents=True, exist_ok=True)
            for size in (16, 32, 128, 256, 512):
                subprocess.run(
                    [
                        "sips",
                        "-z",
                        str(size),
                        str(size),
                        str(png_path),
                        "--out",
                        str(iconset_dir / f"icon_{size}x{size}.png"),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                double = size * 2
                subprocess.run(
                    [
                        "sips",
                        "-z",
                        str(double),
                        str(double),
                        str(png_path),
                        "--out",
                        str(iconset_dir / f"icon_{size}x{size}@2x.png"),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            subprocess.run(
                ["iconutil", "--convert", "icns", "--output", str(icns_path), str(iconset_dir)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if icns_path.exists():
            return icns_path
    except Exception as exc:
        print(f"Icon conversion failed: {exc}. Install Pillow or provide an .icns icon.")
    return None


icon_path = _ensure_icns(icon_png, icon_icns)

ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
ffprobe_path = ffmpeg_path.with_name("ffprobe")

datas = collect_data_files("imageio_ffmpeg", include_py_files=False)
datas.append((str(icon_png), "bout_review/assets"))
if icon_icns.exists():
    datas.append((str(icon_icns), "bout_review/assets"))

binaries = [(str(ffmpeg_path), "ffmpeg")]
if ffprobe_path.exists():
    binaries.append((str(ffprobe_path), "ffprobe"))
hiddenimports = collect_submodules("imageio_ffmpeg")


block_cipher = None

a = Analysis(
    ["scripts/pyinstaller_entry.py"],
    pathex=[str(project_root), str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Bout Review",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Bout Review",
)

app = BUNDLE(
    coll,
    name="Bout Review.app",
    icon=str(icon_path) if icon_path else None,
    info_plist={
        "CFBundleName": "Bout Review",
        "CFBundleDisplayName": "Bout Review",
        "CFBundleIdentifier": "com.boutreview.app",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
    },
)
