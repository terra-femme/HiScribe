# server.py — The main web server that receives requests and routes them to the right handler

## What This File Is For
This file is the entry point for the entire HiScribe pipeline service. It creates a web server using FastAPI that listens for HTTP requests — such as "run the transcription pipeline" or "approve this session" — and hands each request off to the correct function. Think of it as the front desk of an office: it receives visitors (requests), figures out where they need to go, and directs them accordingly.

## How It Fits In The Project
This file sits at the very top of the pipeline. The Node.js gateway (a separate service) sends HTTP requests to this server. `server.py` imports from `db/sqlite.py` for all database operations and from `graph/pipeline.py` to trigger the processing pipeline. Nothing imports this file — it is the outermost shell that everything else lives inside.

## Line-by-Line Breakdown

### Lines 1–5 — Imports
```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
```
**What it does:** Pulls in the four libraries this file needs: FastAPI (the web framework), CORSMiddleware (a security layer), Pydantic (for validating incoming data), python-dotenv (for reading `.env` files), and the built-in `os` module for file paths.
**Why:** FastAPI is the industry standard for building Python APIs quickly and safely. Pydantic ensures that if a request is missing a required field, the server rejects it automatically with a clear error message before any of your code even runs.
**ELI5:** Imagine you're building with LEGO. These imports are you opening the boxes of pre-built pieces — you didn't have to make the pieces yourself, you just bring them in and start using them.
**Best practice:** Always import only what you need from each library. Wildcard imports like `from fastapi import *` make it hard to know where any given name came from.

---

### Lines 7–8 — Internal imports
```python
from db.sqlite import init_db, get_review_payload, approve_session, remap_segment, edit_segment, delete_segment, add_amendment
from graph.pipeline import run_pipeline
```
**What it does:** Imports all the database helper functions from `db/sqlite.py` and the pipeline runner from `graph/pipeline.py`.
**Why:** Keeping database logic in its own module and importing it here is called separation of concerns. The server file stays thin — it only handles routing, not SQL queries.
**ELI5:** The server is the receptionist. It doesn't fix your computer or do your taxes — it just points you to the right specialist. Importing from other files is how it hands work off.
**Best practice:** If you find yourself writing SQL inside `server.py`, that is a red flag. Move it to `db/sqlite.py`.

---

### Line 10 — Loading environment variables
```python
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'))
```
**What it does:** Reads the `.env` file from one directory above the pipeline folder, and loads all its key=value pairs into the process's environment variables. After this line runs, `os.environ['OPENAI_API_KEY']` will work, for example.
**Why:** API keys and secrets should never be hardcoded in source code. A `.env` file is kept off version control (via `.gitignore`), so secrets stay private.
**ELI5:** Your `.env` file is like a sticky note with your passwords on it that you keep in your desk drawer — not in the code itself, which anyone on the internet might read.
**Best practice:** Always add `.env` to your `.gitignore`. Never commit secrets to git. Use `os.environ.get('KEY')` (not `os.environ['KEY']`) when a variable might be optional, so you get `None` instead of a crash.

---

### Lines 12–19 — Creating the app and configuring CORS
```python
app = FastAPI(title='HiScribe Pipeline', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*']
)
```
**What it does:** Creates the FastAPI application object and adds CORS middleware. CORS (Cross-Origin Resource Sharing) is a browser security rule that normally blocks a web page from calling an API on a different domain. `allow_origins=['*']` disables that restriction.
**Why:** The frontend (a separate web app) runs on a different port or domain than this Python server. Without CORS enabled, the browser would refuse to let the frontend talk to this API.
**ELI5:** Imagine your house has a rule that only family members can enter. CORS is that rule for web requests. Setting `allow_origins=['*']` is like saying "anyone can knock on the door."
**Best practice:** For production in healthcare, replace `['*']` with a specific list of allowed origins, e.g. `['https://app.hiscribe.com']`. Wildcard is fine in development but a security concern when real patient data is involved.

---

