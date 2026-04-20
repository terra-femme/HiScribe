import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { bearerHeader } from './auth'

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? ''

export default function SessionStart() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  async function startSession() {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${GATEWAY}/session/start`, {
        method: 'POST',
        headers: bearerHeader()
      })
      if (!res.ok) throw new Error('Failed to create session')
      const { session_id } = await res.json()
      navigate(`/session/${session_id}/capture`)
    } catch (e: any) {
      setError(e.message)
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: '560px', margin: '80px auto', textAlign: 'center' }}>
      <div style={{
        background: '#161924', border: '1px solid #2a2d3a',
        borderRadius: '12px', padding: '48px 40px'
      }}>
        <div style={{ fontSize: '40px', marginBottom: '16px' }}>🎙</div>
        <h2 style={{ fontSize: '22px', fontWeight: 600, marginBottom: '8px' }}>
          Ready to Record
        </h2>
        <p style={{ color: '#6b7280', fontSize: '14px', lineHeight: 1.6, marginBottom: '32px' }}>
          HiScribe will listen passively during the visit, separate doctor and patient speech,
          and map the conversation to a SOAP note for your review.
          <br /><br />
          Nothing enters the chart until you approve it.
        </p>

        {error && (
          <p style={{ color: '#f87171', fontSize: '13px', marginBottom: '16px' }}>{error}</p>
        )}

        <button
          onClick={startSession}
          disabled={loading}
          style={{
            background: loading ? '#374151' : '#2563eb',
            color: '#fff', border: 'none', borderRadius: '8px',
            padding: '14px 32px', fontSize: '15px', fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer', width: '100%'
          }}
        >
          {loading ? 'Starting...' : '● Start Session'}
        </button>
      </div>
    </div>
  )
}
