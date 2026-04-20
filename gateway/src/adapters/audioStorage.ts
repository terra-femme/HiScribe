/**
 * gateway/src/adapters/audioStorage.ts
 *
 * Saves raw PCM audio to disk as chunks arrive (streaming write),
 * then wraps in a WAV header on finalize.
 *
 * Changes applied:
 *  - Streaming writes replace in-memory Buffer[] accumulation — eliminates
 *    OOM risk for long sessions and reduces peak heap usage to near zero
 *  - deleteAudio() export for post-pipeline HIPAA cleanup
 *  - Session start-time tracking for duration enforcement
 *  - Aggressive debug logging at every step
 *
 * Audio directory: <repo_root>/data/audio/
 * Per session files:
 *   {sessionId}.pcm  — raw Int16 PCM written incrementally (deleted on finalize)
 *   {sessionId}.wav  — WAV-wrapped output consumed by pyannote pipeline
 */

import fs from 'fs'
import path from 'path'

export const MAX_SESSION_SECONDS = 5400  // 90 minutes hard cap

const AUDIO_DIR = path.resolve(__dirname, '../../../data/audio')

// Track active write streams and session start times
const writeStreams  = new Map<string, fs.WriteStream>()
const sessionStart  = new Map<string, number>()         // sessionId → epoch ms
const bytesWritten  = new Map<string, number>()         // sessionId → total PCM bytes

// ─── helpers ─────────────────────────────────────────────────────────────────

function pcmPath(sessionId: string)  { return path.join(AUDIO_DIR, `${sessionId}.pcm`) }
function wavPath(sessionId: string)  { return path.join(AUDIO_DIR, `${sessionId}.wav`) }

function ensureDir(): void {
  if (!fs.existsSync(AUDIO_DIR)) {
    fs.mkdirSync(AUDIO_DIR, { recursive: true })
    console.log(`[audioStorage] Created audio directory: ${AUDIO_DIR}`)
  }
}

// ─── public API ──────────────────────────────────────────────────────────────

/**
 * Open a streaming write handle for this session.
 * Call once when the WebSocket connection is established.
 */
export function initAudioSession(sessionId: string): void {
  ensureDir()

  if (writeStreams.has(sessionId)) {
    console.warn(`[audioStorage][${sessionId}] initAudioSession called but stream already open — ignoring`)
    return
  }

  const pcm = pcmPath(sessionId)
  const stream = fs.createWriteStream(pcm, { flags: 'w' })

  stream.on('error', (err) => {
    console.error(`[audioStorage][${sessionId}] Write stream error:`, err.message)
  })

  writeStreams.set(sessionId, stream)
  sessionStart.set(sessionId, Date.now())
  bytesWritten.set(sessionId, 0)

  console.log(`[audioStorage][${sessionId}] Audio session started — writing to ${pcm}`)
}

/**
 * Append a PCM chunk to the session's raw audio file.
 * Returns false if the session has exceeded MAX_SESSION_SECONDS.
 */
export function saveAudioChunk(sessionId: string, chunk: Buffer): boolean {
  const startMs = sessionStart.get(sessionId)
  if (startMs !== undefined) {
    const elapsedSec = (Date.now() - startMs) / 1000
    if (elapsedSec > MAX_SESSION_SECONDS) {
      console.warn(
        `[audioStorage][${sessionId}] Session exceeded max duration ` +
        `(${elapsedSec.toFixed(0)}s > ${MAX_SESSION_SECONDS}s) — rejecting chunk`
      )
      return false
    }
  }

  const stream = writeStreams.get(sessionId)
  if (!stream) {
    console.warn(
      `[audioStorage][${sessionId}] saveAudioChunk called with no open stream — ` +
      `was initAudioSession() called? Chunk dropped (${chunk.length} bytes)`
    )
    return true  // not a duration-exceeded error; caller need not stop
  }

  stream.write(chunk)
  const prev = bytesWritten.get(sessionId) ?? 0
  bytesWritten.set(sessionId, prev + chunk.length)

  // Log every ~1MB written so we can track progress without spam
  const total = prev + chunk.length
  if (Math.floor(total / 1_000_000) > Math.floor(prev / 1_000_000)) {
    const durationSec = (Date.now() - (startMs ?? Date.now())) / 1000
    console.log(
      `[audioStorage][${sessionId}] Written ${(total / 1_000_000).toFixed(1)} MB ` +
      `(~${durationSec.toFixed(0)}s recorded)`
    )
  }

  return true
}

