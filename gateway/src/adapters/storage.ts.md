# storage.ts — Session Storage Adapter Re-Export (The Swap File)

## What This File Is For
One line. This file decides which database the gateway uses for storing sessions and segments. Change one commented line to swap from SQLite to Azure Cosmos DB or GCP Firestore. Nothing else in the codebase changes.

## How It Fits In The Project
`session.ts` and `note.ts` import `saveSession`, `getSession`, `saveSegment`, and `getSegments` from this file. This file re-exports those functions from whichever storage adapter is active.

---

## Line-by-Line Breakdown

### Lines 1–4 — The entire file
```typescript
export { saveSession, getSession, saveSegment, getSegments } from './sqlite'
// export { saveSession, getSession, saveSegment, getSegments } from './cosmos_db'
// export { saveSession, getSession, saveSegment, getSegments } from './firestore'
```
**What it does:** Re-exports four storage functions from the active adapter.
**Why:** The same adapter pattern as `speech.ts`. Routes import from `./storage` (stable path), not from `./sqlite` (concrete implementation). Swap = change one line here.
**ELI5:** Your app orders food from "the kitchen." Whether the kitchen is Italian, Chinese, or Mexican is an internal detail. The menu (the four exported functions) is always the same.
**Best practice:** All three adapters must export the exact same four function names with the same signatures. TypeScript will catch mismatches at compile time.

---

## Common Mistakes
1. Uncommenting a new adapter without commenting out the old one — duplicate export error.
2. Adding a fifth function to `sqlite.ts` but not to `cosmos_db.ts` and `firestore.ts` stubs — the stubs will be missing the function when you swap, causing a runtime error instead of a compile-time one.

## Key Concepts To Look Up
- Named exports vs default exports in TypeScript
- Adapter/repository pattern for database abstraction
