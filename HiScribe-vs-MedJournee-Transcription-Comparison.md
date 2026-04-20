# HiScribe vs MedJournee — Transcription Architecture Comparison

> **Date:** 2026-04-03  
> **Purpose:** Educational deep-dive into why these two projects handle audio transcription differently, what each approach means for real-time performance, and what you should know as a speech recognition / audio AI engineer.

---

## Table of Contents

1. [The 30-Second Summary](#the-30-second-summary)
2. [What "Real-Time" Actually Means in This Context](#what-real-time-actually-means-in-this-context)
3. [HiScribe — Architecture Deep Dive](#hiscribe--architecture-deep-dive)
4. [MedJournee — Architecture Deep Dive](#medjournee--architecture-deep-dive)
5. [Side-by-Side Code Comparison](#side-by-side-code-comparison)
6. [Theory: Why the Pipelines Diverged](#theory-why-the-pipelines-diverged)
7. [Key Concepts Explained](#key-concepts-explained)
8. [Trade-offs Table](#trade-offs-table)
9. [What This Means for Your Career](#what-this-means-for-your-career)
10. [Cross-Apply: Features Each Project Should Borrow From the Other](#cross-apply-features-each-project-should-borrow-from-the-other)
11. [Independent Engineering Recommendations](#independent-engineering-recommendations)

---

## The 30-Second Summary

Both projects use **Gladia** for live audio streaming over WebSocket. That part is the same. The difference is what happens **around** Gladia and **after** the recording ends.

| | HiScribe | MedJournee |
|---|---|---|
| **Live transcription** | Gladia WebSocket (streaming) | Gladia WebSocket **+** OpenAI Whisper chunks (two paths) |
| **Speaker labels (live)** | `UNKNOWN` — deferred to pipeline | Gladia assigns speaker index immediately |
| **Post-processing** | LangGraph 6-node DAG, triggered manually | 5 independent agents, triggered automatically on session end |
| **Diarization model** | pyannote (local, offline) | AssemblyAI (cloud, async) |
| **Translation** | Not included | Bidirectional (deep-translator), runs in real time |
| **Clinical output** | SOAP sections | AI journal entry + terminology extraction |

**HiScribe is more of a clean, disciplined clinical pipeline.** It does one thing well: capture, transcribe, diarize, and map to SOAP. Its real-time layer is thin — Gladia gets you fast text, but speaker labels and clinical structure are deferred to the post-recording pipeline.

**MedJournee is a hybrid real-time system.** It tries to show the user more during the recording (speaker roles, translations) by combining two live transcription paths. It's more complex, more configurable, and more ambitious — but also more brittle.

---

## What "Real-Time" Actually Means in This Context

"Real-time" transcription is not a binary — it's a spectrum measured by **latency** (how long before you see the text) and **completeness** (how much information is in that text when you see it).

```
FASTER / LESS COMPLETE ◄─────────────────────────────► SLOWER / MORE COMPLETE

  Gladia partial          Gladia final        Whisper API         AssemblyAI
  transcripts             transcripts         (~2-3 sec)          (~15-30 sec)
  (50-200ms)              (1-2 sec)           No speaker          Full speaker
  Unstable text           Stable text         labels              labels + timing
```

Both projects land in the **Gladia final** zone for their live display. MedJournee also has the **Whisper API** path as a fallback for audio chunks. The real difference is in what comes after.

---

## HiScribe — Architecture Deep Dive

### Audio Flow

```
Browser microphone
  │
  │  Float32 PCM → Int16 PCM conversion
  │  (in LiveCapture.tsx)
  ▼
WebSocket  ws://localhost:3000/session/{id}/audio
  │
  │  Raw Int16 PCM chunks (4096 samples at 16 kHz = 256ms per chunk)
  ▼
Gateway (Node.js / Fastify)
  ├──► AudioStorage: saves raw PCM to disk → /data/audio/{session_id}.wav
  └──► Gladia WebSocket  wss://api.gladia.io/audio/text/audio-transcription
            │
            │  Returns: partial + final transcript events
            ▼
       SSE stream → browser (live display)

On "End Session":
  POST /session/{id}/end
  │
  ▼
Python Pipeline (LangGraph)
  finalize → diarize → role_classify → map → score → package
  │
  ▼
SSE event: pipeline_complete → browser navigates to /review
```

### Key File 1: `client/src/LiveCapture.tsx`

```tsx
async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  mediaRef.current = stream

  const ws = new WebSocket(`${WS_GATEWAY}/session/${sessionId}/audio`)
  wsRef.current = ws

  ws.onopen = () => {
    setRecording(true)
    timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)

    // Stream PCM audio chunks over WebSocket
    const audioCtx = new AudioContext({ sampleRate: 16000 })
    const source = audioCtx.createMediaStreamSource(stream)
    const processor = audioCtx.createScriptProcessor(4096, 1, 1)

    processor.onaudioprocess = (e) => {
      if (ws.readyState !== WebSocket.OPEN) return
      const float32 = e.inputBuffer.getChannelData(0)
      const int16 = float32ToInt16(float32)
      ws.send(int16.buffer)    // <-- raw PCM, no encoding overhead
    }

    source.connect(processor)
    processor.connect(audioCtx.destination)
  }
}

function float32ToInt16(buffer: Float32Array): Int16Array {
  const out = new Int16Array(buffer.length)
  for (let i = 0; i < buffer.length; i++) {
    out[i] = Math.max(-32768, Math.min(32767, buffer[i] * 32768))
  }
  return out
}
```

**What this does line by line:**

- `AudioContext({ sampleRate: 16000 })` — creates the browser's audio processing graph at 16 kHz. Speech recognition models are trained at 16 kHz; using 48 kHz (the browser default) wastes bandwidth and can confuse models.
- `createScriptProcessor(4096, 1, 1)` — creates an audio processing node that fires every 4096 samples. At 16 kHz, `4096 / 16000 = 256ms` per callback. This is your chunk size.
- `e.inputBuffer.getChannelData(0)` — gets the raw float samples from channel 0 (mono).
- `float32ToInt16` — the Web Audio API gives you 32-bit floats in the range `[-1.0, 1.0]`. ASR APIs expect 16-bit signed integers (`-32768` to `32767`). This multiply-and-clamp is the standard conversion.
- `ws.send(int16.buffer)` — sends the raw binary ArrayBuffer over WebSocket. No JSON wrapping, no base64 encoding — raw binary is the most efficient.

### Key File 2: `gateway/src/adapters/gladia.ts`

```typescript
export function transcribe(
  sessionId: string,
  clientSocket: WebSocket,
  onSegment: OnSegment
): void {
  const gladiaWs = new WebSocket(
    'wss://api.gladia.io/audio/text/audio-transcription',
    { headers: { 'x-gladia-key': apiKey } }
  )

  gladiaWs.on('open', () => {
    // Send session config on connect
    gladiaWs.send(JSON.stringify({
      x_gladia_key: apiKey,
      encoding: 'WAV/PCM',
      sample_rate: 16000,
      language_behaviour: 'automatic single language',
      frames_format: 'bytes'
    }))
  })

  gladiaWs.on('message', (data: Buffer) => {
    const msg = JSON.parse(data.toString())
    if (msg.event === 'transcript' && msg.transcription) {
      const isFinal = msg.type === 'final'
      onSegment({
        text: msg.transcription,
        speaker: 'UNKNOWN',   // <-- NOTE: speaker is intentionally blank here
        start_ms: msg.time_begin ? Math.round(msg.time_begin * 1000) : 0,
        end_ms: msg.time_end ? Math.round(msg.time_end * 1000) : 0,
        confidence: msg.confidence ?? 1.0,
        is_final: isFinal
      })
    }
  })

  // Gateway acts as a transparent pass-through for audio chunks
  clientSocket.on('message', (chunk: Buffer) => {
    if (gladiaWs.readyState === WebSocket.OPEN) {
      gladiaWs.send(chunk)
    }
  })

  clientSocket.on('close', () => gladiaWs.close())
}
```

**The critical architectural decision here:** speaker is always `'UNKNOWN'`. HiScribe deliberately does not trust Gladia's live speaker index. Why? Because Gladia's live diarization is acoustic — it distinguishes voices by who sounds different. But it cannot tell you _which_ voice is the doctor and which is the patient. HiScribe defers that judgment to its pyannote + role classifier pipeline, which has access to the full recording and two separate models.

### Key File 3: `pipeline/graph/nodes.py` (the LangGraph pipeline)

```python
# Node 2: pyannote diarization runs on the FULL saved audio
def diarize_node(state: ScribeState) -> ScribeState:
    session_id = state['session_id']
    audio_path = os.path.join(AUDIO_DIR, f'{session_id}.wav')

    diarization = diarize(audio_path)

    for seg in segments:
        label = _match_speaker(seg['start_ms'], seg['end_ms'], diarization)
        seg['speaker'] = label
        update_segment_diarization(seg['segment_id'], label, role_flag=False)

    return {**state, 'segments': segments}


# Node 3: Keras role classifier cross-checks pyannote
def role_classify_node(state: ScribeState) -> ScribeState:
    for seg in segments:
        predicted_role = role_classify(pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s)
        diarized_role = seg.get('speaker', 'SPEAKER_0')

        # Flag if classifier disagrees with diarization label
        disagrees = False
        if predicted_role == 'DOCTOR' and 'SPEAKER_1' in diarized_role:
            disagrees = True
        elif predicted_role == 'PATIENT' and 'SPEAKER_0' in diarized_role:
            disagrees = True

        if disagrees:
            seg['role_flag'] = True
            role_flags.append(seg['segment_id'])


# Node 4: LLM maps each segment to SOAP section
def map_node(state: ScribeState) -> ScribeState:
    mappings = map_segments(segments)  # LLM call
    for seg in segments:
        seg['soap_section'] = mapping_dict.get(str(seg.get('id', '')), 'UNCLASSIFIED')


# Node 5: PyTorch confidence rescorer
def score_node(state: ScribeState) -> ScribeState:
    for seg in segments:
        reliability = rescore(
            asr_confidence=seg.get('confidence', 1.0),
            token_count=len(seg['text'].split()),
            soap_section=seg.get('soap_section', 'S')
        )
        seg['reliability_score'] = reliability
        seg['confidence_flag'] = reliability < 0.6
```

**What this pattern is called:** a **DAG (Directed Acyclic Graph) pipeline**. Each node receives state, modifies it, and passes it forward. No node can go backwards. LangGraph manages this as a typed state machine.

---

## MedJournee — Architecture Deep Dive

### Audio Flow

```
Browser microphone
  │
  ├──PATH A: Live Gladia ─────────────────────────────────────────────────────────┐
  │    │                                                                           │
  │    │  POST /gladia/session  → gets Gladia session URL                         │
  │    │  WS  /gladia/ws/{session_id}                                             │
  │    │                                                                           │
  │    │  Browser sends: raw PCM binary (16-bit, 16 kHz, mono)                   │
  │    │  Backend → Gladia WebSocket (transparent proxy)                          │
  │    │  Gladia → Backend: final transcript + speaker_index + language           │
  │    │  Backend enriches with translation                                       │
  │    │  Backend → Browser: JSON {text, translation, speaker_role, ...}          │
  │    └───────────────────────────────────────────────────────────────────────────┤
  │                                                                                │
  └──PATH B: Instant Transcription (file upload chunks)                           │
       │                                                                           │
       │  POST /instant-transcribe/ (multipart file upload)                       │
       │  Backend: FFmpeg → WAV → OpenAI Whisper API                              │
       │  Returns: text + translation + detected_language (~2-3 sec latency)      │
       └───────────────────────────────────────────────────────────────────────────┘

Recording stops → POST /finalize-session/
  │
  ├──► Skip AssemblyAI if Gladia was used (transcripts already collected)
  ├──► Voice enrollment matching (identify family members)
  ├──► Parallel:
  │    ├──► TranslationAgent
  │    └──► TerminologyAgent
  ├──► SummarizationAgent (GPT-4 journal entry)
  └──► Save to database
```

### Key File 4: `services/gladia_service.py`

```python
async def create_live_session(languages: list[str]) -> dict:
    """
    Create a Gladia live transcription session.
    Called BEFORE the WebSocket opens — establishes the session on Gladia's side.
    """
    clean_langs = [l for l in languages if l and l not in ("auto", "")]
    if not clean_langs:
        clean_langs = ["en"]

    config = {
        "encoding": "wav/pcm",
        "bit_depth": 16,
        "sample_rate": 16000,
        "channels": 1,
        "language_config": {
            "languages": clean_langs,
            "code_switching": len(clean_langs) > 1,  # enables multilingual mode
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{GLADIA_BASE_URL}/v2/live",   # <-- Gladia v2 API
            headers={"X-Gladia-Key": GLADIA_API_KEY, "Content-Type": "application/json"},
            json=config,
        )
        data = response.json()

    session_id = data["id"]
    gladia_url = data["url"]
    _sessions[session_id] = gladia_url   # store for WebSocket proxy to look up
    return {"session_id": session_id, "url": gladia_url}
```

**Important difference from HiScribe:** MedJournee uses **Gladia v2** (`/v2/live`), which requires a two-step process:
1. `POST /v2/live` → get a session ID and WebSocket URL
2. Connect to that specific URL with your PCM audio

HiScribe uses **Gladia v1** (`/audio/text/audio-transcription`), a single persistent WebSocket that accepts config as the first message.

### Key File 5: `routes/gladia_routes.py` — The WebSocket Proxy

```python
@router.websocket("/ws/{session_id}")
async def websocket_proxy(websocket: WebSocket, session_id: str, token: str = "", ...):
    await websocket.accept()
    gladia_url = get_session_url(session_id)

    async with websockets.connect(gladia_url) as gladia_ws:

        async def audio_to_gladia():
            """Forward PCM audio from browser to Gladia."""
            while True:
                data = await websocket.receive_bytes()
                await gladia_ws.send(data)   # transparent pass-through

        async def gladia_to_browser():
            """Receive Gladia transcripts, enrich with translation, forward to browser."""
            async for raw in gladia_ws:
                msg = json.loads(raw)

                # Only forward FINAL transcripts (not partials)
                if msg.get("type") != "transcript":
                    continue
                data = msg.get("data", {})
                if not data.get("is_final"):
                    continue

                utterance = data.get("utterance") or data.get("utterances")
                # ...

                for utterance in utterances:
                    text = utterance.get("text", "").strip()
                    speaker_index = utterance.get("speaker", 0)
                    detected_lang = utterance.get("language", "en").lower()

                    # Speaker 0 = provider, Speaker 1 = family (Gladia's guess)
                    is_family = speaker_index == 1
                    speaker_role = "patient_family" if is_family else "provider"

                    # Translate based on detected language
                    t_result = await translate_text(text, target, detected_lang)
                    translation = t_result.get("translated_text", "")

                    await websocket.send_json({
                        "type": "transcript",
                        "text": text,
                        "translation": translation,
                        "speaker_role": speaker_role,
                        "speaker_index": speaker_index,
                        "detected_language": detected_lang,
                        "is_final": True,
                    })

        # Run both directions concurrently
        await asyncio.gather(audio_to_gladia(), gladia_to_browser(), return_exceptions=True)
```

**What `asyncio.gather` does here:** it runs two coroutines concurrently within the same async event loop. `audio_to_gladia()` is always listening for browser audio. `gladia_to_browser()` is always listening for Gladia responses. They run in parallel without threading — this is Python's cooperative multitasking.

### Key File 6: `services/realtime_transcription_service.py` — The Whisper Path

```python
async def transcribe_chunk_instant(self, audio_file) -> Dict[str, Any]:
    """
    FAST transcription using OpenAI Whisper API.
    Returns text within 2-3 seconds. No speaker detection.
    Use this DURING recording for instant feedback.
    """

    # Step 1: Check minimum size (silence filter)
    if len(audio_content) < 5000:   # < 5KB = likely silence
        return {"success": True, "text": "", "is_empty": True}

    # Step 2: FFmpeg converts browser audio chunks to WAV
    # CRITICAL: MediaRecorder chunks after the first are NOT self-contained.
    # They lack the audio header that tells the decoder how to interpret them.
    result = subprocess.run([
        'ffmpeg',
        '-f', input_ext,        # force input format (bypasses broken headers)
        '-i', temp_input.name,
        '-ar', '16000',         # 16 kHz sample rate
        '-ac', '1',             # mono
        '-c:a', 'pcm_s16le',    # 16-bit signed PCM (what Whisper expects)
        '-y', temp_output.name
    ], capture_output=True, text=True, timeout=10)

    # Step 3: Send to OpenAI Whisper
    response = self.openai_client.audio.transcriptions.create(
        model="whisper-1",
        file=file_tuple,
        response_format="verbose_json"   # includes detected language
    )

    # Step 4: Filter Whisper hallucinations
    hallucination_phrases = [
        "thank you", "thanks for watching", "subscribe",
        "music", "applause", "silence"
    ]
    if any(phrase in transcribed_text.lower() for phrase in hallucination_phrases):
        return {"success": True, "text": "", "is_empty": True}

    return {
        "success": True,
        "text": transcribed_text,
        "detected_language": detected_language
    }
```

---

## Side-by-Side Code Comparison

### How audio leaves the browser

**HiScribe** (`LiveCapture.tsx`):
```typescript
// Uses Web Audio API ScriptProcessor for raw PCM streaming
const processor = audioCtx.createScriptProcessor(4096, 1, 1)
processor.onaudioprocess = (e) => {
  const float32 = e.inputBuffer.getChannelData(0)
  const int16 = float32ToInt16(float32)
  ws.send(int16.buffer)   // raw binary, no encoding
}
```

**MedJournee** (`gladia_routes.py` — Python proxy side):
```python
async def audio_to_gladia():
    while True:
        data = await websocket.receive_bytes()   # raw PCM from browser
        await gladia_ws.send(data)               # pass-through to Gladia
```
The browser-side audio capture in MedJournee is similar — raw PCM over WebSocket. The difference is that MedJournee also has a **second path** using `MediaRecorder` file chunks sent via HTTP multipart upload (the Whisper path).

---

### How transcripts are received and routed

**HiScribe** (gateway handles Gladia, pushes to SSE):
```typescript
gladiaWs.on('message', (data: Buffer) => {
  const msg = JSON.parse(data.toString())
  if (msg.event === 'transcript' && msg.transcription) {
    onSegment({
      text: msg.transcription,
      speaker: 'UNKNOWN',    // <-- deferred — pipeline assigns speakers later
      is_final: msg.type === 'final'
    })
  }
})
```

**MedJournee** (proxy enriches and forwards immediately):
```python
speaker_index = utterance.get("speaker", 0)
speaker_role = "patient_family" if speaker_index == 1 else "provider"

# Translation happens HERE, in the WebSocket loop
t_result = await translate_text(text, target, detected_lang)

await websocket.send_json({
    "text": text,
    "translation": translation,          # <-- enriched immediately
    "speaker_role": speaker_role,        # <-- assigned immediately
    "detected_language": detected_lang,
})
```

---

### How speaker diarization works

**HiScribe** — offline pyannote on the full recording:
```python
def diarize_node(state: ScribeState) -> ScribeState:
    audio_path = os.path.join(AUDIO_DIR, f'{session_id}.wav')
    diarization = diarize(audio_path)   # pyannote on complete file

    for seg in segments:
        label = _match_speaker(seg['start_ms'], seg['end_ms'], diarization)
        seg['speaker'] = label
```

**MedJournee** — AssemblyAI cloud diarization as a fallback after recording:
```python
# In finalize_with_diarization():
diarized_segments = await cloud_speaker_service.process_audio_with_diarization(file_wrapper)

# Then voice enrollment matching to identify known family members
if enrolled_name and confidence >= 0.65:
    segment["speaker"] = "SPEAKER_2"
    segment["enrolled_speaker"] = enrolled_name
```

---

## Theory: Why the Pipelines Diverged

### HiScribe's Philosophy: **Deferred Accuracy**

HiScribe treats the live display as a rough real-time preview, and the post-processing pipeline as the source of truth. This is a **two-pass architecture**:

- **Pass 1 (live):** Get text on screen quickly. Speaker labels don't matter yet.
- **Pass 2 (offline):** Run the best diarization model available (pyannote locally) over the full, uninterrupted audio. Then use a second ML model to cross-check the labels.

**Why this is good for clinical use:** In a medical appointment, getting the transcript structure right is more important than getting it fast. A doctor reviewing notes after a visit doesn't need instantaneous labels — they need accurate ones. A wrong speaker attribution in a SOAP note is a patient safety issue.

**The cost:** There is a `~10-20 second` processing gap after recording stops before the review screen appears. You can see this in the UI:
```tsx
{stopping && (
  <div style={{ textAlign: 'center', color: '#6b7280', padding: '16px' }}>
    Processing... pipeline running (~10–20 seconds)
  </div>
)}
```

### MedJournee's Philosophy: **Hybrid Real-Time with Graceful Degradation**

MedJournee tries to give users useful information at every stage:
- During recording: speaker roles + translations from Gladia
- On chunk upload: fast text from Whisper  
- After recording: enhanced speaker matching via voice enrollment

This is called a **progressive enrichment** pattern. The same conversation keeps getting more information added to it as more processing completes.

**Why this exists:** MedJournee serves multi-generational families where a patient might be elderly and not speak English. The family member translating in the room needs to see both languages in real time. Deferring translation to post-processing isn't an option — the conversation happens now.

**The cost:** More moving parts. Two live transcription paths means two hallucination filters, two audio conversion paths, two WebSocket connections to manage. The complexity is visible in the `transcribe_chunk_instant` function's FFmpeg fallback logic.

### The Deeper Reason: Different Users, Different Needs

```
HiScribe user:           MedJournee user:
- Doctor reviewing       - Family member watching
  notes after visit        real-time translation
- Accuracy critical      - Immediacy critical
- Can wait 20 seconds    - Cannot wait 3 seconds
- English-only           - Multi-language
- SOAP structure needed  - Journal narrative needed
```

---

## Key Concepts Explained

### WebSocket vs SSE — Two Different Channels in HiScribe

HiScribe uses **two** separate protocols simultaneously:

```
Browser ──WebSocket──► Gateway  (audio goes UP)
Browser ◄───SSE──────  Gateway  (transcripts come DOWN)
```

**WebSocket** (`ws://`) is bidirectional — both sides can send and receive. Good for audio streaming because it supports binary frames efficiently.

**SSE (Server-Sent Events)** is one-way — server pushes, browser listens. HiScribe uses SSE for transcripts because:
- The browser only needs to receive transcript events, never send
- SSE reconnects automatically if the connection drops
- SSE is more firewall-friendly than WebSockets for long-lived connections

MedJournee uses a single bidirectional WebSocket for both audio (up) and transcripts (down). This is simpler but means reconnection logic has to be handled manually.

### `asyncio.gather` — Python's Concurrent Coroutines

```python
await asyncio.gather(
    audio_to_gladia(),     # loop: browser → Gladia
    gladia_to_browser(),   # loop: Gladia → browser
    return_exceptions=True
)
```

This is the heart of MedJournee's WebSocket proxy. It runs both async loops simultaneously in a single thread. When `audio_to_gladia()` is awaiting a browser message (`await websocket.receive_bytes()`), Python's event loop switches to running `gladia_to_browser()`. This is cooperative multitasking — no threads needed.

`return_exceptions=True` means if one coroutine crashes, the other keeps running. This is why you see `logger.warning` inside each function — either can fail independently without killing the proxy.

### PCM — Why Raw Samples Instead of MP3/WebM

Both projects convert audio to raw PCM (Pulse Code Modulation) before sending to ASR:
- **Float32** (Web Audio API native) → **Int16** (ASR API expected format)
- **16 kHz** sample rate (speech is mostly below 8 kHz, so 16 kHz captures all of it per Nyquist theorem)
- **Mono** (speech recognition doesn't need stereo; stereo doubles bandwidth)

The reason MedJournee needs FFmpeg: `MediaRecorder` (the browser's file-recording API) produces encoded audio files (WebM/Opus, MP4/AAC). After the first chunk, subsequent chunks are missing their file headers — they're delta-encoded segments that only make sense in sequence. FFmpeg reads the raw bitstream and re-wraps it into a self-contained WAV file that Whisper can process.

HiScribe avoids this problem entirely by using `ScriptProcessor` to get raw PCM samples directly — it never goes through `MediaRecorder`.

### Hallucination Filtering — A Real Production Problem

Both projects filter Whisper/Gladia hallucinations. This is not a nice-to-have — it's a clinical necessity.

Whisper hallucinates specific phrases when given silence or ambient noise:
```python
hallucination_phrases = [
    "thank you", "thanks for watching", "subscribe",
    "music", "applause", "silence"
]
```

Gladia also hallucinates on short silence segments:
```python
_HALLUCINATIONS = {
    "thank you", "thanks", "you", "uh", "um", "hmm",
    "slurp", "conversation", "bye", "bye bye",
    "okay", "ok", "hey", "hi", "hello",
}
```

In a medical note, `"thank you"` appearing as a spontaneous artifact could be misread as part of a patient's symptom description. Both projects filter these out before they reach the display layer.

### LangGraph vs Multi-Agent Orchestrator

**HiScribe's LangGraph** is a typed state machine. The state (`ScribeState`) carries everything — segments, role_flags, soap mappings — through each node. Nodes are pure functions: they receive state and return modified state.

```python
class ScribeState(TypedDict):
    session_id: str
    segments: List[dict]
    role_flags: List[str]
    mapped_segments: List[dict]
    scored_segments: List[dict]
    review_payload: dict
```

**MedJournee's orchestrator** is more like a task runner. Agents are independent objects that receive inputs and produce outputs. The orchestrator calls them in sequence or parallel with quality gates between them.

The key difference: LangGraph enforces that each step receives the output of the previous step. The multi-agent pattern allows parallel execution but requires more careful output merging.

---

## Trade-offs Table

| Concern | HiScribe Choice | MedJournee Choice | Winner (depends on) |
|---|---|---|---|
| **Speaker accuracy** | pyannote + role classifier (2 models) | AssemblyAI + voice enrollment | HiScribe for raw accuracy; MedJournee for known-speaker recognition |
| **Translation** | None | Bidirectional, real-time | MedJournee (required for multilingual patients) |
| **Latency to first text** | Sub-second (Gladia partials displayed) | Sub-second (Gladia) + 2-3s (Whisper) | Gladia path is equivalent |
| **Latency to speaker labels** | 10-20 seconds after recording ends | 0 seconds (Gladia live) / 15-30 seconds (AssemblyAI) | MedJournee for immediacy; HiScribe for accuracy |
| **Complexity** | Lower (one live path) | Higher (two live paths + proxy logic) | HiScribe for maintainability |
| **Custom ML** | Yes (2 local models: confidence, role) | No custom models | HiScribe for portfolio differentiation |
| **Clinical structure** | SOAP sections (standard medical) | AI journal + terminology | HiScribe for EHR integration |
| **Compliance guardrails** | Minimal | HIPAA PII detection, audio deletion | MedJournee for production readiness |
| **API cost** | One API (Gladia) | Three APIs (Gladia + Whisper + AssemblyAI) | HiScribe for cost efficiency |

---

## What This Means for Your Career

As someone targeting **speech recognition AI engineering in healthtech**, here is what both projects demonstrate to a hiring manager:

### What HiScribe Demonstrates

1. **You understand the full ASR pipeline** — not just "call the API." You know about:
   - Float32 → Int16 PCM conversion and why it exists
   - 16 kHz as the standard for speech (Nyquist, speech frequency range)
   - WebSocket binary frame streaming vs encoded file upload
   - Post-recording diarization as a design choice, not a limitation

2. **You use production patterns** — LangGraph state machines, typed state with TypedDict, SSE for push notifications, custom ML inference for confidence scoring.

3. **You understand clinical data structures** — SOAP note mapping is not obvious. It shows you researched the medical domain, not just the ML domain.

### What MedJournee Demonstrates

1. **You solve real user problems** — real-time translation for multilingual healthcare is a genuine healthcare equity issue. You built for it.

2. **You handle operational complexity** — FFmpeg fallbacks, hallucination filtering, voice enrollment matching, retry logic, HIPAA guardrails. These are the details that distinguish a production system from a demo.

3. **You think about failure** — `return_exceptions=True`, graceful degradation to alternating speakers, `_apply_default_speakers` as a fallback. Real systems fail. You planned for it.

### What to Say in Interviews

When asked "which approach is better," the correct answer is: **it depends on the latency vs. accuracy trade-off your use case requires.**

- If the output feeds a doctor's EHR review workflow → defer, be accurate → HiScribe approach
- If the output serves a real-time interpretation need → enrich progressively, tolerate some noise → MedJournee approach
- In production, you would likely **combine both**: use Gladia live for immediate display, replace with diarized transcript once AssemblyAI completes (like a diff/merge)

The fact that you built both versions — and can articulate why they differ — is the portfolio artifact. Most candidates bring one approach. You bring two, and can compare them.

---

## Architecture Diagrams Summary

### HiScribe — Clean Two-Pass Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    PASS 1: LIVE (ms latency)                │
│                                                             │
│  Browser ──PCM WebSocket──► Gateway ──► Gladia             │
│                                │                            │
│                            SSE stream                       │
│                                │                            │
│  Browser ◄─────────────────────┘                           │
│  (shows text, speaker = UNKNOWN)                            │
└─────────────────────────────────────────────────────────────┘
                          ▼ recording ends
┌─────────────────────────────────────────────────────────────┐
│                 PASS 2: PIPELINE (10-20 sec)                │
│                                                             │
│  finalize → diarize (pyannote) → role_classify (Keras)     │
│      → map (LLM → SOAP) → score (PyTorch) → package       │
│                                                             │
│  Result: structured SOAP note with speaker labels,          │
│  confidence flags, role disagreements                       │
└─────────────────────────────────────────────────────────────┘
```

### MedJournee — Progressive Enrichment

```
┌─────────────────────────────────────────────────────────────┐
│              LIVE: Gladia (0ms display lag)                 │
│                                                             │
│  Browser ──PCM WebSocket──► Backend proxy ──► Gladia       │
│                                │                            │
│                         enrich with translation             │
│                                │                            │
│  Browser ◄─────────────────────┘                           │
│  (shows text + translation + speaker_role)                  │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│           PARALLEL: Whisper chunks (2-3 sec lag)            │
│                                                             │
│  Browser ──file upload──► FFmpeg ──► Whisper API           │
│  (fallback path, no speaker labels)                         │
└─────────────────────────────────────────────────────────────┘
                          ▼ recording ends
┌─────────────────────────────────────────────────────────────┐
│            FINALIZE: 5-agent orchestration                  │
│                                                             │
│  AssemblyAI diarization ──► voice enrollment match         │
│  ├── TranslationAgent (parallel)                           │
│  ├── TerminologyAgent (parallel)                           │
│  └── SummarizationAgent ──► AI journal entry (GPT-4)      │
└─────────────────────────────────────────────────────────────┘
```

---

---

## Cross-Apply: Features Each Project Should Borrow From the Other

These are gaps verified against the actual code — not hypothetical improvements, but specific things one project already solved that the other has not applied.

---

### From MedJournee → HiScribe

#### 1. Hallucination filtering in the Gladia adapter — critical, easy fix

**Where the gap is:** `gateway/src/adapters/gladia.ts:43-56`

HiScribe passes every word Gladia returns straight to the database and SSE stream with zero filtering:

```typescript
if (msg.event === 'transcript' && msg.transcription) {
  onSegment({
    text: msg.transcription,  // no filtering — goes directly to saveSegment()
    speaker: 'UNKNOWN',
    ...
  })
}
```

**What MedJournee does instead** (`routes/gladia_routes.py:130-145`):

```python
_HALLUCINATIONS = {
    "thank you", "thanks", "you", "uh", "um", "hmm",
    "slurp", "conversation", "bye", "bye bye", "okay", ...
}
if text.lower().rstrip(".!?,") in _HALLUCINATIONS:
    logger.debug(f"[Gladia] Hallucination filtered: {text!r}")
    continue  # never reaches browser or DB
```

**Why it matters:** In a SOAP note, a spurious `"thank you"` under the Plan section is a data quality issue that a reviewing doctor could act on. Whisper and Gladia both hallucinate these phrases on silence or ambient noise. This filter belongs in HiScribe's `gladia.ts` before `onSegment` is called. It's a ~5-line addition.

**What this teaches:** ASR hallucinations are not bugs in the API — they are a known behavior of transformer-based models when given insufficient signal. Every production ASR pipeline needs a filtering layer between the model output and any storage or display layer.

---

#### 2. Audio deletion after pipeline completes — compliance gap

**Where the gap is:** `gateway/src/adapters/audioStorage.ts:17-31`

The raw PCM WAV is written to disk and never deleted:

```typescript
export function finalizeAudio(sessionId: string): void {
  fs.writeFileSync(outPath, wavBuffer)
  chunkBuffers.delete(sessionId)
  // ← nothing ever removes this file from /data/audio/
}
```

**What MedJournee does instead:** `guardrails/audio_deletion_enforcer.py` — a full audit-logged guardrail that tracks every audio file written, verifies deletion after processing, and force-deletes anything remaining at pipeline end.

**The minimum HiScribe fix:** In `pipeline/graph/nodes.py`, the final node is `package_node`. After the review payload is built, add:

```python
import os
audio_path = os.path.join(AUDIO_DIR, f"{state['session_id']}.wav")
if os.path.exists(audio_path):
    os.unlink(audio_path)
    print(f"[package] Audio deleted: {audio_path}")
```

**Why it matters:** Real patient audio sitting on disk indefinitely after a visit is a HIPAA exposure. Clinical recording tools must have a defined audio retention policy and enforce it in code, not just in documentation.

**What this teaches:** In healthcare systems, audio is PHI (Protected Health Information). The compliance contract is not just "don't expose it" — it's "delete it as soon as it is no longer needed for processing." Audit trails of deletion (like MedJournee's `DeletionAuditLog`) are expected in regulated environments.

---

#### 3. Speaker confidence guard — distinct from text confidence

**Where the gap is:** `pipeline/graph/nodes.py:117-134` (the `score_node`)

HiScribe's `score_node` measures **text reliability** — how confident the ASR was about the words themselves. That's the PyTorch rescorer. But it has no equivalent check for **speaker attribution reliability** — how confident pyannote was about which speaker window a segment falls in.

**What MedJournee does instead:** `guardrails/speaker_confidence_guard.py` — enforces a minimum confidence threshold on speaker labels and downgrades low-confidence attributions to `SPEAKER_UNKNOWN`:

```python
if confidence < self.config.min_confidence:  # default: 0.6
    segment["speaker"] = "SPEAKER_UNKNOWN"
    segment["speaker_role"] = "Unknown"
```

**Why these are different:**
- Text confidence: Did ASR correctly transcribe `"myocarditis"` vs `"my oh car dye tis"`?
- Speaker confidence: Was pyannote's window assignment for this segment reliable, or was there audio overlap/cross-talk that made the speaker boundary ambiguous?

A segment can have high text confidence but a misattributed speaker — and in a clinical note, a misattributed statement is still a patient safety risk regardless of how well the words were transcribed.

**What this teaches:** Confidence in a machine learning pipeline is not a single value — it is a property of each step independently. Text confidence, speaker confidence, and section-mapping confidence are three separate dimensions. Surfacing all three to the reviewer gives them the information they need to decide what to trust.

---

### From HiScribe → MedJournee

#### 4. Partial transcript display — the UI feels dead without it

**Where the gap is:** `routes/gladia_routes.py:118-119`

MedJournee explicitly drops every non-final Gladia event:

```python
if not data.get("is_final"):
    continue  # partials are silently dropped
```

**What HiScribe does instead:** `gateway/src/routes/session.ts:64-66` broadcasts partials to SSE, and `client/src/LiveCapture.tsx:46-50` renders them with a cursor:

```typescript
if (!segment.is_final) {
  broadcastSegment(sessionId, { type: 'partial', ...segment })
  return
}
```

```tsx
{partial && (
  <div style={{ color: '#6b7280', fontSize: '14px', fontStyle: 'italic' }}>
    {partial}▊
  </div>
)}
```

**Why it matters:** Between Gladia final transcripts there is 1-2 seconds of silence where MedJournee shows nothing. The user stares at a frozen screen and has no indication whether the microphone is still active or whether transcription is working. Partials make the system feel live. They are intentionally styled differently (italic, dimmer color) so the user knows they are not committed text.

**What this teaches:** UI responsiveness is not just about speed — it's about feedback. A 2-second wait feels instant if something is visibly happening. The same 2-second wait feels broken if the screen is frozen. Partial transcripts are a UX affordance, not a data accuracy feature.

---

#### 5. Role classifier cross-check — MedJournee trusts Gladia blindly

**Where the gap is:** `routes/gladia_routes.py:156-157`

MedJournee assigns speaker role directly from Gladia's `speaker_index`:

```python
is_family = speaker_index == 1
speaker_role = "patient_family" if is_family else "provider"
```

Gladia says "first voice heard = index 0." That is a positional guess based on acoustic separation. It has no knowledge of clinical vocabulary, speaking rate, pitch range, or any other feature that distinguishes a provider from a patient.

**What HiScribe does instead:** `pipeline/graph/nodes.py:65-96` — a TF Keras role classifier checks acoustic features (pitch mean, pitch variance, words-per-second, pause ratio, average word length, duration) and flags segments where the classifier prediction disagrees with the diarization label:

```python
predicted_role = role_classify(pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s)

if predicted_role == 'DOCTOR' and 'SPEAKER_1' in diarized_role:
    disagrees = True
# → role_flag = True, surfaced in review UI
```

**Why it matters:** If Gladia's speaker index is wrong — which happens when both speakers start talking at the same time, or when the provider is the quieter voice — MedJournee's journal entry is misattributed and nobody is alerted. HiScribe's `role_flags` list gives the reviewer explicit notice of disagreements to check. Applied to MedJournee's finalize step, this would meaningfully improve attribution reliability for ambiguous recordings.

**What this teaches:** Any system that assigns clinical meaning to speaker labels (provider said X, patient said Y) must have at least two independent signals cross-checking those labels. A single model's output, no matter how good, should be treated as a hypothesis to verify, not a fact to act on.

---

### Cross-Apply Priority Table

| | From | To | Impact | Effort |
|---|---|---|---|---|
| Hallucination filter in Gladia adapter | MedJournee | HiScribe | High | Trivial (~5 lines) |
| Audio deletion after pipeline | MedJournee | HiScribe | High (compliance) | Low (1-3 lines in package_node) |
| Partial transcript display | HiScribe | MedJournee | High (UX) | Low (remove the `continue`, add partial send) |
| Role classifier cross-check | HiScribe | MedJournee | High (accuracy) | Medium (port or adapt the pattern) |
| Speaker confidence guard | MedJournee | HiScribe | Medium | Medium (add to diarize_node output) |

---

## Independent Engineering Recommendations

These are gaps identified from engineering knowledge and best practices — not based on what one project has vs the other, but on what the code shows is missing when measured against production-quality standards for clinical audio systems.

---

### HiScribe — Independent Recommendations

#### A. The entire gateway has no authentication

**Verified in:** `gateway/src/server.ts` — zero auth middleware registered. `gateway/src/routes/session.ts` — no guards on any route.

Any browser tab that knows a valid session UUID can:
- Open `ws://host:3000/session/{id}/audio` and inject audio into a live clinical recording
- Listen to `GET /session/{id}/stream` and read another patient's transcript
- `POST /session/{id}/end` and trigger the pipeline on any session

MedJournee solves this with two separate auth patterns:

```python
# HTTP routes: Bearer JWT
@router.post("/session")
async def create_session(req: SessionRequest, _user: dict = Depends(require_auth)):
    ...

# WebSocket: query param JWT (browsers can't send headers during WS handshake)
async def websocket_proxy(websocket: WebSocket, token: str = ""):
    verify_ws_token(token)
```

The two-pattern approach exists because browsers cannot send custom `Authorization` headers during the WebSocket upgrade handshake — the token must travel as a URL query parameter (`?token=<jwt>`). HiScribe needs both patterns: `Authorization: Bearer` for HTTP routes and `?token=` for WebSocket and SSE.

**What this teaches:** WebSocket authentication is frequently misunderstood. The HTTP handshake that upgrades a connection to WebSocket does not carry `Authorization` headers in browser environments. The industry-standard workaround is passing a short-lived token as a query parameter, validating it server-side on connection, and then not re-validating per-message (because the connection itself is authenticated). Tokens passed in URLs do appear in server logs — so they should be short-lived (< 60 seconds) or scoped to the session.

---

#### B. `createScriptProcessor` is deprecated

**Verified in:** `client/src/LiveCapture.tsx:69`

```tsx
const processor = audioCtx.createScriptProcessor(4096, 1, 1)
```

`ScriptProcessor` was deprecated in the Web Audio API spec and is being removed from browsers. It also runs on the **main thread**, which means it competes with React rendering — UI updates during recording can cause audio dropouts because the same thread is handling both. The modern replacement is `AudioWorklet`, which runs audio processing in a dedicated worker thread isolated from the main thread.

The migration requires:
1. Writing a small `audio-processor.worklet.js` file that extends `AudioWorkletProcessor`
2. Loading it with `audioCtx.audioWorklet.addModule('audio-processor.worklet.js')`
3. Creating an `AudioWorkletNode` instead of `ScriptProcessor`
4. Communicating PCM data back to the main thread via `MessagePort`

**What this teaches:** The Web Audio API has two generations. The first generation (`ScriptProcessor`) was convenient but architecturally flawed — audio processing that misses its deadline because the main thread is busy causes audible glitches. `AudioWorklet` was designed from scratch to run on a real-time audio thread with guaranteed scheduling priority. For any production audio capture application this matters — a frozen UI during React re-renders should never cause a recording dropout.

---

#### C. No retry or queue for the pipeline trigger

**Verified in:** `gateway/src/routes/session.ts:93-100`

```typescript
const response = await fetch(`${pipelineUrl}/pipeline/run`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ session_id: sessionId })
})
```

This is a single `fetch` with no retry, no queue, no dead-letter mechanism. If the Python pipeline is restarting, saturated, or unreachable when `POST /session/:id/end` fires, the session is permanently lost — the `pipeline_complete` SSE event never arrives, the browser waits on the "Processing..." screen indefinitely, and the clinical notes from that visit are never generated.

The proper solution is a durable job queue (BullMQ with Redis, or Celery). At minimum, exponential backoff retry (3 attempts, 1s / 2s / 4s delays) reduces the failure rate significantly at zero infrastructure cost:

```typescript
async function triggerPipeline(sessionId: string, retries = 3): Promise<void> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${pipelineUrl}/pipeline/run`, { method: 'POST', ... })
      if (res.ok) return
    } catch (err) {
      if (i === retries - 1) throw err
      await new Promise(r => setTimeout(r, 1000 * 2 ** i))
    }
  }
}
```

**What this teaches:** In distributed systems, any network call can fail. A synchronous fire-and-forget HTTP call between two services in a clinical pipeline is the wrong pattern. The general principle is: if losing this message means losing a patient's medical record, it must go through a durable queue with at-least-once delivery guarantees. HTTP is not a queue.

---

#### D. Unlimited session duration — memory and compliance risk

**Verified in:** `gateway/src/adapters/audioStorage.ts:8`, `client/src/LiveCapture.tsx:23`

```typescript
const chunkBuffers = new Map<string, Buffer[]>()  // grows forever until finalizeAudio()
```

A 1-hour recording at 16 kHz, 16-bit, mono = ~115 MB held in Node.js heap memory. There is no maximum session duration enforced on the server or client. A forgotten browser tab can accumulate hours of audio and eventually crash the gateway with an OOM error. Separately, many compliance frameworks require specifying and enforcing maximum recording durations for clinical audio.

The fix has two parts:
1. Client: enforce a configurable `MAX_DURATION_SECONDS` timer that calls `stopRecording()` automatically
2. Server: stream audio chunks directly to disk as they arrive (appending to the WAV file incrementally) rather than buffering everything in memory

**What this teaches:** In-memory accumulation of user-generated binary data is a class of vulnerability called an unbounded buffer. It is both a reliability risk (OOM crash) and a compliance risk (uncontrolled data retention). The correct pattern for large binary streams is to write through to durable storage immediately and keep only a small working buffer in memory.

---

### MedJournee — Independent Recommendations

#### E. `subprocess.run` blocks the async event loop

**Verified in:** `services/realtime_transcription_service.py:96-106`

```python
result = subprocess.run([
    'ffmpeg', '-loglevel', 'error', '-f', input_ext, '-i', temp_input.name,
    '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-y', temp_output.name
], capture_output=True, text=True, timeout=10)
```

`subprocess.run` is **synchronous blocking** — it halts the Python thread until FFmpeg completes. Because this is called inside an `async` function in FastAPI, it blocks the entire event loop for up to 10 seconds per chunk. During that time, no other requests can be handled: no other WebSocket messages forwarded, no auth checks, no health checks — nothing.

The correct async equivalent:

```python
proc = await asyncio.create_subprocess_exec(
    'ffmpeg', '-loglevel', 'error', '-f', input_ext, '-i', temp_input.name,
    '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-y', temp_output.name,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE
)
stdout, stderr = await proc.communicate()
```

This yields control back to the event loop while FFmpeg runs, so other requests are processed concurrently.

**What this teaches:** Calling any blocking I/O inside an `async` function defeats the purpose of async. The event loop is single-threaded — one blocking call stops everything. This is one of the most common mistakes in FastAPI/asyncio codebases and is invisible in testing (single user, no concurrency) but catastrophic in production. The rule: in async code, any call that does I/O — subprocess, file read, network — must be the async variant. If no async variant exists, use `asyncio.run_in_executor` to run it in a thread pool.

---

#### F. In-memory `_sessions` dict will not survive a process restart

**Verified in:** `services/gladia_service.py:24`

```python
_sessions: dict[str, str] = {}
```

This maps `session_id → Gladia WebSocket URL`. If FastAPI restarts mid-session (deploy, OOM, crash), this dict is gone. The WebSocket proxy calls `get_session_url(session_id)` which returns `None` and immediately closes the browser's connection with code `4004`. The patient's ongoing recording is silently dropped with no recovery path.

The fix is backing this with Redis (or a short-TTL database row). Redis is the standard choice for ephemeral session state that must survive process restarts:

```python
import redis.asyncio as redis
r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

async def store_session(session_id: str, url: str, ttl: int = 7200):
    await r.setex(f"gladia_session:{session_id}", ttl, url)

async def get_session_url(session_id: str) -> str | None:
    return await r.get(f"gladia_session:{session_id}")
```

**What this teaches:** Any state that must outlive a single process belongs in an external store. In-process dicts (`_sessions`, `chunkBuffers`, `pending_sessions`) are appropriate for caches where loss is acceptable. They are never appropriate for state that represents an in-progress user action — especially a clinical recording.

---

#### G. Translation timeout in the WebSocket hot path

**Verified in:** `routes/gladia_routes.py:161-170`

```python
t_result = await translate_text(text, target, detected_lang)
translation = t_result.get("translated_text", "")
```

This `await` is inside `gladia_to_browser()` — the loop that forwards every utterance to the browser. If `translate_text` takes 2+ seconds (rate limit, DNS hiccup, cold start), the entire transcript delivery pipeline backs up for that duration. Gladia keeps sending final transcripts to the backend, but the backend can't forward them because it's stuck awaiting translation. The browser sees a gap in the live transcript.

The fix is a hard timeout with graceful fallback:

```python
try:
    t_result = await asyncio.wait_for(translate_text(text, target, detected_lang), timeout=1.5)
    translation = t_result.get("translated_text", "")
except asyncio.TimeoutError:
    translation = ""  # send original text without translation rather than stalling
    logger.warning("[Gladia] Translation timeout — sending untranslated")
```

**What this teaches:** In a hot path (code that runs on every event), every `await` is a potential stall. External API calls in hot paths must have timeouts. The pattern is: set the tightest timeout that is still reasonable for the happy path, and design the fallback to degrade gracefully (show original text) rather than fail visibly (show nothing, drop the event). This is the difference between a briefly degraded feature and a broken feature.

---

#### H. No audio quality pre-check before ASR calls

**Verified in:** `services/realtime_transcription_service.py:62-68` and `routes/gladia_routes.py` (Gladia receives all audio unconditionally)

MedJournee checks file size (`< 5000 bytes → skip`) as a proxy for silence. HiScribe has no check at all. Neither project measures actual signal energy before committing to an ASR API call.

A 10 KB file of HVAC hum, keyboard clicks, or street noise will be sent to Whisper or Gladia and return a hallucinated transcript. The RMS (Root Mean Square) energy check is fast and accurate:

```python
import numpy as np

def has_speech_energy(audio_bytes: bytes, threshold: float = 200.0) -> bool:
    """
    Returns True if audio contains meaningful signal energy.
    threshold=200 is empirically reasonable for 16-bit PCM at 16 kHz.
    Too-quiet audio produces hallucinations; this filters it before the API call.
    """
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    rms = np.sqrt(np.mean(samples ** 2))
    return rms >= threshold
```

This runs in microseconds and prevents both wasted API spend and hallucinated clinical content.

**What this teaches:** Signal pre-processing is a first-class concern in any audio ML pipeline. "Feed everything to the model" is a prototyping approach, not a production approach. Silence detection, noise floor estimation, and clipping detection belong between audio capture and ASR inference. They reduce cost, reduce hallucination rate, and improve the quality of everything downstream that depends on the transcript.

---

### Shared Gaps — Both Projects

| Gap | HiScribe location | MedJournee location | Recommendation |
|---|---|---|---|
| **Auth on audio endpoints** | None — `server.ts` registers no auth middleware | Has it — `require_auth`, `verify_ws_token` | HiScribe: add immediately before any deployment |
| **Audio quality pre-check** | `gladia.ts:60` before `gladiaWs.send(chunk)` | `realtime_transcription_service.py:62` before Whisper call | Add RMS threshold check to both |
| **Max session duration** | `LiveCapture.tsx` timer is display-only, no server enforcement | No visible cap | Enforce server-side with a configurable timeout |
| **Structured logging with request IDs** | `console.log` with no session correlation on all paths | Inconsistent — some routes use `logger`, some use `print()` | Adopt a consistent logger with session_id on every line |
| **External session state** | `chunkBuffers` Map in memory | `_sessions` dict in memory | Redis or DB-backed session store for anything that must survive restarts |

---

*Updated 2026-04-03. Added cross-apply recommendations and independent engineering analysis.*
