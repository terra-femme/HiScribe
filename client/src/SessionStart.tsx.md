# SessionStart.tsx — The landing screen that creates a new patient session on the server

## What This File Is For
This is the first screen a provider sees. It shows a single button labeled "Start Session." When clicked, it sends an HTTP POST request to the backend to create a new session record, then navigates the user to the live recording screen. It also handles the loading and error states while the request is in flight.

## How It Fits In The Project
`SessionStart` is rendered by `App.tsx` when the URL is `/session`. It calls the backend gateway at `POST /session/start`. On success it navigates to `LiveCapture` by pushing a new URL (`/session/:id/capture`) into the browser history.

## Line-by-Line Breakdown

### Lines 1–2 — Imports
```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
```
**What it does:** Imports two hooks. `useState` is a React built-in for tracking values that can change over time (like whether a button is loading). `useNavigate` is a React Router hook that gives access to the navigation function so the component can programmatically change the URL.

**Why:** Both are hooks — functions whose names start with `use` that can only be called inside React components or other hooks. They follow special rules that React uses to manage state and side effects.

**ELI5:** `useState` is like a sticky note on your fridge that the app can read and update. `useNavigate` is like a remote control for the browser's address bar.

**Best practice:** Import only what you need from each package. Unused imports add noise and can slow down bundlers in large projects.

---

### Line 4 — GATEWAY constant
```tsx
const GATEWAY = 'http://localhost:3000'
```
**What it does:** Declares the base URL for the backend API as a module-level constant.

**Why:** Hardcoding `'http://localhost:3000'` directly in every `fetch` call would mean updating many lines if the URL ever changes. Defining it once at the top means you only change one line.

**ELI5:** This is like writing your doctor's office phone number on the fridge instead of memorizing it. One place to look it up, and easy to change when they move offices.

**Best practice:** For real production apps, use environment variables (e.g., `import.meta.env.VITE_GATEWAY`) rather than hardcoded localhost URLs. Vite reads `.env` files and injects these values at build time, so you can have different URLs for development and production without changing source code.

---

### Lines 7–9 — State and navigation hook
```tsx
const [loading, setLoading] = useState(false)
const [error, setError] = useState('')
const navigate = useNavigate()
```
**What it does:**
- `loading` — a boolean that tracks whether the "start session" request is currently in flight. Starts as `false`.
- `error` — a string that stores an error message if the request fails. Starts as empty string `''`.
- `navigate` — a function returned by `useNavigate` that changes the current URL.

**Why:** These three values represent the entire state of this simple screen. When `loading` is `true`, the button disables and shows "Starting..." — this prevents double-submissions. When `error` is non-empty, a red message appears.

**ELI5:** `useState(false)` is like a light switch that starts in the "off" position. React is watching that switch. When you flip it to `true` (by calling `setLoading(true)`), React automatically redraws the button to show the loading state.

**Best practice:** Always pair loading state with error state when making async requests. Users need feedback for both "please wait" and "something went wrong." Never leave the UI stuck in a loading state if the request fails — always `setLoading(false)` in your error path.

---

### Lines 11–23 — The `startSession` async function
```tsx
async function startSession() {
  setLoading(true)
  setError('')
  try {
    const res = await fetch(`${GATEWAY}/session/start`, { method: 'POST' })
    if (!res.ok) throw new Error('Failed to create session')
    const { session_id } = await res.json()
    navigate(`/session/${session_id}/capture`)
  } catch (e: any) {
    setError(e.message)
    setLoading(false)
  }
}
```
**What it does:** This is the core logic of the component. Step by step:
1. Sets `loading` to `true` and clears any previous error.
2. Sends an HTTP POST to `/session/start` using `fetch`.
3. Checks if the response is a success (status 200–299). If not, throws an error.
4. Parses the response JSON and extracts the `session_id` field.
5. Uses `navigate` to send the user to the capture screen with that ID in the URL.
6. If anything goes wrong, catches the error, stores its message in `error` state, and re-enables the button.

