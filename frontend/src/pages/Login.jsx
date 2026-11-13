import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { ThemeToggle } from '../components/Layout'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const profile = await login(form.username, form.password)
      // Admin goes to admin dashboard, users go to user dashboard — never mixed
      if (profile.is_admin) {
        navigate('/admin', { replace: true })
      } else {
        navigate('/dashboard', { replace: true })
      }
    } catch (err) {
      const msg = err.response?.data?.detail || 'Login failed'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 auth-screen relative"
    >
      <div
        className="absolute inset-0 pointer-events-none auth-overlay"
      />
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, rgba(var(--accent-rgb),0.06) 0%, transparent 70%)' }}
      />

      <div className="absolute top-4 right-4 z-10"><ThemeToggle /></div>

      <div className="w-full max-w-md relative">
        <div
          className="rounded-2xl p-8"
          style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
        >
          <div className="flex justify-center mb-6">
            <Logo size={36} />
          </div>

          <h1 className="text-2xl font-bold text-white mb-1">Welcome back</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--text-secondary)' }}>Sign in to your Luxus account</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>Username</label>
              <input
                type="text"
                required
                autoCapitalize="none"
                autoCorrect="off"
                value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                placeholder="yourusername"
                className="w-full px-4 py-3 rounded-xl text-sm outline-none transition-all"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>Password</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  required
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder="••••••••"
                  className="w-full px-4 py-3 pr-12 rounded-xl text-sm outline-none transition-all"
                  style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                  onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                  onBlur={e => e.target.style.borderColor = 'var(--border)'}
                />
                <button
                  type="button"
                  onClick={() => setShowPw(v => !v)}
                  className="absolute right-4 top-1/2 -translate-y-1/2"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <div className="mt-2 text-right">
                <Link to="/forgot-password" className="text-xs" style={{ color: 'var(--accent)' }}>
                  Forgot password?
                </Link>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all"
              style={{
                background: loading ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)',
                color: loading ? 'var(--text-secondary)' : '#000',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? (
                <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
              ) : (
                <><LogIn size={16} /> Sign In</>
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
            Don't have an account?{' '}
            <Link to="/register" style={{ color: 'var(--accent)' }} className="font-medium">Register</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
