/**
 * gateway/src/routes/session.ts
 *
 * Changes applied:
 *  - Auth guards on all routes (requireAuth for HTTP, verifyWsToken for WS/SSE)
 *  - Exponential backoff retry (3 attempts) for pipeline trigger
 *  - Audio deletion handled exclusively by Python package_node (os.unlink) — HIPAA
 *  - initAudioSession() called on WS open — streaming writes instead of memory buffer
 *  - Max duration enforcement: WS closed automatically if session exceeds limit
 *  - Aggressive debug logging throughout
 */

import { FastifyInstance } from 'fastify'
import { randomUUID } from 'crypto'
import { transcribe } from '../adapters/speech'
import { saveSession, saveSegment } from '../adapters/storage'
import {
  initAudioSession,
  saveAudioChunk,
  finalizeAudio,
  getSessionElapsed,
  MAX_SESSION_SECONDS
} from '../adapters/audioStorage'
import { requireAuth, verifyWsToken } from '../middleware/auth'

// ─── SSE broadcast ────────────────────────────────────────────────────────────

const sseClients = new Map<string, import('stream').Writable>()

export function broadcastSegment(sessionId: string, segment: object): void {
  const client = sseClients.get(sessionId)
  if (!client) {
    console.debug(`[session] broadcastSegment: no SSE client for session ${sessionId}`)
    return
  }
  if (client.destroyed) {
    console.warn(`[session][${sessionId}] SSE client stream is destroyed — removing from map`)
    sseClients.delete(sessionId)
    return
  }
  client.write(`data: ${JSON.stringify(segment)}\n\n`)
}

// ─── Pipeline trigger with retry ─────────────────────────────────────────────

async function triggerPipeline(sessionId: string, maxAttempts = 3): Promise<any> {
  const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
  const url = `${pipelineUrl}/pipeline/run`

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const delayMs = attempt === 1 ? 0 : 1000 * 2 ** (attempt - 2)  // 0, 1000, 2000ms
    if (delayMs > 0) {
      console.log(`[session][${sessionId}] Pipeline retry attempt ${attempt}/${maxAttempts} in ${delayMs}ms`)
      await new Promise(r => setTimeout(r, delayMs))
    }

    try {
      console.log(`[session][${sessionId}] Triggering pipeline — attempt ${attempt}/${maxAttempts} → ${url}`)
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
        signal: AbortSignal.timeout(30_000)  // 30s per attempt
      })

      if (!res.ok) {
        const body = await res.text().catch(() => '<unreadable>')
        console.error(
          `[session][${sessionId}] Pipeline returned HTTP ${res.status} on attempt ${attempt}: ${body}`
        )
        if (attempt === maxAttempts) throw new Error(`Pipeline HTTP ${res.status}: ${body}`)
        continue  // retry
      }

      const result = await res.json()
      console.log(`[session][${sessionId}] Pipeline succeeded on attempt ${attempt}`)
      return result

    } catch (err: any) {
      console.error(
        `[session][${sessionId}] Pipeline trigger error on attempt ${attempt}/${maxAttempts}: ${err.message}`
      )
      if (attempt === maxAttempts) throw err
    }
  }
}

// ─── Rate limiter for POST /session/start ────────────────────────────────────
// Max 5 session starts per IP per 60 seconds (in-memory, resets on restart)

const sessionStartAttempts = new Map<string, number[]>()
const RATE_WINDOW_MS  = 60_000
const RATE_LIMIT_MAX  = 5

function checkRateLimit(ip: string): boolean {
  const now = Date.now()
  const prev = (sessionStartAttempts.get(ip) ?? []).filter(t => now - t < RATE_WINDOW_MS)
  if (prev.length >= RATE_LIMIT_MAX) return false
  prev.push(now)
  sessionStartAttempts.set(ip, prev)
  return true
}

// ─── Routes ──────────────────────────────────────────────────────────────────

