import { useState, useEffect, useRef } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import { useAuth } from '../../context/AuthContext'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Send, Wallet, ArrowRight, CheckCircle, XCircle, Loader } from 'lucide-react'
import { formatDateTimeIST } from '../../utils/datetime'

export default function AdminTransfer() {
  const [balance, setBalance] = useState(0)
  const [form, setForm] = useState({ to_username: '', amount: '' })
  const [loading, setLoading] = useState(false)
  const [activity, setActivity] = useState([])
  const { user } = useAuth()
  const [recipientStatus, setRecipientStatus] = useState(null) // null | checking | found | notfound | self
  const debounceRef = useRef(null)

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

  const refresh = () => {
    api.get('/admin/treasury/balance').then(r => setBalance(parseFloat(r.data.account_balance) || 0)).catch(() => {})
    api.get('/admin/treasury/activity')
      .then(r => setActivity(r.data.filter(t => t.transaction_type === 'transfer_out')))
      .catch(() => {})
  }

  useEffect(() => { refresh() }, [])

  const handleTransfer = async (e) => {
    e.preventDefault()
    if (recipientStatus === 'self') { toast.error('You cannot transfer to your own admin account'); return }
    if (recipientStatus === 'notfound') { toast.error('That username does not exist'); return }
    if (recipientStatus === 'checking') { toast.error('Still checking the username — please wait'); return }
    const amt = parseFloat(form.amount)
    if (!(amt > 0)) { toast.error('Enter an amount greater than zero'); return }
    if (amt > balance) { toast.error('Amount exceeds treasury balance'); return }
    setLoading(true)
    try {
      const { data } = await api.post('/admin/transfer', {
        to_username: form.to_username.trim(),
        amount: amt,
      })
      toast.success(`$${amt.toFixed(2)} sent to @${data.recipient_username}`)
      setBalance(parseFloat(data.account_balance) || 0)
      setForm({ to_username: '', amount: '' })
      refresh()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Transfer failed')
    } finally {
      setLoading(false)
    }
  }

  const amt = parseFloat(form.amount) || 0
  const remaining = balance - amt

  return (
    <Layout>
      <div className="space-y-6 fade-in max-w-lg">
        <div>
          <h1 className="text-2xl font-bold text-white">Send to User</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            Send treasury funds straight to a user's account balance by username.
            Credited in full, instantly — no fee.
          </p>
        </div>

        {/* Treasury balance */}
        <div
          className="rounded-xl p-4 flex items-center justify-between"
          style={{ background: '#141922', border: '1px solid rgba(0,212,180,0.2)' }}
        >
          <div>
            <p className="text-xs" style={{ color: '#8899AA' }}>Treasury Balance</p>
            <p className="text-2xl font-bold" style={{ color: '#00D4B4' }}>${balance.toFixed(2)}</p>
          </div>
          <Wallet size={24} style={{ color: '#00D4B4', opacity: 0.6 }} />
        </div>

        <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
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
                <p className="text-xs mt-1" style={{ color: '#FF4D6A' }}>You can't transfer to your own account</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Amount (USD)</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 font-semibold" style={{ color: '#8899AA' }}>$</span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                  value={form.amount}
                  onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
                  placeholder="0.00"
                  className="w-full pl-8 pr-4 py-3 rounded-xl text-sm outline-none"
                  style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
                  onFocus={e => e.target.style.borderColor = '#00D4B4'}
                  onBlur={e => e.target.style.borderColor = '#1E2A38'}
                />
              </div>
            </div>

            {amt > 0 && (
              <div className="rounded-lg p-3 text-xs space-y-1" style={{ background: '#0E1117' }}>
                <div className="flex justify-between" style={{ color: '#8899AA' }}>
                  <span>Recipient receives</span>
                  <span style={{ color: '#00D4B4' }}>${amt.toFixed(2)}</span>
                </div>
                <div className="flex justify-between font-semibold border-t pt-1" style={{ borderColor: '#1E2A38', color: '#fff' }}>
                  <span>Treasury after send</span>
                  <span style={{ color: remaining < 0 ? '#FF4D6A' : '#fff' }}>${remaining.toFixed(2)}</span>
                </div>
              </div>
            )}

            {(() => {
              const blocked = loading || amt <= 0 || amt > balance
                || recipientStatus === 'notfound' || recipientStatus === 'self' || recipientStatus === 'checking'
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
                    : <><Send size={14} /> Send Funds</>
                  }
                </button>
              )
            })()}
          </form>
        </div>

        {/* Recent transfers */}
        <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <div className="px-5 py-3.5" style={{ borderBottom: '1px solid #1E2A38' }}>
            <h2 className="font-semibold text-white text-sm">Recent Transfers</h2>
          </div>
          {activity.length === 0 ? (
            <div className="p-6 text-center text-sm" style={{ color: '#8899AA' }}>No transfers yet</div>
          ) : (
            <div className="row-divide">
              {activity.map(t => (
                <div key={t.id} className="flex items-center gap-3 px-5 py-3">
                  <ArrowRight size={16} style={{ color: '#FFB547' }} className="flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{t.notes || 'Transfer'}</p>
                    <p className="text-xs" style={{ color: '#4A5568' }}>{formatDateTimeIST(t.created_at)}</p>
                  </div>
                  <p className="text-sm font-semibold flex-shrink-0" style={{ color: '#FF4D6A' }}>
                    −${Math.abs(parseFloat(t.amount)).toFixed(2)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
