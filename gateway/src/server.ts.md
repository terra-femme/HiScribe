# server.ts — The entry point that boots the HTTP server and wires all routes together

## What This File Is For
This is the main startup file for the HiScribe gateway service. It creates a web server, turns on the features that server needs (like WebSocket support and CORS), registers all the URL routes defined in other files, and then starts listening for incoming network requests. Think of it as the front door of the backend — nothing works until this file runs.

## How It Fits In The Project
This file sits at the very top of the gateway service. It imports routes from `routes/session.ts` and `routes/note.ts`, which in turn use adapters and the database client. Nothing calls this file — it is the starting point. You run it with a command like `ts-node src/server.ts` or `node dist/server.js`. Everything else in the project is downstream of it.

---

## Line-by-Line Breakdown

### Lines 1–7 — Imports

```typescript
import Fastify from 'fastify'
import fastifyWebsocket from '@fastify/websocket'
import fastifyCors from '@fastify/cors'
import dotenv from 'dotenv'
import path from 'path'
import { sessionRoutes } from './routes/session'
import { noteRoutes } from './routes/note'
```

**What it does:** Pulls in every external library and internal module that this file needs before it can do any work.

**Why:** Node.js and TypeScript use a module system — code is split across files and you must explicitly declare what you want to use. `Fastify` is the web framework, `fastifyWebsocket` and `fastifyCors` are optional plugins that extend it, `dotenv` reads environment variables from a file, `path` helps build cross-platform file paths, and the two route imports bring in the URL handlers.

**ELI5:** Imagine you're setting up a kitchen. Before you cook, you lay out your tools: the cutting board, the pots, the recipe cards. Imports are you laying out your tools before the work begins.

**Best practice:** Always import only what you need. Importing everything from a library (like `import * as Fastify`) when you only need one thing wastes memory and makes code harder to read.

---

### Line 9 — Load environment variables

```typescript
dotenv.config({ path: path.resolve(__dirname, '../../.env') })
```

**What it does:** Reads the `.env` file (two directories up from this file) and loads its contents into `process.env` so any code in the project can read them as `process.env.SOME_KEY`.

**Why:** Secrets like API keys and port numbers should never be hardcoded in source code. A `.env` file keeps them separate and out of version control (via `.gitignore`). `path.resolve(__dirname, '../../.env')` builds an absolute path so the file is found correctly no matter where the process is run from.

**ELI5:** Think of `.env` as a locked box of settings. This line opens the box and puts all the settings on the table so everyone in the kitchen can see them.

**Best practice:** Call `dotenv.config()` as early as possible — before any other code that reads `process.env`. If you call it after, other modules might run first and find the variables missing.

---

### Line 11 — Create the Fastify app instance

```typescript
const app = Fastify({ logger: true })
```

**What it does:** Creates the web server object. `{ logger: true }` turns on built-in request logging so every HTTP request and error is printed to the console automatically.

**Why:** `app` is the central object everything else attaches to — routes, plugins, and error handlers all go on `app`. Enabling the logger from the start means you get free visibility into what the server is doing without writing any extra log code.

**ELI5:** This is like hiring a manager for the kitchen. The `app` object is that manager. They keep track of everything happening and log it all in a notebook (`logger: true`).

**Best practice:** In production you'd typically pass a structured logger like `pino` with `logger: { level: 'info' }` for JSON-formatted logs. The default `logger: true` is fine for development.

---

### Lines 13–16 — Register plugins and routes

```typescript
app.register(fastifyCors, { origin: true })
app.register(fastifyWebsocket)
app.register(sessionRoutes)
app.register(noteRoutes)
```

**What it does:** Attaches four pieces of functionality to the server. CORS allows browsers on different domains to talk to this server. The WebSocket plugin enables real-time bidirectional connections. `sessionRoutes` and `noteRoutes` define all the actual URL endpoints.

**Why:** Fastify uses a plugin architecture — features are added with `app.register()` rather than being built-in. This keeps the core fast and lets you add only what you need. `{ origin: true }` on CORS means any origin is allowed, which is suitable during development.

**ELI5:** If `app` is your kitchen manager, `register` is handing them new tools and recipe books. Each `register` call says "here's something new you need to know how to do."

