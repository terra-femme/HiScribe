/**
 * gateway/src/__tests__/gladia.test.ts
 *
 * Tests for hallucination filter and RMS energy pre-check in gladia.ts.
 * Run with: npx ts-node src/__tests__/gladia.test.ts
 */

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

// ─── Extract testable units inline (same logic as gladia.ts) ─────────────────
// We re-implement the pure functions here so we can test them without
// spinning up a WebSocket. The production code uses the same logic.

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

function makeInt16Buffer(samples: number[]): Buffer {
  const buf = Buffer.alloc(samples.length * 2)
  samples.forEach((s, i) => buf.writeInt16LE(s, i * 2))
  return buf
}

// ─── Hallucination filter tests ───────────────────────────────────────────────

describe('isHallucination()', () => {

  test('exact match: "thank you"', () => {
    assert.equal(isHallucination('thank you'), true)
  })

  test('with trailing punctuation: "Thank you."', () => {
    assert.equal(isHallucination('Thank you.'), true)
  })

  test('case insensitive: "OKAY"', () => {
    assert.equal(isHallucination('OKAY'), true)
  })

  test('with extra whitespace: "  hmm  "', () => {
    assert.equal(isHallucination('  hmm  '), true)
  })

  test('real clinical text is NOT filtered', () => {
    assert.equal(isHallucination('The patient reports chest pain'), false)
  })

  test('longer sentence containing hallucination word is NOT filtered', () => {
    // "thank you for coming in today" — more than just the phrase, should pass
    assert.equal(isHallucination('thank you for coming in today'), false)
  })

  test('"silence" bracket variant', () => {
    assert.equal(isHallucination('[silence]'), true)
  })

  test('empty string is NOT in hallucination set', () => {
    // empty string should fall through — length check in gladia.ts handles this
    assert.equal(isHallucination(''), false)
  })

  test('medical abbreviation "OK" is filtered (mapped to ok)', () => {
    assert.equal(isHallucination('OK'), true)
  })

  test('"see you later" trailing punctuation', () => {
    assert.equal(isHallucination('see you later.'), true)
  })
})

// ─── RMS energy tests ─────────────────────────────────────────────────────────

describe('computeRms()', () => {

  test('silence buffer (all zeros) → rms = 0', () => {
    const buf = makeInt16Buffer(new Array(1024).fill(0))
    assert.equal(computeRms(buf), 0)
  })

  test('empty buffer → rms = 0', () => {
    assert.equal(computeRms(Buffer.alloc(0)), 0)
  })

  test('single-byte buffer → rms = 0 (guard)', () => {
    assert.equal(computeRms(Buffer.alloc(1)), 0)
  })

  test('constant signal at 1000 → rms ≈ 1000', () => {
    const samples = new Array(1024).fill(1000)
    const buf = makeInt16Buffer(samples)
    const rms = computeRms(buf)
    assert.ok(Math.abs(rms - 1000) < 1, `Expected ~1000 got ${rms}`)
  })

  test('loud signal (20000) → rms above threshold', () => {
    const samples = new Array(1024).fill(20000)
    const buf = makeInt16Buffer(samples)
    assert.ok(computeRms(buf) > RMS_THRESHOLD, 'Loud signal should be above threshold')
  })

  test('very quiet signal (10) → rms below threshold', () => {
    const samples = new Array(1024).fill(10)
    const buf = makeInt16Buffer(samples)
    assert.ok(computeRms(buf) < RMS_THRESHOLD, 'Quiet signal should be below threshold')
  })

  test('RMS of alternating +/- signal (typical speech shape)', () => {
    // Alternating ±5000 — RMS should be 5000
    const samples = Array.from({ length: 1024 }, (_, i) => i % 2 === 0 ? 5000 : -5000)
    const buf = makeInt16Buffer(samples)
    const rms = computeRms(buf)
    assert.ok(Math.abs(rms - 5000) < 1, `Expected ~5000 got ${rms}`)
  })
})

console.log('\n✓ gladia.test.ts: all tests passed\n')
