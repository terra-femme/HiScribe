/**
 * gateway/src/middleware/auth.ts
 *
 * JWT authentication for HiScribe gateway.
 *
 * HTTP routes:   expect  Authorization: Bearer <jwt>
 * WS / SSE:      expect  ?token=<jwt>  (browsers cannot send custom headers
 *                during the WebSocket/EventSource handshake)
 *
 * Set JWT_SECRET in .env.
 * Set DEV_MODE=true to bypass auth entirely in local development.
 */

import jwt from 'jsonwebtoken'
import { FastifyRequest, FastifyReply } from 'fastify'

const DEV_MODE = process.env.DEV_MODE === 'true'

export interface AuthPayload {
  sub: string
  role?: string
  iat?: number
  exp?: number
}

const DEV_PAYLOAD: AuthPayload = { sub: 'dev-user', role: 'authenticated' }

// ─── helpers ────────────────────────────────────────────────────────────────

function getSecret(): string {
  const secret = process.env.JWT_SECRET
  if (!secret) {
    console.error('[auth] FATAL: JWT_SECRET is not set in environment')
    throw new Error('JWT_SECRET not configured')
  }
  return secret
}

function decodeToken(token: string): AuthPayload {
  const secret = getSecret()
  try {
    const payload = jwt.verify(token, secret) as AuthPayload
    console.debug(`[auth] Token verified for sub=${payload.sub}`)
    return payload
  } catch (err: any) {
    console.warn(`[auth] Token verification failed: ${err.message}`)
    throw err
  }
}

// ─── HTTP route hook ─────────────────────────────────────────────────────────

/**
 * Fastify preHandler hook for HTTP routes.
 * Attach as: { preHandler: requireAuth }
 */
export async function requireAuth(
  req: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  if (DEV_MODE) {
    console.debug('[auth] DEV_MODE — bypassing HTTP auth')
    ;(req as any).user = DEV_PAYLOAD
    return
  }

  const authHeader = req.headers['authorization']
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    console.warn(`[auth] Missing or malformed Authorization header — ${req.method} ${req.url}`)
    reply.status(401).send({ error: 'Authorization required. Use Bearer token.' })
    return
  }

  const token = authHeader.slice(7)
  try {
    ;(req as any).user = decodeToken(token)
  } catch (err: any) {
    const msg = err.name === 'TokenExpiredError' ? 'Token expired.' : 'Invalid token.'
    reply.status(401).send({ error: msg })
  }
}

// ─── WebSocket / SSE query-param token ───────────────────────────────────────

/**
 * Validates a JWT passed as ?token=<jwt> query parameter.
 * Used for WebSocket and SSE connections where browsers cannot
 * send custom headers during the handshake.
 *
 * Returns the decoded payload on success.
 * Throws with a descriptive message on failure — caller should close the socket.
 */
export function verifyWsToken(token: string | undefined): AuthPayload {
  if (DEV_MODE) {
    console.debug('[auth] DEV_MODE — bypassing WS/SSE token check')
    return DEV_PAYLOAD
  }

  if (!token) {
    console.warn('[auth] WS/SSE connection rejected — no token provided')
    throw new Error('Missing token')
  }

  return decodeToken(token)
}

// ─── utility ──────────────────────────────────────────────────────────────────

/**
 * Sign a short-lived token. Useful for issuing WS tokens from a REST endpoint.
 * The caller (e.g. a session-start route) signs a token the client passes
 * back when opening the WebSocket.
 */
export function signToken(payload: Omit<AuthPayload, 'iat' | 'exp'>, expiresIn = '2h'): string {
  const secret = getSecret()
  const token = jwt.sign(payload, secret, { expiresIn } as jwt.SignOptions)
  console.debug(`[auth] Signed token for sub=${payload.sub}, expiresIn=${expiresIn}`)
  return token
}
