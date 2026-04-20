# azure_blob.py — Azure Blob Storage Audio Adapter (Stub)

## What This File Is For
Placeholder for storing session audio files in Azure Blob Storage instead of local disk. In production, you'd upload the WAV file to Azure, then this adapter downloads it to a temp location when diarization needs it.

## What a Real Implementation Would Need
- `azure-storage-blob` Python package
- `AZURE_STORAGE_CONNECTION_STRING` and `AZURE_BLOB_CONTAINER` env vars
- Download the blob to `tempfile.NamedTemporaryFile()`, return that temp path
- Clean up the temp file after diarization completes

**ELI5:** Instead of storing the recording on your laptop, store it in a cloud locker (Azure Blob). When you need it, borrow it from the locker temporarily.

## Key Concepts To Look Up
- Azure Blob Storage — object storage for large files
- `tempfile.NamedTemporaryFile` in Python — safe temporary files
- Context managers (`with` statement) for resource cleanup
