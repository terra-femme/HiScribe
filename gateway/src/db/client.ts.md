# client.ts — SQLite Singleton + Schema Initialization

## What This File Is For
Creates one database connection that the entire gateway shares, enables performance settings, and runs the schema on first boot to create tables if they don't exist. This file runs once when the server starts.

## How It Fits In The Project
`sqlite.ts` imports `db` from this file. Every DB operation in the gateway goes through this single connection. The database file itself is shared with the Python pipeline — both layers read and write the same `hiscribe.db`.

---

## Line-by-Line Breakdown

### Lines 1–5 — Imports
```typescript
import Database from 'better-sqlite3'
import path from 'path'
import fs from 'fs'
import dotenv from 'dotenv'
```
**What it does:** Imports the SQLite driver, path utilities, file system access, and env var loader.
**Why:** `better-sqlite3` is used over the older `sqlite3` package because it's synchronous (simpler code, no callbacks/promises needed for DB operations), faster, and has a cleaner API.
**ELI5:** `better-sqlite3` is a newer, better-designed filing cabinet system. It does the same job but faster and without the clunky paperwork.
**Best practice:** Prefer `better-sqlite3` for Node applications that don't need concurrent async DB access. The synchronous API eliminates an entire class of async bugs.

### Lines 7–8 — Resolve DB path
```typescript
const DB_PATH = process.env.DB_PATH
  ? path.resolve(__dirname, '../../../../', process.env.DB_PATH)
  : path.resolve(__dirname, '../../../../data/hiscribe.db')
```
**What it does:** Gets the database file path from the env var, or falls back to a default path.
**Why:** The `../../../../` navigates from `gateway/src/db/` up to the `HiScribe/` root, then into `data/`. The env var override lets you point to a different database in tests or Docker environments without changing code.
**ELI5:** "Where is the filing cabinet?" — check if someone told you a specific location, otherwise go to the default location.
**Best practice:** Always resolve paths from `__dirname`, not from the current working directory (`process.cwd()`). The working directory changes depending on where you run the command from. `__dirname` is always the directory of the file, regardless.

### Line 12 — Ensure data directory exists
```typescript
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true })
```
**What it does:** Creates the `data/` directory if it doesn't exist. Won't throw if it already exists.
**Why:** `better-sqlite3` throws if you try to open a DB file in a directory that doesn't exist. `recursive: true` creates the full path including parent directories, and does nothing if the directory already exists.
**ELI5:** Before you try to file something, make sure the filing cabinet drawer exists. If it doesn't, create it.
**Best practice:** Always ensure directories exist before writing files. Never rely on them being present from a previous run.

### Lines 14–16 — Create the connection + pragmas
```typescript
export const db = new Database(DB_PATH)
db.pragma('journal_mode = WAL')
db.pragma('foreign_keys = ON')
```
**What it does:** Opens the database connection and sets two important SQLite settings.
**Why — WAL mode:** WAL (Write-Ahead Logging) allows readers and writers to coexist without blocking each other. This is critical because the Python pipeline reads the DB while the Node gateway is actively writing new segments. Without WAL, the pipeline's read would block until the gateway finishes writing, causing delays.
**Why — foreign_keys ON:** SQLite doesn't enforce foreign key constraints by default — you have to opt in. `ON` means if you try to insert a segment with a `session_id` that doesn't exist in the `sessions` table, SQLite will reject it.
**ELI5:** WAL is like a library that lets you read books while someone else is returning new ones. Foreign keys are like requiring that you can only file something in a drawer that actually exists.
**Best practice:** Always set both pragmas. WAL is essentially free performance for concurrent access. Foreign keys are data integrity — without them, you can silently accumulate orphaned records.

### Lines 18–23 — Run schema
```typescript
if (fs.existsSync(SCHEMA_PATH)) {
  const schema = fs.readFileSync(SCHEMA_PATH, 'utf-8')
  db.exec(schema)
}
```
**What it does:** Reads `schema.sql` and runs it against the database.
**Why:** The schema uses `CREATE TABLE IF NOT EXISTS` — so running it on an existing database is safe. It only creates tables that don't already exist. This means the same code handles both "first boot ever" and "server restarted."
**ELI5:** Every time the server starts, it checks its own rulebook (schema.sql). If the tables in the rulebook don't exist yet, it creates them. If they already exist, it does nothing.
**Best practice:** Always use `CREATE TABLE IF NOT EXISTS` in schema files you run on boot. Never use `CREATE TABLE` without `IF NOT EXISTS` — it will throw an error on the second boot.

---

## Common Mistakes
1. Creating `new Database()` inside a route handler — creates a new connection per request, exhausting file handles and losing the WAL benefits.
2. Forgetting WAL mode when the Python pipeline runs simultaneously — the gateway and pipeline will block each other on reads/writes, causing intermittent slowdowns.
3. Resolving paths with `process.cwd()` — breaks when the server is started from a different directory (e.g., `node gateway/src/server.js` vs `cd gateway && node src/server.js`).

## Key Concepts To Look Up
- SQLite WAL (Write-Ahead Logging) — how it enables concurrent reads
- SQLite pragmas — how to configure SQLite behavior at runtime
- Singleton pattern — why one shared connection is better than many
- `__dirname` in Node.js
- Foreign key constraints in SQLite — why they're off by default
