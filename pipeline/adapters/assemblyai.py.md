# assemblyai.py — AssemblyAI Diarization Adapter (Stub)

## What This File Is For
Placeholder for AssemblyAI diarization. AssemblyAI is a cloud speech API with HIPAA-eligible diarization — the production upgrade path when pyannote's offline accuracy isn't sufficient or when you need a signed BAA for compliance.

## Why AssemblyAI Over pyannote For Production
- HIPAA-eligible with a signed Business Associate Agreement
- Handles more than 2 speakers cleanly
- No GPU required (cloud-based inference)
- Better accuracy on noisy recordings
- Disadvantage: PHI leaves your device (requires trust + compliance docs)

## What a Real Implementation Would Need
- `assemblyai` Python package
- `ASSEMBLYAI_API_KEY` environment variable
- Upload the WAV file to AssemblyAI, poll for diarization results, return in the same format as `pyannote.py`: `[{ start_ms, end_ms, speaker_label }]`

**ELI5:** pyannote is the free intern who works offline. AssemblyAI is the professional contractor you hire when you need guaranteed quality and a signed compliance form.

## Key Concepts To Look Up
- HIPAA Business Associate Agreement (BAA) — what it is and why it matters for healthcare AI
- AssemblyAI speaker diarization API docs
- Polling vs webhook patterns for async cloud APIs
