# Bout Review

Desktop app for reviewing fencing bouts: import videos, mark segments, add notes, and export highlights + chapter timestamps.

## Run (development)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m bout_review
```

On first run, a `bout_review_config.json` is created in the repo root for colors + hotkeys.

## Build macOS app (PyInstaller)

1) Install build deps:
```bash
pip install pyinstaller pillow
```

2) Build:
```bash
pyinstaller BoutReview.spec
```

3) Result:
```
dist/Bout Review.app
```

4) Share with friends:
```bash
ditto -c -k --sequesterRsrc --keepParent "dist/Bout Review.app" "Bout Review.zip"
```
They can unzip and run. On first launch they may need to right-click → Open to bypass Gatekeeper (unsigned app).

### Notes
- The build bundles an FFmpeg binary from `imageio-ffmpeg` so no system FFmpeg install is needed.
- App icon uses `src/bout_review/assets/bout_review_icon.png` at runtime.

## Windows / Linux

PyInstaller builds are OS-specific. To support Windows/Linux you build on each target OS (or use CI runners for each). The spec file can be reused with minor tweaks (icons + metadata).
