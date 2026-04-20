# firestore.ts — GCP Firestore Storage Adapter (Stub)

## What This File Is For
A placeholder for the Google Cloud Firestore storage adapter. All four functions throw immediately. Exists to define the contract and make the swap path clear.

## How It Fits In The Project
`storage.ts` has a commented-out line pointing to this file. Uncomment it, implement the four functions, and the gateway switches to Firestore with no other code changes.

---

## What a Real Implementation Would Need
- `@google-cloud/firestore` npm package
- `GOOGLE_APPLICATION_CREDENTIALS` env var (path to a service account JSON file)
- `GCP_PROJECT_ID` env var
- A Firestore database created in the GCP console

## Why This Stub Exists
Same reason as `cosmos_db.ts` — it's a placeholder that makes the swap path explicit and gives you a clear implementation target.

**ELI5:** A blueprint for a room that hasn't been built yet. The blueprint tells you exactly what the room needs, even though it's empty right now.

## Key Concepts To Look Up
- Google Cloud Firestore — real-time NoSQL database
- GCP service accounts and credentials
- Document vs collection model in Firestore
