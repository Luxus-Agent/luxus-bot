import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { UserLayout, AdminLayout } from '../components/Layout'
import { User, Mail, LogOut, Calendar, Users } from 'lucide-react'

const CARD = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  padding: '24px',
}

function Row({ icon: Icon, label, children, last }) {
  return (
    <div
      className="flex items-start gap-3 py-4"
      style={last ? {} : { borderBottom: '1px solid var(--border)' }}
    >
      <div
        className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
        style={{ background: 'rgba(var(--accent-rgb),0.08)' }}
      >
        <Icon size={16} style={{ color: 'var(--accent)' }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>{label}</p>
        <div className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{children}</div>
      </div>
    </div>
  )
}


export default function Profile() {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const Layout = isAdmin ? AdminLayout : UserLayout

  if (!user) return null

  // Backend stores naive UTC without a tz suffix — mark it UTC, then show in IST.
  const createdAt = user.created_at
    ? new Date(`${user.created_at}${/[zZ]|[+-]\d{2}:?\d{2}$/.test(user.created_at) ? '' : 'Z'}`)
        .toLocaleDateString('en-US', {
          timeZone: 'Asia/Kolkata',
          year: 'numeric', month: 'long', day: 'numeric',
        })
    : '—'

  return (
    <Layout>
      <div className="max-w-lg mx-auto space-y-5">

        {/* Header */}
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>My Profile</h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>Your account information</p>
        </div>

        {/* Avatar */}
        <div style={{ ...CARD, display: 'flex', alignItems: 'center', gap: 16 }}>
          <div
            className="flex-shrink-0 flex items-center justify-center rounded-full font-bold text-2xl"
            style={{
              width: 64, height: 64,
              background: 'rgba(var(--accent-rgb),0.12)',
              color: 'var(--accent)',
              border: '2px solid rgba(var(--accent-rgb),0.25)',
            }}
          >
            {(user.username || 'U')[0].toUpperCase()}
          </div>
          <div>
            <p className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>{user.username}</p>
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>{user.email}</p>
          </div>
        </div>

        {/* Fields */}
        <div style={CARD}>
          <Row icon={User} label="Username">
            {user.username}
          </Row>
          <Row icon={Mail} label="Email">
            {user.email}
          </Row>
          <Row icon={Calendar} label="Member Since">
            {createdAt}
          </Row>
          <Row icon={Users} label="Sponsor" last>
            {user.sponsor_username ? `@${user.sponsor_username}` : '—'}
          </Row>
        </div>

        {/* Sign out */}
        <button
          onClick={() => { logout(); navigate('/login') }}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-semibold transition-all"
          style={{
            background: 'rgba(255,77,106,0.08)',
            border: '1px solid rgba(255,77,106,0.2)',
            color: '#FF4D6A',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,77,106,0.15)'}
          onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,77,106,0.08)'}
        >
          <LogOut size={15} />
          Sign Out
        </button>

      </div>
    </Layout>
  )
}