/**
 * Close the write stream and assemble the final WAV file.
 * The raw .pcm file is deleted after WAV is written.
 */
export function finalizeAudio(sessionId: string): void {
  const stream = writeStreams.get(sessionId)
  if (!stream) {
    console.warn(`[audioStorage][${sessionId}] finalizeAudio: no open stream found — nothing to finalize`)
    return
  }

  stream.end(() => {
    writeStreams.delete(sessionId)
    sessionStart.delete(sessionId)
    const totalBytes = bytesWritten.get(sessionId) ?? 0
    bytesWritten.delete(sessionId)

    const pcm = pcmPath(sessionId)
    const wav = wavPath(sessionId)

    if (!fs.existsSync(pcm)) {
      console.error(`[audioStorage][${sessionId}] PCM file missing after stream close: ${pcm}`)
      return
    }

    const pcmData = fs.readFileSync(pcm)
    console.log(
      `[audioStorage][${sessionId}] PCM read: ${pcmData.length} bytes ` +
      `(tracked: ${totalBytes} bytes)`
    )

    if (pcmData.length === 0) {
      console.warn(`[audioStorage][${sessionId}] PCM file is empty — no audio recorded`)
      fs.unlinkSync(pcm)
      return
    }

    const wavBuffer = pcmToWav(pcmData, 16000, 1, 16)
    fs.writeFileSync(wav, wavBuffer)
    console.log(`[audioStorage][${sessionId}] WAV written: ${wav} (${wavBuffer.length} bytes)`)

    try {
      fs.unlinkSync(pcm)
      console.log(`[audioStorage][${sessionId}] PCM temp file deleted: ${pcm}`)
    } catch (err: any) {
      console.error(`[audioStorage][${sessionId}] Failed to delete PCM temp file: ${err.message}`)
    }
  })
}

/**
 * Delete the WAV file after the pipeline has consumed it.
 * Call from the pipeline-complete handler to enforce audio retention policy.
 * Safe to call even if the file does not exist.
 */
export function deleteAudio(sessionId: string): void {
  const wav = wavPath(sessionId)
  if (!fs.existsSync(wav)) {
    console.debug(`[audioStorage][${sessionId}] deleteAudio: WAV not found (already deleted or never created) — ${wav}`)
    return
  }

  try {
    fs.unlinkSync(wav)
    console.log(`[audioStorage][${sessionId}] Audio deleted post-pipeline (HIPAA): ${wav}`)
  } catch (err: any) {
    console.error(`[audioStorage][${sessionId}] FAILED to delete audio: ${err.message} — manual cleanup required`)
  }
}

/**
 * Return elapsed recording seconds for a session.
 * Returns null if session is not active.
 */
export function getSessionElapsed(sessionId: string): number | null {
  const start = sessionStart.get(sessionId)
  return start != null ? (Date.now() - start) / 1000 : null
}

// ─── WAV header ───────────────────────────────────────────────────────────────

function pcmToWav(pcm: Buffer, sampleRate: number, channels: number, bitDepth: number): Buffer {
  const byteRate   = sampleRate * channels * (bitDepth / 8)
  const blockAlign = channels * (bitDepth / 8)
  const header     = Buffer.alloc(44)

  header.write('RIFF', 0)
  header.writeUInt32LE(36 + pcm.length, 4)
  header.write('WAVE', 8)
  header.write('fmt ', 12)
  header.writeUInt32LE(16, 16)
  header.writeUInt16LE(1, 20)              // PCM = 1
  header.writeUInt16LE(channels, 22)
  header.writeUInt32LE(sampleRate, 24)
  header.writeUInt32LE(byteRate, 28)
  header.writeUInt16LE(blockAlign, 32)
  header.writeUInt16LE(bitDepth, 34)
  header.write('data', 36)
  header.writeUInt32LE(pcm.length, 40)

  return Buffer.concat([header, pcm])
}
