# SOAPReview.tsx — The review screen where a provider reads, edits, and approves the generated SOAP note

## What This File Is For
This is the final step in the clinical workflow. After the recording is processed, this screen displays the AI-generated SOAP note organized into four columns (Subjective, Objective, Assessment, Plan). Each piece of transcribed speech is shown as an editable card. The provider fills in their NPI and the patient's MRN, reviews any flagged segments, and clicks "Approve" to generate the official FHIR document.

## How It Fits In The Project
`SOAPReview` is rendered by `App.tsx` at `/session/:id/review`. It fetches the note from `GET /session/:id/note`. It renders `SegmentCard` for each transcript segment and `AmendmentPanel` in each SOAP column for adding free-text notes. When approved, it calls `POST /session/:id/approve` and navigates back to `/session`.

## Line-by-Line Breakdown

### Lines 1–4 — Imports
```tsx
import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import SegmentCard from './SegmentCard'
import AmendmentPanel from './AmendmentPanel'
```
**What it does:** Imports three React hooks (`useEffect`, `useState`, `useCallback`) plus routing hooks and two child components.

**Why `useCallback` here?** `useCallback` is used to memoize the `fetchNote` function so it has a stable identity across renders. This matters because `fetchNote` is listed as a dependency of `useEffect`. If `fetchNote` were recreated on every render (as it would be without `useCallback`), the `useEffect` would fire on every render — causing infinite fetch loops.

**ELI5:** Without `useCallback`, React would think the `fetchNote` function is "new" on every render (because a new function object is created). The `useEffect` that depends on it would see a "new" dependency and re-run. `useCallback` gives the function a permanent identity so the effect only runs when `sessionId` actually changes.

**Best practice:** Only use `useCallback` when a function is in a dependency array or passed as a prop to a memoized child component. Do not use it everywhere — it has its own overhead.

---

### Lines 6–14 — Constants and type definitions
```tsx
const GATEWAY = 'http://localhost:3000'

const SECTIONS = ['S', 'O', 'A', 'P'] as const
const SECTION_LABELS: Record<string, string> = {
  S: 'Subjective', O: 'Objective', A: 'Assessment', P: 'Plan'
}
const SECTION_COLORS: Record<string, string> = {
  S: '#34d399', O: '#60a5fa', A: '#f59e0b', P: '#a78bfa'
}
```
**What it does:** Defines the four SOAP sections and their display labels and colors.

**Why `as const`?** `['S', 'O', 'A', 'P'] as const` tells TypeScript to treat this array as a readonly tuple of literal types `'S' | 'O' | 'A' | 'P'`, rather than `string[]`. This provides stricter type checking downstream.

**Why `Record<string, string>`?** `Record<K, V>` is a TypeScript utility type that represents an object whose keys are type `K` and values are type `V`. `Record<string, string>` means "an object with string keys and string values," which is exactly what a lookup table like `SECTION_LABELS` is.

**ELI5:** `SECTION_LABELS` is a dictionary. You look up a key (`'S'`) and get the full word (`'Subjective'`). `Record<string, string>` tells TypeScript what kind of dictionary it is — string keys, string values.

**Best practice:** Centralizing display metadata like labels and colors in a lookup table (rather than inline conditional logic) makes it easy to add or rename sections without hunting through JSX.

---

### Lines 16–34 — Type definitions
```tsx
type Segment = {
  id: number
  segment_id: string
  session_id: string
  text: string
  speaker: string
  soap_section: string
  start_ms: number
  confidence: number
  reliability_score: number
  confidence_flag: boolean
  role_flag: boolean
}

type ReviewPayload = {
  session: { id: string; status: string }
  soap: Record<string, Segment[]>
  amendments: any[]
}
```
**What it does:** Defines the shape of a `Segment` (a single transcribed speech fragment with metadata) and `ReviewPayload` (the full response from `GET /session/:id/note`).

**Why two separate types?** `Segment` in `SOAPReview.tsx` is richer than the `Segment` type in `LiveCapture.tsx` — it has additional fields like `reliability_score`, `confidence_flag`, and `role_flag` that are only available after the processing pipeline has run. Defining them separately is intentional and correct.

**Why `soap: Record<string, Segment[]>`?** The SOAP note from the server is organized as an object where each key is a section name (`'S'`, `'O'`, `'A'`, `'P'`, or `'UNCLASSIFIED'`) and each value is an array of segments in that section. `Record<string, Segment[]>` models this exactly.

**Best practice:** Avoid using `any[]` for `amendments` if possible — define the amendment shape as a type too. `any` disables TypeScript's safety checks for those values.

---

