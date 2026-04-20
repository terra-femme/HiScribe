/**
 * gateway/src/server.ts
 *
 * Changes applied:
 *  - Startup validation: logs auth mode and required env vars on boot
 *  - Request ID added to every request for correlation in logs
 */

import Fastify from 'fastify'
import fastifyWebsocket from '@fastify/websocket'
import fastifyCors from '@fastify/cors'
import dotenv from 'dotenv'
import path from 'path'
import { sessionRoutes } from './routes/session'
import { noteRoutes } from './routes/note'
import { enrollmentRoutes } from './routes/enrollment'

dotenv.config({ path: path.resolve(__dirname, '../../.env') })

// ─── Startup validation ───────────────────────────────────────────────────────

const DEV_MODE = process.env.DEV_MODE === 'true'
const REQUIRED_VARS = ['GLADIA_API_KEY', 'JWT_SECRET', 'PIPELINE_URL']

console.log('[server] ─── HiScribe Gateway startup ───────────────────────────')
console.log(`[server] Auth mode: ${DEV_MODE ? 'DEV (bypassed — set DEV_MODE=false for production)' : 'JWT enforced'}`)

const missing: string[] = []
for (const v of REQUIRED_VARS) {
  if (!process.env[v]) {
    if (v === 'JWT_SECRET' && DEV_MODE) {
      console.warn(`[server] ${v} not set — OK in DEV_MODE, required in production`)
    } else {
      missing.push(v)
      console.error(`[server] MISSING env var: ${v}`)
    }
  } else {
    console.log(`[server] ${v}: set`)
  }
}

if (missing.length > 0 && !DEV_MODE) {
  console.error(`[server] FATAL: Missing required env vars: ${missing.join(', ')} — exiting`)
  process.exit(1)
}

// ─── Fastify instance ─────────────────────────────────────────────────────────

const app = Fastify({
  logger: true,
  genReqId: () => crypto.randomUUID()  // correlation ID on every request
})

app.register(fastifyCors, {
  origin: process.env.CLIENT_URL || 'http://localhost:5173'
})
app.register(fastifyWebsocket)
app.register(sessionRoutes)
app.register(noteRoutes)
app.register(enrollmentRoutes)

app.get('/health', async () => ({
  status: 'ok',
  service: 'hiscribe-gateway',
  timestamp: new Date().toISOString(),
  auth: DEV_MODE ? 'dev-mode' : 'jwt-enforced'
}))

// ─── Listen ───────────────────────────────────────────────────────────────────

const port = Number(process.env.GATEWAY_PORT) || 3000

app.listen({ port, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1) }
  app.log.info(`[server] HiScribe gateway running on port ${port}`)
  console.log('[server] ─────────────────────────────────────────────────────')
})
