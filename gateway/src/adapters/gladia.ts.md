# gladia.ts — Connects to the Gladia real-time transcription API over WebSocket and pipes audio from the browser to it

## What This File Is For
This file implements the actual speech-to-text logic using Gladia's streaming API. It opens a WebSocket connection to Gladia's servers, forwards audio chunks arriving from the browser, and translates Gladia's response messages into a standard internal format that the rest of the application understands. It also defines the shared TypeScript types (`Segment`, `OnSegment`) used by all speech adapters.

## How It Fits In The Project
`speech.ts` re-exports `transcribe` from this file, making it the currently active ASR adapter. `routes/session.ts` calls `transcribe(sessionId, socket, onSegment)`. When a segment is ready, `transcribe` calls back to `session.ts`'s anonymous function, which then saves to the database and broadcasts over SSE. `azure_speech.ts` imports the `OnSegment` type from this file since it is the canonical location for shared types.

---

## Line-by-Line Breakdown

### Line 1 — Import WebSocket client

```typescript
import WebSocket from 'ws'
```

**What it does:** Imports the `ws` library, which is a WebSocket client/server implementation for Node.js.

**Why:** Browsers have a built-in `WebSocket` class, but Node.js does not (in older versions). The `ws` package fills that gap. This import gives the server the ability to open a WebSocket connection *to* Gladia's API (acting as a WebSocket client), not just accept WebSocket connections from browsers.

**ELI5:** The browser can make phone calls natively. Node.js needs to borrow a phone from the `ws` library to make calls of its own — in this case, calling Gladia's servers.

**Best practice:** In modern Node.js (18+), there is a built-in `WebSocket` class available globally. The `ws` library is still widely used because it offers more control and better performance. Stick with `ws` unless you have a specific reason to switch.

---

### Lines 3–10 — `Segment` type definition

```typescript
export type Segment = {
  text: string
  speaker: string
  start_ms: number
  end_ms: number
  confidence: number
  is_final: boolean
}
```

**What it does:** Defines the shape of one unit of transcribed speech — a `Segment`. Every field is explicitly typed. `text` is the words spoken, `speaker` is the speaker label (assigned later by diarization), `start_ms` and `end_ms` are timestamps in milliseconds, `confidence` is how certain the model is (0.0–1.0), and `is_final` marks whether this is a confirmed result or a preliminary guess.

**Why:** Defining a shared type here forces every part of the system that creates or consumes segments to agree on the same structure. If `gladia.ts` produces a `Segment` and `sqlite.ts` consumes a `SegmentRecord` (which mirrors this structure), TypeScript will catch mismatches at compile time rather than at runtime.

**ELI5:** It's like defining the format of an official form. Every department that fills out or reads this form must use the same boxes. If someone adds a new box, TypeScript yells at everyone who didn't update their copy.

**Best practice:** Exporting this type (with `export type`) makes it available to any file that imports it. Placing shared types in the file closest to their origin (Gladia is the source of transcription data) is reasonable. In a larger project, you might put all shared types in a dedicated `types.ts` file.

---

### Line 12 — `OnSegment` type alias

```typescript
export type OnSegment = (segment: Segment) => void
```

**What it does:** Defines a type alias for a callback function that receives a `Segment` and returns nothing (`void`).

**Why:** Without this alias, the `transcribe` function signature would have an inline function type like `onSegment: (segment: Segment) => void`, which is harder to read and must be repeated in every adapter. The alias also appears in `azure_speech.ts`, which imports it from here.

**ELI5:** Instead of writing out "a function that takes a piece of text, a speaker name, timestamps, confidence, and a boolean" every time, you just say "an `OnSegment` callback." It's a shorthand label.

**Best practice:** Use type aliases for complex types that appear in more than one place. It makes function signatures readable and ensures consistency — if the `Segment` type changes, `OnSegment` automatically reflects the change because it references `Segment` by name.

---

### Lines 14–18 — `transcribe` function signature

```typescript
export function transcribe(
  sessionId: string,
  clientSocket: WebSocket,
  onSegment: OnSegment
): void {
```

**What it does:** Declares the `transcribe` function with three parameters: the session ID (for logging), the browser's WebSocket connection (to read audio from), and a callback function to call when a segment is ready.

**Why:** The function returns `void` because it is event-driven — it sets up event listeners and returns immediately. Work happens asynchronously over the lifetime of the WebSocket connections. The `onSegment` callback pattern means the caller decides what to do with each segment; this file only decides how to get them.

