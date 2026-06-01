import { useState, useEffect, useRef } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Send, ShieldCheck, AlertCircle, Wallet, CheckCircle, XCircle, Loader } from 'lucide-react'

export default function Transfer() {
  const [step, setStep] = useState('form') // form | otp
  const [form, setForm] = useState({ to_username: '', amount: '' })
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const [needsOtp, setNeedsOtp] = useState(false)
  const [preview, setPreview] = useState(null)
  const [accountBalance, setAccountBalance] = useState(0)
  const { user } = useAuth()
  const [recipientStatus, setRecipientStatus] = useState(null) // null | checking | found | notfound | self
  const debounceRef = useRef(null)

  useEffect(() => {
    api.get('/deposit/balance')
      .then(r => setAccountBalance(parseFloat(r.data.account_balance) || 0))
      .catch(() => {})
  }, [])

  // Live recipient validation — debounced existence check (recipient must exist)
  useEffect(() => {
    const name = form.to_username.trim()
    if (!name) { setRecipientStatus(null); return }
    if (user && name.toLowerCase() === user.username.toLowerCase()) {
      setRecipientStatus('self'); return
    }
    setRecipientStatus('checking')
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get(`/auth/check-username?username=${encodeURIComponent(name)}`)
        // available === true => username is free => the user does NOT exist
        setRecipientStatus(data.available ? 'notfound' : 'found')
      } catch {
        setRecipientStatus(null)
      }
    }, 500)
    return () => clearTimeout(debounceRef.current)
  }, [form.to_username, user])

  const handleTransfer = async (e) => {
    e.preventDefault()
    if (recipientStatus === 'self') { toast.error('You cannot transfer to yourself'); return }
    if (recipientStatus === 'notfound') { toast.error('That username does not exist'); return }
    if (recipientStatus === 'checking') { toast.error('Still checking the username — please wait'); return }
    const amt = parseFloat(form.amount)
    if (amt < 1) { toast.error('Minimum transfer is $1'); return }
    setLoading(true)
    try {
      const { data } = await api.post('/deposit/transfer', {
        to_username: form.to_username,
        amount: amt,
      })
      setPreview({ ...form, amount: amt, fee: amt * 0.01, receive: amt * 0.99 })
      if (data.requires_verification) {
        setNeedsOtp(true)
        setStep('otp')
        toast.success('OTP sent to your email — first-time transfer to this user')
      } else {
        toast.success(`$${amt.toFixed(2)} transferred to ${form.to_username}!`)
        setForm({ to_username: '', amount: '' })
        api.get('/deposit/balance').then(r => setAccountBalance(parseFloat(r.data.account_balance) || 0)).catch(() => {})
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Transfer failed')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await api.post('/deposit/transfer/verify', {
        to_username: form.to_username,
        amount: parseFloat(form.amount),
        otp,
      })
      toast.success(`$${parseFloat(form.amount).toFixed(2)} transferred to ${form.to_username}!`)
      setStep('form')
      setOtp('')
      setPreview(null)
      setForm({ to_username: '', amount: '' })
      api.get('/deposit/balance').then(r => setAccountBalance(parseFloat(r.data.account_balance) || 0)).catch(() => {})
    } catch (err) {
      toast.error(err.response?.data?.detail || 'OTP verification failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Layout>
      <div className="space-y-6 fade-in max-w-lg">
        <div>
          <h1 className="text-2xl font-bold text-white">Transfer Balance</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            Send account balance to another user. 1% platform fee applies.
          </p>
        </div>

        {/* Account Balance Banner */}
        <div
          className="rounded-xl p-4 flex items-center justify-between"
          style={{ background: '#141922', border: '1px solid rgba(0,212,180,0.2)' }}
        >
          <div>
            <p className="text-xs" style={{ color: '#8899AA' }}>Account Balance</p>
            <p className="text-xl font-bold" style={{ color: '#00D4B4' }}>${accountBalance.toFixed(2)}</p>
          </div>
          <Wallet size={22} style={{ color: '#00D4B4', opacity: 0.6 }} />
        </div>

        <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          {step === 'form' ? (
            <form onSubmit={handleTransfer} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Recipient Username</label>
                <div className="relative">
                  <input
                    type="text"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    value={form.to_username}
                    onChange={e => setForm(f => ({ ...f, to_username: e.target.value }))}
                    placeholder="Enter username"
                    className="w-full px-4 py-3 rounded-xl text-sm outline-none"
                    style={{
                      background: '#0E1117', color: '#fff', paddingRight: '2.75rem',
                      border: `1px solid ${
                        recipientStatus === 'found' ? '#00D4B4'
                        : (recipientStatus === 'notfound' || recipientStatus === 'self') ? '#FF4D6A'
                        : '#1E2A38'
                      }`,
                    }}
                  />
                  {recipientStatus === 'checking' && (
                    <Loader size={16} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin" style={{ color: '#8899AA' }} />
                  )}
                  {recipientStatus === 'found' && (
                    <CheckCircle size={16} className="absolute right-3 top-1/2 -translate-y-1/2" style={{ color: '#00D4B4' }} />
                  )}
                  {(recipientStatus === 'notfound' || recipientStatus === 'self') && (
                    <XCircle size={16} className="absolute right-3 top-1/2 -translate-y-1/2" style={{ color: '#FF4D6A' }} />
                  )}
                </div>
                {recipientStatus === 'found' && (
                  <p className="text-xs mt-1" style={{ color: '#00D4B4' }}>User found</p>
                )}
                {recipientStatus === 'notfound' && (
                  <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>No user with that username</p>
                )}
                {recipientStatus === 'self' && (
                  <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>You can't transfer to yourself</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Amount (USD)</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 font-semibold" style={{ color: '#8899AA' }}>$</span>
                  <input
                    type="number"
                    min="1"
                    step="0.01"
                    required
                    value={form.amount}
                    onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
                    placeholder="1.00"
                    className="w-full pl-8 pr-4 py-3 rounded-xl text-sm outline-none"
                    style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
                    onFocus={e => e.target.style.borderColor = '#00D4B4'}
                    onBlur={e => e.target.style.borderColor = '#1E2A38'}
                  />
                </div>
              </div>

              {/* Fee Preview */}
              {parseFloat(form.amount) >= 1 && (
                <div className="rounded-lg p-3 text-xs space-y-1" style={{ background: '#0E1117' }}>
                  <div className="flex justify-between" style={{ color: '#8899AA' }}>
                    <span>Transfer amount</span>
                    <span className="text-white">${parseFloat(form.amount || 0).toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between" style={{ color: '#8899AA' }}>
                    <span>Platform fee (1%)</span>
                    <span style={{ color: '#FF4D6A' }}>−${(parseFloat(form.amount || 0) * 0.01).toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between font-semibold border-t pt-1" style={{ borderColor: '#1E2A38', color: '#fff' }}>
                    <span>Recipient receives</span>
                    <span style={{ color: '#00D4B4' }}>${(parseFloat(form.amount || 0) * 0.99).toFixed(2)}</span>
                  </div>
                </div>
              )}

              <div className="rounded-lg px-3 py-2 flex gap-2 text-xs" style={{ background: 'rgba(255,181,71,0.08)', border: '1px solid rgba(255,181,71,0.2)', color: '#FFB547' }}>
                <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
                <span>First transfer to a new recipient requires email OTP verification</span>
              </div>

              {(() => {
                const blocked = loading || recipientStatus === 'notfound' || recipientStatus === 'self' || recipientStatus === 'checking'
                return (
                  <button
                    type="submit"
                    disabled={blocked}
                    className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
                    style={{
                      background: blocked ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                      color: blocked ? '#8899AA' : '#000',
                      cursor: blocked ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {loading
                      ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                      : <><Send size={14} /> Send Transfer</>
                    }
                  </button>
                )
              })()}
            </form>
          ) : (
            <form onSubmit={handleVerify} className="space-y-4">
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto"
                style={{ background: 'rgba(0,212,180,0.12)', border: '1px solid rgba(0,212,180,0.3)' }}
              >
                <ShieldCheck size={28} style={{ color: '#00D4B4' }} />
              </div>
              <h2 className="text-lg font-semibold text-white text-center">Verify Transfer</h2>
              {preview && (
                <div className="rounded-lg p-3 text-xs space-y-1 text-center" style={{ background: '#0E1117' }}>
                  <p style={{ color: '#8899AA' }}>Sending to <span className="text-white font-medium">{preview.to_username}</span></p>
                  <p className="text-lg font-bold" style={{ color: '#00D4B4' }}>${preview.receive.toFixed(2)}</p>
                  <p style={{ color: '#4A5568' }}>after 1% fee</p>
                </div>
              )}
              <div>
                <label className="block text-sm font-medium mb-2 text-center" style={{ color: '#8899AA' }}>
                  Enter OTP from your email
                </label>
                <input
                  type="text"
                  required
                  maxLength={6}
                  value={otp}
                  onChange={e => setOtp(e.target.value.replace(/\D/g, ''))}
                  placeholder="000000"
                  className="w-full px-4 py-3 rounded-xl text-center text-2xl font-bold tracking-widest outline-none"
                  style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
                  onFocus={e => e.target.style.borderColor = '#00D4B4'}
                  onBlur={e => e.target.style.borderColor = '#1E2A38'}
                />
              </div>
              <button
                type="submit"
                disabled={loading || otp.length < 6}
                className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
                style={{
                  background: (loading || otp.length < 6) ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                  color: (loading || otp.length < 6) ? '#8899AA' : '#000',
                  cursor: (loading || otp.length < 6) ? 'not-allowed' : 'pointer',
                }}
              >
                {loading
                  ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                  : 'Confirm Transfer'
                }
              </button>
              <button
                type="button"
                onClick={() => { setStep('form'); setOtp('') }}
                className="w-full py-2.5 rounded-xl text-sm"
                style={{ border: '1px solid #1E2A38', color: '#8899AA', background: 'transparent' }}
              >
                Cancel
              </button>
            </form>
          )}
        </div>
      </div>
    </Layout>
  )
}
