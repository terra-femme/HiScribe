# audio_storage.py — Audio File Path Adapter Re-Export

## What This File Is For
One line. Returns the file path for a session's WAV audio file. The default is local disk; Azure Blob Storage and GCP Cloud Storage are the swap-in options when you're ready to move audio to the cloud.

## How It Fits In The Project
`diarize_node` in `nodes.py` needs to know where the audio file is. It imports `get_audio_path` from this file. Swapping to cloud storage = change one line here, implement the blob download in `azure_blob.py`, and the node code stays identical.

---

## Line-by-Line Breakdown

```python
from .local_disk import get_audio_path
# from .azure_blob import get_audio_path
# from .gcs import get_audio_path
```

**What it does:** Re-exports `get_audio_path` from the active storage adapter.
**Why:** The same adapter/re-export pattern used throughout the project. The node that needs the audio path doesn't care where the file comes from — local disk, Azure, or GCP.
**ELI5:** "Where is the audio file?" — this file answers that question, regardless of whether the file is on your laptop or in the cloud.
**Best practice:** The function signature `get_audio_path(session_id: str) -> str` must be the same in all three adapters. For cloud adapters, the function would download the file to a temp location and return that local path — the node still gets a local file path either way.

## Key Concepts To Look Up
- Adapter pattern in Python
- Cloud object storage — Azure Blob, GCP Cloud Storage
- Temporary files in Python (`tempfile` module) — for cloud adapter downloads
