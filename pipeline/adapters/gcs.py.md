# gcs.py — Google Cloud Storage Audio Adapter (Stub)

## What This File Is For
Placeholder for storing session audio files in Google Cloud Storage. The GCP equivalent of `azure_blob.py`.

## What a Real Implementation Would Need
- `google-cloud-storage` Python package
- `GOOGLE_APPLICATION_CREDENTIALS` and `GCS_BUCKET` env vars
- Download blob to temp file, return temp path, clean up after use

**ELI5:** Same as Azure Blob but in Google's cloud instead of Microsoft's.

## Key Concepts To Look Up
- Google Cloud Storage (GCS) — buckets, blobs, signed URLs
- GCS Python client library
