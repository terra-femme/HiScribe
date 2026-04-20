# azure_speech.ts — A placeholder stub for a future Azure Cognitive Services speech-to-text adapter

## What This File Is For
This file is a stub — it has the correct shape of a real speech adapter but throws an error immediately if called. Its purpose is to define where the Azure Speech implementation will live when it is eventually built, and to document the required interface and environment variables. It is currently inactive because `speech.ts` points to `gladia.ts` instead.

## How It Fits In The Project
This file is dormant unless `speech.ts` is changed to re-export from this file instead of from `gladia.ts`. It imports the `OnSegment` type from `gladia.ts` because that is where the shared types live. It mirrors the exact function signature of `gladia.ts`'s `transcribe` function — this is the contract all adapters must fulfill.

---

## Line-by-Line Breakdown

### Line 1 — Import WebSocket

```typescript
import WebSocket from 'ws'
```

**What it does:** Imports the `ws` library for WebSocket support, identical to the import in `gladia.ts`.

**Why:** Even though this stub never uses the WebSocket, the import must be present because the function signature includes a `WebSocket` parameter. TypeScript needs to know what `WebSocket` refers to in the type annotation.

**ELI5:** You're filling out a job application form. The form asks for your driver's license number even if you never plan to drive. You still have to put something in that field for the form to be valid.

**Best practice:** When a stub grows into a real implementation, the import will already be there and correct. Starting from a properly-typed skeleton avoids "I forgot to import the WebSocket library" surprises.

---

### Lines 2–3 — Import OnSegment type

```typescript
import { OnSegment } from './gladia'

// Stub — swap speech.ts re-export to activate
// Required env vars: AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
```

**What it does:** Imports the `OnSegment` callback type from `gladia.ts`. The comment documents what environment variables will be needed when this adapter is built out.

**Why:** All adapters must use the same callback signature. Importing `OnSegment` from `gladia.ts` enforces this — if the type changes in `gladia.ts`, this file will immediately get a TypeScript error reminding you to update the implementation. The comment about environment variables is early documentation for the developer who will implement this.

**ELI5:** All translators must use the same reporting format (the `OnSegment` type). This file imports that format from the person who designed it. The comment is a sticky note: "when you build this, you'll need these two secret codes."

**Best practice:** Shared types should live in one canonical place and be imported from there, not duplicated. If each adapter defined its own version of `OnSegment`, they might drift out of sync and cause subtle bugs.

---

### Lines 5–15 — Stub `transcribe` function

```typescript
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
```

**What it does:** Exports a `transcribe` function with exactly the same signature as `gladia.ts`. The parameters are prefixed with underscores to signal they are intentionally unused. The function body immediately throws an error with a detailed, actionable message.

**Why:** The function signature must be identical to `gladia.ts` so that `speech.ts` can re-export it transparently and `session.ts` can call it without modification. The underscore prefix (`_sessionId`, `_clientSocket`, `_onSegment`) is a TypeScript and JavaScript convention for "I know this parameter exists but I'm not using it yet" — it suppresses unused-variable linter warnings. The error message is written to guide the next developer: it names the exact env vars needed, not just "not implemented."

**ELI5:** The office has a desk labeled "Azure Transcription Department," a nameplate, and a note on the door that says "Coming soon — bring your key and region code." The desk is empty, but the infrastructure for when someone sits down is already there.

**Best practice:** Stubs should always `throw` with helpful messages rather than silently failing (returning early, returning `undefined`, etc.). A silent stub is the worst kind — it looks like it worked, then you spend an hour wondering why no transcription is appearing.

---

## Common Mistakes

1. **Activating this adapter before implementing it.** If you change `speech.ts` to point to this file without filling in the implementation, every audio WebSocket connection will immediately throw an error and close. Make sure the implementation is complete before switching.

2. **Removing the underscore prefixes from unused parameters.** Without the underscores, TypeScript (with `noUnusedParameters` enabled) or ESLint will warn about unused parameters, creating unnecessary noise. The underscores are intentional signals.

3. **Duplicating the `OnSegment` type instead of importing it.** If you copy-paste the type definition rather than importing it, future changes to `Segment` in `gladia.ts` won't automatically propagate here, and the two adapters could silently diverge.

---

## Key Concepts To Look Up

- **Stub / placeholder** — a piece of code with the right shape but no real implementation, used to sketch out an architecture before building it
- **Underscore convention in TypeScript/JavaScript** — prefixing unused parameters with `_` to signal intentional non-use
- **`throw new Error(...)`** — immediately stops execution and propagates an error up the call stack
- **Interface contract** — the agreement that all speech adapters must export `transcribe` with the same parameter types and return type
- **Azure Cognitive Services Speech SDK** — the Microsoft library that would replace the `throw` in a real implementation; worth reading its WebSocket streaming docs
