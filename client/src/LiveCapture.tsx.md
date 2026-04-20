# LiveCapture.tsx — The recording screen that streams microphone audio to the server and displays a live transcript

## What This File Is For
This is the most technically complex file in the project. It opens the user's microphone, converts the raw audio into a compact format, and sends it in real-time to the backend over a WebSocket connection. Simultaneously it listens on a separate channel (SSE) for the backend to send back transcript segments. The result is a live, auto-updating transcript displayed on screen. When the session ends, it waits for the backend to finish processing and then navigates to the review screen.

## How It Fits In The Project
`LiveCapture` is rendered by `App.tsx` at `/session/:id/capture`. It uses the session ID from the URL (passed by `SessionStart`). It opens two connections to the backend simultaneously: a WebSocket for outgoing audio, and a Server-Sent Events stream for incoming transcripts. When done, it navigates to `SOAPReview`.

## Line-by-Line Breakdown

### Lines 1–2 — Imports
```tsx
import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
```
**What it does:** Imports three React hooks (`useEffect`, `useRef`, `useState`) and two React Router hooks (`useParams`, `useNavigate`).

**Why:**
- `useState` — tracks values that cause re-renders when changed (recording status, elapsed time, transcript segments)
- `useEffect` — runs code when the component mounts or specific values change (used here to open the SSE connection)
- `useRef` — stores mutable values that do NOT cause re-renders (used here to hold the WebSocket, EventSource, MediaStream, and timer references)
- `useParams` — reads the `:id` from the URL
- `useNavigate` — navigates to the review screen programmatically

**ELI5:** Think of `useState` as a whiteboard on the wall — when you erase it and write something new, everyone in the room (the UI) notices. `useRef` is like a sticky note in your pocket — you can read and change it without anyone noticing, and it is perfect for things like holding a connection open.

**Best practice:** Use `useRef` for things like WebSocket instances, DOM nodes, timers, and stream references — anything that is mutable but doesn't need to trigger a visual update when it changes. Using `useState` for these would cause unnecessary re-renders.

---

### Lines 4–5 — Gateway constants
```tsx
const GATEWAY = 'http://localhost:3000'
const WS_GATEWAY = 'ws://localhost:3000'
```
**What it does:** Defines the base URLs for HTTP requests and WebSocket connections separately.

**Why:** HTTP uses `http://` and WebSocket uses `ws://` (or `wss://` for secure connections over TLS). They are different protocols even though they often run on the same port. The server handles them with different handlers.

**ELI5:** HTTP is like mailing a letter and waiting for a response. WebSocket is like a phone call — the line stays open and both sides can talk whenever they want. They both connect to the same building (port 3000) but through different doors.

**Best practice:** In production, always use `wss://` (WebSocket Secure) just as you would use `https://` for HTTP. Sending unencrypted audio over plain `ws://` in a medical context would be a serious security and compliance risk.

---

### Lines 7–13 — The Segment type definition
```tsx
type Segment = {
  type: 'partial' | 'final' | 'pipeline_complete'
  text: string
  speaker: string
  start_ms: number
  confidence: number
}
```
**What it does:** Defines a TypeScript type that describes the shape of the JSON messages arriving from the SSE stream.

**Why:** TypeScript can only give you autocomplete and catch type errors if it knows what shape your data is. Without this type, every SSE message would be typed as `any`, and bugs like accessing `msg.tekst` instead of `msg.text` would not be caught until runtime.

**ELI5:** Think of it as a template form. Every message that arrives must have these fields filled in, in these types. If someone sends you a message without a `speaker` field, TypeScript warns you while you are writing code rather than crashing at runtime.

**Best practice:** Define types for all API response shapes. In larger projects, generate these types automatically from an OpenAPI schema or a shared type package so the frontend and backend always agree.

---