**ELI5:** You're hiring a live translator. You hand them a microphone (clientSocket), tell them your event ID (sessionId), and give them your phone number (onSegment). They'll call you whenever they hear something. You don't wait for them — you go back to your other work.

**Best practice:** Designing `transcribe` to accept a callback rather than returning a promise or async generator makes it easy to swap adapters — any adapter just needs to call `onSegment` at the right time, regardless of how it gets the data. This is the "callback" or "observer" pattern.

---

### Lines 19–20 — API key guard

```typescript
const apiKey = process.env.GLADIA_API_KEY
if (!apiKey) throw new Error('GLADIA_API_KEY not set in .env')
```

**What it does:** Reads the Gladia API key from the environment. If it is missing, throws an error immediately with a helpful message.

**Why:** Throwing early with a clear error message is far better than letting the code proceed and fail later with a cryptic "401 Unauthorized" from Gladia's servers. This is called a "fail fast" pattern — catch configuration problems at startup, not during a live session.

**ELI5:** Before you start the car, you check that you have the ignition key. If it's missing, you say "no key — not going" right away instead of finding out after you've already tried to drive.

**Best practice:** Validate required environment variables early, before any side-effectful work (like opening network connections). Consider doing all validation at server startup in `server.ts` so you know on boot whether the configuration is complete.

---

### Lines 22–26 — Open WebSocket to Gladia

```typescript
const gladiaWs = new WebSocket(
  'wss://api.gladia.io/audio/text/audio-transcription',
  { headers: { 'x-gladia-key': apiKey } }
)
```

**What it does:** Opens a WebSocket connection to Gladia's streaming transcription endpoint. The API key is passed as a custom HTTP header during the WebSocket handshake.

**Why:** `wss://` is WebSocket over TLS (encrypted), analogous to `https://` for regular HTTP. The API key in the header authenticates the connection — Gladia knows who is calling. This connection is established once per audio session and stays open for the duration.

**ELI5:** The server dials Gladia's number on a secure line and says "hello, here's my membership card" (the API key). Gladia answers and keeps the line open for the whole session.

**Best practice:** Always use `wss://` (not `ws://`) for connections to third-party APIs. Plain `ws://` transmits data unencrypted, which would expose patient audio to anyone who could intercept the traffic.

---

### Lines 27–37 — Gladia `open` event handler

```typescript
gladiaWs.on('open', () => {
  gladiaWs.send(JSON.stringify({
    x_gladia_key: apiKey,
    encoding: 'WAV/PCM',
    sample_rate: 16000,
    language_behaviour: 'automatic single language',
    frames_format: 'bytes'
  }))
  console.log(`[gladia] Session ${sessionId} — stream opened`)
})
```

**What it does:** Once the WebSocket connection to Gladia is open, immediately sends a configuration message telling Gladia what audio format to expect. The config specifies PCM encoding, 16kHz sample rate, automatic language detection, and binary frame format.

**Why:** Gladia needs to know the audio parameters before it can process any audio. Sending the config on `open` ensures it arrives before any audio chunks. These parameters must match what the browser sends — if the browser records at 44kHz but Gladia is told to expect 16kHz, the transcription will be garbled or fail entirely.

**ELI5:** Before the translator starts listening, you tell them "the person will be speaking English or French, and they're using a regular microphone." This is that briefing.

**Best practice:** Never hardcode audio parameters that might change. In a production system, these would be in environment variables or a configuration file, matching whatever the browser's `MediaRecorder` is configured to produce.

---

### Lines 39–57 — Gladia `message` event handler

```typescript
gladiaWs.on('message', (data: Buffer) => {
  try {
    const msg = JSON.parse(data.toString())

    if (msg.event === 'transcript' && msg.transcription) {
      const isFinal = msg.type === 'final'
      onSegment({
        text: msg.transcription,
        speaker: 'UNKNOWN',
        start_ms: msg.time_begin ? Math.round(msg.time_begin * 1000) : 0,
        end_ms: msg.time_end ? Math.round(msg.time_end * 1000) : 0,
        confidence: msg.confidence ?? 1.0,
        is_final: isFinal
      })
    }
  } catch (e) {
    console.error('[gladia] parse error', e)
  }
})
```

**What it does:** Handles every message arriving from Gladia. Each message is parsed from JSON. If the message is a transcript event with actual text, it is mapped into a `Segment` object and passed to the `onSegment` callback. Non-transcript messages (like connection acknowledgments) are silently ignored.

