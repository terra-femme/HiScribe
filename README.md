# HiScribe

**Ambient Clinical Scribe — Real-Time Two-Speaker Documentation Pipeline**

HiScribe listens passively during a doctor-patient visit, transcribes both voices in real time, separates who said what, and maps the conversation into a structured SOAP note for the provider to review. The provider has full control over every word before anything enters a record.

> **The LLM does not write clinical notes. It maps existing speech to chart sections.**
> Nothing enters the chart without explicit provider approval.

---

## The Problem It Solves

Physicians spend an estimated **49% of their time on EHR documentation** — more time than they spend with patients. After-hours charting ("pajama time") is one of the leading drivers of clinical burnout.

HiScribe eliminates the typing entirely:

1. Doctor and patient talk normally
2. HiScribe listens, transcribes, and separates the voices
3. A 6-node ML pipeline maps the transcript to a SOAP note
4. The provider reviews, corrects if needed, and approves in under 90 seconds
5. A FHIR-compliant document is generated with a sealed audit trail

---

## Core Design Principle — Human In The Loop

Every decision in this system is designed around one constraint: **the provider is the final authority, not the model.**

- The LLM maps segments to sections — it never generates, paraphrases, or summarizes
- No segment enters a chart section without the provider seeing it
- Every edit, remap, deletion, and amendment is permanently logged
- The audio is always available for any disputed segment
- Approval is an explicit action — there is no auto-submit
- The approve button is disabled until required metadata is filled

---

## Architecture Overview

```
Browser (React + TypeScript)
        │
        │  PCM audio over WebSocket
        │  SSE transcript stream back
        ▼
Node / TypeScript Gateway (Fastify)       ← all browser communication
        │
        ├── adapters/speech.ts            ← ASR (Auto Speech Rec = Gladia default)
        └── adapters/storage.ts           ← session DB (SQLite default)
        │
        │  HTTP → POST /pipeline/run
        ▼
Python Pipeline (FastAPI + LangGraph)     ← all ML and processing
        │
        ├── adapters/diarize.py           ← diarization (pyannote default)
        ├── adapters/llm.py               ← LLM mapping (OpenAI default)
        ├── adapters/audio_storage.py     ← audio files (local disk default)
        ├── models/confidence_rescorer/   ← PyTorch: per-segment reliability score
        └── models/role_classifier/       ← TensorFlow/Keras: DOCTOR vs PATIENT
```

Every external service is behind a single re-export adapter. Swapping any provider = **change one commented line**. No rework required.

---

## Session Flow

```
Provider opens /session
        │  POST /session/start → session_id created in DB
        ▼
Visit begins — mic opens in browser
        │  PCM audio → WebSocket → Node gateway → Gladia (real-time ASR)
        │  Segments stream back via SSE → LiveCapture.tsx (color-coded live)
        │  Raw audio saved to disk for post-session diarization
        ▼
Provider clicks "End Session"
        │  POST /session/:id/end → Node gateway → Python pipeline triggered
        ▼
LangGraph pipeline (~10–20 seconds)
        ├── FinalizeNode     load all final segments, order by timestamp
        ├── DiarizeNode      pyannote assigns SPEAKER_0 / SPEAKER_1 labels
        ├── RoleClassifyNode TF Keras cross-checks labels (DOCTOR vs PATIENT)
        │                    flags disagreements for provider review
        ├── MapNode          LLM assigns each segment → S / O / A / P
        ├── ScoreNode        PyTorch reliability score per segment
        │                    < 0.6 → flagged yellow in review UI
        └── PackageNode      builds review payload, notifies client via SSE
        ▼
Provider Review Screen (SOAPReview.tsx)
        │  4 SOAP sections visible simultaneously
        │  Flagged segments highlighted (confidence flag + role flag)
        │  Full CRUD: re-map / edit / amend / delete / audio playback
        │  Metadata fields (NPI, MRN, visit type) gate the approve button
        ▼
Provider clicks Approve
        │  POST /session/:id/approve
        │  FHIR Composition JSON generated
        │  Audit trail finalized and sealed
        └── Stored to SQLite
```

---

## Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Client | React 18 + TypeScript + Vite | Browser UI — live capture + SOAP review |
| Gateway | Node.js + TypeScript + Fastify | Browser comms — WebSocket, SSE, REST |
| Pipeline | Python + FastAPI + LangGraph | ML pipeline — diarization, LLM mapping, scoring |
| ASR (default) | Gladia | Real-time word-by-word transcription |
| Diarization (default) | pyannote.audio | Offline 2-speaker separation |
| LLM (default) | OpenAI gpt-4o-mini | SOAP section classification only |
| ML: confidence | PyTorch | Per-segment reliability scorer |
| ML: role | TensorFlow / Keras | DOCTOR vs PATIENT acoustic classifier |
| Storage | SQLite (shared) | Sessions, segments, audit log, amendments |
| Audio | Local disk | Raw WAV files per session (for diarization) |

---

## Swappable Components

Change **one line** in the adapter re-export file to swap any provider:

| Component | Default (free/offline) | Azure swap-in | GCP swap-in |
|-----------|----------------------|---------------|-------------|
| ASR | Gladia | Azure Speech Services | Google STT |
| Session storage | SQLite | Azure Cosmos DB | Firestore |
| Diarization | pyannote.audio | AssemblyAI (HIPAA-eligible) | Google STT built-in |
| LLM mapping | OpenAI gpt-4o-mini | Azure OpenAI | Vertex AI Gemini |
| Audio storage | Local disk | Azure Blob Storage | Google Cloud Storage |

---

## SOAP Note — What The LLM Does and Does Not Do

SOAP is the standard format for a clinical visit note:

| Section | Contains | Source |
|---------|----------|--------|
| **S — Subjective** | What the patient says: symptoms, complaints | Patient speech |
| **O — Objective** | What the clinician observes: vitals, exam findings | Doctor speech |
| **A — Assessment** | Clinical judgment: diagnosis or differential | Doctor speech |
| **P — Plan** | What happens next: medications, referrals, follow-up | Doctor speech |

**What the LLM does:** reads each diarized segment and asks "which SOAP section does this belong in?" Returns section labels only.

**What the LLM never does:** paraphrase, summarize, rewrite, combine segments, generate clinical language, or fill in gaps.

The raw words the provider and patient spoke appear in the note exactly as spoken.

---

## Audit Trail

The audit log is **append-only** — no UPDATE or DELETE ever runs on it. Every provider action is permanently recorded:

| Event | Triggered by |
|-------|-------------|
| `segment_created` | ASR + diarization produces a finalized segment |
| `segment_remapped` | Provider drags segment to different SOAP section |
| `segment_edited` | Provider corrects a transcription error |
| `segment_deleted` | Provider removes a segment |
| `amendment_added` | Provider adds clinical info not in the transcript |
| `session_approved` | Provider clicks Approve |
| `fhir_generated` | FHIR document created post-approval |

### Edit vs Amendment — Legal Distinction

**Edit** — corrects what the ASR heard. The spoken word was X, the transcript says Y, the provider fixes it to X. Original ASR text preserved in the audit log.

**Amendment** — adds new clinical information not captured in the recording. Stored separately, clearly marked `[AMENDMENT]`, with provider ID and timestamp. In litigation these are treated as different acts — the system enforces the distinction at the data layer.

---

## Guardrails

| Guardrail | Location | What It Prevents |
|-----------|----------|-----------------|
| Approve button disabled | `SOAPReview.tsx` | Missing NPI, MRN, or visit type |
| Flagged segment warning | `SOAPReview.tsx` | Approving without reviewing flagged segments |
| LLM output validation | `adapters/openai_api.py` | Invalid section names, missing segments, malformed JSON |
| Double-approval prevention | `gateway/routes/note.ts` | Duplicate approvals from rapid re-clicks (409 Conflict) |
| Append-only audit log | `db/sqlite.py` schema | No silent deletion of clinical record history |
| Confidence flag threshold | `models/confidence_rescorer/infer.py` | Low-reliability segments always surfaced to provider |
| Role disagreement flag | `graph/nodes.py` | Diarization errors always surfaced, never silently accepted |

---

## ML Models

### PyTorch — Confidence Re-Scorer

Takes ASR confidence + segment token count + SOAP section (one-hot) and outputs a reliability score [0, 1]. Segments below 0.6 are flagged yellow in the review UI.

```
Input:  [asr_confidence, token_count, soap_S, soap_O, soap_A, soap_P]
Model:  Linear(6→32) → ReLU → Linear(32→16) → ReLU → Linear(16→1) → Sigmoid
Output: reliability score [0, 1]
```

Ships untrained. Run `python -m models.confidence_rescorer.train` after collecting approved session data.

### TensorFlow/Keras — Role Classifier

Takes acoustic features per segment and predicts DOCTOR or PATIENT. Cross-checks pyannote diarization labels. Disagreements are flagged for provider review.

