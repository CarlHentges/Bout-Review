# Bout Review
<img src="src/bout_review/assets/bout_review_icon.png" alt="Bout Review icon" width="300">

Desktop app for reviewing fencing bouts: import videos, mark segments, add notes, and export highlights + chapter timestamps.

## What's new (v1.2)
- Timeline scrubber now jumps to any click position—no more drag-only playhead.
- Export gap fast-forward: optional button under the video to render unselected parts at a chosen speed in the highlights output.
- Cross-platform PyInstaller spec + `scripts/package_release.py` for Windows and Linux zip builds.

## What's new (v1.1)
- Score tracker window (always on top): log Point Left/Right/No Point, optionally auto-increment scores, and drop timestamped comments at the playhead.
- Per-segment playback speed: set slow/fast motion when editing or duplicating segments; speeds carry through to exported clips and stitched highlights.

## Instructions
![Bout Review screenshot](images/image.jpeg)
- Launch the app.
- **Create/open a project**: click *New Project* or *Open Project*, and create a folder where you want the output files to be.
- **Import videos**: Select *Import Videos* and choose files. (If you have multiple videos, drag to reorder them in the display).
- **Play**: select a video; **spacebar** = play/pause, **M** = mute toggle. **Left/Right** arrows scrub seconds; **Shift+Left/Right** step frames.
- **Export gap fast-forward**: button under the video toggles including unselected gaps in the highlights at your chosen speed (default 3×).
- **Mark segments**: To Mark the action, at the start use **I** (Mark In), at end press **O** (Mark Out). Segments appear in the list; double-click to jump.
- **[Optional] Edit/duplicate segments**: select a segment -> Edit segment (start/end/label/speed) or Duplicate segment.
- **[Optional] notes**: move playhead -> Add Comment or Add Chapter; double-click a note to edit timestamp/type/text.
- **[Optional] Score tracker**: toolbar -> Score Tracker (stays on top). Use *Point Left/Right/No Point*; with "*Enable Score*" checked, scores auto-increment and get appended to the comment. You can manually adjust the score boxes anytime.
- **Export**: click *Export*. Outputs go to exports/: `highlights.mp4` (`/clips/` contain individual segments, chapters and notes found in `youtube_chapters.txt`, `comments_timestamps.txt`. )
- **Open exports folder**: toolbar button or *Ctrl+Shift+E*.

## How To Install
Go to the releases page [https://github.com/CarlHentges/Bout-Review/releases](https://github.com/CarlHentges/Bout-Review/releases)

### Mac
- Apple Silicon (M1/M2/M3): download `Bout_Review_Mac-arm64.zip`
- Intel Macs: download `Bout_Review_Mac-x64.zip`

After downloading:
1) Extract the zip and move “Bout Review.app” wherever you like (e.g., Applications).
2) If macOS blocks it, go to *System Settings → Privacy & Security* and choose “Open Anyway”.

### Windows
1) Download `Bout_Review_Windows-x64.zip`
2) Extract the file (portable app). Keep all files together in the folder.
3) Run `Bout Review.exe` (create a desktop shortcut if you like).

### Linux
1) Download `Bout_Review_Linux-x64.zip`
2) Extract the folder.
3) Run `./Bout\\ Review/Bout\\ Review` (mark executable if needed: `chmod +x \"Bout Review/Bout Review\"`).


## Development Notes

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m bout_review
```

On first run, a `bout_review_config.json` is created in the repo root for colors + hotkeys.

### Build releases (Mac / Windows / Linux)

```bash
pip install pyinstaller pillow
pyinstaller BoutReview.spec
python scripts/package_release.py
```

Outputs land in `dist/` as `Bout_Review_<Platform>-<arch>.zip` (e.g., `Bout_Review_Windows-x64.zip`, `Bout_Review_Linux-x64.zip`, `Bout_Review_Mac-arm64.zip`). Run the executable inside the unzipped folder for your OS.

### PyInstaller

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
macOS:   dist/Bout Review.app
Windows: dist/Bout Review/Bout Review.exe
Linux:   dist/Bout Review/Bout Review
```

4) Package for release:
```bash
python scripts/package_release.py
```
This zips the right folder for your platform into `dist/Bout_Review_<Platform>-<arch>.zip`.

### Notes
- The build bundles an FFmpeg binary from `imageio-ffmpeg` so no system FFmpeg install is needed.
- App icon uses `src/bout_review/assets/bout_review_icon.png` at runtime.
