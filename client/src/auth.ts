/**
 * client/src/auth.ts
 *
 * Shared auth helpers for all client components.
 * Token is stored in localStorage under 'hiscribe_token' after login.
 * In DEV_MODE the gateway accepts an empty token; all helpers degrade gracefully.
 */

const TOKEN_KEY = 'hiscribe_token'

/** Return the raw JWT string, or '' in DEV_MODE when no login has occurred. */
export function getAuthToken(): string {
  const token = localStorage.getItem(TOKEN_KEY) ?? ''
  if (!token) {
    console.warn(
      `[auth] No token in localStorage["${TOKEN_KEY}"] — ` +
      'using empty string (DEV_MODE only)'
    )
  }
  return token
}

/**
 * Decode the JWT payload and return the `sub` claim.
 * Falls back to 'dev-user' when no token is present (matches gateway DEV_MODE bypass).
 * Falls back to 'unknown' if the token is malformed.
 */
export function getUserId(): string {
  const token = getAuthToken()
  if (!token) return 'dev-user'
  try {
    // JWT format: header.payload.signature — all base64url encoded
    const payloadB64 = token.split('.')[1]
    // base64url → base64: replace URL-safe chars
    const payloadJson = atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(payloadJson)
    return payload.sub ?? 'unknown'
  } catch {
    console.warn('[auth] Failed to decode JWT payload — using "unknown"')
    return 'unknown'
  }
}

/** Return an Authorization header object suitable for spreading into fetch headers. */
export function bearerHeader(): { Authorization: string } {
  return { Authorization: `Bearer ${getAuthToken()}` }
}
