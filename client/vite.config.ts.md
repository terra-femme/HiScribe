# vite.config.ts — Vite Development Server Configuration

## What This File Is For
Configures Vite, the build tool and development server for the React client. Sets the port, enables the React plugin, and configures a proxy so the browser can talk to the Node gateway without CORS errors during development.

## How It Fits In The Project
This file is read by Vite when you run `npm run dev`. It affects the development experience only — the final production build is a static bundle that gets deployed separately.

---

## Line-by-Line Breakdown

### Lines 1–2 — Imports
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
```
**What it does:** Imports Vite's config helper and the official React plugin.
**Why `defineConfig`:** You could export a plain object, but `defineConfig()` gives you TypeScript autocomplete for all config options. Same output, better developer experience.
**Why the React plugin:** React uses JSX syntax (`<Component />`), which isn't valid JavaScript. The React plugin adds a Babel/SWC transform that converts JSX to regular JavaScript that browsers understand.
**ELI5:** `defineConfig` is the form you fill out. The React plugin is the JSX translator that makes React code work in browsers.

### Lines 4–15 — Config object
```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/session': 'http://localhost:3000',
      '/health': 'http://localhost:3000'
    }
  }
})
```

**`plugins: [react()]`**
**What it does:** Activates the React plugin for JSX transformation and Fast Refresh.
**Why Fast Refresh:** When you edit a React component, Vite updates only that component in the browser without a full page reload. Your app state is preserved. This is the feature that makes React development feel instant.
**Best practice:** Always include the React plugin. Without it, Vite treats `.tsx` files as plain TypeScript — JSX will cause parse errors.

**`server.port: 5173`**
**What it does:** Runs the dev server on port 5173.
**Why 5173:** Vite's default. It's just a convention — you can change it to any available port. The `vite.config.ts` in the proxy section assumes the client is on 5173 and the gateway is on 3000.
**Best practice:** Document your port assignments somewhere (the README does this). Three services on three ports is manageable; ten services requires a port map.

**`server.proxy`**
**What it does:** Forwards requests starting with `/session` or `/health` from `localhost:5173` to `localhost:3000`.
**Why this is needed:** The browser sends requests to `http://localhost:5173` (where it loaded the page from). If the gateway is on port 3000, the browser blocks cross-origin requests. The proxy makes the gateway appear to be on the same origin as the client — the browser sees everything as coming from 5173.
**ELI5:** The browser is suspicious of anyone from a different address. The proxy is a middleman that receives the request on the right address (5173) and secretly forwards it to the gateway (3000). The browser never knows the difference.
**Why only `/session` and `/health`:** Only API routes need proxying. Static files (JS, CSS, images) are served directly by Vite. You only proxy the routes your code actually calls.
**Best practice:** In production, this proxy isn't needed — you'd configure nginx or a cloud load balancer to route `/api/*` to the backend and everything else to the static files. The Vite proxy is a dev-only convenience.

---

## Common Mistakes
1. Not including `/session` in the proxy — every API call fails with a CORS error and you spend an hour debugging the wrong thing.
2. Forgetting `react()` in plugins — JSX stops working and you get cryptic parse errors.
3. Hardcoding `http://localhost:3000` in fetch calls without the proxy — works locally but breaks in any other environment.

## Key Concepts To Look Up
- Vite — what it is and why it replaced Create React App
- Fast Refresh (HMR) — how hot module replacement works
- CORS — why the proxy exists and how it solves the same-origin problem
- Development proxy vs production reverse proxy (nginx/load balancer)
- JSX transform — how `<Component />` becomes `React.createElement(Component, null)`
