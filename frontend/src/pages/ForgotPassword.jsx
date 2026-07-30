import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { KeyRound, ArrowLeft } from 'lucide-react'
import loginBg from '../assets/login-bg.png'

export default function ForgotPassword() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
      toast.success('Password reset OTP sent!')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to send OTP')
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-4 bg-cover bg-center bg-no-repeat relative"
        style={{ backgroundImage: `url(${loginBg})` }}
      >
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: 'linear-gradient(135deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.35) 50%, rgba(0,0,0,0.55) 100%)' }}
        />
        <div className="w-full max-w-md relative">
          <div className="rounded-2xl p-8" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
            <div className="flex justify-center mb-6"><Logo size={36} /></div>
            <h1 className="text-2xl font-bold text-white mb-2 text-center">OTP Sent</h1>
            <p className="text-sm mb-6 text-center" style={{ color: 'var(--text-secondary)' }}>
              Check your email for the password reset OTP
            </p>
            <button
              onClick={() => navigate(`/reset-password?email=${encodeURIComponent(email)}`)}
              className="w-full py-3 rounded-xl font-semibold text-sm"
              style={{ background: 'var(--accent)', color: '#000' }}
            >
              Enter OTP
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 bg-cover bg-center bg-no-repeat relative"
      style={{ backgroundImage: `url(${loginBg})` }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: 'linear-gradient(135deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.35) 50%, rgba(0,0,0,0.55) 100%)' }}
      />
      <div className="w-full max-w-md relative">
        <div className="rounded-2xl p-8" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          <div className="flex justify-center mb-6"><Logo size={36} /></div>
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 mx-auto"
            style={{ background: 'rgba(var(--accent-rgb),0.12)', border: '1px solid rgba(var(--accent-rgb),0.3)' }}
          >
            <KeyRound size={28} style={{ color: 'var(--accent)' }} />
          </div>
          <h1 className="text-2xl font-bold text-white mb-1 text-center">Forgot Password</h1>
          <p className="text-sm mb-6 text-center" style={{ color: 'var(--text-secondary)' }}>
            Enter your email to receive a reset OTP
          </p>
          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              type="email"
              required
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full px-4 py-3 rounded-xl text-sm outline-none"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
              onFocus={e => e.target.style.borderColor = 'var(--accent)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
              style={{ background: loading ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)', color: loading ? 'var(--text-secondary)' : '#000' }}
            >
              {loading ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : 'Send Reset OTP'}
            </button>
          </form>
          <p className="mt-4 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
            <Link to="/login" className="flex items-center justify-center gap-1" style={{ color: 'var(--accent)' }}>
              <ArrowLeft size={14} /> Back to Login
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