### Lines 19–24 — State declarations
```tsx
const [segments, setSegments] = useState<Segment[]>([])
const [partial, setPartial] = useState('')
const [recording, setRecording] = useState(false)
const [stopping, setStopping] = useState(false)
const [elapsed, setElapsed] = useState(0)
```
**What it does:** Declares five pieces of state:
- `segments` — array of finalized transcript segments to display (starts empty)
- `partial` — the current in-progress, not-yet-finalized transcription text
- `recording` — whether the microphone is active and audio is being sent
- `stopping` — whether the user has hit "End Session" and is waiting for processing
- `elapsed` — the number of seconds since recording started (for the timer display)

**Why:** Each of these controls a different part of the UI. For example, `recording` controls which button is shown (Start vs Stop), and `stopping` shows the "Processing..." message.

**ELI5:** These are the five dials on the control panel. When any dial turns, React automatically repaints the part of the screen that cares about that dial.

**Best practice:** Group state into objects if multiple values always change together (e.g., `{ npi, mrn, visitType }` in `SOAPReview`). But for independent values like these, separate `useState` calls are cleaner and avoid accidentally overwriting unrelated state.

---

### Lines 26–29 — Refs
```tsx
const wsRef = useRef<WebSocket | null>(null)
const sseRef = useRef<EventSource | null>(null)
const mediaRef = useRef<MediaStream | null>(null)
const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
```
**What it does:** Creates four "boxes" that can hold references to objects across renders:
- `wsRef` — the WebSocket connection for sending audio
- `sseRef` — the EventSource (SSE) connection for receiving transcripts
- `mediaRef` — the browser MediaStream (microphone handle)
- `timerRef` — the interval timer ID for counting elapsed seconds

**Why:** These objects are created asynchronously and need to be accessible from multiple functions (`startRecording`, `stopRecording`). Storing them in `useRef` makes them available everywhere in the component without causing re-renders when they change.

**ELI5:** Refs are like named hooks on the wall. You hang the WebSocket on one hook and the media stream on another. When you need to close them later, you know exactly where they are hanging.

**Best practice:** Always initialize refs to `null` for objects that haven't been created yet. Check `if (wsRef.current)` before using them. TypeScript's `| null` type enforces this discipline — it will warn you if you try to call methods on something that might be null.

---

### Lines 30–52 — The SSE `useEffect`
```tsx
useEffect(() => {
  if (!sessionId) return

  const sse = new EventSource(`${GATEWAY}/session/${sessionId}/stream`)
  sseRef.current = sse

  sse.onmessage = (e) => {
    const msg: Segment = JSON.parse(e.data)
    if (msg.type === 'pipeline_complete') {
      navigate(`/session/${sessionId}/review`)
      return
    }
    if (msg.type === 'final') {
      setSegments(prev => [...prev, msg])
      setPartial('')
    } else if (msg.type === 'partial') {
      setPartial(msg.text)
    }
  }

  return () => sse.close()
}, [sessionId])
```
**What it does:** When the component first mounts, this effect opens a Server-Sent Events connection to the backend. It then listens for three types of messages and handles each differently:
- `pipeline_complete` — the backend has finished processing; navigate to review
- `final` — a completed transcript segment; add it to the permanent list and clear the partial
- `partial` — an in-progress transcription; update the "ghost" text at the bottom

The `return () => sse.close()` is the **cleanup function** — it runs when the component unmounts and closes the connection so it doesn't leak.

**Why SSE instead of WebSocket for the transcript feed?** SSE is a simpler, one-direction-only protocol — the server pushes events to the client, and the client just listens. It is perfect for a stream of messages flowing in one direction. WebSocket is bidirectional (both sides can send at any time), which is why it is used for the audio stream but SSE is used for the incoming transcript.

**ELI5 — What is SSE?** Imagine subscribing to a news wire feed. You open a connection once, and the wire keeps sending you headlines as they are published. You never send anything back — you just listen. SSE works the same way: the browser opens a connection to the server, and the server can send events at any time. The browser's browser history API has this built in via `EventSource`.

**ELI5 — Why `prev => [...prev, msg]`?** When updating state based on the previous value, always use the function form. `setSegments(prev => [...prev, msg])` says "take whatever the current array is, and return a new array that has everything it had plus this new item." If you wrote `setSegments([...segments, msg])` instead, you would capture `segments` in a closure and might get stale data if multiple updates happen quickly.

