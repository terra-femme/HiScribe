# session.ts — Defines the HTTP and WebSocket routes that manage recording sessions and real-time audio transcription

## What This File Is For
This file handles everything that happens during a live recording session: starting a session, streaming transcribed text back to the browser in real time, accepting raw audio from the browser, and triggering the AI processing pipeline when recording ends. It is the heart of the real-time data flow — audio comes in one connection, and text goes out another.

## How It Fits In The Project
`server.ts` registers this file's `sessionRoutes` function as a plugin. Inside, this file uses three adapters: `speech.ts` (to send audio to a transcription service), `storage.ts` (to save session records and text segments to the database), and `audioStorage.ts` (to save the raw audio file to disk). The browser connects to the routes defined here. The Python pipeline is triggered from here when the session ends.

---

## Line-by-Line Breakdown

### Lines 1–5 — Imports

```typescript
import { FastifyInstance } from 'fastify'
import { randomUUID } from 'crypto'
import { transcribe } from '../adapters/speech'
import { saveSession, saveSegment } from '../adapters/storage'
import { saveAudioChunk, finalizeAudio } from '../adapters/audioStorage'
```

**What it does:** Imports the Fastify type (for TypeScript to understand what `app` is), a UUID generator from Node's built-in `crypto` module, and three adapter functions for transcription, database storage, and audio file storage.

**Why:** `FastifyInstance` is the TypeScript type that describes a Fastify server object — it tells the editor what methods are available on `app`. `randomUUID` generates a unique ID for each session. The three adapter imports are deliberately thin: this file doesn't care whether storage is SQLite or Cosmos DB — it just calls `saveSession` and the adapter layer handles the details.

**ELI5:** Before cooking, you gather your sous-chefs: one who speaks to the transcription service, one who writes to the database, and one who saves audio files.

**Best practice:** Importing from adapter files (like `../adapters/storage`) rather than directly from `../adapters/sqlite` means you can swap the database engine by changing one line in `storage.ts` instead of hunting through every file that uses storage.

---

### Lines 7–8 — SSE client map

```typescript
// In-memory SSE connection map: sessionId → reply.raw
const sseClients = new Map<string, NodeJS.WritableStream>()
```

**What it does:** Creates an in-memory dictionary that maps a session ID string to an open HTTP response stream. When a browser subscribes to live transcript updates, its open connection is stored here so the server can write to it later.

**Why:** Server-Sent Events (SSE) work by keeping an HTTP response open indefinitely. To push data to a specific browser tab, you need to hold onto its response stream. A `Map` gives O(1) lookup by session ID.

**ELI5:** Imagine a bulletin board where each hook is labeled with a session ID. When a browser tunes in for updates, you hang its "mailbox" (the open connection) on the hook. When new text arrives, you know exactly which mailbox to drop a note into.

**Best practice:** Because this is in-memory, it only works when all requests for the same session hit the same server process. In a multi-server (horizontally scaled) deployment, you'd need a shared pub/sub system like Redis instead.

---

### Lines 10–15 — `broadcastSegment` function

```typescript
export function broadcastSegment(sessionId: string, segment: object) {
  const client = sseClients.get(sessionId)
  if (client && !client.destroyed) {
    client.write(`data: ${JSON.stringify(segment)}\n\n`)
  }
}
```

**What it does:** Looks up the open SSE connection for a given session and, if it exists and is still active, writes a formatted event message to it. The message is serialized JSON wrapped in the SSE protocol format (`data: ...\n\n`).

**Why:** This function is exported so the audio WebSocket handler (and any future code) can call it. The `!client.destroyed` guard prevents writing to a closed connection, which would throw an error. The `data: ...\n\n` format is required by the SSE specification — browsers only parse messages in that exact format.

**ELI5:** Think of this as a PA announcement system. You look up which room (session) the announcement goes to, check the microphone is still plugged in, and then speak into it.

**Best practice:** Always check `!client.destroyed` before writing to a stream. Streams can close unexpectedly (the user closed the tab, network dropped). Writing to a destroyed stream throws an unhandled error that can crash the server.

---

### Lines 17–28 — `POST /session/start` route

