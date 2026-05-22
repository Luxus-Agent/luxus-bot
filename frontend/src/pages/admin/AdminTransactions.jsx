import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Activity, Search } from 'lucide-react'

const TX_COLOR = {
  DEPOSIT: '#00D4B4', PROACTIVE_INCOME: '#00D4B4', PROPORTION_PAYOUT: '#3498DB',
  SPECULATION_PAYOUT: '#9B59B6', SPONSOR_MILESTONE_INCOME: '#00D4B4',
  TRANSFER_IN: '#00D4B4', WITHDRAWAL: '#FF4D6A', TRANSFER_OUT: '#FF4D6A',
  REPURCHASE_HOLD: '#FFB547', REENTRY: '#8899AA', PURCHASE: '#FF4D6A', AGENT_PURCHASE: '#FF4D6A',
}
const NEGATIVE = ['WITHDRAWAL', 'TRANSFER_OUT', 'PURCHASE', 'AGENT_PURCHASE']

export default function AdminTransactions() {
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('all')

  useEffect(() => {
    api.get('/admin/transactions')
      .then(r => setTransactions(r.data))
      .catch(() => toast.error('Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  const txTypes = [...new Set(transactions.map(t => t.transaction_type))]

  const filtered = transactions.filter(t => {
    if (filterType !== 'all' && t.transaction_type !== filterType) return false
    if (search && !String(t.user_id).includes(search) && !t.transaction_type.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const totalVolume = transactions
    .filter(t => !NEGATIVE.includes(t.transaction_type))
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
      </div>
    </Layout>
  )

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Transactions Monitor</h1>
            <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
              {transactions.length} records — ${totalVolume.toFixed(2)} total volume
            </p>
          </div>
          <div className="flex gap-2">
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#4A5568' }} />
              <input
                type="text"
                placeholder="Search..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-8 pr-4 py-2 rounded-xl text-sm outline-none w-48"
                style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
              />
            </div>
            <select
              value={filterType}
              onChange={e => setFilterType(e.target.value)}
              className="px-3 py-2 rounded-xl text-sm outline-none"
              style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
            >
              <option value="all">All Types</option>
              {txTypes.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
            </select>
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <div
            className="hidden sm:grid grid-cols-6 px-5 py-3 text-xs font-semibold uppercase tracking-wider"
            style={{ background: '#0E1117', color: '#4A5568', borderBottom: '1px solid #1E2A38' }}
          >
            <span className="col-span-2">Type</span>
            <span>User</span>
            <span>Tier</span>
            <span>Date</span>
            <span className="text-right">Amount</span>
          </div>

          <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
            {filtered.length === 0 ? (
              <div className="p-8 text-center" style={{ color: '#8899AA' }}>
                <Activity size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">No transactions found</p>
              </div>
            ) : filtered.map(tx => {
              const isNeg = NEGATIVE.includes(tx.transaction_type)
              const color = TX_COLOR[tx.transaction_type] || '#8899AA'
              return (
                <div key={tx.id} className="flex sm:grid sm:grid-cols-6 items-center gap-3 px-5 py-3">
                  <div className="col-span-2 flex items-center gap-2 min-w-0">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">
                        {tx.transaction_type.replace(/_/g, ' ')}
                      </p>
                      {tx.notes && <p className="text-xs truncate" style={{ color: '#4A5568' }}>{tx.notes}</p>}
                    </div>
                  </div>
                  <span className="hidden sm:block text-xs" style={{ color: '#8899AA' }}>#{tx.user_id}</span>
                  <span className="hidden sm:block text-xs" style={{ color: '#8899AA' }}>
                    {tx.agent_tier === 0 ? 'Acct' : `A${tx.agent_tier}`}
                  </span>
                  <span className="hidden sm:block text-xs" style={{ color: '#4A5568' }}>
                    {new Date(tx.created_at).toLocaleDateString()}
                  </span>
                  <p className="text-sm font-semibold ml-auto sm:ml-0 text-right" style={{ color: isNeg ? '#FF4D6A' : '#00D4B4' }}>
                    {isNeg ? '−' : '+'}${Math.abs(parseFloat(tx.amount)).toFixed(2)}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </Layout>
  )
}
