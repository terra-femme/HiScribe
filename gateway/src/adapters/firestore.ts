// Stub — swap storage.ts re-export to activate
// Required env vars: GOOGLE_APPLICATION_CREDENTIALS, GCP_PROJECT_ID
export async function saveSession(_session: any): Promise<void> {
  throw new Error('Firestore adapter not yet implemented.')
}
export async function getSession(_id: string): Promise<any> {
  throw new Error('Firestore adapter not yet implemented.')
}
export async function saveSegment(_segment: any): Promise<void> {
  throw new Error('Firestore adapter not yet implemented.')
}
export async function getSegments(_sessionId: string): Promise<any[]> {
  throw new Error('Firestore adapter not yet implemented.')
}
