import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { ArrowDownToLine, ExternalLink, Copy, Check, Clock, CheckCircle, XCircle, RefreshCw } from 'lucide-react'

export default function Deposit() {
  const [balance, setBalance] = useState(0)
  const [deposits, setDeposits] = useState([])
  const [loading, setLoading] = useState(true)
  const [amount, setAmount] = useState('')
  const [creating, setCreating] = useState(false)
  const [invoiceUrl, setInvoiceUrl] = useState(null)
  const [copied, setCopied] = useState(false)

  const load = () =>
    Promise.all([api.get('/deposit/balance'), api.get('/deposit')])
      .then(([b, d]) => { setBalance(parseFloat(b.data.account_balance) || 0); setDeposits(d.data) })
      .catch(() => toast.error('Failed to load'))
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (amt < 10) { toast.error('Minimum deposit is $10'); return }
    setCreating(true)
    try {
      const { data } = await api.post('/deposit', { amount_usd: amt })
      setInvoiceUrl(data.invoice_url)
      toast.success('Invoice created! Complete payment to credit your account.')
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create deposit')
    } finally {
      setCreating(false)
    }
  }

  const copyUrl = () => {
    navigator.clipboard.writeText(invoiceUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const statusIcon = { pending: Clock, completed: CheckCircle, failed: XCircle }
  const statusColor = { pending: '#FFB547', completed: '#00D4B4', failed: '#FF4D6A' }

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
      </div>
    </Layout>
  )

  return (
    <Layout>
      <div className="space-y-6 fade-in max-w-2xl">
        <div>
          <h1 className="text-2xl font-bold text-white">Deposit USDT</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>Top up your account balance via USDT BEP-20</p>
        </div>

        {/* Current Balance */}
        <div
          className="rounded-xl p-5 flex items-center justify-between"
          style={{ background: '#141922', border: '1px solid rgba(0,212,180,0.2)' }}
        >
          <div>
            <p className="text-sm" style={{ color: '#8899AA' }}>Current Account Balance</p>
            <p className="text-3xl font-bold mt-1" style={{ color: '#00D4B4' }}>${balance.toFixed(2)}</p>
          </div>
          <div
            className="w-14 h-14 rounded-xl flex items-center justify-center"
            style={{ background: 'rgba(0,212,180,0.1)', border: '1px solid rgba(0,212,180,0.2)' }}
          >
            <ArrowDownToLine size={26} style={{ color: '#00D4B4' }} />
          </div>
        </div>

        {/* Deposit Form */}
        <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <h2 className="font-semibold text-white mb-4">Create Deposit Invoice</h2>

          {invoiceUrl ? (
            <div className="space-y-4">
              <div
                className="rounded-xl p-4"
                style={{ background: 'rgba(0,212,180,0.05)', border: '1px solid rgba(0,212,180,0.2)' }}
              >
                <p className="text-sm font-semibold mb-2" style={{ color: '#00D4B4' }}>Invoice Created</p>
                <p className="text-xs mb-3" style={{ color: '#8899AA' }}>
                  Complete your USDT BEP-20 payment using the link below. Your account will be credited automatically.
                </p>
                <div className="flex gap-2">
                  <a
                    href={invoiceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 py-2.5 px-4 rounded-lg text-sm font-semibold flex items-center justify-center gap-2"
                    style={{ background: '#00D4B4', color: '#000' }}
                  >
                    <ExternalLink size={14} />
                    Open Payment Page
                  </a>
                  <button
                    onClick={copyUrl}
                    className="px-3 rounded-lg"
                    style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#8899AA' }}
                  >
                    {copied ? <Check size={16} style={{ color: '#00D4B4' }} /> : <Copy size={16} />}
                  </button>
                </div>
              </div>
              <button
                onClick={() => setInvoiceUrl(null)}
                className="w-full py-2.5 rounded-xl text-sm"
                style={{ border: '1px solid #1E2A38', color: '#8899AA', background: 'transparent' }}
              >
                Create Another Deposit
              </button>
            </div>
          ) : (
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>
                  Amount (USD)
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 font-semibold" style={{ color: '#8899AA' }}>$</span>
                  <input
                    type="number"
                    min="10"
                    step="0.01"
                    required
                    value={amount}
                    onChange={e => setAmount(e.target.value)}
                    placeholder="10.00"
                    className="w-full pl-8 pr-4 py-3 rounded-xl text-sm outline-none"
                    style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
                    onFocus={e => e.target.style.borderColor = '#00D4B4'}
                    onBlur={e => e.target.style.borderColor = '#1E2A38'}
                  />
                </div>
                <p className="text-xs mt-1" style={{ color: '#4A5568' }}>Minimum deposit: $10.00</p>
              </div>

              {/* Quick amounts */}
              <div className="flex gap-2 flex-wrap">
                {[10, 20, 50, 100, 200].map(a => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => setAmount(String(a))}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                    style={parseFloat(amount) === a
                      ? { background: 'rgba(0,212,180,0.15)', color: '#00D4B4', border: '1px solid rgba(0,212,180,0.4)' }
                      : { background: '#0E1117', color: '#8899AA', border: '1px solid #1E2A38' }
                    }
                  >
                    ${a}
                  </button>
                ))}
              </div>

              <button
                type="submit"
                disabled={creating}
                className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
                style={{
                  background: creating ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                  color: creating ? '#8899AA' : '#000',
                  cursor: creating ? 'not-allowed' : 'pointer',
                }}
              >
                {creating
                  ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                  : <><ArrowDownToLine size={16} /> Generate Invoice</>
                }
              </button>

              <div className="rounded-lg px-4 py-3 text-xs" style={{ background: '#0E1117', color: '#8899AA' }}>
                <p className="font-medium mb-1 text-white">How it works:</p>
                <p>1. Enter amount and click Generate Invoice</p>
                <p>2. Open the NOWPayments page and send USDT BEP-20</p>
                <p>3. Your balance is credited automatically on confirmation</p>
              </div>
            </form>
          )}
        </div>

        {/* Deposit History */}
        {deposits.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-white">Deposit History</h2>
              <button onClick={load} className="p-1.5 rounded-lg" style={{ color: '#8899AA' }}>
                <RefreshCw size={16} />
              </button>
            </div>
            <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
                {deposits.map(d => {
                  const Icon = statusIcon[d.status] || Clock
                  const color = statusColor[d.status] || '#8899AA'
                  return (
                    <div key={d.id} className="flex items-center gap-3 px-4 py-3">
                      <Icon size={18} style={{ color }} className="flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white">${parseFloat(d.amount_usd).toFixed(2)} USDT</p>
                        <p className="text-xs" style={{ color: '#4A5568' }}>
                          {new Date(d.created_at).toLocaleString()}
                        </p>
                      </div>
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0"
                        style={{ background: `${color}18`, color }}
                      >
                        {d.status.toUpperCase()}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  )
}
