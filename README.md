# Bout-Review

Bout-Review is a minimal desktop app for reviewing fencing bouts. Create a project, import one or more videos, mark the keep ranges, add timestamped notes and YouTube chapters, then export a stitched highlights reel plus chapter/comment text files.

## Features

- Project-based workflow with a predictable folder layout
- Import multiple videos into a project
- Mark keep segments with hotkeys (I / O)
- Add notes: `comment` and `chapter`
- Export:
  - `exports/highlights.mp4`
  - `exports/clips/<label>.mp4`
  - `exports/youtube_chapters.txt`
  - `exports/comments_timestamps.txt`
- Uses bundled ffmpeg via `imageio-ffmpeg`

## Installation

Requirements:
- Python 3.11+

Create a virtual environment and install:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
```

If you want to run without installing the package:

```bash
PYTHONPATH=src python -m bout_review
```

## Usage

Launch the app:

```bash
python -m bout_review
# or
bout-review
```

Workflow:
1. **New Project** → choose a project folder (creates `project.json`, `videos/`, `exports/`).
2. **Import Videos** → copies files into `project/videos/`.
3. Review footage and mark segments with **I** (mark in) and **O** (mark out).
4. Add notes:
   - **Ctrl+Shift+C** for `comment`
   - **Ctrl+Shift+H** for `chapter`
5. **Export** (Ctrl+E) to generate highlights, clips, and text outputs.

Hotkeys:
- `Space`: Play/Pause
- `I`: Mark In
- `O`: Mark Out
- `Ctrl+Shift+C`: Add Comment
- `Ctrl+Shift+H`: Add Chapter
- `Ctrl+E`: Export
- `Ctrl+I`: Import Videos
- `Ctrl+N`: New Project
- `Ctrl+O`: Open Project

## Project layout

```
MyProject/
  project.json
  videos/
    bout_01.mp4
  exports/
    highlights.mp4
    youtube_chapters.txt
    comments_timestamps.txt
    clips/
      E1.mp4
    logs/
      ffmpeg_export.log
```

## Notes

- `imageio-ffmpeg` provides the ffmpeg binary used for export.
- If ffprobe is not found, set `FFPROBE_PATH` to a specific executable.
- YouTube chapter rules are validated on export; the app will warn if they are not met.
