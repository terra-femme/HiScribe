# sqlite.ts — SQLite Storage Adapter (Default)

## What This File Is For
This is the default database adapter for the Node gateway. It uses `better-sqlite3` to read and write sessions and segments to the shared SQLite database. It implements the four functions that `storage.ts` re-exports.

## How It Fits In The Project
`storage.ts` re-exports from this file. `session.ts` calls `saveSession()` and `saveSegment()` during live recording. `note.ts` calls `getSession()`. The Python pipeline reads from the same database file.

---

## Line-by-Line Breakdown

### Line 1 — Import the DB singleton
```typescript
import { db } from '../db/client'
```
**What it does:** Imports the shared database connection from `db/client.ts`.
**Why:** There should be exactly one SQLite connection in the whole gateway. Creating multiple connections to SQLite is wasteful and can cause locking issues. The singleton in `client.ts` ensures one connection is shared everywhere.
**ELI5:** There's one set of keys to the filing cabinet. Everyone who needs to file something borrows the same set of keys.
**Best practice:** Never create a `new Database()` inside a function or route handler. Always use a singleton.

### Lines 3–20 — Type definitions
```typescript
export type SessionRecord = {
  id: string
  status: string
  created_at: string
  ...
}
export type SegmentRecord = {
  session_id: string
  text: string
  ...
}
```
**What it does:** Defines the shape of records stored in and returned from the database.
**Why:** Exporting types from the adapter lets TypeScript enforce that callers use the right field names. If you rename `created_at` to `createdAt`, the compiler tells you everywhere that needs to change.
**Best practice:** DB types should mirror your schema columns. When you add a column to `schema.sql`, add it to the type here too.

### Lines 22–27 — saveSession
```typescript
export async function saveSession(session: SessionRecord): Promise<void> {
  db.prepare(`
    INSERT OR REPLACE INTO sessions (id, status, created_at)
    VALUES (@id, @status, @created_at)
  `).run(session)
}
```
**What it does:** Inserts a new session or replaces it if the ID already exists.
**Why:** `INSERT OR REPLACE` is an upsert — insert if new, overwrite if exists. `@id`, `@status`, `@created_at` are named parameters — `better-sqlite3` maps object properties to these automatically. This prevents SQL injection.
**ELI5:** Filing a new document. If a document with the same ID already exists, replace it.
**Why `async`:** The function is marked async to match the interface that `cosmos_db.ts` and `firestore.ts` need (those will be truly async). `better-sqlite3` is synchronous but the interface is async for consistency.
**Best practice:** Always use parameterized queries (`@param` or `?`). Never concatenate user input into SQL strings — that's SQL injection.

### Lines 29–32 — getSession
```typescript
export async function getSession(id: string): Promise<SessionRecord | null> {
  return (db.prepare('SELECT * FROM sessions WHERE id = ?').get(id) as SessionRecord) ?? null
}
```
**What it does:** Fetches a single session by ID. Returns `null` if not found.
**Why:** `.get()` returns `undefined` if no row matches. The `?? null` converts `undefined` to `null` for a cleaner API (callers check `if (!session)` rather than `if (session === undefined)`).
**Best practice:** The `as SessionRecord` cast tells TypeScript what shape to expect. It's not checked at runtime — the real safety is that your schema matches your type definition.

### Lines 34–40 — saveSegment
```typescript
export async function saveSegment(segment: SegmentRecord): Promise<void> {
  db.prepare(`INSERT INTO segments (...) VALUES (...)`).run({
    ...segment,
    is_final: segment.is_final ? 1 : 0
  })
}
```
**What it does:** Inserts a transcript segment. Converts the boolean `is_final` to 0/1 for SQLite.
**Why:** SQLite has no boolean type — it stores booleans as integers (0 = false, 1 = true). The ternary `? 1 : 0` handles this conversion explicitly.
**ELI5:** SQLite doesn't understand "true/false." It only understands "1/0." This line translates.
**Best practice:** Always be explicit about boolean-to-integer conversion. Don't rely on JavaScript's implicit coercion (`true` → `1`) — it works but isn't obvious to future readers.

### Lines 42–46 — getSegments
```typescript
export async function getSegments(sessionId: string): Promise<SegmentRecord[]> {
  return db.prepare(
    'SELECT * FROM segments WHERE session_id = ? AND is_final = 1 ORDER BY start_ms ASC'
  ).all(sessionId) as SegmentRecord[]
}
```
**What it does:** Returns all finalized segments for a session, ordered by timestamp.
**Why:** `is_final = 1` filters out partial ASR results that were broadcast for live display but shouldn't be in the processed note. `ORDER BY start_ms ASC` ensures segments are in chronological order for the diarization timestamp matching.
**Best practice:** Always filter for `is_final` when retrieving segments for processing. Never process partial results.

---

## Common Mistakes
1. Forgetting the `is_final ? 1 : 0` conversion — SQLite will store `true` as a string, which breaks `is_final = 1` queries.
2. Using `.all()` when you expect one row — use `.get()` for single-row queries. `.all()` on a 1-row result returns an array, not the object.
3. Not ordering by `start_ms` — diarization timestamp matching requires segments in chronological order.

## Key Concepts To Look Up
- `better-sqlite3` vs `sqlite3` (Node packages) — why better-sqlite3 is synchronous
- SQL injection — why parameterized queries matter
- INSERT OR REPLACE (upsert) in SQLite
- SQLite data types — no boolean, no datetime, everything is TEXT/INTEGER/REAL/BLOB
