# local_disk.py — Local Disk Audio Storage (Default)

## What This File Is For
Returns the file path for a session's WAV audio file stored on the local disk. Simple and direct — the file lives at `data/audio/{session_id}.wav` relative to the project root.

## How It Fits In The Project
`audio_storage.py` re-exports `get_audio_path` from this file by default. The Node gateway's `audioStorage.ts` writes the WAV file to this exact location. The Python pipeline reads it from here.

---

## Line-by-Line Breakdown

```python
import os

AUDIO_DIR = os.path.join(os.path.dirname(__file__), '../../data/audio')

def get_audio_path(session_id: str) -> str:
    return os.path.normpath(os.path.join(AUDIO_DIR, f'{session_id}.wav'))
```

**`os.path.dirname(__file__)`**
**What it does:** Gets the directory of this file (`pipeline/adapters/`).
**Why:** Using `__file__` makes the path relative to the file's location, not to wherever you run the server from. `../../data/audio` navigates up to `pipeline/`, then up to `HiScribe/`, then into `data/audio/`.
**ELI5:** "I'm in room 204. Go down two floors and into the storage room."
**Best practice:** Always compute paths relative to `__file__` in Python modules. Never use `os.getcwd()` for module-internal paths.

**`os.path.normpath()`**
**What it does:** Cleans up the path — resolves `..` segments, removes double slashes, uses the correct separator for the OS.
**Why:** Without `normpath`, the path has literal `../../` in it. On Windows, this can cause issues with some file APIs.
**Best practice:** Always `normpath` computed paths before using them with file I/O.

## Key Concepts To Look Up
- `__file__` in Python — the current module's file path
- `os.path` vs `pathlib.Path` — two ways to handle paths in Python
- Relative vs absolute file paths