### Lines 42–52 — State declarations and `fetchNote`
```tsx
const [payload, setPayload] = useState<ReviewPayload | null>(null)
const [loading, setLoading] = useState(true)
const [approving, setApproving] = useState(false)
const [meta, setMeta] = useState({ npi: '', mrn: '', visitType: 'follow_up' })

const fetchNote = useCallback(async () => {
  const res = await fetch(`${GATEWAY}/session/${sessionId}/note`)
  if (res.ok) setPayload(await res.json())
  setLoading(false)
}, [sessionId])

useEffect(() => { fetchNote() }, [fetchNote])
```
**What it does:**
- `payload` — the full note data from the server. Starts as `null` (not yet loaded).
- `loading` — whether we are waiting for the initial note fetch.
- `approving` — whether the approve button has been clicked and is waiting.
- `meta` — a grouped state object for the three required approval metadata fields.

`fetchNote` fetches the note and sets the payload. It is wrapped in `useCallback` to avoid recreating it on every render. The `useEffect` calls `fetchNote` once on mount.

**Why does `fetchNote` also serve as a refresh callback?** `fetchNote` is passed down to `SegmentCard` and `AmendmentPanel` as `onUpdate` and `onAdded`. When a child component edits a segment or adds an amendment, it calls this function to re-fetch the whole note from the server, keeping the UI in sync with the database.

**ELI5:** `fetchNote` is like pressing the refresh button. The parent gives each child component a reference to this button. When a child makes a change (edits a segment, adds an amendment), it presses the button, and the parent re-fetches the latest data from the server.

**Best practice:** This "optimistic update" alternative (re-fetch the whole note) is simple and reliable but not the most efficient. A more advanced pattern would be to update the local state directly after a successful edit (optimistic update) and only fall back to re-fetching if there is an error. For a prototype, re-fetching is a perfectly valid approach.

---

### Lines 55–80 — The `approve` function
```tsx
async function approve() {
  if (!meta.npi || !meta.mrn) return

  if (flaggedCount > 0) {
    const confirmed = confirm(
      `${flaggedCount} flagged segment${flaggedCount > 1 ? 's' : ''} still need review.\n\n` +
      `Flagged segments may contain low-confidence transcription or role disagreements.\n\n` +
      `Approve anyway?`
    )
    if (!confirmed) return
  }

  setApproving(true)
  await fetch(`${GATEWAY}/session/${sessionId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      provider_npi: meta.npi,
      patient_mrn: meta.mrn,
      visit_type: meta.visitType
    })
  })
  alert('Note approved. FHIR document generated.')
  navigate('/session')
}
```
**What it does:** Handles the final approval action:
1. Guards against approving without required metadata (NPI and MRN)
2. Warns the provider if any segments are still flagged for review
3. Sends the approval to the backend with provider and patient metadata
4. Alerts the user of success and navigates back to the start screen

**Why require NPI and MRN before approval?** NPI (National Provider Identifier) and MRN (Medical Record Number) are required to correctly attribute the note in the medical record system. Without them, the FHIR document could not be associated with the right provider and patient.

**Why `confirm()` for the flagged segment warning?** `confirm` is the browser's built-in blocking dialog. It is not ideal for polished UIs (it looks like an OS dialog) but it works well for a "human in the loop" guardrail — it forces the provider to explicitly acknowledge unresolved issues rather than accidentally skipping them.

**ELI5:** The `confirm` dialog is like the "Are you sure you want to delete?" pop-up before emptying the trash. The medical equivalent: "Are you sure you want to file a note that has low-confidence sections?" The provider must actively click "OK" to proceed.

**Best practice:** For production medical software, replace `alert` and `confirm` with proper modal dialogs in your UI. Native browser dialogs cannot be styled, may be blocked by popup blockers, and are inaccessible to screen readers.

---

### Lines 82–85 — Derived values
```tsx
const canApprove = meta.npi.trim() && meta.mrn.trim()
const flaggedCount = payload
  ? Object.values(payload.soap).flat().filter(s => s.confidence_flag || s.role_flag).length
  : 0
```
**What it does:**
- `canApprove` — a boolean-ish value that is truthy only if both NPI and MRN have been filled in (ignoring whitespace with `.trim()`)
- `flaggedCount` — counts all segments across all SOAP sections that have either a `confidence_flag` or `role_flag`

**Why `Object.values(payload.soap).flat()`?** `payload.soap` is an object like `{ S: [...], O: [...], A: [...], P: [...] }`. `Object.values` extracts all the arrays into a new array of arrays: `[[...], [...], [...], [...]]`. `.flat()` collapses that into a single array of all segments. Then `.filter` counts how many have flags.

**ELI5:** `.flat()` is like taking a set of envelopes (each containing multiple letters) and dumping all the letters onto one big table. After that, you can count all the letters in one pass instead of opening each envelope separately.

**Best practice:** Derived values like these are computed fresh on every render from the current state, which keeps them always in sync. Avoid storing derived values in `useState` — you would have to remember to keep them synchronized, which leads to bugs.

---

### Lines 152–181 — The 4-column SOAP grid
```tsx
<div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
  {SECTIONS.map(section => (
    <div key={section} ...>
      <h3>...</h3>
      {(payload.soap[section] ?? []).map(seg => (
        <SegmentCard
          key={seg.segment_id}
          segment={seg}
          providerId={PROVIDER_ID}
          onUpdate={fetchNote}
        />
      ))}
      <AmendmentPanel
        sessionId={sessionId!}
        providerId={PROVIDER_ID}
        onAdded={fetchNote}
      />
    </div>
  ))}
