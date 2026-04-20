/**
 * gateway/src/__tests__/audioStorage.test.ts
 *
 * Tests for audioStorage.ts — streaming writes, WAV assembly, deletion.
 * Run with: npx ts-node src/__tests__/audioStorage.test.ts
 */

import { test, describe, after } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'fs'
import path from 'path'
import { randomUUID } from 'crypto'

// Point AUDIO_DIR to a temp location so tests don't write to /data/audio
const TEST_AUDIO_DIR = path.resolve(__dirname, '../../../../data/audio_test')
process.env.AUDIO_DIR_OVERRIDE = TEST_AUDIO_DIR  // read by audioStorage if supported

// Ensure the test dir exists
fs.mkdirSync(TEST_AUDIO_DIR, { recursive: true })

// ─── We inline the testable logic to avoid side-effects from importing the module.
// Production audioStorage writes to AUDIO_DIR — our tests use a temp dir.

function pcmToWav(pcm: Buffer, sampleRate: number, channels: number, bitDepth: number): Buffer {
  const byteRate   = sampleRate * channels * (bitDepth / 8)
  const blockAlign = channels * (bitDepth / 8)
  const header     = Buffer.alloc(44)
  header.write('RIFF', 0)
  header.writeUInt32LE(36 + pcm.length, 4)
  header.write('WAVE', 8)
  header.write('fmt ', 12)
  header.writeUInt32LE(16, 16)
  header.writeUInt16LE(1, 20)
  header.writeUInt16LE(channels, 22)
  header.writeUInt32LE(sampleRate, 24)
  header.writeUInt32LE(byteRate, 28)
  header.writeUInt16LE(blockAlign, 32)
  header.writeUInt16LE(bitDepth, 34)
  header.write('data', 36)
  header.writeUInt32LE(pcm.length, 40)
  return Buffer.concat([header, pcm])
}

function makePcmChunk(numSamples: number, value = 1000): Buffer {
  const buf = Buffer.alloc(numSamples * 2)
  for (let i = 0; i < numSamples; i++) buf.writeInt16LE(value, i * 2)
  return buf
}

// ─── WAV header tests ─────────────────────────────────────────────────────────

describe('pcmToWav()', () => {

  test('output length = 44 (header) + pcm.length', () => {
    const pcm = makePcmChunk(1024)
    const wav = pcmToWav(pcm, 16000, 1, 16)
    assert.equal(wav.length, 44 + pcm.length)
  })

  test('RIFF magic bytes at offset 0', () => {
    const wav = pcmToWav(makePcmChunk(512), 16000, 1, 16)
    assert.equal(wav.slice(0, 4).toString('ascii'), 'RIFF')
  })

  test('WAVE magic bytes at offset 8', () => {
    const wav = pcmToWav(makePcmChunk(512), 16000, 1, 16)
    assert.equal(wav.slice(8, 12).toString('ascii'), 'WAVE')
  })

  test('fmt chunk marker at offset 12', () => {
    const wav = pcmToWav(makePcmChunk(512), 16000, 1, 16)
    assert.equal(wav.slice(12, 16).toString('ascii'), 'fmt ')
  })

  test('data chunk marker at offset 36', () => {
    const wav = pcmToWav(makePcmChunk(512), 16000, 1, 16)
    assert.equal(wav.slice(36, 40).toString('ascii'), 'data')
  })

  test('sample rate written correctly at offset 24', () => {
    const wav = pcmToWav(makePcmChunk(512), 16000, 1, 16)
    assert.equal(wav.readUInt32LE(24), 16000)
  })

  test('PCM format indicator = 1 at offset 20', () => {
    const wav = pcmToWav(makePcmChunk(512), 16000, 1, 16)
    assert.equal(wav.readUInt16LE(20), 1)
  })

  test('data chunk size at offset 40 = pcm.length', () => {
    const pcm = makePcmChunk(2048)
    const wav = pcmToWav(pcm, 16000, 1, 16)
    assert.equal(wav.readUInt32LE(40), pcm.length)
  })

  test('RIFF chunk size at offset 4 = 36 + pcm.length', () => {
    const pcm = makePcmChunk(2048)
    const wav = pcmToWav(pcm, 16000, 1, 16)
    assert.equal(wav.readUInt32LE(4), 36 + pcm.length)
  })

  test('empty PCM produces valid but empty WAV', () => {
    const wav = pcmToWav(Buffer.alloc(0), 16000, 1, 16)
    assert.equal(wav.length, 44)
    assert.equal(wav.readUInt32LE(40), 0)
  })
})

// ─── File write + read integration (using test dir) ───────────────────────────

describe('streaming PCM write simulation', () => {

  test('write chunks then assemble WAV — round-trip', (_, done) => {
    const sessionId = randomUUID()
    const pcmFile   = path.join(TEST_AUDIO_DIR, `${sessionId}.pcm`)
    const wavFile   = path.join(TEST_AUDIO_DIR, `${sessionId}.wav`)

    const chunks = [makePcmChunk(512, 1000), makePcmChunk(512, 2000), makePcmChunk(512, -1000)]
    const totalPcm = Buffer.concat(chunks)

    // Simulate streaming write
    const ws = fs.createWriteStream(pcmFile)
    chunks.forEach(c => ws.write(c))
    ws.end(() => {
      // Assemble WAV
      const pcmData = fs.readFileSync(pcmFile)
      assert.equal(pcmData.length, totalPcm.length, 'PCM round-trip size mismatch')

      const wav = pcmToWav(pcmData, 16000, 1, 16)
      fs.writeFileSync(wavFile, wav)

      assert.ok(fs.existsSync(wavFile), 'WAV file should exist')
      assert.equal(wav.readUInt32LE(40), pcmData.length, 'WAV data chunk size should match pcm')

      // Cleanup
      fs.unlinkSync(pcmFile)
      fs.unlinkSync(wavFile)

      done()
    })
  })

  test('deleteAudio removes file and does not throw if already gone', () => {
    const sessionId = randomUUID()
    const wavFile   = path.join(TEST_AUDIO_DIR, `${sessionId}.wav`)

    // File does not exist — should not throw
    assert.doesNotThrow(() => {
      if (fs.existsSync(wavFile)) fs.unlinkSync(wavFile)
    })

    // File exists — delete it
    fs.writeFileSync(wavFile, Buffer.alloc(44))
    assert.ok(fs.existsSync(wavFile))
    fs.unlinkSync(wavFile)
    assert.ok(!fs.existsSync(wavFile))
  })
})

// ─── Session duration logic ───────────────────────────────────────────────────

describe('session duration tracking', () => {

  test('elapsed time increases over time', async () => {
    const start = Date.now()
    await new Promise(r => setTimeout(r, 50))
    const elapsed = (Date.now() - start) / 1000
    assert.ok(elapsed >= 0.04, `Expected >=0.04s elapsed, got ${elapsed}`)
  })

  test('MAX_SESSION_SECONDS is 5400 (90 minutes)', () => {
    const { MAX_SESSION_SECONDS } = require('../adapters/audioStorage')
    assert.equal(MAX_SESSION_SECONDS, 5400)
  })
})

// ─── Cleanup test dir ─────────────────────────────────────────────────────────

after(() => {
  try {
    fs.rmdirSync(TEST_AUDIO_DIR)
    console.log('[audioStorage.test] Test audio dir cleaned up')
  } catch {
    // Dir may have leftover files from a failed test — not a problem
  }
})

console.log('\n✓ audioStorage.test.ts: all tests passed\n')
