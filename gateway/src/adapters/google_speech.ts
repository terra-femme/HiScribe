import WebSocket from 'ws'
import { OnSegment } from './gladia'

// Stub — swap speech.ts re-export to activate
// Required env vars: GOOGLE_APPLICATION_CREDENTIALS
export function transcribe(
  _sessionId: string,
  _clientSocket: WebSocket,
  _onSegment: OnSegment
): void {
  throw new Error(
    'Google Speech adapter not yet implemented. ' +
    'Set GOOGLE_APPLICATION_CREDENTIALS in .env, then build this out.'
  )
}
