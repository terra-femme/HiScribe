import { useState } from 'react'
import { bearerHeader } from './auth'

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? ''

const SOAP_SECTIONS = ['S', 'O', 'A', 'P', 'UNCLASSIFIED']
const SOAP_LABELS: Record<string, string> = {
  S: 'Subjective', O: 'Objective', A: 'Assessment', P: 'Plan', UNCLASSIFIED: 'Unclassified'
}

type Segment = {
  id: number
  segment_id: string
  session_id: string
  text: string
  speaker: string
  soap_section: string
  start_ms: number
  confidence: number
  reliability_score: number
  confidence_flag: boolean
  role_flag: boolean
}

type Props = {
  segment: Segment
  providerId: string
  onUpdate: () => void
}

export default function SegmentCard({ segment, providerId, onUpdate }: Props) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(segment.text)
  const [remapping, setRemapping] = useState(false)
  const [saving, setSaving] = useState(false)
  const [mutationError, setMutationError] = useState<string | null>(null)

  const ts = (ms: number) => {
    const s = Math.floor(ms / 1000)
    return `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`
  }

  async function saveEdit() {
    setSaving(true)
    setMutationError(null)
    try {
      const res = await fetch(`${GATEWAY}/session/${segment.session_id}/segment/${segment.segment_id}/edit`, {
        method: 'POST',
        headers: { ...bearerHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ corrected_text: editText, provider_id: providerId })
      })
      if (!res.ok) { setMutationError(`Edit failed (${res.status}). Try again.`); return }
      setEditing(false)
      onUpdate()
    } catch {
      setMutationError('Could not reach server.')
    } finally {
      setSaving(false)
    }
  }

  async function remap(toSection: string) {
    setSaving(true)
    setMutationError(null)
    try {
      const res = await fetch(`${GATEWAY}/session/${segment.session_id}/segment/${segment.segment_id}/remap`, {
        method: 'POST',
        headers: { ...bearerHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_section: segment.soap_section, to_section: toSection, provider_id: providerId })
      })
      if (!res.ok) { setMutationError(`Remap failed (${res.status}). Try again.`); return }
      setRemapping(false)
      onUpdate()
    } catch {
      setMutationError('Could not reach server.')
    } finally {
      setSaving(false)
    }
  }

  async function deleteSegment() {
    if (!confirm('Remove this segment from the note?')) return
    setSaving(true)
    setMutationError(null)
    try {
      const res = await fetch(`${GATEWAY}/session/${segment.session_id}/segment/${segment.segment_id}`, {
        method: 'DELETE',
        headers: { ...bearerHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: providerId, reason: '' })
      })
      if (!res.ok) { setMutationError(`Delete failed (${res.status}). Try again.`); return }
      onUpdate()
    } catch {
      setMutationError('Could not reach server.')
    } finally {
      setSaving(false)
    }
  }

  const hasFlag = segment.confidence_flag || segment.role_flag

  return (
    <div style={{
      background: '#1a1e2e',
      border: `1px solid ${hasFlag ? '#854d0e' : '#2a2d3a'}`,
      borderRadius: '6px', padding: '12px', marginBottom: '8px',
      fontSize: '13px'
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{
            fontWeight: 700, fontSize: '11px', letterSpacing: '0.5px',
            color: segment.speaker === 'SPEAKER_0' ? '#60a5fa' : '#34d399'
          }}>
            {segment.speaker}
          </span>
          <span style={{ color: '#4b5563', fontSize: '11px' }}>{ts(segment.start_ms)}</span>
          {segment.confidence_flag && (
            <span style={{ color: '#f59e0b', fontSize: '11px' }}>
              ⚠ {segment.reliability_score?.toFixed(2)}
            </span>
          )}
          {segment.role_flag && (
            <span style={{ color: '#f97316', fontSize: '11px' }}>⚠ role?</span>
          )}
        </div>
      </div>

      {/* Text — editable */}
      {editing ? (
        <div style={{ marginBottom: '8px' }}>
          <textarea
            value={editText}
            onChange={e => setEditText(e.target.value)}
            style={{
              width: '100%', background: '#0f1117', border: '1px solid #3b82f6',
              borderRadius: '4px', color: '#e8eaf0', padding: '8px', fontSize: '13px',
              resize: 'vertical', minHeight: '60px'
            }}
          />
          <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
            <button onClick={saveEdit} disabled={saving} style={btnStyle(saving ? '#1e3a8a' : '#2563eb')}>
              {saving ? 'Saving...' : 'Save edit'}
            </button>
            <button onClick={() => { setEditing(false); setEditText(segment.text); setMutationError(null) }} disabled={saving} style={btnStyle('#374151')}>Cancel</button>
          </div>
        </div>
      ) : (
        <p style={{ color: '#d1d5db', lineHeight: 1.5, marginBottom: '8px' }}>{segment.text}</p>
      )}

      {/* Remap dropdown */}
      {remapping && (
        <div style={{ marginBottom: '8px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {SOAP_SECTIONS.filter(s => s !== segment.soap_section).map(s => (
            <button key={s} onClick={() => remap(s)} style={btnStyle('#1d4ed8')}>
              → {SOAP_LABELS[s]}
            </button>
          ))}
          <button onClick={() => setRemapping(false)} style={btnStyle('#374151')}>Cancel</button>
        </div>
      )}

      {/* Mutation error */}
      {mutationError && (
        <p style={{ color: '#f87171', fontSize: '11px', marginBottom: '4px' }}>{mutationError}</p>
      )}

      {/* Actions */}
      {!editing && !remapping && (
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={() => { setEditing(true); setMutationError(null) }} disabled={saving} style={actionBtn}>✎ edit</button>
          <button onClick={() => { setRemapping(true); setMutationError(null) }} disabled={saving} style={actionBtn}>↔ remap</button>
          <button onClick={deleteSegment} disabled={saving} style={{ ...actionBtn, color: '#f87171' }}>✕ delete</button>
        </div>
      )}
    </div>
  )
}

const btnStyle = (bg: string): React.CSSProperties => ({
  background: bg, color: '#fff', border: 'none', borderRadius: '4px',
  padding: '4px 10px', fontSize: '12px', cursor: 'pointer'
})

const actionBtn: React.CSSProperties = {
  background: 'none', border: 'none', color: '#6b7280', fontSize: '12px',
  cursor: 'pointer', padding: '2px 6px'
}