**Why `[sessionId]` in the dependency array?** This tells React: "only re-run this effect if `sessionId` changes." Without a dependency array, the effect would re-run on every render, opening a new SSE connection each time. With `[sessionId]`, it opens once when the component mounts and cleans up when it unmounts.

**Best practice:** Always return a cleanup function from `useEffect` when you open connections, set timers, or add event listeners. Failing to close an `EventSource` means the browser keeps a connection open in the background forever, which wastes resources and can cause memory leaks.

---

### Lines 54–84 — The `startRecording` function
```tsx
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRef.current = stream

    const ws = new WebSocket(`${WS_GATEWAY}/session/${sessionId}/audio`)
    wsRef.current = ws

    ws.onopen = () => {
      setRecording(true)
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)

      const audioCtx = new AudioContext({ sampleRate: 16000 })
      const source = audioCtx.createMediaStreamSource(stream)
      const processor = audioCtx.createScriptProcessor(4096, 1, 1)

      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return
        const float32 = e.inputBuffer.getChannelData(0)
        const int16 = float32ToInt16(float32)
        ws.send(int16.buffer)
      }

      source.connect(processor)
      processor.connect(audioCtx.destination)
    }
  } catch (err) {
    console.error('Microphone access denied', err)
  }
}
```
**What it does:** This function is called when the user clicks "Start Recording." It:
1. Asks the browser for microphone permission and gets a MediaStream
2. Opens a WebSocket to the audio endpoint
3. Once the WebSocket is open, starts the elapsed-time timer
4. Creates an audio processing pipeline using the Web Audio API
5. On every audio buffer (4096 samples at a time), converts float samples to 16-bit integers and sends them over the WebSocket

**Why `navigator.mediaDevices.getUserMedia`?** This is the standard browser API for accessing the microphone (and camera). It returns a Promise that resolves to a `MediaStream`. The browser will show a permission prompt on the first call; subsequent calls on the same origin may work silently if permission was already granted.

**ELI5 — What is AudioContext?** The Web Audio API is like a sound mixing board built into the browser. `AudioContext` is the mixing board itself. You plug in sources (microphone), run them through processors (effects, analysis), and route them to outputs (speakers). Here we are using a `ScriptProcessor` node to intercept raw audio samples so we can send them over the network.

**ELI5 — Why `sampleRate: 16000`?** Audio quality is measured in samples per second. CD quality is 44,100 Hz. Phone call quality is around 8,000 Hz. Speech recognition models (like Whisper) are typically trained on 16,000 Hz audio — enough to capture all the frequencies in human speech while keeping file sizes small. Using a higher rate would waste bandwidth; lower would reduce accuracy.

**ELI5 — What is `createScriptProcessor(4096, 1, 1)`?** This creates a node that collects audio samples into chunks. The `4096` is the buffer size — how many samples to collect before firing the `onaudioprocess` event. `1, 1` means one input channel and one output channel (mono). Every time 4096 samples accumulate (about 256ms at 16000 Hz), the callback fires with those samples.

**Why connect `processor` to `audioCtx.destination`?** Even though we don't want to play audio back to the user, `ScriptProcessor` requires being connected to the audio graph's output to function. This is a known quirk of the old `ScriptProcessor` API. The destination is essentially muted here.

**ELI5 — What is a WebSocket?** Imagine a walkie-talkie channel that stays open. Unlike a regular HTTP request (which is like sending a letter and waiting for a reply), a WebSocket keeps a two-way tunnel open. Both sides can send messages at any time. Here we open the tunnel when recording starts and send audio chunks continuously until we close it.

**Best practice:** `createScriptProcessor` is technically deprecated in favor of `AudioWorklet`, which runs processing in a separate thread and is more performant. However, `AudioWorklet` requires a separate worker file and is significantly more complex. `ScriptProcessor` is fine for a prototype and still works in all modern browsers.

---

