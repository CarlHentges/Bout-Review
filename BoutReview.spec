# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg
import importlib.util
import sys
import sysconfig
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


spec_path = Path(globals().get("__file__", Path.cwd())).resolve()
project_root = spec_path.parent if spec_path.is_file() else spec_path
src_root = project_root / "src"
APP_VERSION = "1.3.0"

icon_icns = src_root / "bout_review" / "assets" / "bout_review_icon.icns"
icon_ico = src_root / "bout_review" / "assets" / "bout_review_icon.ico"
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


def _ensure_ico(png_path: Path, ico_path: Path) -> Path | None:
    if ico_path.exists():
        return ico_path
    try:
        from PIL import Image  # type: ignore

        img = Image.open(png_path)
        # Save multi-size icon for better scaling on Windows
        img.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        if ico_path.exists():
            return ico_path
    except Exception as exc:
        print(f"ICO conversion failed: {exc}. Install Pillow or provide an .ico icon.")
    return None


is_macos = sys.platform == "darwin"
icon_path = _ensure_icns(icon_png, icon_icns) if is_macos else None
icon_path_ico = _ensure_ico(icon_png, icon_ico)

ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
ffprobe_path = ffmpeg_path.with_name("ffprobe")

datas = collect_data_files("imageio_ffmpeg", include_py_files=False)
datas.append((str(icon_png), "bout_review/assets"))
if icon_icns.exists():
    datas.append((str(icon_icns), "bout_review/assets"))
if icon_ico.exists():
    datas.append((str(icon_ico), "bout_review/assets"))

binaries = [(str(ffmpeg_path), "ffmpeg")]
if ffprobe_path.exists():
    binaries.append((str(ffprobe_path), "ffprobe"))
hiddenimports = collect_submodules("imageio_ffmpeg")
# Ensure core stdlib extension modules are available in the frozen app.
core_exts = ["_struct", "zlib", "binascii", "math", "_random", "_hashlib", "_blake2", "_sha3"]
hiddenimports += core_exts

# Explicitly bundle their binaries inside lib-dynload in the app.
ver = f"{sys.version_info.major}.{sys.version_info.minor}"
dynload_dir = Path(sys.executable).resolve().parent.parent / "lib" / f"python{ver}" / "lib-dynload"
for modname in core_exts:
    spec = importlib.util.find_spec(modname)
    if spec and spec.origin:
        binaries.append((str(Path(spec.origin)), f"python{ver}/lib-dynload"))

# Also bundle every file from lib-dynload as binaries to be safe.
if dynload_dir.exists():
    for item in dynload_dir.iterdir():
        if item.is_file():
            binaries.append((str(item), f"python{ver}/lib-dynload"))

# Drop any binaries/datas whose source paths don't exist (avoid CI failures on optional paths).
datas = [(src, dest) for src, dest in datas if Path(src).exists()]
binaries = [(src, dest) for src, dest in binaries if Path(src).exists()]

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
    icon=str(icon_path_ico) if icon_path_ico else None,
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

if is_macos:
    app = BUNDLE(
        coll,
        name="Bout Review.app",
        icon=str(icon_path) if icon_path else None,
        info_plist={
            "CFBundleName": "Bout Review",
            "CFBundleDisplayName": "Bout Review",
            "CFBundleIdentifier": "com.boutreview.app",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
        },
    )