```typescript
app.post('/session/start', async (_req, reply) => {
  const sessionId = randomUUID()
  await saveSession({
    id: sessionId,
    status: 'recording',
    created_at: new Date().toISOString()
  })
  app.log.info(`Session created: ${sessionId}`)
  return reply.send({ session_id: sessionId })
})
```

**What it does:** When the browser sends a POST request to `/session/start`, this handler generates a unique session ID, saves a new session record to the database with status `'recording'`, and returns the session ID to the browser.

**Why:** The browser needs a session ID to use in all subsequent requests (audio stream, SSE stream, end session). Generating it server-side with `randomUUID()` ensures it is globally unique and cannot be guessed or manipulated by the client. `new Date().toISOString()` produces a standard timestamp string.

**ELI5:** The browser says "I want to start recording." The server stamps a unique ticket number (the UUID), files a record in the cabinet, and hands the ticket back. Every future request will reference that ticket number.

**Best practice:** Using `randomUUID()` from Node's built-in `crypto` module is better than a third-party UUID library — it's cryptographically secure and has no dependencies to install or update.

---

### Lines 31–53 — `GET /session/:id/stream` — SSE endpoint

```typescript
app.get('/session/:id/stream', async (req, reply) => {
  const { id: sessionId } = req.params as { id: string }

  reply.raw.setHeader('Content-Type', 'text/event-stream')
  reply.raw.setHeader('Cache-Control', 'no-cache')
  reply.raw.setHeader('Connection', 'keep-alive')
  reply.raw.setHeader('Access-Control-Allow-Origin', '*')
  reply.raw.flushHeaders()

  sseClients.set(sessionId, reply.raw)
  app.log.info(`SSE client connected for session ${sessionId}`)

  const heartbeat = setInterval(() => {
    reply.raw.write(': heartbeat\n\n')
  }, 15000)

  req.raw.on('close', () => {
    clearInterval(heartbeat)
    sseClients.delete(sessionId)
    app.log.info(`SSE client disconnected for session ${sessionId}`)
  })
})
```

**What it does:** Registers a GET route that keeps the HTTP response permanently open and sets the headers required for Server-Sent Events. It stores the connection in the `sseClients` map, sends a heartbeat comment every 15 seconds, and cleans up when the browser disconnects.

**Why:** `Content-Type: text/event-stream` tells the browser this is an SSE stream. `no-cache` prevents proxies from buffering the response. `flushHeaders()` sends the headers immediately so the browser knows the stream has started before any data arrives. The heartbeat (`': heartbeat\n\n'`) keeps the TCP connection alive through idle periods — lines starting with `:` are comments in SSE and browsers ignore them. The `close` event listener ensures the map entry is removed when the browser disconnects, preventing memory leaks.

**ELI5:** The browser says "keep this line open and tell me whenever new text arrives." The server sends a special "keep-alive knock" every 15 seconds so nobody thinks the line is dead. When the browser hangs up, the server removes its entry from the phonebook.

**Best practice:** Always clean up resources in a `close` handler. If you never call `sseClients.delete(sessionId)`, the map grows forever — this is a classic memory leak. Also, always clear intervals (`clearInterval`) when they're no longer needed.

---

### Lines 56–84 — `WS /session/:id/audio` — WebSocket route

```typescript
app.register(async function wsPlugin(app) {
  app.get('/session/:id/audio', { websocket: true }, (socket, req) => {
    const { id: sessionId } = req.params as { id: string }
    app.log.info(`Audio WebSocket opened for session ${sessionId}`)

    transcribe(sessionId, socket, async (segment) => {
      if (!segment.is_final) {
        broadcastSegment(sessionId, { type: 'partial', ...segment })
        return
      }
      await saveSegment({ session_id: sessionId, ...segment })
      broadcastSegment(sessionId, { type: 'final', ...segment })
    })

    socket.on('message', (chunk: Buffer) => {
      saveAudioChunk(sessionId, chunk)
    })

    socket.on('close', () => {
      finalizeAudio(sessionId)
      app.log.info(`Audio WebSocket closed for session ${sessionId}`)
    })
  })
})
```

**What it does:** Registers a WebSocket endpoint that accepts a real-time binary audio stream from the browser. It starts the transcription process, handles each transcribed segment (broadcasting partial results live and saving final ones to the database), saves every audio chunk to a buffer, and writes the final audio file to disk when the connection closes.

