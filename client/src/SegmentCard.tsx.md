# SegmentCard.tsx — Inline CRUD For a Single Transcript Segment

## What This File Is For
Renders one transcript segment as a card in the SOAP review UI. Provides three actions directly on the card: edit the text (corrects transcription errors), remap to a different SOAP section, and delete. Every action is immediately sent to the gateway and logged in the audit trail.

## How It Fits In The Project
`SOAPReview.tsx` renders one `SegmentCard` per segment in each SOAP column. When an action completes, `SegmentCard` calls the `onUpdate` prop which triggers `SOAPReview` to re-fetch the note and re-render.

---

## Line-by-Line Breakdown

### Lines 1 — Import
```typescript
import { useState } from 'react'
```
**What it does:** Imports the `useState` hook for local UI state.
**Why:** This component manages three pieces of local state: whether it's in editing mode, the current edit text, and whether the remap dropdown is open. These are purely UI concerns — they don't need to live in a parent component.
**ELI5:** The card keeps track of its own "mode" (viewing / editing / remapping) internally. It doesn't need to tell its parent about these details.
**Best practice:** Keep UI state (is this input open? what's the current draft text?) local to the component. Only lift state up when a sibling component needs to know about it.

### Lines 3–6 — Constants
```typescript
const GATEWAY = 'http://localhost:3000'
const SOAP_SECTIONS = ['S', 'O', 'A', 'P', 'UNCLASSIFIED']
const SOAP_LABELS: Record<string, string> = { S: 'Subjective', O: 'Objective', ... }
```
**What it does:** Defines the gateway URL and SOAP section metadata.
**Why `Record<string, string>`:** This TypeScript type says "an object where keys are strings and values are strings." It's more precise than `object` or `any`.
**Best practice:** Module-level constants (all caps) should never be defined inside component functions. They're static — redefining them on every render wastes memory.

### Lines 8–24 — Type definitions
```typescript
type Segment = { id: number; segment_id: string; text: string; ... }
type Props = { segment: Segment; providerId: string; onUpdate: () => void }
```
**What it does:** Defines the segment data shape and the component's props.
**Why `onUpdate: () => void`:** A callback prop — when the card finishes an edit/remap/delete, it calls this function to tell the parent "something changed, please re-fetch." The parent decides what to do; the card just signals that something happened.
**ELI5:** The card is a worker. `onUpdate` is the bell it rings when it's done. The manager (SOAPReview) hears the bell and checks on progress.
**Best practice:** Callback props (`onX: () => void`) are the standard pattern for child-to-parent communication in React. Avoid passing setState functions down — pass callbacks instead.

### Lines 26–31 — Component state
```typescript
const [editing, setEditing] = useState(false)
const [editText, setEditText] = useState(segment.text)
const [remapping, setRemapping] = useState(false)
```
**What it does:** Three boolean/string states for UI modes.
**Why initialize `editText` with `segment.text`:** When the user opens the edit field, they should see the current text pre-filled. If initialized to `''`, they'd have to retype the whole thing.
**ELI5:** The card remembers: "Am I in edit mode? What text is in the edit box right now? Am I showing the remap buttons?"
**Best practice:** Keep editing state local. The "what text is in this input right now" state is UI state, not application state.

### Lines 33–44 — saveEdit
```typescript
async function saveEdit() {
  await fetch(`${GATEWAY}/session/${segment.session_id}/segment/${segment.segment_id}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ corrected_text: editText, provider_id: providerId })
  })
  setEditing(false)
  onUpdate()
}
```
**What it does:** Sends the corrected text to the gateway, closes edit mode, and signals the parent to re-fetch.
**Why this is an edit, not an amendment:** The provider is correcting what the ASR heard wrong. The original text is preserved in the audit log. This is the legal "edit" event type.
**Why `onUpdate()` after `await`:** Only signal "done" after the server has confirmed the change. If you called `onUpdate()` before the await, the parent would re-fetch before the save completed and show the old text.
**Best practice:** In async event handlers, always `await` the server call before updating local state or calling callbacks.

### Lines 46–57 — remap
```typescript
async function remap(toSection: string) {
  await fetch(`.../remap`, {
    body: JSON.stringify({ from_section: segment.soap_section, to_section: toSection, provider_id: providerId })
  })
  setRemapping(false)
  onUpdate()
}
```
**What it does:** Sends a remap event to move this segment to a different SOAP section.
**Why send `from_section`:** The audit log records both where the segment came from and where it went. This is required for the `segment_remapped` audit event — you need the full before/after.
**ELI5:** Moving a sticky note from one column to another. You tell the system "it was in Subjective, now it's in Plan" — not just "it's in Plan now."

### Lines 76–99 — Conditional rendering
```typescript
{editing ? (
  <textarea ... />
) : (
  <p>{segment.text}</p>
)}
{remapping && (
  <div>/* section buttons */</div>
)}
{!editing && !remapping && (
  <div>/* action buttons */</div>
)}
```
**What it does:** Shows different content based on which mode the card is in.
**Why:** The card has three visual states: viewing (show text + action buttons), editing (show textarea + save/cancel), remapping (show section options + cancel). Only one state is active at a time.
**ELI5:** Like a Swiss Army knife — only one tool extends at a time. The others are folded away.
**Best practice:** Conditional rendering with ternaries is clean for two states. For three or more states, consider a `mode: 'view' | 'edit' | 'remap'` state variable instead of three booleans — it's impossible to be in two modes simultaneously with a union type.

---

## Common Mistakes
1. Calling `onUpdate()` before `await` — parent re-fetches stale data.
2. Not resetting `editText` on cancel — next time the user opens edit, they see their old draft.
3. Rendering all three modes simultaneously with `if/else if/else` — easy to accidentally show two modes at once with boolean state.

## Key Concepts To Look Up
- Controlled components in React — why `value={editText}` + `onChange` instead of just `defaultValue`
- Callback props pattern — child-to-parent communication
- Conditional rendering in React — ternary vs `&&` vs early return
- `await` in async event handlers
- `Record<K, V>` TypeScript type