```
Input:  [pitch_mean, pitch_variance, speaking_rate_wps, pause_ratio, avg_word_length, duration_s]
Model:  Dense(6→32, relu) → Dropout(0.2) → Dense(32→16, relu) → Dense(16→1, sigmoid)
Output: probability of DOCTOR [0 = PATIENT, 1 = DOCTOR]
```

Ships with synthetic training data. Improves automatically as providers correct role labels — each `segment_remapped` audit event is a training signal.

---

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.11+
- A Gladia API key (free tier at gladia.io)
- An OpenAI API key
- A HuggingFace token (for pyannote model download on first run)

### 1. Fill in environment variables

```bash
# HiScribe/.env
OPENAI_API_KEY=your_key_here
GLADIA_API_KEY=your_key_here
HUGGINGFACE_TOKEN=your_token_here
PIPELINE_URL=http://localhost:8000
GATEWAY_PORT=3000
JWT_SECRET=hiscribe_dev_secret
DB_PATH=../data/hiscribe.db
```

### 2. Install dependencies

```bash
# Gateway
cd gateway && npm install

# Pipeline
cd pipeline
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt

# Client
cd client && npm install
```

### 3. Start all three services

```bash
# Terminal 1 — Gateway
cd gateway && npm run dev

# Terminal 2 — Pipeline
cd pipeline && uvicorn server:app --reload --port 8000

# Terminal 3 — Client
cd client && npm run dev
```

### 4. Open the app

Navigate to `http://localhost:5173`

The `data/` directory and SQLite database are created automatically on first boot.

---

## Folder Structure

```
HiScribe/
├── .env                              ← environment variables (never commit)
├── schema.sql                        ← shared SQLite schema (both layers use this)
├── docker-compose.yml
│
├── gateway/                          ← Node / TypeScript / Fastify
│   └── src/
│       ├── server.ts                 ← entry point, Fastify setup
│       ├── routes/
│       │   ├── session.ts            ← WebSocket audio + SSE stream + session lifecycle
│       │   └── note.ts               ← approve, remap, edit, delete, amendment
│       ├── adapters/
│       │   ├── speech.ts             ← ASR re-export (change one line to swap)
│       │   ├── gladia.ts             ← DEFAULT: real-time streaming ASR
│       │   ├── azure_speech.ts       ← stub: Azure Speech Services
│       │   ├── google_speech.ts      ← stub: Google STT
│       │   ├── storage.ts            ← session DB re-export
│       │   ├── sqlite.ts             ← DEFAULT: better-sqlite3
│       │   ├── cosmos_db.ts          ← stub: Azure Cosmos DB
│       │   ├── firestore.ts          ← stub: GCP Firestore
│       │   └── audioStorage.ts       ← PCM chunk → WAV file per session
│       └── db/
│           └── client.ts             ← better-sqlite3 singleton + schema init
│
├── pipeline/                         ← Python / FastAPI / LangGraph
│   ├── server.py                     ← FastAPI entry, all REST endpoints
│   ├── graph/
│   │   ├── nodes.py                  ← all 6 LangGraph node functions
│   │   └── pipeline.py               ← StateGraph assembled + compiled
│   ├── adapters/
│   │   ├── diarize.py                ← diarization re-export
│   │   ├── pyannote.py               ← DEFAULT: offline 2-speaker diarization
│   │   ├── assemblyai.py             ← stub: HIPAA-eligible cloud diarization
│   │   ├── google_speech.py          ← stub: GCP built-in diarization
│   │   ├── llm.py                    ← LLM re-export
│   │   ├── openai_api.py             ← DEFAULT: gpt-4o-mini SOAP mapping + validation
│   │   ├── azure_openai.py           ← stub: Azure OpenAI
│   │   ├── vertex_ai.py              ← stub: Vertex AI Gemini
│   │   ├── audio_storage.py          ← audio path re-export
│   │   ├── local_disk.py             ← DEFAULT: local WAV files
│   │   ├── azure_blob.py             ← stub: Azure Blob Storage
│   │   └── gcs.py                    ← stub: Google Cloud Storage
│   ├── models/
│   │   ├── confidence_rescorer/      ← PyTorch: model, train, infer
│   │   └── role_classifier/          ← TensorFlow/Keras: model, train, infer
│   └── db/
│       └── sqlite.py                 ← all DB operations + append-only audit logging
│
├── client/                           ← React / TypeScript / Vite
│   └── src/
│       ├── App.tsx                   ← router: /session → /capture → /review
│       ├── SessionStart.tsx          ← session creation screen
│       ├── LiveCapture.tsx           ← mic → WebSocket → SSE live transcript
│       ├── SOAPReview.tsx            ← 4-column SOAP review, metadata gate, approve
│       ├── SegmentCard.tsx           ← inline edit / remap / delete per segment
│       └── AmendmentPanel.tsx        ← add provider amendment per section
│
└── docs/
    └── Changelog_2026-03-30.md
```

