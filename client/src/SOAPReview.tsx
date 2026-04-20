import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import SegmentCard from './SegmentCard'
import AmendmentPanel from './AmendmentPanel'
import { bearerHeader, getUserId } from './auth'

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? ''

const SECTIONS = ['S', 'O', 'A', 'P'] as const
const SECTION_LABELS: Record<string, string> = {
  S: 'Subjective', O: 'Objective', A: 'Assessment', P: 'Plan'
}
const SECTION_COLORS: Record<string, string> = {
  S: '#34d399', O: '#60a5fa', A: '#f59e0b', P: '#a78bfa'
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

type ReviewPayload = {
  session: { id: string; status: string }
  soap: Record<string, Segment[]>
  amendments: any[]
}

export default function SOAPReview() {
  const providerId = getUserId()
  const { id: sessionId } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [payload, setPayload] = useState<ReviewPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)
  const [meta, setMeta] = useState({ npi: '', mrn: '', visitType: 'follow_up' })

  const fetchNote = useCallback(async () => {
    setFetchError(null)
    try {
      const res = await fetch(`${GATEWAY}/session/${sessionId}/note`, {
        headers: bearerHeader()
      })
      if (!res.ok) {
        setFetchError(res.status === 404 ? 'Note not found.' : `Server error ${res.status} — check pipeline logs.`)
        return
      }
      setPayload(await res.json())
    } catch {
      setFetchError('Could not reach server. Check your connection.')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { fetchNote() }, [fetchNote])

  async function approve() {
    if (!meta.npi || !meta.mrn) return

    // Guardrail: warn if flagged segments are still unresolved
    if (flaggedCount > 0) {
      const confirmed = confirm(
        `${flaggedCount} flagged segment${flaggedCount > 1 ? 's' : ''} still need review.\n\n` +
        `Flagged segments may contain low-confidence transcription or role disagreements.\n\n` +
        `Approve anyway?`
      )
      if (!confirmed) return
    }

    setApproving(true)
    await fetch(`${GATEWAY}/session/${sessionId}/approve`, {
      method: 'POST',
      headers: { ...bearerHeader(), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider_npi: meta.npi,
        patient_mrn: meta.mrn,
        visit_type: meta.visitType
      })
    })
    alert('Note approved. FHIR document generated.')
    navigate('/session')
  }

  const canApprove = meta.npi.trim() && meta.mrn.trim()
  const flaggedCount = payload
    ? Object.values(payload.soap).flat().filter(s => s.confidence_flag || s.role_flag).length
    : 0

  if (loading) {
    return <div style={{ color: '#6b7280', textAlign: 'center', marginTop: '80px' }}>Loading note...</div>
  }

  if (fetchError) {
    return (
      <div style={{ color: '#f87171', textAlign: 'center', marginTop: '80px' }}>
        {fetchError}
        <br />
        <button
          onClick={fetchNote}
          style={{ marginTop: '12px', background: 'none', border: '1px solid #374151', color: '#9ca3af', borderRadius: '6px', padding: '6px 16px', fontSize: '13px', cursor: 'pointer' }}
        >
          Retry
        </button>
      </div>
    )
  }

  if (!payload) {
    return <div style={{ color: '#f87171', textAlign: 'center', marginTop: '80px' }}>Note not found.</div>
  }

  return (
    <div>
      {/* Header bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: '24px', flexWrap: 'wrap', gap: '12px'
      }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 600 }}>Review Note</h2>
          <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>
            Session {sessionId?.slice(0, 8)}
            {flaggedCount > 0 && (
              <span style={{ color: '#f59e0b', marginLeft: '8px' }}>⚑ {flaggedCount} flagged</span>
            )}
          </p>
        </div>

        {/* Metadata gate — must fill before approve is enabled */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            placeholder="Provider NPI"
            value={meta.npi}
            onChange={e => setMeta(m => ({ ...m, npi: e.target.value }))}
            style={inputStyle}
          />
          <input
            placeholder="Patient MRN"
            value={meta.mrn}
            onChange={e => setMeta(m => ({ ...m, mrn: e.target.value }))}
            style={inputStyle}
          />
          <select
            value={meta.visitType}
            onChange={e => setMeta(m => ({ ...m, visitType: e.target.value }))}
            style={inputStyle}
          >
            <option value="new_patient">New Patient</option>
            <option value="follow_up">Follow-up</option>
            <option value="urgent_care">Urgent Care</option>
            <option value="telehealth">Telehealth</option>
          </select>
          <button
            onClick={approve}
            disabled={!canApprove || approving}
            style={{
              background: canApprove ? '#16a34a' : '#1f2937',
              color: canApprove ? '#fff' : '#4b5563',
              border: 'none', borderRadius: '6px', padding: '8px 20px',
              fontSize: '14px', fontWeight: 600, cursor: canApprove ? 'pointer' : 'not-allowed'
            }}
          >
            {approving ? 'Approving...' : '✓ Approve & Generate Note'}
          </button>
        </div>
      </div>

      {/* 4-column SOAP layout */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
        {SECTIONS.map(section => (
          <div key={section} style={{
            background: '#161924', border: `1px solid #2a2d3a`,
            borderRadius: '8px', padding: '16px', minHeight: '400px'
          }}>
            <h3 style={{
              fontSize: '12px', fontWeight: 700, letterSpacing: '1px',
              color: SECTION_COLORS[section], marginBottom: '16px', textTransform: 'uppercase'
            }}>
              {section} — {SECTION_LABELS[section]}
            </h3>

            {(payload.soap[section] ?? []).map(seg => (
              <SegmentCard
                key={seg.segment_id}
                segment={seg}
                providerId={providerId}
                onUpdate={fetchNote}
              />
            ))}

            <AmendmentPanel
              sessionId={sessionId!}
              providerId={providerId}
              defaultSection={section}
              onAdded={fetchNote}
            />
          </div>
        ))}
      </div>

      {/* Unclassified — shown below if any */}
      {(payload.soap['UNCLASSIFIED'] ?? []).length > 0 && (
        <div style={{ marginTop: '16px', background: '#161924', border: '1px solid #374151', borderRadius: '8px', padding: '16px' }}>
          <h3 style={{ fontSize: '12px', fontWeight: 700, color: '#6b7280', marginBottom: '12px' }}>
            UNCLASSIFIED — requires mapping
          </h3>
          {payload.soap['UNCLASSIFIED'].map(seg => (
            <SegmentCard
              key={seg.segment_id}
              segment={seg}
              providerId={providerId}
              onUpdate={fetchNote}
            />
          ))}
        </div>
      )}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  background: '#1a1e2e', border: '1px solid #374151', color: '#e8eaf0',
  borderRadius: '6px', padding: '7px 12px', fontSize: '13px', outline: 'none'
}
