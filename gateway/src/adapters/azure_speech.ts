import WebSocket from 'ws'
import { OnSegment } from './gladia'

// Stub — swap speech.ts re-export to activate
// Required env vars: AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
export function transcribe(
  _sessionId: string,
  _clientSocket: WebSocket,
  _onSegment: OnSegment
): void {
  throw new Error(
    'Azure Speech adapter not yet implemented. ' +
    'Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in .env, then build this out.'
  )
}
