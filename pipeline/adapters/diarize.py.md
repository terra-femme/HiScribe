# diarize.py — A switchboard that controls which speaker-detection service the pipeline uses

## What This File Is For
This file is a "re-export" adapter — it does not contain any diarization logic itself. Its entire purpose is to import the `diarize` function from one specific provider (currently `pyannote.py`) and re-export it under the same name. This means the rest of the codebase only ever imports from `adapters/diarize.py`, never directly from the provider file. To swap providers, you change one line here.

## How It Fits In The Project
`nodes.py` imports `diarize` from this file (`from adapters.diarize import diarize`). This file then forwards that import to `adapters/pyannote.py`. The commented-out lines show two alternative providers that could be dropped in. This file sits between the pipeline logic and the actual diarization implementation, acting as a seam.

## Line-by-Line Breakdown

### Line 1 — Comment explaining the pattern
```python
# Active re-export — change this ONE LINE to swap diarization provider
```
**What it does:** Documents the intent of this file in plain language.
**Why:** This comment is load-bearing documentation. Without it, a future reader might not understand why this file exists with only one import in it.
**ELI5:** A sticky note on a power strip that says "to switch power sources, unplug from here and plug the new cable in."
**Best practice:** One-line comments explaining *why* a file or pattern exists are more valuable than comments that just restate what the code does. "Change this ONE LINE" is a clear instruction that saves time.

---

### Line 2 — The active import
```python
from .pyannote import diarize
```
**What it does:** Imports the `diarize` function from the `pyannote.py` file in the same directory, making it available as `diarize` from this module.
**Why:** The relative import (`.pyannote`) means "from the same package folder." This keeps the adapters package self-contained.
**ELI5:** This is like plugging a lamp into outlet A. The lamp (pipeline) doesn't care which outlet you use — it just needs power. This line decides which outlet.
**Best practice:** By re-exporting under the same name `diarize`, any code that imports `from adapters.diarize import diarize` works identically regardless of which provider is active. This is the **adapter pattern** in action.

---

### Lines 3–4 — Commented-out alternatives
```python
# from .assemblyai import diarize
# from .google_speech import diarize
```
**What it does:** These lines do nothing right now — they are comments. They document that AssemblyAI and Google Speech are planned alternative providers.
**Why:** Keeping the alternatives as comments is a form of lightweight documentation. It signals to other developers: "you can add these files and switch to them."
**ELI5:** These are like empty hooks on a wall labeled with future pictures you plan to hang.
**Best practice:** If a project grows to have many alternative providers, consider moving this switching logic to a factory function or a configuration-driven registry. For now, a one-line swap is clean enough.

## Common Mistakes
1. **Importing directly from `adapters/pyannote.py` instead of through `adapters/diarize.py`.** If you bypass the adapter and import from `pyannote.py` directly, swapping providers becomes a hunt-and-replace across every file that did so.
2. **Forgetting that both imports must be uncommented at the same time.** Python will raise a `NameError` if two `from .X import diarize` lines are both uncommented and the `diarize` name is defined twice — the second import silently overwrites the first with no error in Python. Make sure only one line is active.
3. **Creating a new provider file but not updating this re-export.** The new file has no effect unless this adapter file points to it.

## Key Concepts To Look Up
- The adapter pattern (software design pattern)
- Python relative imports (dot notation)
- Re-exports and public API surfaces in Python packages
- Speaker diarization — what the problem is that these providers solve