**Why:** WebSocket is used here instead of regular HTTP because audio is a continuous stream — you can't wait for the entire recording to finish before sending it. The inner `app.register` is required because Fastify's WebSocket plugin needs its own plugin context to work. The `async (segment) => {...}` callback is the bridge between the transcription service and the rest of the system — it's called by the speech adapter every time a new chunk of text is recognized. Partial results are broadcast but not saved, because they will be superseded by the final result.

**ELI5:** The browser opens a phone line and starts talking. A translator (the `transcribe` function) listens and calls back with what they heard. If it's a rough draft ("I think they said..."), it's displayed on screen but not written down. If it's confirmed ("They definitely said..."), it's both displayed and saved to the notebook. Meanwhile, the raw audio is also being recorded to a tape recorder for later analysis.

**Best practice:** The `{ websocket: true }` option in the route registration is how Fastify knows to treat this route as a WebSocket handler rather than a normal HTTP handler. If you forget it, Fastify will treat the route as a regular GET and the connection will fail.

---

### Lines 87–108 — `POST /session/:id/end` route

```typescript
app.post('/session/:id/end', async (req, reply) => {
  const { id: sessionId } = req.params as { id: string }

  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'

  try {
    const response = await fetch(`${pipelineUrl}/pipeline/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    })
    const result = await response.json()

    broadcastSegment(sessionId, { type: 'pipeline_complete', session_id: sessionId })

    return reply.send(result)
  } catch (err) {
    app.log.error(`Pipeline trigger failed for session ${sessionId}: ${err}`)
    return reply.status(500).send({ error: 'Pipeline trigger failed' })
  }
})
```

**What it does:** When the browser signals that recording has ended, this handler calls the Python pipeline service's `/pipeline/run` endpoint, passing the session ID. Once the pipeline responds, it broadcasts a `pipeline_complete` event over SSE so the browser knows it can fetch the finished note.

**Why:** The actual AI processing (diarization, SOAP note generation, FHIR packaging) happens in a separate Python service. This route is the handoff point. The `try/catch` wraps the outgoing HTTP call because network requests to external services can fail — if the Python pipeline is down, this returns a 500 error instead of crashing. `process.env.PIPELINE_URL || 'http://localhost:8000'` allows the URL to be configured per environment.

**ELI5:** When the recording stops, this route is like a relay runner handing the baton to the next runner (the Python pipeline). It waits for a confirmation that the baton was received, then tells the browser "the race is continuing — the AI is now processing your recording."

**Best practice:** When calling external services, always `try/catch` the fetch call and return a meaningful HTTP status code on failure. Never let an unhandled network error bubble up as an unhandled promise rejection, which can silently crash the Node.js process.

---

## Common Mistakes

1. **Not cleaning up the SSE connection on `close`.** If `sseClients.delete(sessionId)` is missing from the `close` handler, the `Map` grows indefinitely. After enough sessions, the server will run out of memory.

2. **Mixing up partial and final segments.** A common mistake is saving partial segments to the database alongside final ones. This creates duplicate or incomplete records. Notice that `saveSegment` is only called when `segment.is_final` is true.

3. **Forgetting to `await` async operations inside WebSocket event handlers.** The `socket.on('message', ...)` callback is not `async` here, because `saveAudioChunk` is synchronous. If you add an async operation inside a non-async event handler and forget to handle its promise, errors will be silently swallowed.

---

## Key Concepts To Look Up

- **Server-Sent Events (SSE)** — a one-way push technology for streaming data from server to browser over plain HTTP
- **WebSocket** — a full-duplex (two-way simultaneous) communication protocol
- **`Map` in JavaScript** — a key-value data structure with O(1) lookup
- **UUID (Universally Unique Identifier)** — a 128-bit random identifier with astronomically low collision probability
- **`Buffer`** — Node.js's way of handling raw binary data (like audio chunks)
- **Spread operator (`...segment`)** — `{ type: 'final', ...segment }` copies all properties of `segment` into a new object alongside `type`
- **`setInterval` / `clearInterval`** — schedule a function to run repeatedly; always pair them to avoid memory leaks
- **HTTP status 500** — "Internal Server Error" — the standard response when the server itself fails