**Why:** `async/await` makes this code read top-to-bottom like synchronous code, even though HTTP requests take time. The `try/catch` block is essential — without it, a failed network request would silently do nothing and the user would be stuck on a loading button forever.

**ELI5:** Imagine you're ordering food by phone. You pick up the phone (`setLoading(true)`), dial the restaurant (`fetch`), wait for someone to answer (`await`), give your order (`method: 'POST'`), they say "your order number is 42" (`session_id`), and you hang up and walk to the pickup counter (`navigate`). If the restaurant's phone is disconnected (`catch`), you leave a note to yourself about what went wrong (`setError`).

**Best practice:** Notice that `setLoading(false)` is only called in the `catch` block, not after a successful navigation. This is intentional — once `navigate` fires, this component unmounts, so there is no point in resetting loading state. Setting state on an unmounted component can cause a React warning.

---

### Lines 42–44 — Conditional error display
```tsx
{error && (
  <p style={{ color: '#f87171', fontSize: '13px', marginBottom: '16px' }}>{error}</p>
)}
```
**What it does:** Shows the error message in red only when `error` is a non-empty string. When `error` is `''` (falsy), nothing renders.

**Why:** The `&&` short-circuit pattern in JSX is the standard way to conditionally render content. In JavaScript, `false && <something>` evaluates to `false`, which React renders as nothing. `'some text' && <something>` evaluates to `<something>` and React renders it.

**ELI5:** Think of it like an AND gate in electronics: both sides must be true for the output to be on. If `error` is empty (falsy), the gate closes and nothing shows. If `error` has text (truthy), the gate opens and the paragraph appears.

**Best practice:** The `&&` pattern works great for simple show/hide. For more complex "show A or show B" scenarios, use a ternary `condition ? <A /> : <B />` instead.

---

### Lines 46–57 — The start button
```tsx
<button
  onClick={startSession}
  disabled={loading}
  style={{
    background: loading ? '#374151' : '#2563eb',
    ...
    cursor: loading ? 'not-allowed' : 'pointer',
  }}
>
  {loading ? 'Starting...' : '● Start Session'}
</button>
```
**What it does:** Renders a button that:
- Calls `startSession` when clicked
- Is disabled (non-interactive) while `loading` is `true`
- Visually changes color and cursor to communicate its state
- Shows different text labels based on `loading`

**Why:** `disabled={loading}` prevents double-clicks from firing multiple POST requests. The style changes and label change give the user clear feedback that their click was received and the app is working.

**ELI5:** It is like a submit button on a physical kiosk that lights up gray and shows "Processing..." after you tap it, so you don't accidentally tap it again. The `disabled` prop is the hardware lock; the style change is the visual indicator.

**Best practice:** Always disable interactive elements during async operations. A user on a slow connection who clicks a button twice can accidentally create duplicate records. This is especially important for medical data.

---

## Common Mistakes
1. **Not checking `res.ok`** — `fetch` does not throw an error for HTTP 400 or 500 responses. It only throws if the network is completely unavailable. If you forget the `if (!res.ok) throw` line, a 500 error from the server will appear to succeed, and `res.json()` may fail or return unexpected data.
2. **Calling `setLoading(false)` after `navigate`** — The component is already gone after navigation. React will log a warning: "Can't perform a React state update on an unmounted component." Only reset loading state in the error path.
3. **Forgetting `e: any` on the catch parameter** — TypeScript types caught errors as `unknown` by default (a sound choice, since anything can be thrown). If you write `catch (e)` and then access `e.message`, TypeScript will complain. Typing it as `any` is a quick fix; the clean approach is to use `e instanceof Error ? e.message : 'Unknown error'`.

## Key Concepts To Look Up
- `useState` — React's state hook, the basics
- `async/await` in JavaScript — how asynchronous code works
- The Fetch API — `fetch`, `Response.ok`, `Response.json()`
- `useNavigate` — programmatic navigation in React Router v6
- JavaScript short-circuit evaluation (`&&`) in JSX
- `try/catch/finally` — structured error handling