**Best practice:** In production, replace `origin: true` with a specific list of allowed origins (e.g., `origin: 'https://yourapp.com'`) to prevent unauthorized websites from calling your API.

---

### Lines 18–22 — Health check route

```typescript
app.get('/health', async () => ({
  status: 'ok',
  service: 'hiscribe-gateway',
  timestamp: new Date().toISOString()
}))
```

**What it does:** Registers a GET endpoint at `/health` that returns a JSON object confirming the server is running. The response includes the service name and the current time.

**Why:** Health check endpoints are a standard practice for services running in containers or cloud environments. Load balancers and monitoring tools ping `/health` to know whether the service is alive. `new Date().toISOString()` gives a machine-readable timestamp like `2026-03-30T12:00:00.000Z`.

**ELI5:** It's like a "pulse check" — someone knocks on the door and asks "are you alive?" and the server answers "yes, and here's what time it is."

**Best practice:** Always include a health check in any backend service. More advanced versions might also check whether the database is reachable before returning `status: 'ok'`.

---

### Line 24 — Read the port number

```typescript
const port = Number(process.env.GATEWAY_PORT) || 3000
```

**What it does:** Reads the `GATEWAY_PORT` variable from the environment and converts it from a string to a number. If the variable is not set or is empty, it falls back to port `3000`.

**Why:** Environment variables are always strings. Network ports must be numbers. `Number(...)` does the conversion. The `|| 3000` fallback means the server still runs locally even if you forgot to set the variable.

**ELI5:** It's like asking "what door number should we use?" If nobody tells you, you default to door #3000.

**Best practice:** Be careful with `Number(undefined)` — it returns `NaN`, which is falsy, so the `|| 3000` fallback handles it correctly here. For stricter validation, you might use `parseInt` with a radix: `parseInt(process.env.GATEWAY_PORT ?? '', 10) || 3000`.

---

### Lines 26–29 — Start listening

```typescript
app.listen({ port, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1) }
  app.log.info(`HiScribe gateway running on port ${port}`)
})
```

**What it does:** Tells the server to start accepting incoming network connections on the given port. `host: '0.0.0.0'` means accept connections from any network interface (not just localhost). The callback runs once the server is up, or immediately if there was a startup error.

**Why:** Without calling `listen`, the server object exists in memory but no one can reach it. `host: '0.0.0.0'` is required when running inside Docker or on a server — `localhost` would only accept connections from the same machine. If startup fails (e.g., the port is already in use), `process.exit(1)` stops the process with an error code so the container orchestrator knows to restart it.

**ELI5:** This is like opening the restaurant for business. Before this line, everything is set up but the door is locked. `listen` unlocks the door. If something goes wrong during opening, you call it a night (`process.exit(1)`).

**Best practice:** Always handle the error in `app.listen`. Ignoring it means your server silently fails to start and you won't know why.

---

## Common Mistakes

1. **Forgetting `host: '0.0.0.0'` when running in Docker.** By default, Fastify listens on `127.0.0.1` (localhost only), which is unreachable from outside a container. You'll see the server start successfully but get "connection refused" from everywhere else.

2. **Calling `dotenv.config()` after importing route files.** If `routes/session.ts` reads `process.env.GLADIA_API_KEY` at import time before `dotenv.config()` runs, the value will be `undefined`. Always load environment variables first.

3. **Using `{ origin: true }` in production.** This allows any website to call your API. In production, lock it down to specific trusted origins.

---

## Key Concepts To Look Up

- **Fastify** — a Node.js web framework focused on performance and a plugin architecture
- **CORS (Cross-Origin Resource Sharing)** — browser security policy that controls which websites can call your API
- **WebSocket** — a protocol for persistent two-way connections between client and server
- **`process.env`** — the Node.js object that holds all environment variables
- **`dotenv`** — a library that reads a `.env` file and populates `process.env`
- **`__dirname`** — a built-in Node.js variable holding the absolute path to the current file's directory
- **`path.resolve`** — builds an absolute file path from path segments
- **`process.exit(1)`** — terminates the Node.js process with a non-zero exit code, signaling failure