</div>
```
**What it does:** Renders four columns side by side using CSS Grid. Each column corresponds to one SOAP section. Inside each column it maps over the segments for that section, rendering a `SegmentCard` for each, followed by an `AmendmentPanel` for adding free-text amendments.

**Why `payload.soap[section] ?? []`?** The `??` operator (nullish coalescing) returns the right side if the left side is `null` or `undefined`. If the server returns a SOAP object that has no segments for section `'O'`, that key might be missing entirely. `?? []` ensures we always have an array to map over rather than crashing.

**Why pass `fetchNote` as `onUpdate` and `onAdded`?** This is the "lift state up" pattern. The child components (`SegmentCard`, `AmendmentPanel`) can modify server data but don't own the full note state — the parent does. By passing a callback, the parent gives children a way to say "I changed something, please refresh." The parent stays in control of the data.

**ELI5:** The parent (`SOAPReview`) is the library, and each `SegmentCard` is a librarian. When a librarian files a book in the wrong place and corrects it, they ring a bell (`onUpdate`). The library manager (`SOAPReview`) hears the bell and re-counts the inventory (`fetchNote`).

**Best practice:** Using `seg.segment_id` as the React `key` is better than using the array index because the list can change order after an edit or remap. Stable, unique IDs help React efficiently reconcile DOM updates.

---

### Lines 184–198 — Unclassified segments section
```tsx
{(payload.soap['UNCLASSIFIED'] ?? []).length > 0 && (
  <div style={{ marginTop: '16px', ... }}>
    <h3>UNCLASSIFIED — requires mapping</h3>
    {payload.soap['UNCLASSIFIED'].map(seg => (
      <SegmentCard ... />
    ))}
  </div>
)}
```
**What it does:** Shows a separate section below the four SOAP columns if the pipeline was unable to classify some segments. These segments need to be manually remapped by the provider using the `SegmentCard` remap feature.

**Why separate from the main grid?** `UNCLASSIFIED` is not a real SOAP category — it is a holding area for segments the AI could not confidently classify. Putting it outside the main four-column grid avoids confusing it with official clinical sections.

**Best practice:** A provider approving a note with many unclassified segments likely indicates a problem with the AI pipeline. A future improvement might be to count unclassified segments in the same flagged-count warning shown before approval.

---

### Lines 203–206 — The `inputStyle` object
```tsx
const inputStyle: React.CSSProperties = {
  background: '#1a1e2e', border: '1px solid #374151', color: '#e8eaf0',
  borderRadius: '6px', padding: '7px 12px', fontSize: '13px', outline: 'none'
}
```
**What it does:** Defines a reusable style object for the NPI, MRN, and visit-type inputs.

**Why type it as `React.CSSProperties`?** This type provides autocomplete for CSS property names in TypeScript and gives a compile-time error if you accidentally type `colour` instead of `color` or use an invalid value type.

**Best practice:** Define repeated style objects as constants outside the component function, not inside. Defining them inside the function body creates a new object on every render, which technically works but wastes memory. Constants outside the function are created once.

---

## Common Mistakes
1. **Updating `meta` state incorrectly** — `setMeta(m => ({ ...m, npi: e.target.value }))` uses the spread operator to copy all existing `meta` fields and only update `npi`. If you write `setMeta({ npi: e.target.value })`, you will erase the `mrn` and `visitType` fields. Always spread the previous state when updating a partial object.
2. **Using `Object.values(...).flat()` without knowing what `flat` does** — `.flat()` by default only flattens one level deep. If `payload.soap` had nested arrays, you would need `.flat(2)` or `.flat(Infinity)`. Here, the data is one level of nesting, so default `.flat()` is correct.
3. **Forgetting `!` on `sessionId!`** — TypeScript knows `sessionId` could be `undefined` (since `useParams` can return undefined for optional params). The `!` tells TypeScript "I know this is defined here." If your route is set up correctly, it will always be defined at this URL, but TypeScript cannot verify that statically.

## Key Concepts To Look Up
- `useCallback` — memoizing functions to avoid stale closures
- `Record<K, V>` — TypeScript utility type for dictionaries
- `Object.values` and `Array.prototype.flat` — transforming objects into arrays
- Nullish coalescing operator `??` — defaulting null/undefined values
- SOAP note format — Subjective, Objective, Assessment, Plan in clinical documentation
- FHIR — the healthcare data interoperability standard this note targets
- "Lift state up" pattern in React — passing callbacks from parent to child
- NPI (National Provider Identifier) and MRN (Medical Record Number)
