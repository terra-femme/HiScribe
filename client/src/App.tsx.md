# App.tsx — The top-level shell that defines the page layout and maps URLs to components

## What This File Is For
`App.tsx` is the root component of the application. It does two things: it renders the persistent header bar that always appears at the top of every page, and it defines the routing table that decides which component to show based on the URL. Every other screen in the app is a child of `App`.

## How It Fits In The Project
`App` is rendered by `main.tsx` and wraps everything else. It imports and routes to three page-level components: `SessionStart`, `LiveCapture`, and `SOAPReview`. `App` itself is never called by any component — it sits at the top of the tree.

## Line-by-Line Breakdown

### Lines 1–4 — Imports
```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import SessionStart from './SessionStart'
import LiveCapture from './LiveCapture'
import SOAPReview from './SOAPReview'
```
**What it does:** Imports three React Router components (`Routes`, `Route`, `Navigate`) and the three page components this app contains.

**Why:**
- `Routes` is a container that looks at the current URL and renders only the matching `Route`.
- `Route` pairs a URL pattern with a component to render.
- `Navigate` programmatically redirects the browser to a different URL without any user interaction.

**ELI5:** `Routes` is like a train station dispatcher. You give it a list of tracks (`Route`s). When a train (URL) arrives, it reads the destination and sends the train to the right platform (component).

**Best practice:** Always wrap your `Route` components in `Routes`. In React Router v6+, `Routes` replaced the old `Switch`. If you see `Switch` in example code online, that is React Router v5 syntax — the API changed significantly.

---

### Lines 6–26 — The App component
```tsx
export default function App() {
  return (
    <div style={{ minHeight: '100vh', padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
      ...
    </div>
  )
}
```
**What it does:** Declares `App` as a React function component and exports it as the default export so `main.tsx` can import it. The outer `<div>` provides the global page container: full viewport height, padding on all sides, capped at 1400px wide, and centered horizontally with `margin: '0 auto'`.

**Why:** `export default` means when someone writes `import App from './App'`, they get this function. The inline styles create the outer shell that every page shares.

**ELI5:** This is the picture frame. Every page painting (SessionStart, LiveCapture, SOAPReview) gets hung inside this same frame. The frame never changes — only the painting swaps.

**Best practice:** In a larger project you would use a CSS file or a styling library (Tailwind, styled-components) instead of inline `style` objects. Inline styles are fine for prototypes but harder to override and maintain at scale.

---

### Lines 9–16 — The persistent header
```tsx
<header style={{ marginBottom: '32px', borderBottom: '1px solid #2a2d3a', paddingBottom: '16px' }}>
  <h1 style={{ fontSize: '20px', fontWeight: 600, letterSpacing: '0.5px', color: '#7eb8f7' }}>
    HiScribe
  </h1>
  <p style={{ fontSize: '13px', color: '#6b7280', marginTop: '4px' }}>
    Ambient Clinical Scribe — Human in the Loop
  </p>
</header>
```
**What it does:** Renders the app title and tagline at the top of every page. Because this `<header>` is outside the `<Routes>`, it is always visible regardless of which route is active.

**Why:** Putting shared UI (header, footer, nav) outside `<Routes>` is the standard pattern in React Router. Only the content that changes per-page goes inside `<Routes>`.

**ELI5:** Imagine a book. The header bar is the page number and chapter title printed at the top of every page. The `<Routes>` section is the actual story content that changes on each page.

**Best practice:** Consider extracting the header into its own `Header.tsx` component once it grows beyond a few lines. This makes it easier to add things like a user profile menu or navigation links later.

---

### Lines 18–23 — The route table
```tsx
<Routes>
  <Route path="/" element={<Navigate to="/session" replace />} />
  <Route path="/session" element={<SessionStart />} />
  <Route path="/session/:id/capture" element={<LiveCapture />} />
  <Route path="/session/:id/review" element={<SOAPReview />} />
</Routes>
```
**What it does:** Defines four URL patterns:
- `/` — immediately redirects to `/session`
- `/session` — shows the session start screen
- `/session/:id/capture` — shows the live recording screen (`:id` is a URL parameter that holds the session ID)
- `/session/:id/review` — shows the SOAP note review screen

**Why:** The redirect on `/` ensures users always land on something useful rather than a blank page. The `:id` in the path is a dynamic segment — React Router captures whatever is in that position and makes it available to the component via `useParams()`.

**ELI5:** `:id` in a route is like a blank on a form: `/session/___/capture`. Whatever fills that blank — like `/session/abc123/capture` — gets stored as `id` and the component can read it. It is how the app knows which patient session is currently open.

**Best practice:** Use the `replace` prop on `<Navigate>` for redirect routes. Without it, the redirect adds an entry to the browser history, meaning the user would have to press Back twice to leave. With `replace`, the redirect swaps the history entry instead.

---

## Common Mistakes
1. **Forgetting `:id` is a string, not a number** — When you read `useParams()` in `LiveCapture` or `SOAPReview`, the `id` will always be a string. If your API expects a number, you must convert it explicitly with `parseInt` or `Number()`.
2. **Putting UI that should be per-page inside the header** — The header lives outside `<Routes>`, so anything you put there renders on every single page. If you accidentally put page-specific content there, it will show up everywhere.
3. **Mixing React Router v5 and v6 syntax** — If you look up React Router on older blog posts, you may see `<Switch>`, `<Redirect>`, and `component={...}` syntax. None of that works in v6. Always look for docs that specify "React Router v6."

## Key Concepts To Look Up
- React Router v6 — `Routes`, `Route`, `Navigate`
- URL parameters with `:param` syntax
- `export default` vs named exports in JavaScript modules
- The CSS `margin: 0 auto` centering technique
- React component tree and the concept of "parent" vs "child" components
