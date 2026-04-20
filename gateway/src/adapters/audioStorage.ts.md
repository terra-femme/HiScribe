# audioStorage.ts — PCM Audio Buffer → WAV File

## What This File Is For
During a recording session, the browser sends raw PCM audio chunks over WebSocket. This file buffers those chunks in memory per session and, when the session ends, writes them to a proper WAV file on disk. That WAV file is what pyannote.audio reads for post-session diarization.

## How It Fits In The Project
`session.ts` calls `saveAudioChunk()` for every incoming audio message, and `finalizeAudio()` when the WebSocket closes. The Python pipeline then reads the WAV file from `data/audio/{session_id}.wav`.

---

## Line-by-Line Breakdown

### Lines 1–2 — Imports
```typescript
import fs from 'fs'
import path from 'path'
```
**What it does:** Imports Node's built-in file system and path modules.
**Why:** `fs` writes files to disk. `path` constructs file paths safely across operating systems (Windows uses `\`, Unix uses `/` — `path.join` handles both).
**ELI5:** `fs` is your filing cabinet. `path` is the address label that always writes the address correctly no matter what country you're in.
**Best practice:** Always use `path.join()` or `path.resolve()` instead of string concatenation for file paths. `'data/' + sessionId + '.wav'` breaks on Windows.

### Lines 6–7 — In-memory buffer store
```typescript
const AUDIO_DIR = path.resolve(__dirname, '../../../data/audio')
const chunkBuffers = new Map<string, Buffer[]>()
```
**What it does:** Defines where audio files will be saved, and creates a Map to hold chunks in memory per session.
**Why:** A `Map<string, Buffer[]>` maps each `session_id` to an array of raw audio buffers. As chunks arrive, they're pushed into this array. At session end, the whole array is merged and written to disk. This avoids opening and closing a file handle thousands of times during a session.
**ELI5:** Imagine writing a letter one word at a time. Instead of mailing each word separately, you collect all the words in a notebook (the Map) and mail the whole letter at once when you're done.
**Best practice:** Maps are much better than plain objects (`{}`) as dynamic key-value stores in JavaScript. They're faster for frequent adds/deletes and don't have prototype pollution issues.

### Lines 9–13 — Save chunk
```typescript
export function saveAudioChunk(sessionId: string, chunk: Buffer): void {
  if (!chunkBuffers.has(sessionId)) {
    chunkBuffers.set(sessionId, [])
  }
  chunkBuffers.get(sessionId)!.push(chunk)
}
```
**What it does:** Adds an audio chunk to the in-memory buffer for a session. Creates the buffer array on first call.
**Why:** The `!` after `.get()` is TypeScript's non-null assertion — we just checked `.has()` so we know it exists. Without `!`, TypeScript would complain that `.get()` might return `undefined`.
**ELI5:** Every time a piece of audio arrives, stuff it in the session's envelope. If there's no envelope yet, make one first.
**Best practice:** The lazy initialization pattern (`if (!has) set([])`) is common and correct here. An alternative is `chunkBuffers.get(sessionId) ?? []` but that doesn't persist the empty array back into the Map.

### Lines 15–30 — Finalize audio
```typescript
export function finalizeAudio(sessionId: string): void {
  const chunks = chunkBuffers.get(sessionId)
  if (!chunks || chunks.length === 0) return
  fs.mkdirSync(AUDIO_DIR, { recursive: true })
  const outPath = path.join(AUDIO_DIR, `${sessionId}.wav`)
  const combined = Buffer.concat(chunks)
  const wavBuffer = pcmToWav(combined, 16000, 1, 16)
  fs.writeFileSync(outPath, wavBuffer)
  chunkBuffers.delete(sessionId)
}
```
**What it does:** Merges all chunks, wraps them in a WAV header, writes to disk, and cleans up memory.
**Why:** `Buffer.concat(chunks)` merges all the small buffers into one. `{ recursive: true }` in `mkdirSync` means "create the directory and any parent directories if they don't exist" — won't throw if the directory already exists. `chunkBuffers.delete(sessionId)` cleans up memory after writing — important for long-running servers.
**ELI5:** Take all the puzzle pieces out of the envelope, arrange them into a complete picture, frame it (add the WAV header), hang it on the wall (write to disk), and throw away the envelope.
**Best practice:** Always clean up in-memory state after persisting to disk. A long-running server that never deletes from its Maps is a memory leak.

### Lines 32–51 — PCM to WAV conversion
```typescript
function pcmToWav(pcm: Buffer, sampleRate: number, channels: number, bitDepth: number): Buffer {
  const byteRate = sampleRate * channels * (bitDepth / 8)
  ...
  header.write('RIFF', 0)
  ...
  return Buffer.concat([header, pcm])
}
```
**What it does:** Wraps raw PCM bytes in a 44-byte WAV file header so audio software can read it.
**Why:** Raw PCM is just numbers — no metadata about sample rate, channels, or bit depth. A WAV file is PCM with a standardized header prepended that describes the format. Without this header, pyannote (and any other audio library) can't interpret the data.
**ELI5:** Raw PCM is like a bag of letters with no words. The WAV header is the instruction manual that says "read these letters left to right, group them into words of this many characters, at this reading speed."
**Best practice:** The WAV header format is a fixed standard (RIFF/WAVE). The magic numbers (44-byte header, `RIFF` at byte 0, `WAVE` at byte 8, etc.) come from the spec — they're not arbitrary. Always document magic numbers with comments or named constants.

---

## Common Mistakes
1. Forgetting `chunkBuffers.delete(sessionId)` — the server accumulates audio data in memory for every session and eventually runs out of RAM.
2. Using `writeFileSync` in a hot path — it blocks the entire Node event loop while writing. Here it's called once at session end so it's acceptable. For very long sessions (>100MB), switch to `writeFile` (async).
3. Not adding the WAV header — pyannote and librosa expect a proper audio file, not raw PCM bytes. The file will open but produce garbage output.

## Key Concepts To Look Up
- PCM (Pulse Code Modulation) — what raw audio data actually is
- WAV file format — the RIFF/WAVE header structure
- Node.js Buffer — how binary data is handled in Node
- Memory management in long-running Node servers
- `Buffer.concat()` vs manual array merging
