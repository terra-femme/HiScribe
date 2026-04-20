/**
 * client/src/LiveCapture.tsx
 *
 * Changes applied:
 *  - AudioWorklet replaces deprecated ScriptProcessor
 *    (runs on audio thread — no UI jank, not being removed from browsers)
 *  - Max session duration: 90-minute hard cap enforced client-side
 *    (server also enforces this — both sides agree)
 *  - Auth: WS and SSE connections pass ?token= query param
 *    (token retrieved from localStorage key 'hiscribe_token')
 *  - Graceful AudioWorklet fallback error: surfaces to user if browser
 *    doesn't support AudioWorklet (very old browsers only)
 *  - Aggressive debug logging in console for every state transition
 */

import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getAuthToken } from './auth'

const GATEWAY    = import.meta.env.VITE_GATEWAY_URL    ?? ''
const WS_GATEWAY = import.meta.env.VITE_WS_GATEWAY_URL ?? 'ws://localhost:3000'

// Must match server-side MAX_SESSION_SECONDS in audioStorage.ts
const MAX_SESSION_SECONDS = 5400  // 90 minutes

type Segment = {
  type: 'partial' | 'final' | 'pipeline_complete' | 'pipeline_error' | 'session_timeout'
  text: string
  speaker: string
  start_ms: number
  confidence: number
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function LiveCapture() {
  const { id: sessionId } = useParams<{ id: string }>()
  const navigate          = useNavigate()

  const [segments,  setSegments]  = useState<Segment[]>([])
  const [partial,   setPartial]   = useState('')
  const [recording, setRecording] = useState(false)
  const [stopping,  setStopping]  = useState(false)
  const [elapsed,   setElapsed]   = useState(0)
  const [error,     setError]     = useState<string | null>(null)

  const wsRef        = useRef<WebSocket | null>(null)
  const sseRef       = useRef<EventSource | null>(null)
  const mediaRef     = useRef<MediaStream | null>(null)
  const audioCtxRef  = useRef<AudioContext | null>(null)
  const workletRef   = useRef<AudioWorkletNode | null>(null)
  const timerRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const durationRef  = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── SSE: receive transcript segments ───────────────────────────────────────
  useEffect(() => {
    if (!sessionId) return

    const token = getAuthToken()
    const sseUrl = `${GATEWAY}/session/${sessionId}/stream?token=${encodeURIComponent(token)}`
    console.log(`[LiveCapture] Opening SSE stream: ${sseUrl}`)

    const sse = new EventSource(sseUrl)
    sseRef.current = sse

    sse.onopen = () => {
      console.log(`[LiveCapture][${sessionId}] SSE connection established`)
    }

    sse.onmessage = (e) => {
      let msg: Segment
      try {
        msg = JSON.parse(e.data)
      } catch (err) {
        console.error('[LiveCapture] SSE parse error:', e.data, err)
        return
      }

      console.debug(`[LiveCapture][${sessionId}] SSE message type=${msg.type}`)

      if (msg.type === 'pipeline_complete') {
        console.log(`[LiveCapture][${sessionId}] Pipeline complete — navigating to review`)
        navigate(`/session/${sessionId}/review`)
        return
      }

      if (msg.type === 'pipeline_error') {
        console.error(`[LiveCapture][${sessionId}] Pipeline error received via SSE`)
        setError('Pipeline failed — check server logs. Your recording was saved.')
        setStopping(false)
        return
      }

      if (msg.type === 'session_timeout') {
        console.warn(`[LiveCapture][${sessionId}] Server signalled session timeout`)
        setError('Recording stopped: maximum session duration reached.')
        stopRecording()
        return
      }

      if (msg.type === 'final') {
        console.debug(
          `[LiveCapture][${sessionId}] Final segment: "${msg.text?.slice(0, 60)}" ` +
          `speaker=${msg.speaker} conf=${msg.confidence?.toFixed(2)}`
        )
        setSegments(prev => [...prev, msg])
        setPartial('')
        return
      }

      if (msg.type === 'partial') {
        setPartial(msg.text)
      }
    }

    sse.onerror = (e) => {
      console.error(`[LiveCapture][${sessionId}] SSE error:`, e)
    }

    return () => {
      console.log(`[LiveCapture][${sessionId}] Closing SSE connection`)
      sse.close()
    }
  }, [sessionId])

  // ── Recording ───────────────────────────────────────────────────────────────

  async function startRecording() {
    console.log(`[LiveCapture][${sessionId}] startRecording() called`)

    if (!('AudioWorklet' in window)) {
      const msg = 'AudioWorklet is not supported in this browser. Please use a modern browser (Chrome 66+, Firefox 76+).'
      console.error('[LiveCapture] ' + msg)
      setError(msg)
      return
    }

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaRef.current = stream
      console.log('[LiveCapture] Microphone access granted')
    } catch (err: any) {
      console.error('[LiveCapture] Microphone access denied:', err.message)
      setError(`Microphone access denied: ${err.message}`)
      return
    }

    const token   = getAuthToken()
    const wsUrl   = `${WS_GATEWAY}/session/${sessionId}/audio?token=${encodeURIComponent(token)}`
    console.log(`[LiveCapture][${sessionId}] Opening audio WebSocket: ${wsUrl}`)

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = async () => {
      console.log(`[LiveCapture][${sessionId}] Audio WebSocket open`)

      // ── Set up AudioContext at 16kHz ────────────────────────────────────
      const audioCtx = new AudioContext({ sampleRate: 16000 })
      audioCtxRef.current = audioCtx

      if (audioCtx.sampleRate !== 16000) {
        console.warn(
          `[LiveCapture] AudioContext sample rate is ${audioCtx.sampleRate}Hz ` +
          '(requested 16000Hz) — some browsers ignore the hint. Proceeding anyway.'
        )
      }

      try {
        // Load the AudioWorklet module (served from /public/)
        await audioCtx.audioWorklet.addModule('/audio-processor.worklet.js')
        console.log('[LiveCapture] AudioWorklet module loaded')
      } catch (err: any) {
        console.error('[LiveCapture] Failed to load AudioWorklet module:', err.message)
        setError('Failed to load audio processor. Check browser console for details.')
        ws.close()
        stream.getTracks().forEach(t => t.stop())
        return
      }

      const source   = audioCtx.createMediaStreamSource(stream)
      const worklet  = new AudioWorkletNode(audioCtx, 'audio-capture-processor')
      workletRef.current = worklet

      // Main thread receives Int16 chunks from the audio thread
      worklet.port.onmessage = (e: MessageEvent) => {
        if (ws.readyState !== WebSocket.OPEN) {
          console.debug('[LiveCapture] WS not open — dropping AudioWorklet chunk')
          return
        }
        ws.send(e.data.int16Buffer)
      }

      worklet.port.onmessageerror = (e) => {
        console.error('[LiveCapture] AudioWorklet port message error:', e)
      }

      source.connect(worklet)
      // Do NOT connect worklet to audioCtx.destination — we don't want monitor playback

      setRecording(true)
      setError(null)
      console.log(`[LiveCapture][${sessionId}] Recording started`)

      // Elapsed timer (UI display)
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)

      // Client-side duration cap
      durationRef.current = setInterval(() => {
        setElapsed(prev => {
          if (prev >= MAX_SESSION_SECONDS) {
            console.warn(
              `[LiveCapture][${sessionId}] Client-side max duration reached ` +
              `(${MAX_SESSION_SECONDS}s) — auto-stopping`
            )
            setError('Maximum session duration reached. Recording stopped automatically.')
            stopRecording()
          }
          return prev
        })
      }, 10_000)
    }

    ws.onerror = (e) => {
      console.error(`[LiveCapture][${sessionId}] Audio WebSocket error:`, e)
      setError('WebSocket error — check server connection.')
    }

    ws.onclose = (e) => {
      console.log(
        `[LiveCapture][${sessionId}] Audio WebSocket closed — ` +
        `code=${e.code} reason=${e.reason || 'none'} wasClean=${e.wasClean}`
      )
      if (e.code === 1008) {
        setError('Session rejected by server — invalid auth token.')
      }
    }
  }

  async function stopRecording() {
    console.log(`[LiveCapture][${sessionId}] stopRecording() called`)
    setStopping(true)

    // Teardown audio graph
    workletRef.current?.port.close()
    workletRef.current?.disconnect()
    workletRef.current = null

    await audioCtxRef.current?.close()
    audioCtxRef.current = null

    wsRef.current?.close()
    wsRef.current = null

    mediaRef.current?.getTracks().forEach(t => {
      t.stop()
      console.log(`[LiveCapture] Track stopped: kind=${t.kind} label=${t.label}`)
    })
    mediaRef.current = null

    if (timerRef.current)   clearInterval(timerRef.current)
    if (durationRef.current) clearInterval(durationRef.current)

    console.log(`[LiveCapture][${sessionId}] Triggering pipeline via POST /session/:id/end`)
    try {
      const token = getAuthToken()
      const res = await fetch(`${GATEWAY}/session/${sessionId}/end`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        console.error(`[LiveCapture] /end returned HTTP ${res.status}: ${text}`)
        setError(`Server error ${res.status} on session end.`)
        setStopping(false)
      } else {
        console.log(`[LiveCapture][${sessionId}] /end request succeeded`)
        // Navigation triggered by pipeline_complete SSE event, not here
      }
    } catch (err: any) {
      console.error(`[LiveCapture] /end fetch failed: ${err.message}`)
      setError('Failed to reach server. Check your connection.')
      setStopping(false)
    }
  }

  // ── Format helpers ─────────────────────────────────────────────────────────

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`

  const timeRemaining = MAX_SESSION_SECONDS - elapsed
  const nearLimit = timeRemaining <= 300  // warn last 5 minutes

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 600 }}>
            {recording ? <span style={{ color: '#f87171' }}>● Recording</span> : 'Session'}
          </h2>
          <p style={{ color: '#6b7280', fontSize: '12px', marginTop: '2px' }}>
            Session: {sessionId?.slice(0, 8)}
          </p>
        </div>
        {recording && (
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontFamily: 'monospace', fontSize: '20px', color: '#9ca3af' }}>
              {formatTime(elapsed)}
            </span>
            {nearLimit && (
              <p style={{ fontSize: '11px', color: '#f87171', marginTop: '2px' }}>
                {Math.ceil(timeRemaining / 60)} min remaining
              </p>
            )}
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          background: '#2d1b1b', border: '1px solid #dc2626', borderRadius: '8px',
          padding: '12px 16px', marginBottom: '16px', color: '#fca5a5', fontSize: '13px'
        }}>
          ⚠ {error}
        </div>
      )}

      {/* Live transcript */}
      <div style={{
        background: '#161924', border: '1px solid #2a2d3a', borderRadius: '8px',
        padding: '20px', minHeight: '300px', marginBottom: '24px'
      }}>
        {segments.length === 0 && !partial && (
          <p style={{ color: '#4b5563', fontSize: '14px', textAlign: 'center', marginTop: '40px' }}>
            {recording ? 'Listening...' : 'Start recording to begin'}
          </p>
        )}
        {segments.map((seg, i) => (
          <div key={i} style={{ marginBottom: '12px' }}>
            <span style={{
              fontSize: '11px', fontWeight: 600, letterSpacing: '0.5px',
              color: seg.speaker === 'DOCTOR' ? '#60a5fa' : seg.speaker === 'UNKNOWN' ? '#9ca3af' : '#34d399',
              marginRight: '8px'
            }}>
              {seg.speaker}
            </span>
            <span style={{ fontSize: '14px', color: '#d1d5db' }}>{seg.text}</span>
          </div>
        ))}
        {partial && (
          <div style={{ color: '#6b7280', fontSize: '14px', fontStyle: 'italic' }}>
            {partial}▊
          </div>
        )}
      </div>

      {/* Controls */}
      {!recording && !stopping && (
        <button
          onClick={startRecording}
          style={{
            background: '#dc2626', color: '#fff', border: 'none', borderRadius: '8px',
            padding: '14px 32px', fontSize: '15px', fontWeight: 600, cursor: 'pointer', width: '100%'
          }}
        >
          ● Start Recording
        </button>
      )}
      {recording && !stopping && (
        <button
          onClick={stopRecording}
          style={{
            background: '#374151', color: '#fff', border: 'none', borderRadius: '8px',
            padding: '14px 32px', fontSize: '15px', fontWeight: 600, cursor: 'pointer', width: '100%'
          }}
        >
          ■ End Session & Process
        </button>
      )}
      {stopping && (
        <div style={{ textAlign: 'center', color: '#6b7280', padding: '16px' }}>
          Processing... pipeline running (~10–20 seconds)
        </div>
      )}
    </div>
  )
}