**Why:** Gladia sends various event types over the WebSocket. Only `event === 'transcript'` contains transcription data. The `msg.type === 'final'` check determines if this is a definitive result or a preliminary one. Timestamps arrive as floating-point seconds (`time_begin: 3.14`), so multiplying by 1000 and rounding converts them to whole milliseconds. `msg.confidence ?? 1.0` uses the nullish coalescing operator — if `confidence` is `null` or `undefined`, default to `1.0`. Speaker is set to `'UNKNOWN'` because diarization (speaker identification) happens later in the Python pipeline.

**ELI5:** Gladia is constantly sending notes over the phone. Most are just "still connected" pings. When it sends a real transcription note, you copy it onto your standard form (the `Segment` format) and hand it to whoever called `transcribe` (the `onSegment` callback). If the note arrives in a language you can't read (malformed JSON), you log the confusion and move on.

**Best practice:** Always wrap JSON parsing in a `try/catch`. Third-party APIs occasionally send unexpected payloads. A parse error without `try/catch` would throw an unhandled exception and potentially crash the WebSocket handler for every user, not just the one affected session.

---

### Lines 60–63 — Forward audio from browser to Gladia

```typescript
clientSocket.on('message', (chunk: Buffer) => {
  if (gladiaWs.readyState === WebSocket.OPEN) {
    gladiaWs.send(chunk)
  }
})
```

**What it does:** Every time a binary audio chunk arrives from the browser's WebSocket, it is immediately forwarded to Gladia — if and only if the Gladia connection is still open.

**Why:** This is the core audio relay. The browser records audio and sends small binary chunks in real time. This code pipes them directly through to Gladia without modification. The `readyState === WebSocket.OPEN` check prevents sending to a closed connection, which would throw an error.

**ELI5:** Audio chunks arrive through one pipe (the browser WebSocket). This code immediately pours them into the other pipe (the Gladia WebSocket). If the other pipe is clogged or disconnected (`readyState !== OPEN`), the chunk is dropped rather than causing a crash.

**Best practice:** Always check `readyState` before calling `send` on a WebSocket. A brief race condition (the browser sends a chunk the instant after Gladia disconnects) can otherwise cause uncaught errors.

---

### Lines 65–68 — Connection cleanup and error handling

```typescript
clientSocket.on('close', () => gladiaWs.close())
gladiaWs.on('error', (err) => console.error('[gladia] error', err))
gladiaWs.on('close', () => console.log(`[gladia] Session ${sessionId} — stream closed`))
```

**What it does:** Three event listeners for end-of-life events. When the browser disconnects, the Gladia connection is also closed. Gladia errors are logged. When the Gladia connection closes, a log message is printed.

**Why:** When the browser stops recording, there is no more audio to send. Keeping the Gladia connection open would waste API credits (Gladia bills by the minute) and keep a socket open unnecessarily. Closing Gladia when the browser closes ensures proper resource cleanup.

**ELI5:** When the person recording hangs up their phone, you hang up the translator's phone too. If the translator's phone makes a weird sound (error), you write it down. When the translator's phone finally goes quiet, you note that the session ended.

**Best practice:** Always close upstream connections when the downstream connection closes. Failing to close Gladia would mean: (1) billing continues, (2) the `gladiaWs` object stays in memory until garbage collected, (3) Gladia might send more transcript events after the session is "over," causing confusing log entries.

---

## Common Mistakes

1. **Assuming `msg.event === 'transcript'` means the data is valid.** The guard also checks `&& msg.transcription` — if `transcription` is an empty string or `null`, calling `onSegment` with empty text would create empty segment records in the database.

2. **Not checking `gladiaWs.readyState` before sending.** If the browser sends audio very quickly after connecting, but the Gladia WebSocket hasn't finished its handshake yet, chunks arrive before `readyState === OPEN`. The check protects against this race condition.

3. **Forgetting that Gladia timestamps are in seconds, not milliseconds.** `msg.time_begin` is something like `2.450`. If you forget to multiply by 1000, your database stores `2` instead of `2450` — and all your timestamps appear to be in the first few seconds.

---

## Key Concepts To Look Up

- **WebSocket `readyState`** — an integer representing the connection state: 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED
- **Callback pattern** — passing a function as an argument to be called later when an event occurs
- **Nullish coalescing operator (`??`)** — returns the right-hand value only when the left-hand value is `null` or `undefined` (unlike `||` which also triggers on `0`, `false`, `''`)
- **PCM audio** — Pulse Code Modulation, the raw uncompressed format of digital audio
- **Sample rate** — how many audio samples are taken per second (16kHz = 16,000 per second)
- **Diarization** — the process of identifying and labeling which speaker said what in an audio recording
- **Fail fast** — designing a system to report errors as early as possible rather than failing silently later
