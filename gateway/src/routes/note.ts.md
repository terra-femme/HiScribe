# note.ts — Defines the HTTP routes that let a provider review, edit, and approve clinical notes after a session ends

## What This File Is For
This file contains all the routes that the provider (the doctor or clinician) uses after the AI pipeline has finished processing the recording. They can fetch the generated note, approve it for FHIR export, correct transcription mistakes, move segments between SOAP sections, delete unwanted segments, and add new clinical information that wasn't captured in the transcript. Every action here proxies a request to the Python pipeline service.

## How It Fits In The Project
`server.ts` registers this file's `noteRoutes` function as a plugin. This file does not talk to the database directly — it forwards every request to the Python pipeline service (whose URL is set in `PIPELINE_URL`). It imports `getSession` from `storage.ts` (though it is not currently used in the visible code — it may be used for future session-level validation). The browser's review UI calls these endpoints after receiving a `pipeline_complete` SSE event from `session.ts`.

---

## Line-by-Line Breakdown

### Lines 1–2 — Imports

```typescript
import { FastifyInstance } from 'fastify'
import { getSession } from '../adapters/storage'
```

**What it does:** Imports the Fastify server type for TypeScript type checking, and the `getSession` function from the storage adapter layer.

**Why:** `FastifyInstance` is needed to type the `app` parameter in `noteRoutes`. `getSession` is imported here for potential use in route handlers (for example, to verify a session exists before allowing an approval). Even if it is not called in every handler today, having it available avoids a future import-and-edit cycle.

**ELI5:** You gather the tools you might need before starting — even if you don't use every single one, they're within reach.

**Best practice:** Be intentional about imports. If `getSession` is truly not used anywhere in the file, a linter like ESLint with the `no-unused-vars` rule would flag it. It may be there as a placeholder for near-future validation logic.

---

### Lines 4–5 — In-flight approvals guardrail

```typescript
// Guardrail: prevents double-approval from rapid re-clicks or duplicate requests
const approvalsInFlight = new Set<string>()
```

**What it does:** Creates an in-memory `Set` of session IDs that are currently being approved. Before processing an approval request, the route checks this set. If the session ID is already in it, the request is rejected immediately.

**Why:** Without this guardrail, a provider who double-clicks the "Approve" button (or a browser that retries a slow request) could trigger the full FHIR generation pipeline twice for the same session. Duplicate FHIR records in a clinical system are a serious data integrity problem. A `Set` is the right data structure here — it only stores unique values and has O(1) `has` and `add` operations.

**ELI5:** Imagine you're signing a legal document. This guardrail is like a notary who says "I already have your signature in process — you can't sign it twice at the same time."

**Best practice:** Like the SSE `Map` in `session.ts`, this is in-memory, so it only works with a single server process. In production, this kind of idempotency lock should live in a shared store like Redis with a short TTL so it automatically expires if the request somehow never finishes.

---

### Lines 8–20 — `GET /session/:id/note` route

```typescript
app.get('/session/:id/note', async (req, reply) => {
  const { id: sessionId } = req.params as { id: string }

  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
  const response = await fetch(`${pipelineUrl}/session/${sessionId}/note`)

  if (!response.ok) {
    return reply.status(404).send({ error: 'Note not found' })
  }

  return reply.send(await response.json())
})
```

**What it does:** Fetches the structured clinical note for a session from the Python pipeline and returns it to the browser. If the pipeline returns any non-OK HTTP status (like 404), the gateway also returns a 404 with an error message.

**Why:** The gateway acts as a proxy here — it does not store the note itself, it just retrieves it from the pipeline service on behalf of the browser. This keeps the data in one place (the Python service) while the browser only needs to know one API address (the gateway). Checking `response.ok` and returning a meaningful 404 is better than blindly forwarding a confusing error from the pipeline.

**ELI5:** The browser asks "what's in the note for session 123?" The gateway calls the Python kitchen to ask, and if the kitchen says "we never cooked that dish," the gateway tells the browser "dish not found" instead of passing along a confusing chef's shout.

**Best practice:** Always check `response.ok` (or the HTTP status) when making server-to-server fetch calls. Never assume the upstream service succeeded. Forwarding error responses transparently to the client is fine, but mapping them to sensible status codes at the gateway makes the API easier to consume.

---

### Lines 22–49 — `POST /session/:id/approve` route

