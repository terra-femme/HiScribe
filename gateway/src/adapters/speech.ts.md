# speech.ts — A one-line switchboard that controls which speech-to-text provider the rest of the app uses

## What This File Is For
This file does almost nothing on its own — and that is exactly the point. It re-exports the `transcribe` function from whichever speech adapter is currently active. By changing a single line in this file, an engineer can swap the entire transcription backend (Gladia, Azure, Google, etc.) without touching any other file in the project.

## How It Fits In The Project
`routes/session.ts` imports `transcribe` from `./adapters/speech` (this file). It never imports from `gladia.ts` or `azure_speech.ts` directly. This file is the indirection layer — the public interface for transcription. The commented-out lines document which other adapters exist and how to activate them.

---

## Line-by-Line Breakdown

### Line 1 — Comment explaining the pattern

```typescript
// Active re-export — change this ONE LINE to swap ASR provider
// All adapters implement the same (sessionId, socket, onSegment) signature
```

**What it does:** Documents the design intent of the file for any future developer who opens it.

**Why:** Code comments that explain *why* a design decision was made are more valuable than comments that explain *what* the code does (the code already shows what it does). This comment answers "why does this file exist at all?" before anyone has to ask.

**ELI5:** It's a sticky note on a switchbox that says "flip switch 3 to change the power source." Without it, someone might wonder why there's a box that just passes electricity through.

**Best practice:** Write comments for the "why," not the "what." `// re-exports transcribe` adds no value. `// change this ONE LINE to swap ASR provider` saves the next developer real time.

---

### Line 3 — Active export

```typescript
export { transcribe } from './gladia'
```

**What it does:** Imports `transcribe` from `gladia.ts` and immediately re-exports it under the same name. Any file that imports `transcribe` from `speech.ts` will get the Gladia implementation.

**Why:** This is a named re-export. TypeScript and JavaScript modules allow you to re-export from another module without having to import it into a variable first. The syntax `export { X } from './module'` is shorthand for `import { X } from './module'; export { X }`. This keeps the file to a single line of real logic.

**ELI5:** Imagine a store that sells "Brand X" milk but repackages it under their own label. The store is `speech.ts`, and right now "Brand X" is Gladia. You buy milk from the store — you don't need to know or care which farm it came from.

**Best practice:** This pattern is called a "facade" or "barrel export." It's excellent for decoupling: the consumer (`session.ts`) depends on a stable interface (`speech.ts`), not on a specific implementation. This makes testing easier too — you can swap in a mock adapter for tests by just changing this one file.

---

### Lines 4–5 — Commented alternatives

```typescript
// export { transcribe } from './azure_speech'
// export { transcribe } from './google_speech'
```

**What it does:** Documents two other adapter options that are available but not currently active. To switch providers, you uncomment one of these lines and comment out line 3.

**Why:** Keeping these commented lines in the file serves as living documentation of what adapters exist. It also makes the switch instant — no need to remember the module path or the export name. This is much better than having to search the codebase for "what was that Azure adapter called again?"

**ELI5:** These are the other flavors on the menu, crossed out because they're not available today. But you can see them and could order them if the kitchen switches suppliers.

**Best practice:** When you have multiple swappable implementations, it's fine to leave commented alternatives in a switchboard file like this. But in a larger project, you might prefer a configuration-driven approach — reading `process.env.ASR_PROVIDER` and selecting the adapter at runtime — so you can switch providers with an environment variable change instead of a code change.

---

## Common Mistakes

1. **Importing directly from `./gladia` in `session.ts` instead of from `./speech`.** This defeats the entire purpose of the indirection layer. If someone hard-codes `import { transcribe } from './gladia'` in the route file, swapping to Azure requires editing the route file too — and potentially every other file that uses transcription.

2. **Uncommenting multiple export lines simultaneously.** If both line 3 and line 4 are active at the same time, TypeScript will throw a duplicate export error. Only one `export { transcribe }` can exist at a time.

3. **Adding a new adapter but forgetting to add it as a commented option here.** Over time this file should be the authoritative list of available adapters. If you write `google_speech.ts` but never add the commented line, the next engineer won't know it exists.

---

## Key Concepts To Look Up

- **Re-export / barrel export** — the pattern of exporting from one module through another module to create a stable public API
- **Facade pattern** — a design pattern that provides a simplified interface to a more complex subsystem
- **ASR (Automatic Speech Recognition)** — the technical term for software that converts spoken audio to text
- **Named exports vs. default exports** — `export { transcribe }` is a named export; `export default transcribe` is a default export; they are imported differently
- **Decoupling** — designing code so that components don't directly depend on each other's internal details