### Line 21 — Initialize the database on startup
```python
init_db()
```
**What it does:** Runs the database schema setup once when the server starts. This creates all the tables (sessions, segments, audit_log, etc.) if they don't already exist.
**Why:** Running this at module load time guarantees the database is ready before any request arrives.
**ELI5:** Before opening a restaurant, you make sure all the tables and chairs are set up. `init_db()` sets up the database "furniture."
**Best practice:** `init_db()` uses `IF NOT EXISTS` SQL logic (inside the schema file) so it is safe to call multiple times — it won't wipe your data if tables already exist.

---

### Lines 24–26 — Health check endpoint
```python
@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'hiscribe-pipeline'}
```
**What it does:** Creates an HTTP GET endpoint at `/health` that simply returns a JSON object confirming the server is running.
**Why:** Health checks are used by orchestration tools (like Docker, Kubernetes, or a load balancer) to verify that the service is alive. If `/health` stops returning 200 OK, the infrastructure knows to restart the container.
**ELI5:** It is like a "are you there?" ping. The server responds "yes, I'm here."
**Best practice:** Health endpoints should be fast and dependency-free. Do not put database calls here — if the DB is down, you still want to know the server process itself is running.

---

### Lines 31–37 — Pipeline trigger endpoint
```python
class PipelineRequest(BaseModel):
    session_id: str

@app.post('/pipeline/run')
async def trigger_pipeline(req: PipelineRequest):
    result = await run_pipeline(req.session_id)
    return result
```
**What it does:** Defines a Pydantic model requiring a `session_id` string, then creates a POST endpoint that receives that model and calls `run_pipeline()` with the session ID.
**Why:** The `async def` keyword means Python won't block the server while the pipeline runs — other requests can be handled at the same time. `run_pipeline` is the main processing workflow (transcription → diarization → SOAP mapping → scoring).
**ELI5:** When someone submits an audio session for processing, this is the door they knock on. The server takes the session ID, runs the full pipeline, and returns the result.
**Best practice:** For long-running pipelines, consider returning immediately with a job ID and polling for status rather than waiting for completion. The current design blocks the HTTP connection for the full pipeline duration.

---

### Lines 42–47 — Note retrieval endpoint
```python
@app.get('/session/{session_id}/note')
def get_note(session_id: str):
    payload = get_review_payload(session_id)
    if not payload:
        raise HTTPException(status_code=404, detail='Session not found')
    return payload
```
**What it does:** GET endpoint that looks up the full review payload for a session (segments organized by SOAP section, amendments, etc.) and returns it. Raises a 404 if the session doesn't exist.
**Why:** The `{session_id}` in the URL is a path parameter — FastAPI automatically extracts it and passes it to the function as the `session_id` argument.
**ELI5:** Think of a library catalog: you ask for book number 123, and the librarian either brings it to you or says "we don't have that one."
**Best practice:** Always return proper HTTP status codes. `404 Not Found` is the correct code when a resource doesn't exist. Returning 200 with an empty body is misleading.

---

### Lines 52–60 — Session approval endpoint
```python
class ApproveRequest(BaseModel):
    provider_npi: str
    patient_mrn: str
    visit_type: str

@app.post('/session/{session_id}/approve')
def approve(session_id: str, req: ApproveRequest):
    approve_session(session_id, req.provider_npi, req.patient_mrn, req.visit_type)
    return {'status': 'approved', 'session_id': session_id}
```
**What it does:** Accepts the provider's NPI (a healthcare identifier), patient's MRN (medical record number), and visit type, then marks the session as approved in the database.
**Why:** Medical documentation requires a provider's signature. This endpoint captures that attestation and links it to the clinical identifiers.
**ELI5:** After the doctor reviews the transcript, they press "approve." This endpoint handles that button press.
**Best practice:** In a real deployment, the `provider_npi` should be validated against the authenticated user's token — not just trusted from the request body.

---

