# main.tsx — The entry point that boots the React app and wires up routing

## What This File Is For
This is the very first file that runs when the browser loads the app. It grabs the single `<div id="root">` element that lives in `index.html`, and mounts the entire React application inside it. Think of it as the "ignition switch" — nothing in the app exists until this file runs.

It also wraps the whole app in two important providers: one that enables URL-based navigation, and one that helps catch bugs during development.

## How It Fits In The Project
This file is the root of the component tree. It is called by Vite's build system automatically (configured as the entry point). It calls `App`, which in turn calls `SessionStart`, `LiveCapture`, and `SOAPReview` depending on the URL. Nothing calls `main.tsx` — it is the starting point.

## Line-by-Line Breakdown

### Lines 1–2 — Importing React and ReactDOM
```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
```
**What it does:** Pulls in the two core React libraries. `React` provides the JSX system (the ability to write HTML-like syntax in JavaScript). `ReactDOM` is the part of React that knows how to attach your component tree to a real browser page.

**Why:** React is split into two packages on purpose. `react` contains the logic for components, hooks, and state. `react-dom` contains the browser-specific rendering code. This separation means React can also render to mobile screens (React Native) or PDFs without changing the core logic.

**ELI5:** Imagine React is a blueprint system. `react` is the set of drafting tools you use to draw blueprints. `react-dom` is the construction crew that actually builds the house from the blueprint into the browser. You need both.

**Best practice:** Always import `React` in files that use JSX in older codebases. In modern React (17+) with the right compiler settings this import is often optional, but it never hurts to include it explicitly.

---

### Line 3 — Importing BrowserRouter
```tsx
import { BrowserRouter } from 'react-router-dom'
```
**What it does:** Imports the routing provider from React Router. `BrowserRouter` listens to the browser's URL bar and makes the current URL available to every component in the tree.

**Why:** React itself has no concept of URLs or pages. React Router adds this capability. `BrowserRouter` specifically uses the browser's History API so URLs look clean (e.g., `/session/abc/capture`) rather than using hash-based URLs like `/#/session/abc/capture`.

**ELI5:** The URL bar in your browser is like an address on a building. `BrowserRouter` is the postal system — it reads the address and makes sure the right component (room) appears.

**Best practice:** Wrap your entire app in `BrowserRouter` exactly once, at the top level. Never nest two `BrowserRouter`s — this causes bugs where navigation stops working inside the inner one.

---

### Line 4 — Importing App
```tsx
import App from './App'
```
**What it does:** Imports the root `App` component from `App.tsx` in the same directory.

**Why:** `main.tsx` is kept deliberately minimal — it only handles the "bootstrap" concern of attaching React to the DOM. All actual routing and UI lives in `App`.

**ELI5:** `main.tsx` is the power switch. `App` is the actual machine. The power switch doesn't need to know what the machine does — it just turns it on.

**Best practice:** Keep `main.tsx` as lean as possible. Only put global providers here (routing, themes, auth context). Business logic and UI belong in `App` and its children.

---

### Lines 6–12 — Mounting the App
```tsx
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
```
**What it does:** This is the single statement that makes everything happen. It:
1. Finds the `<div id="root">` element in `public/index.html`
2. Creates a React "root" attached to that element
3. Renders the component tree inside it

**Why:** The `!` after `getElementById('root')` is a TypeScript non-null assertion. It tells TypeScript "I promise this element exists — don't warn me that it might be null." If you removed it, TypeScript would show an error because `getElementById` can technically return `null`.

**ELI5:** The `index.html` file is an empty stage. `createRoot` sets up the stage lighting and sound system. `render` sends out the actors (components) to perform.

**Best practice:** Always use `createRoot` (React 18+) rather than the older `ReactDOM.render`. The older API is deprecated. If you see a project still using `ReactDOM.render(...)`, it is running an older version of React.

---

### `<React.StrictMode>` — Development safety wrapper
```tsx
<React.StrictMode>
  ...
</React.StrictMode>
```
**What it does:** Activates extra checks and warnings during development. Notably, it intentionally runs certain lifecycle functions twice to help you find bugs caused by side effects in the wrong places.

**Why:** `StrictMode` catches common mistakes early — like running an API call inside a render function instead of inside `useEffect`. It has zero effect in production builds; it is purely a development tool.

**ELI5:** Imagine a spell-checker that highlights suspicious sentences. `StrictMode` is the spell-checker for your React logic. It does not change what gets published — it just helps you write better code while you work.

**Best practice:** Always leave `StrictMode` on during development. If removing it "fixes" a bug, that means the bug was always there — `StrictMode` was just making it visible. Fix the real bug instead of removing `StrictMode`.

---

## Common Mistakes
1. **Forgetting `BrowserRouter`** — If you try to use `useNavigate` or `<Route>` without a `BrowserRouter` ancestor, React Router throws a cryptic error saying "useNavigate() may be used only in the context of a Router component." The fix is always to make sure `BrowserRouter` wraps the whole app here in `main.tsx`.
2. **Using `document.getElementById('root')` without `!`** — TypeScript will flag this as possibly null. If you suppress the warning by removing the `!`, do it intentionally and understand why. The better fix is to confirm your `index.html` actually has `<div id="root"></div>`.
3. **Putting component logic inside `main.tsx`** — This file should stay minimal. Beginners sometimes start adding `useState` or routes here, which makes the code hard to follow. Keep it as a clean bootstrap file.

## Key Concepts To Look Up
- `ReactDOM.createRoot` — React 18 concurrent rendering entry point
- `React.StrictMode` — what double-invocation means and why it matters
- `BrowserRouter` vs `HashRouter` — when to use each
- TypeScript non-null assertion operator (`!`)
- Vite entry points — how Vite decides which file to run first