```typescript
app.post('/session/:id/approve', async (req, reply) => {
  const { id: sessionId } = req.params as { id: string }

  if (approvalsInFlight.has(sessionId)) {
    return reply.status(409).send({ error: 'Approval already in progress for this session' })
  }

  const body = req.body as {
    provider_npi: string
    patient_mrn: string
    visit_type: string
  }

  approvalsInFlight.add(sessionId)
  try {
    const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
    const response = await fetch(`${pipelineUrl}/session/${sessionId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    return reply.send(await response.json())
  } finally {
    approvalsInFlight.delete(sessionId)
  }
})
```

**What it does:** Processes a provider's approval of a clinical note. It first checks the in-flight set, rejects duplicate requests with a 409 Conflict, then adds the session to the set, forwards the approval to the Python pipeline (with provider and patient identifiers), and removes the session from the set when done — whether the pipeline call succeeded or failed.

**Why:** The `try/finally` pattern is critical: `finally` runs no matter what happens — even if `fetch` throws an error, even if the pipeline returns a bad response. This guarantees `approvalsInFlight.delete(sessionId)` always runs and the guardrail is always released. Without `finally`, a network error would leave the session ID in the set forever, permanently blocking future approvals. The 409 status code ("Conflict") is the semantically correct HTTP code for "this action is already in progress."

**ELI5:** The notary checks their pending-signatures list first. If your name is already there, they say "come back in a moment" (409). Otherwise, they add your name, process the signature with the pipeline, and cross your name off when done — even if something goes wrong in the middle.

**Best practice:** `try/finally` (without a `catch`) is a pattern specifically for "do cleanup no matter what." If you used `try/catch/finally`, you could also log the error, but you'd still delete from the set in `finally`. This is one of the most important patterns in async backend code.

---

### Lines 51–68 — `POST /session/:id/segment/:segId/remap` route

```typescript
app.post('/session/:id/segment/:segId/remap', async (req, reply) => {
  const { id: sessionId, segId } = req.params as { id: string; segId: string }
  const { from_section, to_section, provider_id } = req.body as {
    from_section: string
    to_section: string
    provider_id: string
  }

  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
  const response = await fetch(`${pipelineUrl}/segment/${segId}/remap`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, from_section, to_section, provider_id })
  })

  return reply.send(await response.json())
})
```

**What it does:** Allows a provider to move a transcript segment from one SOAP note section to another (e.g., from Subjective to Assessment). Extracts two URL parameters (`sessionId` and `segId`), reads the remap details from the request body, and forwards everything to the Python pipeline.

**Why:** SOAP notes have four sections: Subjective, Objective, Assessment, and Plan. AI classification is imperfect — a provider might need to move a statement to the correct section. The gateway accepts this human correction and forwards it to the pipeline where the note model is maintained. Tracking `from_section`, `to_section`, and `provider_id` creates an audit trail of who changed what.

**ELI5:** The doctor looks at the note and says "you put 'patient reports pain' in the wrong box — it should go in Subjective, not Objective." This route is the form they fill out to request that move.

**Best practice:** Destructuring both URL params at once — `const { id: sessionId, segId } = req.params as {...}` — is cleaner than accessing them one by one. Note the rename: `id: sessionId` renames the param `id` to the more descriptive local variable `sessionId`.

---

### Lines 70–86 — `POST /session/:id/segment/:segId/edit` route

```typescript
app.post('/session/:id/segment/:segId/edit', async (req, reply) => {
  const { id: sessionId, segId } = req.params as { id: string; segId: string }
  const { corrected_text, provider_id } = req.body as {
    corrected_text: string
    provider_id: string
  }

  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
  const response = await fetch(`${pipelineUrl}/segment/${segId}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, corrected_text, provider_id })
  })

  return reply.send(await response.json())
})
```

**What it does:** Lets a provider fix the transcribed text of a specific segment. Takes the corrected text and provider ID from the request body and proxies the edit to the Python pipeline.

**Why:** Speech recognition is not perfect. This endpoint is the escape hatch for when the AI transcribed "acetaminophen" as "a set of mean a fin." The correction is attributed to a specific provider via `provider_id`, which is important for clinical accountability.

**ELI5:** The doctor reads the transcript, spots a typo, and uses this route to white-out the wrong word and write the correct one — and their name is recorded next to the correction.

**Best practice:** Notice the consistent pattern across all these proxy routes: extract params, read body, build fetch call, return result. When you see repetition like this, it's a signal that a helper function (like `proxyToPipeline`) could reduce the boilerplate. That said, the explicit repetition here also makes each route independently readable without having to trace through abstractions.

---

### Lines 88–101 — `DELETE /session/:id/segment/:segId` route

```typescript
app.delete('/session/:id/segment/:segId', async (req, reply) => {
  const { id: sessionId, segId } = req.params as { id: string; segId: string }
  const { provider_id, reason } = req.body as { provider_id: string; reason?: string }

  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
  const response = await fetch(`${pipelineUrl}/segment/${segId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, provider_id, reason })
  })

  return reply.send(await response.json())
})
```

**What it does:** Removes a specific segment from the note. The `reason` field in the request body is optional (`reason?: string`) — the provider can explain why they deleted the segment, but it is not required.

**Why:** Sometimes the transcript captures ambient noise, side conversations, or irrelevant remarks that should not appear in a clinical note. Deletion with an optional reason maintains data quality. Using the HTTP DELETE method (rather than POST) is semantically correct — REST conventions say DELETE removes a resource.

**ELI5:** The doctor finds a part of the transcript that should not be in the note (like "hold on, I need to sneeze") and uses this route to strike it out. Optionally, they write a note in the margin explaining why.

**Best practice:** The `reason?: string` type annotation with the `?` marks the field as optional — TypeScript won't complain if the browser doesn't send it. This is more flexible than requiring it but still documents that it exists.

---

### Lines 103–120 — `POST /session/:id/amendment` route

```typescript
app.post('/session/:id/amendment', async (req, reply) => {
  const { id: sessionId } = req.params as { id: string }
  const { content, soap_section, provider_id } = req.body as {
    content: string
    soap_section: string
    provider_id: string
  }

  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
  const response = await fetch(`${pipelineUrl}/session/${sessionId}/amendment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, soap_section, provider_id })
  })

  return reply.send(await response.json())
})
```

**What it does:** Allows a provider to add brand-new clinical content to the note that was not captured in the original transcript. The amendment is tied to a specific SOAP section and attributed to the provider.

**Why:** Physicians often remember relevant information after the visit — a prior medication, a family history detail, a finding from a physical exam not spoken aloud. An amendment mechanism lets them add this without re-doing the transcription. This is distinct from "edit" (which corrects existing text) — an amendment adds new text.

**ELI5:** After the visit, the doctor remembers "I forgot to mention I checked the patient's reflexes and they were normal." This route is how they add that note to the chart even though it was never said during the recorded session.

**Best practice:** All three identifiers (`content`, `soap_section`, `provider_id`) are required (no `?`). This is correct — an amendment without knowing who wrote it or where it belongs would be ambiguous and potentially dangerous in a clinical context.

---

## Common Mistakes

1. **Forgetting `try/finally` around the pipeline fetch in the approve route.** If you use a plain `try/catch` and forget `finally`, a network error will leave the session stuck in `approvalsInFlight` forever. The provider would be locked out from approving that session until the server restarts.

2. **Not checking `response.ok` before calling `response.json()`.** If the pipeline returns a 500 error with an HTML error page instead of JSON, `response.json()` will throw a parse error. The note GET route handles this, but the other routes return whatever the pipeline sends — which works fine as long as the pipeline always returns JSON.

3. **Confusing `edit` with `amendment`.** Edit corrects existing transcript text. Amendment adds new content that was never in the transcript. Mixing them up means you'd either overwrite an existing segment when you meant to add something new, or add a duplicate segment when you meant to fix a typo.

---

## Key Concepts To Look Up

- **HTTP methods (GET, POST, DELETE)** — conventions for what kind of action a request represents
- **HTTP 409 Conflict** — standard response when a request cannot be completed because of the current state of the resource
- **`try/finally`** — a pattern for guaranteeing cleanup code runs regardless of success or failure
- **`Set` in JavaScript** — a collection of unique values with O(1) membership testing
- **SOAP note** — a structured clinical documentation format: Subjective, Objective, Assessment, Plan
- **Idempotency** — the property of an operation that produces the same result no matter how many times you run it
- **REST conventions** — guidelines for designing HTTP APIs using methods and URLs as meaningful verbs/nouns
- **Optional chaining and optional properties (`?`)** — TypeScript syntax for marking a property or parameter as not required
