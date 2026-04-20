# AmendmentPanel.tsx — Add Clinical Amendments Per SOAP Section

## What This File Is For
Renders a collapsed "+ Add amendment" button at the bottom of each SOAP section. When clicked, it expands to a form where the provider can enter new clinical information that wasn't captured in the audio recording. Submitting creates an `amendment_added` audit event — legally distinct from editing a segment.

## How It Fits In The Project
`SOAPReview.tsx` renders one `AmendmentPanel` at the bottom of each SOAP column. It calls `onAdded` when an amendment is saved, which triggers the parent to re-fetch and display the new amendment.

---

## Line-by-Line Breakdown

### Lines 1–9 — Imports and constants
```typescript
import { useState } from 'react'
const SOAP_LABELS: Record<string, string> = { S: 'Subjective', O: 'Objective', A: 'Assessment', P: 'Plan' }
```
**What it does:** One hook import and the section label map.
**Why only `useState`:** This component has no side effects, no subscriptions, no external data fetching on mount. It only manages its own open/closed state and form field values.

### Lines 11–17 — Props
```typescript
type Props = {
  sessionId: string
  providerId: string
  onAdded: () => void
}
```
**What it does:** The panel needs to know which session and provider this is for, and what to call when done.
**Why not pass `soapSection` as a prop:** Each panel renders inside a specific section column in `SOAPReview` — but the provider can choose any section from the dropdown. The section defaults to the column it's in but is user-selectable.

### Lines 19–23 — Component state
```typescript
const [open, setOpen] = useState(false)
const [content, setContent] = useState('')
const [section, setSection] = useState('S')
const [saving, setSaving] = useState(false)
```
**What it does:** Four state variables: whether the form is open, the text content, selected section, and whether a save is in progress.
**Why `saving` state:** When the form is submitted, you disable the button and show "Saving..." to prevent duplicate submissions and give feedback that the network request is in progress.
**ELI5:** The panel tracks: "Am I open or closed? What did the provider type? Which section are they adding to? Is the save currently happening?"
**Best practice:** Always use a loading/saving state for any async operation triggered by user interaction. Never leave a button clickable while its action is in flight.

### Lines 25–37 — submit function
```typescript
async function submit() {
  if (!content.trim()) return
  setSaving(true)
  await fetch(`${GATEWAY}/session/${sessionId}/amendment`, {
    method: 'POST',
    body: JSON.stringify({ content, soap_section: section, provider_id: providerId })
  })
  setContent('')
  setSection('S')
  setOpen(false)
  setSaving(false)
  onAdded()
}
```
**What it does:** Validates, sends the amendment, resets the form, closes the panel, and signals the parent.
**Why `content.trim()`:** Prevents saving empty or whitespace-only amendments. `.trim()` removes leading/trailing whitespace before checking.
**Why reset all state after save:** The panel should be ready for a new amendment immediately. If you leave the content in the field, the provider might accidentally submit the same thing twice.
**Why `setSaving(false)` after `onAdded()`:** `onAdded()` re-fetches data. Keeping `saving: true` until after the re-fetch prevents any brief flash where the panel appears ready before the new data arrives.
**ELI5:** Write the note, file it, erase the whiteboard, close the cabinet drawer, and tell the boss it's done.
**Best practice:** Always reset form state after a successful submit. State left in a form after save is a common source of accidental duplicate submissions.

### Lines 39–52 — Collapsed state (button only)
```typescript
if (!open) {
  return (
    <button onClick={() => setOpen(true)} style={{ border: '1px dashed ...', ... }}>
      + Add amendment
    </button>
  )
}
```
**What it does:** When closed, renders just a subtle dashed button.
**Why dashed border:** The visual design choice signals "optional action" — dashed borders conventionally indicate secondary or additive actions. Solid borders are for primary actions.
**ELI5:** A door that's usually closed. The dashed outline says "you can open me, but you don't have to."
**Best practice:** Early returns for different component states (collapsed vs expanded) are cleaner than wrapping everything in a conditional. The component "bails out" early when collapsed.

### Lines 54–96 — Expanded form
```typescript
<div style={{ border: '1px solid #854d0e', ... }}>
  <span style={{ color: '#f59e0b' }}>[AMENDMENT]</span>
  <select value={section} onChange={e => setSection(e.target.value)}>...</select>
  <textarea value={content} onChange={e => setContent(e.target.value)} />
  <button disabled={saving || !content.trim()}>Save amendment</button>
</div>
```
**What it does:** Renders the amendment form with a warning-colored border and the `[AMENDMENT]` label.
**Why the amber/orange border:** Visual distinction matters. An amendment is legally different from the transcript — it's new information added after the fact, not a correction. The amber color and `[AMENDMENT]` label reinforce this at a glance.
**Why `disabled={saving || !content.trim()}`:** The save button is disabled in two cases: while saving (prevents double-submit) or if the content is empty/whitespace (prevents empty amendments).
**ELI5:** The form is orange to say "hey, this is different from editing — you're adding something new." The save button is grayed out until you've actually written something.
**Best practice:** Always show `[AMENDMENT]` visually in the UI and in the stored data. Providers need to quickly distinguish between "what was said" and "what I added afterward."

---

## Common Mistakes
1. Not resetting `content` and `section` after saving — the form remembers the last amendment, making accidental duplicates easy.
2. Not disabling the save button during the `await` — rapid clicking submits multiple amendments.
3. Using the same visual style for amendments and edits — they're legally distinct acts. Visual distinction reinforces this.

## Key Concepts To Look Up
- Controlled form components in React (`value` + `onChange`)
- Early return pattern for conditional rendering
- `disabled` attribute on buttons — when and why
- Edit vs amendment in clinical documentation law
- `String.trim()` — why it's important for form validation
