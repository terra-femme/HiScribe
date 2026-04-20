import { useEffect, useRef, useState } from 'react'
import { bearerHeader } from './auth'

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? ''

interface Provider {
  provider_id:  string
  name:         string
  quality_score: number
  sample_count: number
  enrolled_at:  string
  updated_at:   string
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const card: React.CSSProperties = {
  background: '#161924', border: '1px solid #2a2d3a',
  borderRadius: '12px', padding: '32px'
}

const label: React.CSSProperties = {
  display: 'block', fontSize: '13px', color: '#9ca3af',
  marginBottom: '6px', fontWeight: 500
}

const input: React.CSSProperties = {
  width: '100%', background: '#0d0f18', border: '1px solid #2a2d3a',
  borderRadius: '8px', padding: '10px 14px', color: '#e5e7eb',
  fontSize: '14px', boxSizing: 'border-box'
}

const btnPrimary: React.CSSProperties = {
  background: '#2563eb', color: '#fff', border: 'none',
  borderRadius: '8px', padding: '11px 24px', fontSize: '14px',
  fontWeight: 600, cursor: 'pointer'
}

const btnDisabled: React.CSSProperties = {
  ...btnPrimary, background: '#374151', cursor: 'not-allowed'
}

const btnDanger: React.CSSProperties = {
  background: 'transparent', color: '#f87171', border: '1px solid #3f2020',
  borderRadius: '6px', padding: '5px 12px', fontSize: '12px',
  cursor: 'pointer'
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function EnrollmentPage() {
  const [providers, setProviders]   = useState<Provider[]>([])
  const [loadError, setLoadError]   = useState('')

  const [providerId, setProviderId] = useState('')
  const [name, setName]             = useState('')
  const [audioFile, setAudioFile]   = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<{ ok: boolean; msg: string } | null>(null)

  const [deletingId, setDeletingId] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Load providers on mount ──────────────────────────────────────────────
  async function loadProviders() {
    setLoadError('')
    try {
      const res = await fetch(`${GATEWAY}/enrollment/providers`, {
        headers: bearerHeader()
      })
      if (!res.ok) throw new Error(`Failed to load providers (${res.status})`)
      setProviders(await res.json())
    } catch (e: any) {
      setLoadError(e.message)
    }
  }

  useEffect(() => { loadProviders() }, [])

  // ── Enroll ───────────────────────────────────────────────────────────────
  async function handleEnroll(e: React.FormEvent) {
    e.preventDefault()
    if (!audioFile) return

    setSubmitting(true)
    setSubmitResult(null)

    const form = new FormData()
    form.append('provider_id', providerId.trim())
    form.append('name', name.trim())
    form.append('audio', audioFile)

    try {
      const res = await fetch(`${GATEWAY}/enrollment/enroll`, {
        method: 'POST',
        headers: bearerHeader(),
        body: form
      })
      const json = await res.json()

      if (!res.ok) {
        setSubmitResult({ ok: false, msg: json.detail ?? 'Enrollment failed' })
      } else {
        setSubmitResult({
          ok: true,
          msg: `Enrolled ${name.trim()} — quality ${(json.quality_score * 100).toFixed(0)}% across ${json.sample_count} voice windows`
        })
        // Reset form
        setProviderId('')
        setName('')
        setAudioFile(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
        await loadProviders()
      }
    } catch (e: any) {
      setSubmitResult({ ok: false, msg: e.message })
    } finally {
      setSubmitting(false)
    }
  }

  // ── Delete ───────────────────────────────────────────────────────────────
  async function handleDelete(id: string, displayName: string) {
    if (!window.confirm(`Remove voice profile for ${displayName}? This cannot be undone.`)) return

    setDeletingId(id)
    try {
      const res = await fetch(`${GATEWAY}/enrollment/${id}`, {
        method: 'DELETE',
        headers: bearerHeader()
      })
      if (!res.ok) {
        const json = await res.json()
        alert(json.detail ?? 'Delete failed')
      } else {
        await loadProviders()
      }
    } catch (e: any) {
      alert(e.message)
    } finally {
      setDeletingId(null)
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────
  const canSubmit = providerId.trim() && name.trim() && audioFile && !submitting

  return (
    <div style={{ maxWidth: '680px', margin: '0 auto' }}>
      <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '24px', color: '#e5e7eb' }}>
        Provider Voice Enrollment
      </h2>
      <p style={{ color: '#6b7280', fontSize: '13px', lineHeight: 1.6, marginBottom: '32px' }}>
        Enroll a provider's voice so HiScribe can identify them during sessions. Upload
        15–20 seconds of clean speech — no background noise, no patient present.
        Voice profiles are encrypted at rest and never leave this system.
      </p>

      {/* ── Enroll form ────────────────────────────────────────────────── */}
      <div style={{ ...card, marginBottom: '32px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 600, marginBottom: '24px', color: '#e5e7eb' }}>
          Add Voice Profile
        </h3>

        <form onSubmit={handleEnroll}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={label}>Provider ID</label>
              <input
                style={input}
                type="text"
                placeholder="e.g. dr_smith_001"
                value={providerId}
                onChange={e => setProviderId(e.target.value)}
                disabled={submitting}
              />
            </div>
            <div>
              <label style={label}>Display Name</label>
              <input
                style={input}
                type="text"
                placeholder="e.g. Dr. Sarah Smith"
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={submitting}
              />
            </div>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={label}>Voice Sample (WAV, 15–20 seconds)</label>
            <input
              ref={fileInputRef}
              style={{ ...input, padding: '8px 14px', cursor: 'pointer' }}
              type="file"
              accept="audio/wav,audio/wave,.wav"
              disabled={submitting}
              onChange={e => setAudioFile(e.target.files?.[0] ?? null)}
            />
            {audioFile && (
              <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '6px' }}>
                {audioFile.name} — {(audioFile.size / 1024).toFixed(0)} KB
              </p>
            )}
          </div>

          {submitResult && (
            <div style={{
              padding: '10px 14px', borderRadius: '8px', marginBottom: '16px',
              background: submitResult.ok ? '#0d2218' : '#2a0a0a',
              border: `1px solid ${submitResult.ok ? '#166534' : '#7f1d1d'}`,
              color: submitResult.ok ? '#4ade80' : '#f87171',
              fontSize: '13px'
            }}>
              {submitResult.msg}
            </div>
          )}

          <button
            type="submit"
            style={canSubmit ? btnPrimary : btnDisabled}
            disabled={!canSubmit}
          >
            {submitting ? 'Enrolling...' : 'Enroll Provider'}
          </button>
        </form>
      </div>

      {/* ── Enrolled providers list ─────────────────────────────────────── */}
      <div style={card}>
        <h3 style={{ fontSize: '15px', fontWeight: 600, marginBottom: '20px', color: '#e5e7eb' }}>
          Enrolled Providers
        </h3>

        {loadError && (
          <p style={{ color: '#f87171', fontSize: '13px', marginBottom: '16px' }}>{loadError}</p>
        )}

        {providers.length === 0 && !loadError ? (
          <p style={{ color: '#4b5563', fontSize: '13px' }}>
            No providers enrolled yet. Add one above.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {providers.map(p => (
              <div key={p.provider_id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: '#0d0f18', border: '1px solid #2a2d3a',
                borderRadius: '8px', padding: '14px 16px'
              }}>
                <div>
                  <p style={{ fontSize: '14px', fontWeight: 600, color: '#e5e7eb', margin: 0 }}>
                    {p.name}
                  </p>
                  <p style={{ fontSize: '12px', color: '#4b5563', margin: '3px 0 0' }}>
                    ID: {p.provider_id}
                    &nbsp;·&nbsp;Quality: {(p.quality_score * 100).toFixed(0)}%
                    &nbsp;·&nbsp;{p.sample_count} windows
                    &nbsp;·&nbsp;Enrolled {new Date(p.enrolled_at).toLocaleDateString()}
                  </p>
                </div>

                <button
                  style={btnDanger}
                  disabled={deletingId === p.provider_id}
                  onClick={() => handleDelete(p.provider_id, p.name)}
                >
                  {deletingId === p.provider_id ? 'Removing...' : 'Remove'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
