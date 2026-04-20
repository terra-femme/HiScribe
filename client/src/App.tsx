import { Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import SessionStart from './SessionStart'
import LiveCapture from './LiveCapture'
import SOAPReview from './SOAPReview'
import EnrollmentPage from './EnrollmentPage'

function NavLink({ to, label }: { to: string; label: string }) {
  const { pathname } = useLocation()
  const active = pathname.startsWith(to)
  return (
    <Link to={to} style={{
      fontSize: '13px', fontWeight: 500, textDecoration: 'none',
      color: active ? '#7eb8f7' : '#6b7280',
      borderBottom: active ? '2px solid #7eb8f7' : '2px solid transparent',
      paddingBottom: '2px'
    }}>
      {label}
    </Link>
  )
}

export default function App() {
  return (
    <div style={{ minHeight: '100vh', padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
      <header style={{ marginBottom: '32px', borderBottom: '1px solid #2a2d3a', paddingBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: '20px', fontWeight: 600, letterSpacing: '0.5px', color: '#7eb8f7' }}>
              HiScribe
            </h1>
            <p style={{ fontSize: '13px', color: '#6b7280', marginTop: '4px' }}>
              Ambient Clinical Scribe — Human in the Loop
            </p>
          </div>
          <nav style={{ display: 'flex', gap: '24px', paddingBottom: '4px' }}>
            <NavLink to="/session" label="Sessions" />
            <NavLink to="/enroll" label="Voice Enrollment" />
          </nav>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/session" replace />} />
        <Route path="/session" element={<SessionStart />} />
        <Route path="/session/:id/capture" element={<LiveCapture />} />
        <Route path="/session/:id/review" element={<SOAPReview />} />
        <Route path="/enroll" element={<EnrollmentPage />} />
      </Routes>
    </div>
  )
}