### Lines 86–94 — The `stopRecording` function
```tsx
async function stopRecording() {
  setStopping(true)
  wsRef.current?.close()
  mediaRef.current?.getTracks().forEach(t => t.stop())
  if (timerRef.current) clearInterval(timerRef.current)

  await fetch(`${GATEWAY}/session/${sessionId}/end`, { method: 'POST' })
  // Navigation happens when pipeline_complete SSE event arrives
}
```
**What it does:** Cleans up all the active connections and resources when the user clicks "End Session":
1. Sets `stopping` to `true` (shows the "Processing..." message)
2. Closes the WebSocket connection
3. Stops all microphone tracks (releases the microphone to the OS)
4. Clears the elapsed-time timer
5. Sends a POST to tell the backend to start the processing pipeline

**Why stop the microphone tracks explicitly?** Browsers show a recording indicator (usually a red dot or camera icon) in the tab or system tray while any track from `getUserMedia` is active. Calling `.stop()` on each track releases the microphone and removes the indicator. Just closing the WebSocket does not stop the microphone.

**Why `?.` (optional chaining)?** The `wsRef.current?.close()` syntax means "call `.close()` only if `wsRef.current` is not null." This prevents a crash if `stopRecording` is somehow called before `startRecording` completed.

**Why is there no `navigate` call here?** Navigation is intentionally delayed. The backend needs to run its full pipeline (diarization, NLP, SOAP classification) before the review screen has anything to show. Rather than navigating immediately and showing an empty page, the code waits for the `pipeline_complete` SSE event (handled in the `useEffect` above) which fires only when the backend is truly done.

**ELI5:** It is like finishing a cooking show recording. You put down the knife (`wsRef.current?.close()`), turn off the kitchen lights (`mediaRef.current?.getTracks().forEach(t => t.stop())`), stop the clock (`clearInterval`), then tell the producer "we're done" (`fetch /end`). The producer edits the footage (pipeline) and calls you when the episode is ready to review (`pipeline_complete`).

**Best practice:** Always release media tracks explicitly. This is especially important in medical contexts — leaving the microphone active when recording has ended is a privacy and compliance issue.

---

