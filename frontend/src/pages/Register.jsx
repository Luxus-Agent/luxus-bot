import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { Eye, EyeOff, UserPlus, CheckCircle, XCircle, Loader } from 'lucide-react'

const Required = () => <span style={{ color: '#FF4D6A' }}> *</span>

export default function Register() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [form, setForm] = useState({
    email: '',
    username: '',
    password: '',
    confirm_password: '',
    sponsor_username: params.get('ref') || '',
  })
  const [showPw, setShowPw] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [usernameStatus, setUsernameStatus] = useState(null) // null | 'checking' | 'available' | 'taken'
  const debounceRef = useRef(null)

  useEffect(() => {
    const name = form.username.trim()
    if (!name) { setUsernameStatus(null); return }
    setUsernameStatus('checking')
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get(`/auth/check-username?username=${encodeURIComponent(name)}`)
        setUsernameStatus(data.available ? 'available' : 'taken')
      } catch {
        setUsernameStatus(null)
      }
    }, 500)
    return () => clearTimeout(debounceRef.current)
  }, [form.username])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (usernameStatus === 'taken') {
      toast.error('Username already taken — please choose another')
      return
    }
    if (form.password !== form.confirm_password) {
      toast.error('Passwords do not match')
      return
    }
    if (form.password.length < 8) {
      toast.error('Password must be at least 8 characters')
      return
    }
    setLoading(true)
    try {
      const { confirm_password, ...payload } = form  // sponsor_username sent as-is
      await api.post('/auth/register', payload)
      toast.success('Account created! Check your email for OTP.')
      navigate(`/verify-email?email=${encodeURIComponent(form.email)}`)
    } catch (err) {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        toast.error(detail[0]?.msg || 'Registration failed')
      } else {
        toast.error(detail || 'Registration failed')
      }
    } finally {
      setLoading(false)
    }
  }

  const inputBase = {
    background: '#0E1117',
    border: '1px solid #1E2A38',
    color: '#fff',
  }

  const inputClass = 'w-full px-4 py-3 rounded-xl text-sm outline-none transition-all'

  const passwordMismatch = form.confirm_password && form.password !== form.confirm_password

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 py-8"
      style={{ background: 'linear-gradient(135deg, #080B10 0%, #0E1117 50%, #080B10 100%)' }}
    >
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, rgba(0,212,180,0.05) 0%, transparent 70%)' }}
      />

      <div className="w-full max-w-md relative">
        <div className="flex justify-center mb-8">
          <Logo size={36} />
        </div>

        <div className="rounded-2xl p-8" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <h1 className="text-2xl font-bold text-white mb-1">Create Account</h1>
          <p className="text-sm mb-1" style={{ color: '#8899AA' }}>Join Luxus — your sponsor's username is required</p>
          <p className="text-xs mb-6" style={{ color: '#4A5568' }}>
            Fields marked <span style={{ color: '#FF4D6A' }}>*</span> are required
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Sponsor Username */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>
                Sponsor Username<Required />
              </label>
              <input
                type="text"
                required
                value={form.sponsor_username}
                onChange={e => setForm(f => ({ ...f, sponsor_username: e.target.value }))}
                placeholder="Enter your sponsor's username"
                className={inputClass}
                style={inputBase}
                onFocus={e => e.target.style.borderColor = '#00D4B4'}
                onBlur={e => e.target.style.borderColor = '#1E2A38'}
              />
            </div>

            {/* Email */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>
                Email<Required />
              </label>
              <input
                type="email"
                required
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                placeholder="you@example.com"
                className={inputClass}
                style={inputBase}
                onFocus={e => e.target.style.borderColor = '#00D4B4'}
                onBlur={e => e.target.style.borderColor = '#1E2A38'}
              />
            </div>

            {/* Username */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>
                Username<Required />
              </label>
              <div className="relative">
                <input
                  type="text"
                  required
                  value={form.username}
                  onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                  placeholder="Choose a username"
                  className={inputClass}
                  style={{
                    ...inputBase,
                    paddingRight: '2.75rem',
                    borderColor: usernameStatus === 'taken' ? '#FF4D6A' : usernameStatus === 'available' ? '#00D4B4' : '#1E2A38',
                  }}
                  onFocus={e => { if (!usernameStatus || usernameStatus === 'checking') e.target.style.borderColor = '#00D4B4' }}
                  onBlur={e => { e.target.style.borderColor = usernameStatus === 'taken' ? '#FF4D6A' : usernameStatus === 'available' ? '#00D4B4' : '#1E2A38' }}
                />
                {usernameStatus === 'checking' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <Loader size={16} style={{ color: '#8899AA' }} className="animate-spin" />
                  </div>
                )}
                {usernameStatus === 'available' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <CheckCircle size={16} style={{ color: '#00D4B4' }} />
                  </div>
                )}
                {usernameStatus === 'taken' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <XCircle size={16} style={{ color: '#FF4D6A' }} />
                  </div>
                )}
              </div>
              {usernameStatus === 'taken' && (
                <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>
                  Username already taken — please try another
                </p>
              )}
              {usernameStatus === 'available' && (
                <p className="text-xs mt-1" style={{ color: '#00D4B4' }}>Username is available</p>
              )}
            </div>

            {/* Password */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>
                Password<Required />
              </label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  required
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder="Min. 8 characters"
                  className={inputClass}
                  style={{ ...inputBase, paddingRight: '3rem' }}
                  onFocus={e => e.target.style.borderColor = '#00D4B4'}
                  onBlur={e => e.target.style.borderColor = '#1E2A38'}
                />
                <button
                  type="button"
                  onClick={() => setShowPw(v => !v)}
                  className="absolute right-4 top-1/2 -translate-y-1/2"
                  style={{ color: '#8899AA' }}
                >
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Confirm Password */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>
                Confirm Password<Required />
              </label>
              <div className="relative">
                <input
                  type={showConfirm ? 'text' : 'password'}
                  required
                  value={form.confirm_password}
                  onChange={e => setForm(f => ({ ...f, confirm_password: e.target.value }))}
                  placeholder="Re-enter your password"
                  className={inputClass}
                  style={{
                    ...inputBase,
                    paddingRight: '3rem',
                    borderColor: passwordMismatch ? '#FF4D6A' : '#1E2A38',
                  }}
                  onFocus={e => { if (!passwordMismatch) e.target.style.borderColor = '#00D4B4' }}
                  onBlur={e => { e.target.style.borderColor = passwordMismatch ? '#FF4D6A' : '#1E2A38' }}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(v => !v)}
                  className="absolute right-4 top-1/2 -translate-y-1/2"
                  style={{ color: '#8899AA' }}
                >
                  {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {passwordMismatch && (
                <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>Passwords do not match</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || !!passwordMismatch || usernameStatus === 'taken'}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all mt-2"
              style={{
                background: (loading || passwordMismatch || usernameStatus === 'taken') ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                color: (loading || passwordMismatch || usernameStatus === 'taken') ? '#8899AA' : '#000',
                cursor: (loading || passwordMismatch || usernameStatus === 'taken') ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? (
                <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
              ) : (
                <><UserPlus size={16} /> Create Account</>
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-sm" style={{ color: '#8899AA' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: '#00D4B4' }} className="font-medium">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
