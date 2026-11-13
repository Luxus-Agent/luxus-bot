import { useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import api from '../api/client'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { MailCheck, RefreshCw } from 'lucide-react'
import { ThemeToggle } from '../components/Layout'

export default function VerifyEmail() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const email = params.get('email') || ''
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const [resending, setResending] = useState(false)

  const handleVerify = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await api.post('/auth/verify-email', { email, otp })
      toast.success('Email verified! You can now log in.')
      navigate('/login')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Verification failed')
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    setResending(true)
    try {
      await api.post('/auth/resend-verification', { email })
      toast.success('New OTP sent to your email')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to resend')
    } finally {
      setResending(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 auth-screen relative"
    >
      <div
        className="absolute inset-0 pointer-events-none auth-overlay"
      />
      <div className="absolute top-4 right-4 z-10"><ThemeToggle /></div>
      <div className="w-full max-w-md relative">
        <div className="rounded-2xl p-8" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          <div className="flex justify-center mb-6"><Logo size={36} /></div>

          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 mx-auto"
            style={{ background: 'rgba(var(--accent-rgb),0.12)', border: '1px solid rgba(var(--accent-rgb),0.3)' }}
          >
            <MailCheck size={28} style={{ color: 'var(--accent)' }} />
          </div>

          <h1 className="text-2xl font-bold text-white mb-1 text-center">Verify Email</h1>
          <p className="text-sm mb-6 text-center" style={{ color: 'var(--text-secondary)' }}>
            Enter the 6-digit OTP sent to <span className="text-white">{email}</span>
          </p>

          <form onSubmit={handleVerify} className="space-y-4">
            <input
              type="text"
              required
              maxLength={6}
              value={otp}
              onChange={e => setOtp(e.target.value.replace(/\D/g, ''))}
              placeholder="000000"
              className="w-full px-4 py-3 rounded-xl text-center text-2xl font-bold tracking-widest outline-none"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
              onFocus={e => e.target.style.borderColor = 'var(--accent)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />

            <button
              type="submit"
              disabled={loading || otp.length < 6}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
              style={{
                background: (loading || otp.length < 6) ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)',
                color: (loading || otp.length < 6) ? 'var(--text-secondary)' : '#000',
                cursor: (loading || otp.length < 6) ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : 'Verify Email'}
            </button>
          </form>

          <button
            onClick={handleResend}
            disabled={resending}
            className="w-full mt-3 py-3 rounded-xl font-medium text-sm flex items-center justify-center gap-2"
            style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'transparent' }}
          >
            <RefreshCw size={15} className={resending ? 'animate-spin' : ''} />
            Resend OTP
          </button>

          <p className="mt-4 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
            <Link to="/login" style={{ color: 'var(--accent)' }}>Back to Login</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
