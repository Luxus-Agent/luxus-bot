import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { KeyRound, ArrowLeft } from 'lucide-react'

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
      <div className="min-h-screen flex items-center justify-center px-4"
        style={{ background: 'linear-gradient(135deg, #080B10 0%, #0E1117 50%, #080B10 100%)' }}>
        <div className="w-full max-w-md">
          <div className="flex justify-center mb-8"><Logo size={36} /></div>
          <div className="rounded-2xl p-8" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            <h1 className="text-2xl font-bold text-white mb-2 text-center">OTP Sent</h1>
            <p className="text-sm mb-6 text-center" style={{ color: '#8899AA' }}>
              Check your email for the password reset OTP
            </p>
            <button
              onClick={() => navigate(`/reset-password?email=${encodeURIComponent(email)}`)}
              className="w-full py-3 rounded-xl font-semibold text-sm"
              style={{ background: '#00D4B4', color: '#000' }}
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
      className="min-h-screen flex items-center justify-center px-4"
      style={{ background: 'linear-gradient(135deg, #080B10 0%, #0E1117 50%, #080B10 100%)' }}
    >
      <div className="w-full max-w-md">
        <div className="flex justify-center mb-8"><Logo size={36} /></div>
        <div className="rounded-2xl p-8" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 mx-auto"
            style={{ background: 'rgba(0,212,180,0.12)', border: '1px solid rgba(0,212,180,0.3)' }}
          >
            <KeyRound size={28} style={{ color: '#00D4B4' }} />
          </div>
          <h1 className="text-2xl font-bold text-white mb-1 text-center">Forgot Password</h1>
          <p className="text-sm mb-6 text-center" style={{ color: '#8899AA' }}>
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
              style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
              onFocus={e => e.target.style.borderColor = '#00D4B4'}
              onBlur={e => e.target.style.borderColor = '#1E2A38'}
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
              style={{ background: loading ? 'rgba(0,212,180,0.3)' : '#00D4B4', color: loading ? '#8899AA' : '#000' }}
            >
              {loading ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : 'Send Reset OTP'}
            </button>
          </form>
          <p className="mt-4 text-center text-sm" style={{ color: '#8899AA' }}>
            <Link to="/login" className="flex items-center justify-center gap-1" style={{ color: '#00D4B4' }}>
              <ArrowLeft size={14} /> Back to Login
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