### Lines 96–102 — The `float32ToInt16` converter
```tsx
function float32ToInt16(buffer: Float32Array): Int16Array {
  const out = new Int16Array(buffer.length)
  for (let i = 0; i < buffer.length; i++) {
    out[i] = Math.max(-32768, Math.min(32767, buffer[i] * 32768))
  }
  return out
}
```
**What it does:** Converts audio samples from floating-point format (which the browser's Web Audio API provides) to 16-bit integer format (which speech recognition backends typically expect).

**Why the conversion?** The Web Audio API represents audio samples as 32-bit floating point numbers in the range -1.0 to +1.0. PCM audio (the format used by telephony and most ASR systems) represents samples as 16-bit integers in the range -32768 to +32767. Multiplying by 32768 scales the float range to the integer range.

**Why `Math.max(-32768, Math.min(32767, ...))`?** This is a clamp operation. Floating-point audio can occasionally exceed the -1.0 to +1.0 range due to gain or mixing. If you multiplied 1.5 by 32768 you would get 49152, which overflows a 16-bit integer. Clamping ensures the output stays within the valid range.

**ELI5 — Float32 vs Int16:** Imagine a ruler. Float32 audio uses a ruler that goes from -1.0 to +1.0 with infinite precision between marks. Int16 audio uses a ruler that goes from -32768 to +32767, with exactly 65,536 steps and nothing in between. We are taking a measurement from the fancy ruler and marking it on the simpler ruler. The multiplication is the conversion factor, and the clamp prevents you from writing a number the second ruler can't represent.

**ELI5 — PCM audio:** PCM stands for Pulse Code Modulation. It is the most fundamental digital audio format — a list of numbers, one for every sample, each representing the air pressure (sound wave amplitude) at that instant. No compression, no headers — just the raw numbers. It is the audio equivalent of a BMP bitmap image (uncompressed raw pixel values).

**Why Int16 specifically?** Most phone and medical audio systems, as well as cloud speech APIs (Google, AWS Transcribe, Deepgram, Whisper), accept or prefer 16-bit PCM audio because it is a universal "lowest common denominator" format. 16-bit provides enough dynamic range for speech (96 dB) without the large file sizes of 32-bit formats.

**Best practice:** When sending binary data over WebSockets, use `ArrayBuffer` (which is what `int16.buffer` is). Never `.toString()` binary data — you will corrupt it. The line `ws.send(int16.buffer)` sends the raw binary buffer directly.

---

### Lines 104–105 — The `formatTime` helper
```tsx
const formatTime = (s: number) =>
  `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`
```
**What it does:** Converts a number of seconds into a `MM:SS` string. For example, `75` becomes `"01:15"`.

**Why `padStart(2, '0')`?** Without padding, 3 seconds would display as `0:3` instead of `00:03`. `padStart(2, '0')` ensures the string is always at least 2 characters wide by prepending zeros if needed.

**ELI5:** This is like formatting time on a digital clock. `Math.floor(s / 60)` gives you the minutes. `s % 60` gives you the remaining seconds. `padStart` adds a leading zero so it looks like `01:05` instead of `1:5`.

**Best practice:** Template literals (the backtick syntax `` `${...}` ``) are cleaner for string building than `+` concatenation, especially when mixing static text with dynamic values.

---

### Lines 107–183 — The JSX return
```tsx
return (
  <div style={{ maxWidth: '800px', margin: '0 auto' }}>
    ...
  </div>
)
```
**What it does:** Renders the recording screen UI. Contains:
1. A header with the session ID and elapsed timer (if recording)
2. A scrollable transcript area with finalized segments and a "ghost" partial segment
3. Conditional buttons — "Start Recording" / "End Session & Process" / "Processing..." depending on state

**Why three different button states?** The UI has three mutually exclusive phases:
- `!recording && !stopping` → before recording: show Start button
- `recording && !stopping` → actively recording: show Stop button
- `stopping` → waiting for pipeline: show Processing message

This ensures only one control is ever visible at a time, preventing the user from taking contradictory actions.

**Why `key={i}` on the segment list?** React needs a unique `key` prop on list items to track which items have changed, been added, or removed. Using the array index (`i`) is acceptable for append-only lists like this, where items are never re-ordered or deleted during rendering. For editable lists, prefer a stable unique ID like `seg.segment_id`.

**Best practice:** The transcript box should ideally auto-scroll to the bottom when new segments arrive. This is typically done with a `useRef` on the scroll container and `ref.current.scrollIntoView()` inside a `useEffect` that depends on `segments`. This is not implemented here but would be important for a real clinical use case.

---

## Common Mistakes
1. **Not cleaning up `EventSource` in the `useEffect` return** — Forgetting `return () => sse.close()` means the SSE connection stays open even after the component unmounts (e.g., the user navigates away). This wastes server resources and can cause strange behavior if the user navigates back and a second connection is opened.
2. **Sending audio before the WebSocket is open** — The `onaudioprocess` callback fires very quickly after `getUserMedia`. If you start audio processing outside the `ws.onopen` handler, you may try to `ws.send()` before the connection is ready, which silently drops data. Always set up the audio graph inside `ws.onopen`.
3. **Forgetting to stop media tracks** — If you close the WebSocket but don't call `.stop()` on each track, the browser keeps the microphone active. The OS recording indicator stays on, the microphone is held by the browser process, and the user cannot use the microphone in another application.

## Key Concepts To Look Up
- `useEffect` — when it runs, the cleanup function, and the dependency array
- `useRef` — mutable values that don't trigger re-renders
- Server-Sent Events (SSE) — `EventSource`, one-way server push
- WebSocket API — bidirectional real-time connection, `readyState`, `send`, `close`
- Web Audio API — `AudioContext`, `MediaStreamSource`, `ScriptProcessor`, `onaudioprocess`
- `navigator.mediaDevices.getUserMedia` — browser microphone access
- PCM audio — what it is, why it is used in speech recognition
- Float32 to Int16 conversion — the math behind audio format conversion
- `ArrayBuffer` and typed arrays (`Float32Array`, `Int16Array`) — binary data in JavaScript
- Optional chaining `?.` — safe property access and method calls
