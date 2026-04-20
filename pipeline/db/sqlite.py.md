# sqlite.py — All database read and write operations for the HiScribe pipeline

## What This File Is For
This file is the single point of contact between the pipeline and its SQLite database. Every SQL query in the system lives here. It handles initializing the database schema, reading and writing segments, recording provider edits, and maintaining a tamper-evident audit trail of every action taken on a session. Keeping all SQL in one place means that if the database ever changes, you only have one file to update.

## How It Fits In The Project
`sqlite.py` is imported by both `server.py` (for the review/edit/approve endpoints) and `graph/nodes.py` (for reading and writing segment data during pipeline processing). The training scripts in `models/` also import `_conn` directly to read training data. This file is a shared utility that the rest of the system depends on.

## Line-by-Line Breakdown

### Lines 1–4 — Imports
```python
import sqlite3
import json
import os
from datetime import datetime
```
**What it does:** Imports the four standard library modules needed: `sqlite3` for database access, `json` for serializing audit log payloads, `os` for path handling, and `datetime` for generating timestamps.
**Why:** All four are part of Python's standard library — no installation needed. SQLite3 is the built-in Python database driver.
**ELI5:** These are tools you already own that come with Python. No need to go to the store (pip install) for these.
**Best practice:** Python's built-in `sqlite3` module is perfectly suitable for single-server applications with moderate load. For higher concurrency or larger datasets, a migration to PostgreSQL would be appropriate.

---

### Lines 7–11 — Database and schema paths
```python
_DB_PATH = os.environ.get(
    'DB_PATH',
    os.path.join(os.path.dirname(__file__), '../../data/hiscribe.db')
)
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '../../schema.sql')
```
**What it does:** Defines where the database file lives. First checks if a `DB_PATH` environment variable is set (useful for deployment/testing), then falls back to a default path two directories up from this file. Also defines the path to the SQL schema file.
**Why:** Using `os.environ.get('DB_PATH', default)` makes the database location configurable without changing code. In tests, you can point to an in-memory database or a temp file. In production, you can point to a mounted volume.
**ELI5:** Instead of hardcoding your address, you check a whiteboard first to see if someone wrote a different address. If the board is blank, you use your home address.
**Best practice:** The underscore prefix on `_DB_PATH` and `_SCHEMA_PATH` marks them as module-private constants. This is a soft convention — Python won't stop you from importing them, but it signals "you shouldn't."

---

### Lines 14–19 — The _conn() function
```python
def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.normpath(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn
```
**What it does:** Opens a new SQLite connection each time it is called. `row_factory = sqlite3.Row` makes query results behave like dictionaries (you can access columns by name: `row['segment_id']`). The two PRAGMA statements configure performance and correctness settings.
**Why:** `PRAGMA journal_mode=WAL` (Write-Ahead Logging) allows concurrent reads and writes — readers don't block writers and vice versa. `PRAGMA foreign_keys=ON` enables enforcement of foreign key constraints, which SQLite disables by default for historical reasons.
**ELI5:** `sqlite3.Row` is like giving each result a name tag instead of just a number. Instead of `row[0]`, you can say `row['segment_id']`, which is much clearer.
**Best practice:** This function creates a new connection on every call rather than reusing a shared connection. This is the correct pattern for SQLite — shared connections across threads are dangerous. Use `with _conn() as conn:` to also get automatic transaction commit/rollback.

---

### Lines 22–29 — init_db()
```python
def init_db():
    os.makedirs(os.path.dirname(os.path.normpath(_DB_PATH)), exist_ok=True)
    if os.path.exists(_SCHEMA_PATH):
        with open(_SCHEMA_PATH) as f:
            schema = f.read()
        with _conn() as conn:
            conn.executescript(schema)
        print(f'[db] Schema initialized at {_DB_PATH}')
```
**What it does:** Creates the `data/` directory if it doesn't exist, reads the `schema.sql` file, and runs all the SQL statements in it to set up (or verify) the database tables.
**Why:** `exist_ok=True` prevents a crash if the directory already exists. `executescript()` runs multiple SQL statements at once, which is needed for a schema file that creates many tables.
**ELI5:** Before filling a filing cabinet, you have to make sure the cabinet exists and the folders inside it are set up. This function does that for the database.
**Best practice:** The schema file should use `CREATE TABLE IF NOT EXISTS` so running `init_db()` a second time (e.g. on server restart) doesn't drop existing tables or throw errors.

