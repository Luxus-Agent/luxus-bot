import { useState, useEffect } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Coins, Wallet, PlusCircle } from 'lucide-react'
import { formatDateTimeIST } from '../../utils/datetime'

export default function AdminGenerate() {
  const [summary, setSummary] = useState({ account_balance: 0, total_generated: 0 })
  const [amount, setAmount] = useState('')
  const [loading, setLoading] = useState(false)
  const [activity, setActivity] = useState([])

  const refresh = () => {
    api.get('/admin/treasury/summary').then(r => setSummary(r.data)).catch(() => {})
    api.get('/admin/treasury/activity')
      .then(r => setActivity(r.data.filter(t => t.transaction_type === 'admin_generate')))
      .catch(() => {})
  }

  useEffect(() => { refresh() }, [])

  const handleGenerate = async (e) => {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (!(amt > 0)) { toast.error('Enter an amount greater than zero'); return }
    setLoading(true)
    try {
      await api.post('/admin/generate', { amount: amt })
      toast.success(`$${amt.toFixed(2)} generated into treasury`)
      setAmount('')
      refresh()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Generate failed')
    } finally {
      setLoading(false)
    }
  }

  const QUICK = [100, 1000, 5000, 10000]

  return (
    <Layout>
      <div className="space-y-6 fade-in max-w-lg">
        <div>
          <h1 className="text-2xl font-bold text-white">Generate Funds</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            Mint funds into your treasury after receiving payment off-platform (cash, GPay,
            cheque, crypto).
          </p>
        </div>

        {/* Balances */}
        <div className="grid grid-cols-2 gap-4">
          <div
            className="rounded-xl p-4 flex items-center justify-between"
            style={{ background: '#141922', border: '1px solid rgba(0,212,180,0.2)' }}
          >
            <div>
              <p className="text-xs" style={{ color: '#8899AA' }}>Treasury Balance</p>
              <p className="text-2xl font-bold" style={{ color: '#00D4B4' }}>${(summary.account_balance || 0).toFixed(2)}</p>
              <p className="text-xs mt-0.5" style={{ color: '#4A5568' }}>Available to send</p>
            </div>
            <Wallet size={22} style={{ color: '#00D4B4', opacity: 0.6 }} />
          </div>
          <div
            className="rounded-xl p-4 flex items-center justify-between"
            style={{ background: '#141922', border: '1px solid rgba(255,181,71,0.2)' }}
          >
            <div>
              <p className="text-xs" style={{ color: '#8899AA' }}>Total Generated</p>
              <p className="text-2xl font-bold" style={{ color: '#FFB547' }}>${(summary.total_generated || 0).toFixed(2)}</p>
              <p className="text-xs mt-0.5" style={{ color: '#4A5568' }}>Minted to date</p>
            </div>
            <Coins size={22} style={{ color: '#FFB547', opacity: 0.6 }} />
          </div>
        </div>

        <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <form onSubmit={handleGenerate} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Amount (USD)</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 font-semibold" style={{ color: '#8899AA' }}>$</span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                  value={amount}
                  onChange={e => setAmount(e.target.value)}
                  placeholder="10000.00"
                  className="w-full pl-8 pr-4 py-3 rounded-xl text-sm outline-none"
                  style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
                  onFocus={e => e.target.style.borderColor = '#00D4B4'}
                  onBlur={e => e.target.style.borderColor = '#1E2A38'}
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {QUICK.map(q => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setAmount(String(q))}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                  style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#8899AA' }}
                >
                  +${q.toLocaleString()}
                </button>
              ))}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
              style={{
                background: loading ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                color: loading ? '#8899AA' : '#000',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading
                ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                : <><PlusCircle size={15} /> Generate Funds</>
              }
            </button>
          </form>
        </div>

        {/* Recent generated */}
        <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <div className="px-5 py-3.5" style={{ borderBottom: '1px solid #1E2A38' }}>
            <h2 className="font-semibold text-white text-sm">Recently Generated</h2>
          </div>
          {activity.length === 0 ? (
            <div className="p-6 text-center text-sm" style={{ color: '#8899AA' }}>Nothing generated yet</div>
          ) : (
            <div className="row-divide">
              {activity.map(t => (
                <div key={t.id} className="flex items-center gap-3 px-5 py-3">
                  <Coins size={16} style={{ color: '#00D4B4' }} className="flex-shrink-0" />
                  <p className="flex-1 text-xs" style={{ color: '#4A5568' }}>
                    {formatDateTimeIST(t.created_at)}
                  </p>
                  <p className="text-sm font-semibold" style={{ color: '#00D4B4' }}>
                    +${Math.abs(parseFloat(t.amount)).toFixed(2)}
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
