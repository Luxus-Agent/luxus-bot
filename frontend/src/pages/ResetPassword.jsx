import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { Eye, EyeOff } from 'lucide-react'

export default function ResetPassword() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const email = params.get('email') || ''
  const [form, setForm] = useState({ otp: '', new_password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await api.post('/auth/reset-password', { email, ...form })
      toast.success('Password reset! Please log in.')
      navigate('/login')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Reset failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ background: 'linear-gradient(135deg, var(--bg-page) 0%, var(--bg-surface) 50%, var(--bg-page) 100%)' }}
    >
      <div className="w-full max-w-md">
        <div className="flex justify-center mb-8"><Logo size={36} /></div>
        <div className="rounded-2xl p-8" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          <h1 className="text-2xl font-bold text-white mb-1">Reset Password</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--text-secondary)' }}>Enter the OTP from your email and a new password</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>OTP Code</label>
              <input
                type="text"
                required
                maxLength={6}
                value={form.otp}
                onChange={e => setForm(f => ({ ...f, otp: e.target.value.replace(/\D/g, '') }))}
                placeholder="000000"
                className="w-full px-4 py-3 rounded-xl text-center text-xl font-bold tracking-widest outline-none"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>New Password</label>
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
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
              style={{ background: loading ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)', color: loading ? 'var(--text-secondary)' : '#000' }}
            >
              {loading ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" /> : 'Reset Password'}
            </button>
          </form>
          <p className="mt-4 text-center text-sm">
            <Link to="/login" style={{ color: 'var(--accent)' }}>Back to Login</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
