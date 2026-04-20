/**
 * audio-processor.worklet.js
 *
 * AudioWorklet processor — runs on the dedicated audio rendering thread,
 * separate from the main UI thread. This replaces the deprecated ScriptProcessor.
 *
 * Responsibilities:
 *  - Receive Float32 PCM samples from the audio graph (128 frames per callback)
 *  - Accumulate frames until CHUNK_FRAMES is reached (4096 = 256ms at 16kHz)
 *  - Convert Float32 [-1.0, 1.0] → Int16 [-32768, 32767]
 *  - Transfer the Int16 ArrayBuffer to the main thread via port.postMessage()
 *    using transferable objects (zero-copy)
 *
 * Why AudioWorklet over ScriptProcessor:
 *  - Runs on audio rendering thread — no UI jank causes audio dropouts
 *  - Not deprecated — ScriptProcessor is being removed from browsers
 *  - Guaranteed scheduling priority for real-time audio
 *
 * Communication:
 *  Main thread creates AudioWorkletNode, listens on workletNode.port.onmessage.
 *  Each message contains { int16Buffer: ArrayBuffer } with the PCM chunk.
 */

const CHUNK_FRAMES = 4096  // frames to accumulate before sending (256ms at 16kHz)

class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._buffer = new Float32Array(CHUNK_FRAMES)
    this._filled = 0
    this._chunksSent = 0
    console.log('[worklet] AudioCaptureProcessor initialised — chunk size:', CHUNK_FRAMES, 'frames')
  }

  process(inputs, _outputs, _params) {
    const input = inputs[0]
    if (!input || input.length === 0) return true

    const channel = input[0]  // mono: channel 0
    if (!channel) return true

    let offset = 0
    while (offset < channel.length) {
      const remaining = CHUNK_FRAMES - this._filled
      const toCopy = Math.min(remaining, channel.length - offset)

      this._buffer.set(channel.subarray(offset, offset + toCopy), this._filled)
      this._filled += toCopy
      offset += toCopy

      if (this._filled >= CHUNK_FRAMES) {
        this._flush()
      }
    }

    return true  // keep processor alive
  }

  _flush() {
    // Convert Float32 → Int16 (in-place, allocate new Int16Array)
    const int16 = new Int16Array(this._filled)
    for (let i = 0; i < this._filled; i++) {
      // Clamp to valid Int16 range
      const clamped = Math.max(-1, Math.min(1, this._buffer[i]))
      int16[i] = clamped < 0
        ? Math.round(clamped * 32768)
        : Math.round(clamped * 32767)
    }

    this._chunksSent++
    if (this._chunksSent % 20 === 0) {
      console.log('[worklet] Chunks sent to main thread:', this._chunksSent)
    }

    // Transfer ownership of the ArrayBuffer — zero-copy
    this.port.postMessage({ int16Buffer: int16.buffer }, [int16.buffer])

    // Reset accumulator
    this._buffer = new Float32Array(CHUNK_FRAMES)
    this._filled = 0
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor)
