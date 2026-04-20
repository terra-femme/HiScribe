/**
 * gateway/src/adapters/gladia.ts
 *
 * Gladia v1 WebSocket ASR adapter.
 *
 * Changes applied:
 *  - Hallucination phrase filter (MedJournee cross-apply)
 *  - RMS energy pre-check on incoming PCM chunks — drops silent/noise-only
 *    chunks before they ever reach Gladia, reducing API cost and hallucination rate
 *  - Aggressive debug logging so failures are immediately locatable
 */

import WebSocket from 'ws'

export type Segment = {
  text: string
  speaker: string
  start_ms: number
  end_ms: number
  confidence: number
  is_final: boolean
}

export type OnSegment = (segment: Segment) => void

// ─── Hallucination filter ────────────────────────────────────────────────────
// Phrases Gladia/Whisper-family models emit on silence, ambient noise,
// or very short audio windows. In a clinical note these are false positives
// that contaminate SOAP sections. Filter before any storage or display.
const HALLUCINATIONS = new Set([
  'thank you', 'thanks', 'thanks.', 'thank you.', 'you', 'you.',
  'uh', 'um', 'hmm', 'hm', 'slurp',
  'bye', 'bye bye', 'goodbye', 'see you', 'see you later', 'see you next time',
  'subscribe', 'like and subscribe', 'thanks for watching',
  'okay', 'ok', 'hey', 'hi', 'hello',
  'music', 'applause', 'silence', '[music]', '[applause]', '[silence]',
])

function isHallucination(text: string): boolean {
  const normalised = text.trim().toLowerCase().replace(/[.!?,]+$/, '')
  return HALLUCINATIONS.has(normalised)
}

// ─── RMS energy check ────────────────────────────────────────────────────────
// Converts Int16 binary buffer → float RMS.
// Threshold 150 is empirically reasonable for 16-bit, 16 kHz speech;
// adjust if environment is noisy. Drops pure-silence chunks before they
// reach the Gladia WebSocket.
const RMS_THRESHOLD = 150

function computeRms(int16Buffer: Buffer): number {
  if (int16Buffer.length < 2) return 0
  const sampleCount = Math.floor(int16Buffer.length / 2)
  let sumSq = 0
  for (let i = 0; i < sampleCount; i++) {
    const sample = int16Buffer.readInt16LE(i * 2)
    sumSq += sample * sample
  }
  return Math.sqrt(sumSq / sampleCount)
}

// ─── Adapter ─────────────────────────────────────────────────────────────────

export function transcribe(
  sessionId: string,
  clientSocket: WebSocket,
  onSegment: OnSegment
): void {
  const apiKey = process.env.GLADIA_API_KEY
  if (!apiKey) {
    console.error(`[gladia][${sessionId}] GLADIA_API_KEY not set — aborting transcribe()`)
    throw new Error('GLADIA_API_KEY not set in .env')
  }

  console.log(`[gladia][${sessionId}] Opening Gladia WebSocket`)

  const gladiaWs = new WebSocket(
    'wss://api.gladia.io/audio/text/audio-transcription',
    { headers: { 'x-gladia-key': apiKey } }
  )

  // ── counters for debug summary ───────────────────────────────────────────
  let chunksReceived = 0
  let chunksSilent = 0
  let chunksForwarded = 0
  let segmentsPartial = 0
  let segmentsFinal = 0
  let hallucinationsFiltered = 0

  gladiaWs.on('open', () => {
    console.log(`[gladia][${sessionId}] Gladia WebSocket open — sending config`)
    gladiaWs.send(JSON.stringify({
      x_gladia_key: apiKey,
      encoding: 'WAV/PCM',
      sample_rate: 16000,
      language_behaviour: 'automatic single language',
      frames_format: 'bytes'
    }))
  })

  gladiaWs.on('message', (data: Buffer) => {
    let msg: any
    try {
      msg = JSON.parse(data.toString())
    } catch (e) {
      console.error(`[gladia][${sessionId}] JSON parse error on Gladia message:`, e)
      return
    }

    // Ignore non-transcript events (config ack, keepalive, etc.)
    if (msg.event !== 'transcript') {
      console.debug(`[gladia][${sessionId}] Non-transcript event: ${msg.event ?? 'unknown'}`)
      return
    }

    if (!msg.transcription) {
      console.debug(`[gladia][${sessionId}] Transcript event with empty transcription — skipping`)
      return
    }

    const text: string = msg.transcription.trim()
    const isFinal: boolean = msg.type === 'final'

    // ── Hallucination filter ───────────────────────────────────────────────
    if (isHallucination(text)) {
      hallucinationsFiltered++
      console.debug(
        `[gladia][${sessionId}] Hallucination filtered (total=${hallucinationsFiltered}): "${text}"`
      )
      return
    }

    if (text.length < 2) {
      console.debug(`[gladia][${sessionId}] Skipping single-char output: "${text}"`)
      return
    }

    if (isFinal) segmentsFinal++
    else segmentsPartial++

    console.debug(
      `[gladia][${sessionId}] Segment type=${msg.type} conf=${msg.confidence ?? 'n/a'} ` +
      `[${msg.time_begin?.toFixed(2) ?? '?'}s – ${msg.time_end?.toFixed(2) ?? '?'}s]: "${text}"`
    )

    onSegment({
      text,
      speaker: 'UNKNOWN',   // speaker labels assigned in post-recording pipeline
      start_ms: msg.time_begin != null ? Math.round(msg.time_begin * 1000) : 0,
      end_ms:   msg.time_end   != null ? Math.round(msg.time_end   * 1000) : 0,
      confidence: msg.confidence ?? 1.0,
      is_final: isFinal
    })
  })

  // ── Forward PCM chunks from browser → Gladia with RMS pre-check ──────────
  clientSocket.on('message', (chunk: Buffer) => {
    chunksReceived++

    const rms = computeRms(chunk)
    if (rms < RMS_THRESHOLD) {
      chunksSilent++
      if (chunksSilent % 20 === 0) {
        console.debug(
          `[gladia][${sessionId}] Silent chunks suppressed so far: ${chunksSilent} ` +
          `(last rms=${rms.toFixed(1)}, threshold=${RMS_THRESHOLD})`
        )
      }
      return  // do not forward silence to Gladia
    }

    if (gladiaWs.readyState === WebSocket.OPEN) {
      gladiaWs.send(chunk)
      chunksForwarded++
    } else {
      console.warn(
        `[gladia][${sessionId}] Gladia WS not open (state=${gladiaWs.readyState}) — ` +
        `dropping chunk (received=${chunksReceived})`
      )
    }
  })

  clientSocket.on('close', () => {
    console.log(
      `[gladia][${sessionId}] Client disconnected — closing Gladia WS. ` +
      `Summary: chunks received=${chunksReceived} silent=${chunksSilent} ` +
      `forwarded=${chunksForwarded} | segments partial=${segmentsPartial} ` +
      `final=${segmentsFinal} hallucinations filtered=${hallucinationsFiltered}`
    )
    gladiaWs.close()
  })

  gladiaWs.on('error', (err) => {
    console.error(`[gladia][${sessionId}] WebSocket error:`, err.message)
  })

  gladiaWs.on('close', (code, reason) => {
    console.log(
      `[gladia][${sessionId}] Gladia WS closed — code=${code} ` +
      `reason=${reason?.toString() || 'none'}`
    )
  })
}