---

### Lines 32–38 — get_segments()
```python
def get_segments(session_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            'SELECT * FROM segments WHERE session_id = ? AND is_final = 1 ORDER BY start_ms ASC',
            (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]
```
**What it does:** Retrieves all final (not interim/streaming) segments for a session, ordered chronologically by start time. Returns a plain list of dictionaries.
**Why:** The `?` placeholder prevents SQL injection — never use string formatting to insert user data into a SQL query. The `is_final = 1` filter excludes partial transcription results.
**ELI5:** This is a database query that says "give me all finished transcript pieces for this session, oldest first."
**Best practice:** Always use parameterized queries (`?` placeholders) for user-supplied values. `f'WHERE session_id = {session_id}'` is a SQL injection vulnerability — a malicious session ID could delete your entire database.

---

### Lines 41–46 — update_segment_diarization()
```python
def update_segment_diarization(segment_id: str, speaker: str, role_flag: bool):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET speaker = ?, role_flag = ? WHERE segment_id = ?',
            (speaker, 1 if role_flag else 0, segment_id)
        )
```
**What it does:** Updates the `speaker` label and `role_flag` on a specific segment row.
**Why:** SQLite stores booleans as integers (0 or 1). The expression `1 if role_flag else 0` converts Python's `True`/`False` to the integer form SQLite expects.
**ELI5:** Like updating a cell in a spreadsheet — find the row for this segment and change the speaker and flag columns.
**Best practice:** The `with _conn() as conn:` context manager automatically commits the transaction on success and rolls it back on exception. Never forget to commit when writing to a database.

---

### Lines 49–54 — update_segment_mapping()
```python
def update_segment_mapping(segment_id: str, soap_section: str):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET soap_section = ? WHERE segment_id = ?',
            (soap_section, segment_id)
        )
```
**What it does:** Writes the SOAP section assignment to a segment row after the LLM classifies it.
**Why:** Persisting the SOAP section to the database means the mapping survives a server restart and can be queried later without re-running the LLM.
**ELI5:** After sorting the mail into folders, you write the folder name on each envelope in permanent marker.
**Best practice:** Simple, focused functions like this are easy to test in isolation. Each DB function should do exactly one thing.

---

### Lines 57–62 — update_segment_score()
```python
def update_segment_score(segment_id: str, reliability_score: float, confidence_flag: bool):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET reliability_score = ?, confidence_flag = ? WHERE segment_id = ?',
            (reliability_score, 1 if confidence_flag else 0, segment_id)
        )
```
**What it does:** Stores the reliability score and confidence flag on the segment row after the PyTorch model scores it.
**Why:** Persisting the score means the review UI can show reliability indicators without re-running inference on every page load.
**ELI5:** After a teacher grades a test, they write the score on the paper. This function writes the score on the segment's database row.
**Best practice:** Consistency: all three `update_*` functions follow the same pattern — one UPDATE statement, parameterized, inside a `with _conn()` block. This makes the file predictable and easy to navigate.

---

