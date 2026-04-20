import { useState } from 'react'
import { bearerHeader } from './auth'

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? ''
const SOAP_LABELS: Record<string, string> = {
  S: 'Subjective', O: 'Objective', A: 'Assessment', P: 'Plan'
}

type Props = {
  sessionId: string
  providerId: string
  defaultSection?: string
  onAdded: () => void
}

export default function AmendmentPanel({ sessionId, providerId, defaultSection = 'S', onAdded }: Props) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState('')
  const [section, setSection] = useState(defaultSection)
  const [saving, setSaving] = useState(false)

  async function submit() {
    if (!content.trim()) return
    setSaving(true)
    await fetch(`${GATEWAY}/session/${sessionId}/amendment`, {
      method: 'POST',
      headers: { ...bearerHeader(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, soap_section: section, provider_id: providerId })
    })
    setContent('')
    setSection(defaultSection)
    setOpen(false)
    setSaving(false)
    onAdded()
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          background: 'none', border: '1px dashed #374151', borderRadius: '6px',
          color: '#6b7280', padding: '8px 16px', fontSize: '13px', cursor: 'pointer',
          width: '100%', marginTop: '8px'
        }}
      >
        + Add amendment
      </button>
    )
  }

  return (
    <div style={{
      background: '#1a1e2e', border: '1px solid #854d0e',
      borderRadius: '6px', padding: '16px', marginTop: '8px'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
        <span style={{ color: '#f59e0b', fontSize: '11px', fontWeight: 700 }}>[AMENDMENT]</span>
        <span style={{ color: '#6b7280', fontSize: '11px' }}>
          — clinical information not captured in the transcript
        </span>
      </div>

      <select
        value={section}
        onChange={e => setSection(e.target.value)}
        style={{
          background: '#0f1117', border: '1px solid #374151', color: '#e8eaf0',
          borderRadius: '4px', padding: '6px 10px', fontSize: '13px',
          width: '100%', marginBottom: '8px'
        }}
      >
        {Object.entries(SOAP_LABELS).map(([k, v]) => (
          <option key={k} value={k}>{v}</option>
        ))}
      </select>

      <textarea
        value={content}
        onChange={e => setContent(e.target.value)}
        placeholder="Add clinical information not captured in the recording..."
        style={{
          width: '100%', background: '#0f1117', border: '1px solid #374151',
          borderRadius: '4px', color: '#e8eaf0', padding: '10px', fontSize: '13px',
          resize: 'vertical', minHeight: '80px', marginBottom: '8px'
        }}
      />

      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          onClick={submit}
          disabled={saving || !content.trim()}
          style={{
            background: '#854d0e', color: '#fff', border: 'none', borderRadius: '4px',
            padding: '6px 16px', fontSize: '13px', cursor: 'pointer'
          }}
        >
          {saving ? 'Saving...' : 'Save amendment'}
        </button>
        <button
          onClick={() => setOpen(false)}
          style={{
            background: 'none', border: '1px solid #374151', color: '#6b7280',
            borderRadius: '4px', padding: '6px 16px', fontSize: '13px', cursor: 'pointer'
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