### Lines 63–72 — Segment remap endpoint
```python
class RemapRequest(BaseModel):
    session_id: str
    from_section: str
    to_section: str
    provider_id: str

@app.post('/segment/{segment_id}/remap')
def remap(segment_id: str, req: RemapRequest):
    remap_segment(segment_id, req.session_id, req.from_section, req.to_section, req.provider_id)
    return {'status': 'remapped'}
```
**What it does:** Lets a provider move a transcript segment from one SOAP section to another (e.g. from "Assessment" to "Plan").
**Why:** The LLM may misclassify a segment. Providers need to be able to correct this without rerunning the whole pipeline.
**ELI5:** Imagine sorting mail into folders. If a letter ends up in the wrong folder, this endpoint lets you move it to the right one.
**Best practice:** Always log the `from_section` alongside `to_section` in the audit trail so corrections are fully reversible and traceable.

---

### Lines 75–83 — Segment edit endpoint
```python
class EditRequest(BaseModel):
    session_id: str
    corrected_text: str
    provider_id: str

@app.post('/segment/{segment_id}/edit')
def edit(segment_id: str, req: EditRequest):
    edit_segment(segment_id, req.session_id, req.corrected_text, req.provider_id)
    return {'status': 'edited'}
```
**What it does:** Replaces the text of a transcript segment with the provider's corrected version, and logs the change to the audit trail.
**Why:** ASR (automatic speech recognition) makes mistakes. Providers must be able to correct words before approving the note.
**ELI5:** Like using "track changes" in a Word document — the original is saved and the correction is recorded.
**Best practice:** The database function saves the original text before overwriting. This is the correct pattern for medical records, which require audit trails.

---

### Lines 86–94 — Segment delete endpoint
```python
class DeleteRequest(BaseModel):
    session_id: str
    provider_id: str
    reason: str = ''

@app.delete('/segment/{segment_id}')
def delete(segment_id: str, req: DeleteRequest):
    delete_segment(segment_id, req.session_id, req.provider_id, req.reason)
    return {'status': 'deleted'}
```
**What it does:** Permanently removes a segment from the session and logs the deletion with the original text and reason.
**Why:** Sometimes a segment is noise, a side conversation, or irrelevant to the clinical note. Providers need to be able to remove it.
**ELI5:** Like shredding a sticky note you don't need — but keeping a record that you shredded it and why.
**Best practice:** Notice `reason: str = ''` — the default value means `reason` is optional. Pydantic handles optional fields with `= default_value`.

---

### Lines 97–105 — Amendment endpoint
```python
class AmendmentRequest(BaseModel):
    content: str
    soap_section: str
    provider_id: str

@app.post('/session/{session_id}/amendment')
def amendment(session_id: str, req: AmendmentRequest):
    add_amendment(session_id, req.content, req.soap_section, req.provider_id)
    return {'status': 'amendment_added'}
```
**What it does:** Adds a free-text addendum to a session, associated with a specific SOAP section and the provider who wrote it.
**Why:** Providers sometimes need to add context that wasn't spoken aloud — e.g. lab results reviewed after the visit, or clarifying notes.
**ELI5:** Like writing a sticky note and attaching it to an existing document without changing the original document.
**Best practice:** Amendments are stored in a separate `amendments` table, not mixed into `segments`. This cleanly separates what was transcribed from what was added afterward.

## Common Mistakes
1. **Forgetting `async`/`await` when calling async functions.** `trigger_pipeline` uses `async def` and `await` because `run_pipeline` is a coroutine. If you call an async function without `await`, you get a coroutine object back instead of the actual result, and no error is raised.
2. **Returning raw exceptions instead of `HTTPException`.** If `get_note` just returned `None`, FastAPI would serialize it as `null` with a 200 status, which is technically a success. Always raise `HTTPException` with the correct status code.
3. **Mixing Pydantic models and path parameters up.** FastAPI automatically matches function parameter names to path parameters in the URL (like `{session_id}`) and maps the request body to Pydantic model parameters. These are different things and must not be confused.

## Key Concepts To Look Up
- FastAPI path operations and dependency injection
- Pydantic BaseModel validation
- HTTP status codes (200, 404, 422)
- CORS and why browsers enforce it
- Python `async`/`await` and asyncio event loops
- `load_dotenv` and the twelve-factor app methodology for configuration
- REST API design conventions (GET vs POST vs DELETE)
