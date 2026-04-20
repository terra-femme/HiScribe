// Stub — swap storage.ts re-export to activate
// Required env vars: AZURE_COSMOS_ENDPOINT, AZURE_COSMOS_KEY
export async function saveSession(_session: any): Promise<void> {
  throw new Error('Cosmos DB adapter not yet implemented.')
}
export async function getSession(_id: string): Promise<any> {
  throw new Error('Cosmos DB adapter not yet implemented.')
}
export async function saveSegment(_segment: any): Promise<void> {
  throw new Error('Cosmos DB adapter not yet implemented.')
}
export async function getSegments(_sessionId: string): Promise<any[]> {
  throw new Error('Cosmos DB adapter not yet implemented.')
}