### Lines 65–90 — get_review_payload()
```python
def get_review_payload(session_id: str) -> dict | None:
    with _conn() as conn:
        session = conn.execute(
            'SELECT * FROM sessions WHERE id = ?', (session_id,)
        ).fetchone()
        if not session:
            return None
        segments = conn.execute(
            'SELECT * FROM segments WHERE session_id = ? AND is_final = 1 ORDER BY start_ms ASC',
            (session_id,)
        ).fetchall()
        amendments = conn.execute(
            'SELECT * FROM amendments WHERE session_id = ?', (session_id,)
        ).fetchall()

    soap: dict = {'S': [], 'O': [], 'A': [], 'P': [], 'UNCLASSIFIED': []}
    for seg in segments:
        s = dict(seg)
        section = s.get('soap_section') or 'UNCLASSIFIED'
        soap.setdefault(section, []).append(s)

    return {
        'session': dict(session),
        'soap': soap,
        'amendments': [dict(a) for a in amendments]
    }
```
**What it does:** Assembles the full review payload for a session by joining three queries — session metadata, segments (organized by SOAP section), and amendments. Returns `None` if the session doesn't exist.
**Why:** All three queries are run within a single `with _conn() as conn:` block to ensure consistency — you won't see segments from one database state and the session from another.
**ELI5:** This is like assembling a complete patient chart: you pull the cover sheet (session), then the notes (segments sorted by section), then the addendums (amendments).
**Best practice:** `s.get('soap_section') or 'UNCLASSIFIED'` handles both a missing key AND a `None` value in one expression. Just `s.get('soap_section', 'UNCLASSIFIED')` would not catch the case where the key exists but its value is `None`.

---

### Lines 93–106 — approve_session()
```python
def approve_session(session_id: str, provider_npi: str, patient_mrn: str, visit_type: str):
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        conn.execute(
            '''UPDATE sessions SET status = 'approved', provider_npi = ?, patient_mrn = ?,
               visit_type = ?, approved_at = ? WHERE id = ?''',
            (provider_npi, patient_mrn, visit_type, now, session_id)
        )
        _append_audit(conn, session_id, 'session_approved', payload={...})
```
**What it does:** Updates the session's status to 'approved', stamps the approval timestamp, and links the session to the provider NPI and patient MRN. Also writes an audit log entry.
**Why:** `datetime.utcnow().isoformat()` generates a UTC timestamp in ISO 8601 format (e.g. `2025-06-15T14:30:00`). UTC is the correct choice for medical records — it is unambiguous regardless of time zone.
**ELI5:** This is the digital equivalent of a doctor signing a document with a timestamp.
**Best practice:** Always use UTC for timestamps in databases. Storing local time is error-prone — daylight saving time transitions can create duplicate or missing timestamps.

---

### Lines 109–116 — remap_segment()
```python
def remap_segment(segment_id: str, session_id: str, from_section: str, to_section: str, provider_id: str):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET soap_section = ? WHERE segment_id = ?',
            (to_section, segment_id)
        )
        _append_audit(conn, session_id, 'segment_remapped', segment_id=segment_id, provider_id=provider_id,
                      payload={'from_section': from_section, 'to_section': to_section})
```
**What it does:** Changes the SOAP section of a segment and logs the change including both the old and new sections.
**Why:** Logging `from_section` is essential — without it, you can't know what the LLM originally assigned. The audit trail needs the full before/after picture.
**ELI5:** Moving a folder from one cabinet to another and writing in a logbook: "Moved folder X from cabinet A to cabinet B."
**Best practice:** Notice that both the UPDATE and the audit insert happen inside the same `with _conn() as conn:` block. This means they are in the same transaction — if the audit insert fails, the UPDATE is also rolled back. This is atomicity.

---

### Lines 119–131 — edit_segment()
```python
def edit_segment(segment_id: str, session_id: str, corrected_text: str, provider_id: str):
    with _conn() as conn:
        original = conn.execute(
            'SELECT text FROM segments WHERE segment_id = ?', (segment_id,)
        ).fetchone()
        original_text = original['text'] if original else ''

        conn.execute(
            'UPDATE segments SET text = ? WHERE segment_id = ?',
            (corrected_text, segment_id)
        )
        _append_audit(conn, session_id, 'segment_edited', segment_id=segment_id, provider_id=provider_id,
                      payload={'original_text': original_text, 'corrected_text': corrected_text})
```
**What it does:** Reads the original text first, then overwrites it with the correction, then logs both versions to the audit trail.
**Why:** Medical documentation requires a permanent record of what was changed and what it used to say. You cannot simply overwrite without preserving the original.
**ELI5:** Like a legal document with a "redline" — you can see both the original text and what it was changed to.
**Best practice:** Reading the original text before updating (within the same connection/transaction) ensures that the audit log captures the true original, not a previously edited version.

---

