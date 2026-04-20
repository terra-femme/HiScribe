import { db } from '../db/client'

export type SessionRecord = {
  id: string
  status: string
  created_at: string
  provider_npi?: string
  patient_mrn?: string
  visit_type?: string
}

export type SegmentRecord = {
  session_id: string
  text: string
  speaker: string
  start_ms: number
  end_ms: number
  confidence: number
  is_final: boolean
}

export async function saveSession(session: SessionRecord): Promise<void> {
  db.prepare(`
    INSERT OR REPLACE INTO sessions (id, status, created_at)
    VALUES (@id, @status, @created_at)
  `).run(session)
}

export async function getSession(id: string): Promise<SessionRecord | null> {
  return (db.prepare('SELECT * FROM sessions WHERE id = ?').get(id) as SessionRecord) ?? null
}

export async function saveSegment(segment: SegmentRecord): Promise<void> {
  db.prepare(`
    INSERT INTO segments (session_id, text, speaker, start_ms, end_ms, confidence, is_final)
    VALUES (@session_id, @text, @speaker, @start_ms, @end_ms, @confidence, @is_final)
  `).run({ ...segment, is_final: segment.is_final ? 1 : 0 })

  // Only count finalised segments — partials are ephemeral and overwritten
  if (segment.is_final) {
    db.prepare('UPDATE sessions SET segment_count = segment_count + 1 WHERE id = ?').run(segment.session_id)
  }
}

export async function getSegments(sessionId: string): Promise<SegmentRecord[]> {
  return db
    .prepare('SELECT * FROM segments WHERE session_id = ? AND is_final = 1 ORDER BY start_ms ASC')
    .all(sessionId) as SegmentRecord[]
}
