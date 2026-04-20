# pyannote.py — Runs offline speaker diarization using the pyannote.audio library

## What This File Is For
This file contains the concrete implementation of speaker diarization for HiScribe. It loads a pretrained deep learning model from HuggingFace called `pyannote/speaker-diarization-3.1`, runs it on a session's audio file, and returns a list of time windows indicating who was speaking and when. Crucially, this runs entirely on-device — no audio data is sent to any external server.

## How It Fits In The Project
This file is imported by `adapters/diarize.py` (the switchboard adapter), which re-exports its `diarize` function. `graph/nodes.py` calls `diarize(audio_path)` in the `diarize_node` step of the pipeline. This is one of two speaker-identification systems — the other is the TensorFlow role classifier in `models/role_classifier/`.

## Line-by-Line Breakdown

### Lines 1–2 — Imports
```python
from pyannote.audio import Pipeline
import os
```
**What it does:** Imports `Pipeline` from the `pyannote.audio` package — this is the main class that wraps the pre-trained speaker diarization model. Also imports `os` for reading environment variables.
**Why:** `pyannote.audio` is a well-established open-source library built on PyTorch specifically for speaker analysis tasks. It handles all the deep learning complexity — you just call it with an audio file.
**ELI5:** You're hiring a specialist. Instead of building the machine yourself, you import pyannote (the expert) and hand them the audio file.
**Best practice:** The `Pipeline` class in pyannote wraps a full neural network pipeline. Loading it is expensive (takes several seconds). This is why the code uses a lazy-load pattern (load once, reuse forever) rather than loading on every call.

---

### Lines 4–8 — Comments explaining privacy and setup
```python
# DEFAULT diarization — offline, no PHI leaves the device
# Requires a HuggingFace token to download the model on first run
# Get one at: https://huggingface.co/pyannote/speaker-diarization-3.1
```
**What it does:** Documents the privacy model and the setup requirement.
**Why:** In healthcare, PHI (Protected Health Information) regulations are paramount. Calling a cloud API with patient audio would require a HIPAA Business Associate Agreement. Running the model locally avoids this entirely.
**ELI5:** The difference between whispering a secret to a friend in the room vs shouting it on a phone call. Local inference keeps the secret in the room.
**Best practice:** Always document your privacy posture in comments near the model loading code. Future developers need to know why a local model was chosen over a potentially more accurate cloud service.

---

### Line 8 — Module-level pipeline variable
```python
_pipeline = None
```
**What it does:** Initializes the pipeline variable to `None` at module load time. The actual model is not loaded yet.
**Why:** Loading the pyannote pipeline takes significant time and memory. You don't want to load it when Python imports the module — only when it is actually needed. This is the lazy initialization pattern.
**ELI5:** You keep a placeholder on your desk that says "phone" rather than keeping the actual phone out until you need to make a call.
**Best practice:** Module-level mutable state (`_pipeline = None` that gets reassigned) is a common pattern in Python for expensive singletons. The underscore prefix signals it is private to this module.

---

### Lines 10–17 — _load() function
```python
def _load():
    global _pipeline
    hf_token = os.environ.get('HUGGINGFACE_TOKEN')
    _pipeline = Pipeline.from_pretrained(
        'pyannote/speaker-diarization-3.1',
        use_auth_token=hf_token
    )
    print('[pyannote] Model loaded')
```
**What it does:** Declares a `global` intent to modify `_pipeline`, reads the HuggingFace token from the environment, and downloads/loads the pretrained model. The token is required to accept pyannote's terms of use on HuggingFace.
**Why:** `global _pipeline` is needed because Python's scoping rules mean that assigning to a variable inside a function creates a new local variable, not modifying the outer one. `global` explicitly says "I mean the module-level variable."
**ELI5:** Imagine you have a shared whiteboard (the module variable). When you work in your office (the function), normally you get your own private notepad. Writing `global` is like saying "no — I mean the shared whiteboard."
**Best practice:** `os.environ.get('HUGGINGFACE_TOKEN')` returns `None` if the variable isn't set. `Pipeline.from_pretrained` with a `None` token will raise a clear error, which is acceptable behavior — the server won't start correctly until the token is configured.

---

### Lines 20–38 — diarize() function
```python
def diarize(audio_path: str) -> list[dict]:
    """
    Run 2-speaker diarization on the session audio file.
    Returns: [{ start_ms, end_ms, speaker_label }]
    """
    global _pipeline
    if _pipeline is None:
        _load()

    diarization = _pipeline(audio_path, num_speakers=2)

    windows = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        windows.append({
            'start_ms': int(turn.start * 1000),
            'end_ms': int(turn.end * 1000),
            'speaker_label': speaker   # 'SPEAKER_00' or 'SPEAKER_01'
        })

    return windows
```
**What it does:** The public function of this file. Lazy-loads the model if not already loaded, then runs diarization on the audio file. Iterates over the resulting "turns" (speaker change events) and converts them to a plain list of dictionaries with millisecond timestamps.
**Why:** `num_speakers=2` tells pyannote there are exactly two speakers (doctor and patient). This constraint makes the model more accurate than letting it guess the speaker count. `turn.start` and `turn.end` are in seconds — multiplying by 1000 and converting to `int` gives milliseconds, which matches the `segments` table in the database.
**ELI5:** The model watches the audio and says "from 0 to 15 seconds, SPEAKER_00 is talking. From 15 to 22 seconds, SPEAKER_01 is talking." This function collects all those time-windows into a list.
**Best practice:** The `_` in `for turn, _, speaker in ...` is a Python convention meaning "I know this is the second value but I don't need it." Using `_` instead of a real variable name signals intentionally ignoring that value.

### Diarization output format detail
```python
{
    'start_ms': int(turn.start * 1000),
    'end_ms': int(turn.end * 1000),
    'speaker_label': speaker   # 'SPEAKER_00' or 'SPEAKER_01'
}
```
**What it does:** Converts pyannote's internal `Segment` objects into plain Python dicts with keys the rest of the codebase expects.
**Why:** Returning pyannote-specific objects to the rest of the pipeline would create a tight dependency on pyannote's internal types. Returning plain dicts means the adapter layer truly abstracts the provider — swapping to AssemblyAI just requires returning the same dict shape.
**ELI5:** No matter which contractor installs your pipes (pyannote, Google, AssemblyAI), the water coming out should look and work the same way.
**Best practice:** Always define and document the output contract of an adapter function (as done in the docstring). Any future provider must return the same shape.

## Common Mistakes
1. **Not setting `HUGGINGFACE_TOKEN` in the environment.** The first time you run this, pyannote downloads the model from HuggingFace. Without a valid token (and having accepted the model's terms on HuggingFace's website), the download will fail with a `401 Unauthorized` error.
2. **Passing `num_speakers=2` when sessions might have more than 2 speakers.** If a session includes a nurse, family member, or student, forcing 2 speakers will cause incorrect assignments. The value should be configurable.
3. **Confusing `SPEAKER_00`/`SPEAKER_01` with DOCTOR/PATIENT.** Pyannote only knows "there are two speakers" — it cannot tell you which is the doctor. That mapping is done downstream in `role_classify_node` and the role classifier model.

## Key Concepts To Look Up
- Speaker diarization — the task of identifying "who spoke when"
- HuggingFace model hub and pretrained model loading
- pyannote.audio library documentation
- Lazy initialization pattern (also called "lazy loading")
- The `global` keyword in Python and function scope
- PHI (Protected Health Information) and HIPAA local processing requirements
- Milliseconds vs seconds in audio timestamps
