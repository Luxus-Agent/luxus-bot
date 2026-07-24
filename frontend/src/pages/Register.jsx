import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import Logo from '../components/Logo'
import toast from 'react-hot-toast'
import { Eye, EyeOff, UserPlus, CheckCircle, XCircle, Loader, Wallet, Link2 } from 'lucide-react'
import { useAppKit, useAppKitAccount, useDisconnect } from '@reown/appkit/react'


export default function Register() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [form, setForm] = useState({
    email: '',
    username: '',
    password: '',
    confirm_password: '',
    sponsor_username: params.get('ref') || '',
    wallet_address: '',
  })
  const [showPw, setShowPw] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [usernameStatus, setUsernameStatus] = useState(null) // null | 'checking' | 'available' | 'taken'
  const [sponsorStatus, setSponsorStatus] = useState(null)   // null | 'checking' | 'valid' | 'invalid'
  const [walletStatus, setWalletStatus] = useState(null)     // null | 'checking' | 'available' | 'taken'
  const debounceRef = useRef(null)
  const sponsorDebounceRef = useRef(null)
  const walletDebounceRef = useRef(null)

  // ── Wallet connect (Reown AppKit) ──────────────────────────────────────────
  // Works on web and inside in-app dApp browsers (TokenPocket, MetaMask, etc.).
  // When a wallet is connected, its address takes over the field (read-only);
  // otherwise the user can paste an address manually.
  const { open: openWallet } = useAppKit()
  const { address, isConnected } = useAppKitAccount()
  const { disconnect } = useDisconnect()

  // The address we actually register with: connected wallet wins, else the
  // manually pasted value.
  const effectiveWallet = (isConnected && address ? address : form.wallet_address).trim()
  const walletValid = /^0x[a-fA-F0-9]{40}$/.test(effectiveWallet)

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

  // Sponsor must be an EXISTING username — reuse check-username, inverted:
  // available === true  → no such user → invalid sponsor
  // available === false → username taken → the sponsor exists → valid
  useEffect(() => {
    const name = form.sponsor_username.trim()
    if (!name) { setSponsorStatus(null); return }
    setSponsorStatus('checking')
    clearTimeout(sponsorDebounceRef.current)
    sponsorDebounceRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get(`/auth/check-username?username=${encodeURIComponent(name)}`)
        setSponsorStatus(data.available ? 'invalid' : 'valid')
      } catch {
        setSponsorStatus(null)
      }
    }, 500)
    return () => clearTimeout(sponsorDebounceRef.current)
  }, [form.sponsor_username])

  // Each wallet address may only be attached to one account — checked live
  // whether it came from a connected wallet or a manually pasted address.
  useEffect(() => {
    if (!walletValid) { setWalletStatus(null); return }
    setWalletStatus('checking')
    clearTimeout(walletDebounceRef.current)
    walletDebounceRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get(`/auth/check-wallet-address?wallet_address=${encodeURIComponent(effectiveWallet)}`)
        setWalletStatus(data.available ? 'available' : 'taken')
      } catch {
        setWalletStatus(null)
      }
    }, 500)
    return () => clearTimeout(walletDebounceRef.current)
  }, [effectiveWallet, walletValid])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (sponsorStatus === 'invalid') {
      toast.error('Sponsor username not found — enter an existing sponsor')
      return
    }
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
    if (!walletValid) {
      toast.error('Connect a wallet or enter a valid BEP-20 address (0x + 40 hex characters)')
      return
    }
    if (walletStatus === 'taken') {
      toast.error('This wallet address is already registered to another account')
      return
    }
    setLoading(true)
    try {
      const payload = {
        email: form.email,
        username: form.username,
        password: form.password,
        sponsor_username: form.sponsor_username,
        wallet_address: effectiveWallet,
      }
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
    background: 'var(--bg-surface)',
    border: '1px solid var(--border)',
    color: 'var(--text-primary)',
  }

  const inputClass = 'w-full px-4 py-3 rounded-xl text-sm outline-none transition-all'

  const passwordMismatch = form.confirm_password && form.password !== form.confirm_password
  // Red-border feedback for the manual paste field (only when not connected).
  const walletInvalid = !isConnected && form.wallet_address.trim() && !walletValid
  const walletTaken = walletStatus === 'taken'

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 py-8"
      style={{ background: 'linear-gradient(135deg, var(--bg-page) 0%, var(--bg-surface) 50%, var(--bg-page) 100%)' }}
    >
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, rgba(var(--accent-rgb),0.05) 0%, transparent 70%)' }}
      />

      <div className="w-full max-w-md relative">
        <div className="flex justify-center mb-8">
          <Logo size={36} />
        </div>

        <div className="rounded-2xl p-8" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          <h1 className="text-2xl font-bold text-white mb-1">Create Account</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--text-secondary)' }}>Join Luxus — all fields are required</p>

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Sponsor Username */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                Sponsor Username              </label>
              <div className="relative">
                <input
                  type="text"
                  required
                  value={form.sponsor_username}
                  onChange={e => setForm(f => ({ ...f, sponsor_username: e.target.value }))}
                  placeholder="Enter your sponsor's username"
                  className={inputClass}
                  style={{
                    ...inputBase,
                    paddingRight: '2.75rem',
                    borderColor: sponsorStatus === 'invalid' ? '#FF4D6A' : sponsorStatus === 'valid' ? 'var(--accent)' : 'var(--border)',
                  }}
                  onFocus={e => { if (!sponsorStatus || sponsorStatus === 'checking') e.target.style.borderColor = 'var(--accent)' }}
                  onBlur={e => { e.target.style.borderColor = sponsorStatus === 'invalid' ? '#FF4D6A' : sponsorStatus === 'valid' ? 'var(--accent)' : 'var(--border)' }}
                />
                {sponsorStatus === 'checking' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <Loader size={16} style={{ color: 'var(--text-secondary)' }} className="animate-spin" />
                  </div>
                )}
                {sponsorStatus === 'valid' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <CheckCircle size={16} style={{ color: 'var(--accent)' }} />
                  </div>
                )}
                {sponsorStatus === 'invalid' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <XCircle size={16} style={{ color: '#FF4D6A' }} />
                  </div>
                )}
              </div>
              {sponsorStatus === 'invalid' && (
                <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>
                  No user with this username — enter an existing sponsor
                </p>
              )}
              {sponsorStatus === 'valid' && (
                <p className="text-xs mt-1" style={{ color: 'var(--accent)' }}>Sponsor found</p>
              )}
            </div>

            {/* BEP-20 Wallet Address */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                BEP-20 Wallet Address
              </label>

              {isConnected && address ? (
                /* Connected: show the address read-only with a disconnect option */
                <div
                  className="rounded-xl px-4 py-3 flex items-center gap-3"
                  style={{ ...inputBase, borderColor: walletTaken ? '#FF4D6A' : 'rgba(var(--accent-rgb),0.45)' }}
                >
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: walletTaken ? 'rgba(255,77,106,0.12)' : 'rgba(var(--accent-rgb),0.12)' }}
                  >
                    <Wallet size={16} style={{ color: walletTaken ? '#FF4D6A' : 'var(--accent)' }} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs" style={{ color: walletTaken ? '#FF4D6A' : 'var(--accent)' }}>
                      {walletTaken ? 'Already registered' : 'Wallet connected'}
                    </p>
                    <p
                      className="text-sm truncate"
                      style={{ color: 'var(--text-primary)', fontFamily: 'monospace' }}
                      title={address}
                    >
                      {address}
                    </p>
                  </div>
                  {walletStatus === 'checking' && (
                    <Loader size={16} style={{ color: 'var(--text-secondary)' }} className="animate-spin flex-shrink-0" />
                  )}
                  <button
                    type="button"
                    onClick={() => disconnect()}
                    className="text-xs font-medium flex-shrink-0 px-2 py-1 rounded-lg"
                    style={{ color: '#FF4D6A', background: 'rgba(255,77,106,0.08)' }}
                  >
                    Disconnect
                  </button>
                </div>
              ) : (
                /* Not connected: paste manually OR connect a wallet */
                <>
                  <div className="relative">
                    <input
                      type="text"
                      value={form.wallet_address}
                      onChange={e => setForm(f => ({ ...f, wallet_address: e.target.value }))}
                      placeholder="0x… (paste your USDT BEP-20 address)"
                      className={inputClass}
                      style={{
                        ...inputBase,
                        paddingRight: '2.75rem',
                        borderColor: (walletInvalid || walletTaken) ? '#FF4D6A' : walletStatus === 'available' ? 'var(--accent)' : 'var(--border)',
                        fontFamily: 'monospace',
                      }}
                      onFocus={e => { if (!walletInvalid && !walletTaken) e.target.style.borderColor = 'var(--accent)' }}
                      onBlur={e => { e.target.style.borderColor = (walletInvalid || walletTaken) ? '#FF4D6A' : walletStatus === 'available' ? 'var(--accent)' : 'var(--border)' }}
                    />
                    {walletStatus === 'checking' && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2">
                        <Loader size={16} style={{ color: 'var(--text-secondary)' }} className="animate-spin" />
                      </div>
                    )}
                    {walletStatus === 'available' && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2">
                        <CheckCircle size={16} style={{ color: 'var(--accent)' }} />
                      </div>
                    )}
                    {walletTaken && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2">
                        <XCircle size={16} style={{ color: '#FF4D6A' }} />
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-3 my-2">
                    <div className="flex-1 h-px" style={{ background: 'var(--border)' }} />
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>or</span>
                    <div className="flex-1 h-px" style={{ background: 'var(--border)' }} />
                  </div>
                  <button
                    type="button"
                    onClick={() => openWallet()}
                    className="w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all"
                    style={{ background: 'rgba(var(--accent-rgb),0.12)', color: 'var(--accent)', border: '1px solid rgba(var(--accent-rgb),0.35)' }}
                  >
                    <Link2 size={16} /> Connect Wallet
                  </button>
                </>
              )}

              {walletInvalid ? (
                <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>
                  Must be 0x followed by 40 hex characters
                </p>
              ) : walletTaken ? (
                <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>
                  This wallet address is already registered to another account
                </p>
              ) : walletStatus === 'available' ? (
                <p className="text-xs mt-1" style={{ color: 'var(--accent)' }}>Wallet address is available</p>
              ) : (
                <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
                  Profits and payouts are sent to this address — double-check it.
                </p>
              )}
            </div>

            {/* Email */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                Email              </label>
              <input
                type="email"
                required
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                placeholder="you@example.com"
                className={inputClass}
                style={inputBase}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
            </div>

            {/* Username */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                Username              </label>
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
                    borderColor: usernameStatus === 'taken' ? '#FF4D6A' : usernameStatus === 'available' ? 'var(--accent)' : 'var(--border)',
                  }}
                  onFocus={e => { if (!usernameStatus || usernameStatus === 'checking') e.target.style.borderColor = 'var(--accent)' }}
                  onBlur={e => { e.target.style.borderColor = usernameStatus === 'taken' ? '#FF4D6A' : usernameStatus === 'available' ? 'var(--accent)' : 'var(--border)' }}
                />
                {usernameStatus === 'checking' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <Loader size={16} style={{ color: 'var(--text-secondary)' }} className="animate-spin" />
                  </div>
                )}
                {usernameStatus === 'available' && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <CheckCircle size={16} style={{ color: 'var(--accent)' }} />
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
                <p className="text-xs mt-1" style={{ color: 'var(--accent)' }}>Username is available</p>
              )}
            </div>

            {/* Password */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                Password              </label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  required
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder="Min. 8 characters"
                  className={inputClass}
                  style={{ ...inputBase, paddingRight: '3rem' }}
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
            </div>

            {/* Confirm Password */}
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                Confirm Password              </label>
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
                    borderColor: passwordMismatch ? '#FF4D6A' : 'var(--border)',
                  }}
                  onFocus={e => { if (!passwordMismatch) e.target.style.borderColor = 'var(--accent)' }}
                  onBlur={e => { e.target.style.borderColor = passwordMismatch ? '#FF4D6A' : 'var(--border)' }}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(v => !v)}
                  className="absolute right-4 top-1/2 -translate-y-1/2"
                  style={{ color: 'var(--text-secondary)' }}
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
              disabled={loading || !!passwordMismatch || !walletValid || walletTaken || usernameStatus === 'taken' || sponsorStatus === 'invalid'}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all mt-2"
              style={{
                background: (loading || passwordMismatch || !walletValid || walletTaken || usernameStatus === 'taken' || sponsorStatus === 'invalid') ? 'rgba(var(--accent-rgb),0.3)' : 'var(--accent)',
                color: (loading || passwordMismatch || !walletValid || walletTaken || usernameStatus === 'taken' || sponsorStatus === 'invalid') ? 'var(--text-secondary)' : '#000',
                cursor: (loading || passwordMismatch || !walletValid || walletTaken || usernameStatus === 'taken' || sponsorStatus === 'invalid') ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? (
                <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
              ) : (
                <><UserPlus size={16} /> Create Account</>
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: 'var(--accent)' }} className="font-medium">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