export async function sessionRoutes(app: FastifyInstance): Promise<void> {

  // POST /session/start — create session
  app.post('/session/start', { preHandler: requireAuth }, async (req, reply) => {
    if (!checkRateLimit(req.ip)) {
      app.log.warn(`[session] Rate limit hit for IP ${req.ip}`)
      return reply.status(429).send({ error: 'Too many session starts. Try again in a minute.' })
    }
    const sessionId = randomUUID()
    console.log(`[session] Creating session ${sessionId}`)
    await saveSession({
      id: sessionId,
      status: 'recording',
      created_at: new Date().toISOString()
    })
    app.log.info(`Session created: ${sessionId}`)
    return reply.send({ session_id: sessionId })
  })

  // GET /session/:id/stream — SSE transcript stream
  app.get('/session/:id/stream', async (req, reply) => {
    const { id: sessionId } = req.params as { id: string }

    // Verify token passed as ?token= query param (SSE cannot send custom headers)
    const token = (req.query as any).token
    try {
      verifyWsToken(token)
    } catch (err: any) {
      console.warn(`[session][${sessionId}] SSE rejected — bad token: ${err.message}`)
      return reply.status(401).send({ error: 'Unauthorized' })
    }

    reply.raw.setHeader('Content-Type', 'text/event-stream')
    reply.raw.setHeader('Cache-Control', 'no-cache')
    reply.raw.setHeader('Connection', 'keep-alive')
    reply.raw.setHeader('Access-Control-Allow-Origin', '*')
    reply.raw.flushHeaders()

    sseClients.set(sessionId, reply.raw)
    app.log.info(`[session][${sessionId}] SSE client connected`)

    // Heartbeat to keep proxy/load-balancer from timing out idle connections
    const heartbeat = setInterval(() => {
      if (reply.raw.destroyed) {
        console.warn(`[session][${sessionId}] Heartbeat: stream destroyed — clearing interval`)
        clearInterval(heartbeat)
        sseClients.delete(sessionId)
        return
      }
      reply.raw.write(': heartbeat\n\n')
    }, 15_000)

    req.raw.on('close', () => {
      clearInterval(heartbeat)
      sseClients.delete(sessionId)
      app.log.info(`[session][${sessionId}] SSE client disconnected`)
    })
  })

  // WS /session/:id/audio — receives PCM audio from browser
  app.register(async function wsPlugin(app) {
    app.get('/session/:id/audio', { websocket: true }, (socket, req) => {
      const { id: sessionId } = req.params as { id: string }
      const token = (req.query as any).token

      // Auth: verify token before accepting audio
      try {
        verifyWsToken(token)
      } catch (err: any) {
        console.warn(`[session][${sessionId}] WS rejected — bad token: ${err.message}`)
        socket.close(1008, 'Unauthorized')
        return
      }

      app.log.info(`[session][${sessionId}] Audio WebSocket opened`)

      // Open streaming write handle — no memory accumulation
      initAudioSession(sessionId)

      // Duration enforcement: close socket if session exceeds max duration
      const durationGuard = setInterval(() => {
        const elapsed = getSessionElapsed(sessionId)
        if (elapsed !== null && elapsed > MAX_SESSION_SECONDS) {
          console.warn(
            `[session][${sessionId}] Max session duration exceeded ` +
            `(${elapsed.toFixed(0)}s > ${MAX_SESSION_SECONDS}s) — force-closing WebSocket`
          )
          broadcastSegment(sessionId, {
            type: 'session_timeout',
            message: `Recording stopped: maximum duration of ${MAX_SESSION_SECONDS / 60} minutes reached`
          })
          socket.close(1001, 'Max session duration exceeded')
          clearInterval(durationGuard)
        }
      }, 10_000)  // check every 10s

      // Stream audio to ASR; broadcast each segment over SSE
      transcribe(sessionId, socket, async (segment) => {
        if (!segment.is_final) {
          broadcastSegment(sessionId, { type: 'partial', ...segment })
          return
        }
        try {
          await saveSegment({ session_id: sessionId, ...segment })
          console.debug(
            `[session][${sessionId}] Segment saved: "${segment.text.slice(0, 60)}..." ` +
            `conf=${segment.confidence.toFixed(2)} [${segment.start_ms}–${segment.end_ms}ms]`
          )
        } catch (err: any) {
          console.error(`[session][${sessionId}] Failed to save segment: ${err.message}`)
        }
        broadcastSegment(sessionId, { type: 'final', ...segment })
      })

      // Stream PCM chunks to disk
      socket.on('message', (chunk: Buffer) => {
        const withinLimit = saveAudioChunk(sessionId, chunk)
        if (!withinLimit) {
          console.warn(
            `[session][${sessionId}] Duration limit hit during message handler — closing socket`
          )
          socket.close(1001, 'Max session duration exceeded')
          clearInterval(durationGuard)
        }
      })

      socket.on('close', (code, reason) => {
        clearInterval(durationGuard)
        console.log(
          `[session][${sessionId}] Audio WS closed — code=${code} ` +
          `reason=${reason?.toString() || 'none'}`
        )
        finalizeAudio(sessionId)
      })

      socket.on('error', (err) => {
        console.error(`[session][${sessionId}] Audio WS error:`, err.message)
      })
    })
  })

  // POST /session/:id/end — stop recording, trigger Python pipeline
  app.post('/session/:id/end', { preHandler: requireAuth }, async (req, reply) => {
    const { id: sessionId } = req.params as { id: string }
    console.log(`[session][${sessionId}] /end called — triggering pipeline`)

    let result: any
    try {
      result = await triggerPipeline(sessionId)
    } catch (err: any) {
      console.error(
        `[session][${sessionId}] Pipeline trigger failed after all retries: ${err.message}`
      )
      broadcastSegment(sessionId, {
        type: 'pipeline_error',
        message: 'Pipeline trigger failed — check server logs'
      })
      return reply.status(500).send({ error: 'Pipeline trigger failed', detail: err.message })
    }

    // Audio deletion is handled by Python package_node (os.unlink) — not duplicated here
    broadcastSegment(sessionId, { type: 'pipeline_complete', session_id: sessionId })
    console.log(`[session][${sessionId}] Pipeline complete — notified SSE client`)

    return reply.send(result)
  })
}