### Lines 134–143 — delete_segment()
```python
def delete_segment(segment_id: str, session_id: str, provider_id: str, reason: str = ''):
    with _conn() as conn:
        row = conn.execute(
            'SELECT text FROM segments WHERE segment_id = ?', (segment_id,)
        ).fetchone()
        deleted_text = row['text'] if row else ''

        conn.execute('DELETE FROM segments WHERE segment_id = ?', (segment_id,))
        _append_audit(conn, session_id, 'segment_deleted', ...)
```
**What it does:** Reads the segment's text before deleting it, performs the deletion, and logs the deleted content and reason to the audit trail.
**Why:** Even deleted records must be auditable in healthcare systems. The audit log captures what was deleted and by whom, satisfying regulatory requirements.
**ELI5:** Like shredding a document but keeping a photocopy in a secure file along with a note about why it was shredded.
**Best practice:** Hard deletes (physical removal from the table) are used here. An alternative is a soft delete: setting `is_deleted = 1` instead of running `DELETE`. Soft deletes are recoverable; hard deletes are not. For medical records, either approach works as long as the audit trail is complete.

---

### Lines 146–153 — add_amendment()
```python
def add_amendment(session_id: str, content: str, soap_section: str, provider_id: str):
    with _conn() as conn:
        conn.execute(
            'INSERT INTO amendments (session_id, content, soap_section, provider_id) VALUES (?, ?, ?, ?)',
            (session_id, content, soap_section, provider_id)
        )
        _append_audit(conn, session_id, 'amendment_added', ...)
```
**What it does:** Inserts a new amendment row and logs the action. Amendments live in a separate table from segments.
**Why:** Amendments are addenda — provider-authored additions after the fact. They are structurally different from transcribed segments and should not be mixed with them.
**ELI5:** Instead of writing on the existing page, the provider adds a new sticky note labeled "Addendum." This function creates that sticky note.
**Best practice:** Using a separate `amendments` table rather than a flag on the `segments` table keeps the schema clean and queries simple.

---

### Lines 156–162 — _append_audit()
```python
def _append_audit(conn, session_id: str, event_type: str, segment_id: str = None,
                  provider_id: str = None, payload: dict = None):
    conn.execute(
        '''INSERT INTO audit_log (session_id, event_type, segment_id, provider_id, payload)
           VALUES (?, ?, ?, ?, ?)''',
        (session_id, event_type, segment_id, provider_id, json.dumps(payload or {}))
    )
```
**What it does:** A private helper that inserts one row into the `audit_log` table. Takes the existing open `conn` as a parameter so it runs inside the caller's transaction.
**Why:** Accepting `conn` rather than creating a new connection is critical — it means the audit insert and the data change (edit/delete/approve) are in the same atomic transaction. If the server crashes between the two operations, both are rolled back, not just one.
**ELI5:** This is the logbook writer. Every time something important happens, this function writes it down: who did it, what was done, and all the details.
**Best practice:** `payload or {}` avoids passing `None` to `json.dumps()`, which would serialize as the string `"null"` instead of `"{}"`. Small defensive coding habits like this prevent subtle bugs.

## Common Mistakes
1. **Using string formatting in SQL instead of parameterized queries.** `f"WHERE id = '{session_id}'"` is a SQL injection vulnerability. Always use `?` placeholders.
2. **Forgetting that SQLite booleans are integers.** `True` is stored as `1` and `False` as `0`. When you read a boolean back from SQLite, you'll get an integer, not a Python `bool`. Use `bool(row['role_flag'])` when you need an actual boolean.
3. **Opening separate connections for a data change and its audit log entry.** If the audit insert is in a different connection from the data change, they are in different transactions. A crash between them leaves the database in an inconsistent state. Always pass the same `conn` to `_append_audit`.

## Key Concepts To Look Up
- SQL parameterized queries and SQL injection
- SQLite WAL (Write-Ahead Logging) mode
- ACID database transactions (Atomicity, Consistency, Isolation, Durability)
- ISO 8601 datetime format and why UTC matters
- Python context managers (`with` statement) and how SQLite uses them
- Audit trails in healthcare and HIPAA requirements
- Soft delete vs hard delete patterns
