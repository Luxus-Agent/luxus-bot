import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { UserLayout, AdminLayout } from '../components/Layout'
import { User, Mail, LogOut, Calendar, Users, KeyRound, Eye, EyeOff } from 'lucide-react'
import api from '../api/client'
import toast from 'react-hot-toast'

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


function ChangePassword({ email }) {
  const [otpSent, setOtpSent] = useState(false)
  const [sending, setSending] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showPw, setShowPw] = useState(false)
  const [form, setForm] = useState({ otp: '', new_password: '' })

  const sendOtp = async () => {
    setSending(true)
    try {
      await api.post('/auth/forgot-password', { email })
      setOtpSent(true)
      toast.success(`OTP sent to ${email}`)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to send OTP')
    } finally {
      setSending(false)
    }
  }

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await api.post('/auth/reset-password', { email, ...form })
      toast.success('Password changed! Please log in again.')
      setTimeout(() => { window.location.href = '/login' }, 800)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to change password')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={CARD}>
      <div className="flex items-center gap-3 mb-1">
        <div
          className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ background: 'rgba(var(--accent-rgb),0.08)' }}
        >
          <KeyRound size={16} style={{ color: 'var(--accent)' }} />
        </div>
        <div>
          <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Change Password</p>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>We'll email a one-time code to {email}</p>
        </div>
      </div>

      {!otpSent ? (
        <button
          onClick={sendOtp}
          disabled={sending}
          className="w-full mt-4 py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
          style={{ background: sending ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)', color: sending ? 'var(--text-secondary)' : '#000' }}
        >
          {sending ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : 'Send OTP to My Email'}
        </button>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>OTP Code</label>
            <input
              type="text"
              required
              maxLength={6}
              value={form.otp}
              onChange={e => setForm(f => ({ ...f, otp: e.target.value.replace(/\D/g, '') }))}
              placeholder="000000"
              className="w-full px-4 py-3 rounded-xl text-center text-lg font-bold tracking-widest outline-none"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
              onFocus={e => e.target.style.borderColor = 'var(--accent)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>New Password</label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'}
                required
                value={form.new_password}
                onChange={e => setForm(f => ({ ...f, new_password: e.target.value }))}
                placeholder="Min. 8 characters"
                className="w-full px-4 py-3 pr-12 rounded-xl text-sm outline-none"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
              <button type="button" onClick={() => setShowPw(v => !v)}
                className="absolute right-4 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-secondary)' }}>
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          <button
            type="submit"
            disabled={saving}
            className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
            style={{ background: saving ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)', color: saving ? 'var(--text-secondary)' : '#000' }}
          >
            {saving ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : 'Update Password'}
          </button>
          <button
            type="button"
            onClick={sendOtp}
            disabled={sending}
            className="w-full text-xs font-medium"
            style={{ color: 'var(--accent)' }}
          >
            {sending ? 'Resending…' : 'Resend OTP'}
          </button>
        </form>
      )}
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

        {/* Change password */}
        <ChangePassword email={user.email} />

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