---

## Swapping a Provider (Demo)

This is the most compelling thing to show in an interview or demo.

**Swap ASR from Gladia to Azure Speech:**
```typescript
// gateway/src/adapters/speech.ts
// export { transcribe } from './gladia'         ← comment this out
export { transcribe } from './azure_speech'      // ← uncomment this
```

Restart the gateway. No other file changes. The entire rest of the system — SSE streaming, segment storage, pipeline trigger — is unchanged.

**Swap diarization from pyannote to AssemblyAI:**
```python
# pipeline/adapters/diarize.py
# from .pyannote import diarize          ← comment this out
from .assemblyai import diarize          # ← uncomment this
```

Restart the pipeline. Nothing else changes.

---

## Training the ML Models

Both models ship untrained (confidence rescorer) or with synthetic data (role classifier). They improve automatically as real session data accumulates.

```bash
# After collecting approved sessions:
cd pipeline

# Train PyTorch confidence re-scorer
python -m models.confidence_rescorer.train

# Train TF/Keras role classifier
python -m models.role_classifier.train
```

Training data comes from the audit log:
- Approved sessions with no edits = high-reliability examples
- Segments the provider edited = low-reliability examples
- Segments the provider remapped = role label corrections

---

## Interview Questions This Project Answers

| Question | Where the answer lives |
|----------|----------------------|
| "Why doesn't the LLM write the SOAP note?" | `adapters/openai_api.py` — MAP_PROMPT rules |
| "What's the difference between an edit and an amendment?" | `db/sqlite.py` — two separate functions, two audit event types |
| "Why pyannote instead of a cloud diarizer?" | `adapters/pyannote.py` — offline, no PHI leaves the device |
| "Why two backends instead of one?" | Separation of browser concerns (Node) from ML concerns (Python) |
| "What is LangGraph doing here vs agents?" | `graph/pipeline.py` — linear pipeline, not autonomous decision-making |
| "How do you prevent double approval?" | `gateway/routes/note.ts` — in-flight Set with 409 response |
| "What happens if the LLM returns garbage?" | `adapters/openai_api.py` — `_validate_mappings()` schema check |

---

## Known Gaps (Production Considerations)

| Gap | What's needed for production |
|-----|---------------------------|
| HIPAA compliance | Signed BAA with Gladia + OpenAI, or swap to Azure (HIPAA-eligible) |
| Authentication | JWT is scaffolded — needs real identity provider |
| EHR integration | FHIR output is generated but not delivered — needs HL7 FHIR server or EHR API |
| pyannote on long sessions | Model accuracy degrades past ~45 minutes — chunk or upgrade |
| SQLite at scale | Single-file DB works for demo — swap to Cosmos DB or Postgres for multi-provider |
| ML model cold start | Both models load lazily on first inference — add warmup on server boot |

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for LLM SOAP mapping |
| `GLADIA_API_KEY` | Yes | Gladia API key for real-time ASR |
| `HUGGINGFACE_TOKEN` | Yes (first run) | Downloads pyannote model weights |
| `PIPELINE_URL` | Yes | URL of Python pipeline (default: http://localhost:8000) |
| `GATEWAY_PORT` | No | Gateway listen port (default: 3000) |
| `JWT_SECRET` | Yes | Secret for session JWT signing |
| `DB_PATH` | No | Path to SQLite file (default: ../data/hiscribe.db) |
| `AZURE_SPEECH_KEY` | Swap only | Azure Speech Services key |
| `AZURE_SPEECH_REGION` | Swap only | Azure Speech region (e.g. eastus) |
| `AZURE_OPENAI_ENDPOINT` | Swap only | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_KEY` | Swap only | Azure OpenAI key |
| `AZURE_OPENAI_DEPLOYMENT` | Swap only | Azure OpenAI deployment name |
| `ASSEMBLYAI_API_KEY` | Swap only | AssemblyAI key for cloud diarization |
| `GOOGLE_APPLICATION_CREDENTIALS` | Swap only | Path to GCP service account JSON |
| `GCP_PROJECT_ID` | Swap only | GCP project ID |
