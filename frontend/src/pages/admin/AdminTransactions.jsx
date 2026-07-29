import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import Pagination from '../../components/Pagination'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Activity, Search, ExternalLink } from 'lucide-react'
import { formatDateIST } from '../../utils/datetime'
import { txExplorerUrl, shortenTxHash } from '../../utils/explorer'

const PAGE_SIZE = 10

// API serializes the TransactionType enum's lowercase *values* (e.g. "agent_purchase"),
// so all keys/lists here must be lowercase to match.
const TX_COLOR = {
  deposit: 'var(--accent)', core_income: 'var(--accent)', stream_payout: '#3498DB',
  boost_payout: '#9B59B6', sponsor_milestone_income: 'var(--accent)',
  transfer_in: 'var(--accent)', withdrawal: '#FF4D6A', transfer_out: '#FF4D6A',
  repurchase_hold: '#FFB547', reentry: 'var(--text-secondary)', purchase: '#FF4D6A', agent_purchase: '#FF4D6A',
  core_sent: 'var(--text-secondary)', software_fee: 'var(--text-secondary)', platform_profit: 'var(--text-secondary)', admin_generate: 'var(--accent)',
  withdrawal_refund: '#FFB547',
}
const INCOME = ['core_income', 'stream_payout', 'boost_payout', 'sponsor_milestone_income', 'transfer_in', 'deposit']
const EXPENSE = ['withdrawal', 'transfer_out', 'purchase', 'agent_purchase']
// Still moving through the platform, not yet delivered to the user's real wallet —
// same definition as the user-facing Transactions page (see PENDING there).
const PENDING = ['repurchase_hold', 'stream_payout', 'boost_payout', 'sponsor_milestone_income']

export default function AdminTransactions() {
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('all')
  const [filterStatus, setFilterStatus] = useState('all')
  const [page, setPage] = useState(1)

  useEffect(() => {
    api.get('/admin/transactions')
      .then(r => setTransactions(r.data))
      .catch(() => toast.error('Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  const txTypes = [...new Set(transactions.map(t => t.transaction_type))]

  const filtered = transactions.filter(t => {
    if (filterType !== 'all' && t.transaction_type !== filterType) return false
    if (filterStatus !== 'all') {
      const isPending = PENDING.includes(t.transaction_type)
      if (filterStatus === 'Pending' && !isPending) return false
      if (filterStatus === 'Completed' && isPending) return false
    }
    if (search) {
      const q = search.toLowerCase()
      const hay = `${t.user_id} ${t.username || ''} ${t.transaction_type} ${t.notes || ''} ${t.tx_hash || ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const totalVolume = transactions
    .filter(t => INCOME.includes(t.transaction_type))
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: 'var(--accent)' }} />
      </div>
    </Layout>
  )

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Transactions Monitor</h1>
            <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
              {transactions.length} records — ${totalVolume.toFixed(2)} total volume
            </p>
          </div>
          <div className="flex gap-2">
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="Search..."
                value={search}
                onChange={e => { setSearch(e.target.value); setPage(1) }}
                className="pl-8 pr-4 py-2 rounded-xl text-sm outline-none w-48"
                style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
              />
            </div>
            <select
              value={filterType}
              onChange={e => { setFilterType(e.target.value); setPage(1) }}
              className="px-3 py-2 rounded-xl text-sm outline-none"
              style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            >
              <option value="all">All Types</option>
              {txTypes.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
            </select>
            <select
              value={filterStatus}
              onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
              className="px-3 py-2 rounded-xl text-sm outline-none"
              style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            >
              <option value="all">All Status</option>
              <option value="Completed">Completed</option>
              <option value="Pending">Pending</option>
            </select>
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          <div
            className="hidden sm:grid grid-cols-8 px-5 py-3 text-xs font-semibold uppercase tracking-wider"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}
          >
            <span className="col-span-2">Type</span>
            <span>User</span>
            <span>Tier</span>
            <span>Status</span>
            <span>Date</span>
            <span>Tx Hash</span>
            <span className="text-right">Amount</span>
          </div>

          <div className="row-divide">
            {filtered.length === 0 ? (
              <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>
                <Activity size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">No transactions found</p>
              </div>
            ) : paginated.map(tx => {
              const ttype = tx.transaction_type || ''
              const isNeg = EXPENSE.includes(ttype)
              const isIncome = INCOME.includes(ttype)
              const sign = isNeg ? '−' : isIncome ? '+' : ''
              const amountColor = isNeg ? '#FF4D6A' : isIncome ? 'var(--accent)' : 'var(--text-secondary)'
              const color = TX_COLOR[ttype] || 'var(--text-secondary)'
              const isPending = PENDING.includes(ttype)
              return (
                <div key={tx.id} className="flex sm:grid sm:grid-cols-8 items-center gap-3 px-5 py-3">
                  <div className="col-span-2 flex items-center gap-2 min-w-0">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">
                        {tx.transaction_type.replace(/_/g, ' ')}
                      </p>
                      {tx.notes && <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>{tx.notes}</p>}
                    </div>
                  </div>
                  <span className="hidden sm:block text-xs truncate" style={{ color: 'var(--text-secondary)' }}>
                    {tx.username ? `@${tx.username}` : `#${tx.user_id}`}
                  </span>
                  <span className="hidden sm:block text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {tx.agent_tier === 0 ? 'Acct' : `A${tx.agent_tier}`}
                  </span>
                  <span className="hidden sm:block">
                    <span
                      className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={
                        isPending
                          ? { background: 'rgba(255,181,71,0.14)', color: '#FFB547' }
                          : { background: 'rgba(var(--accent-rgb),0.12)', color: 'var(--accent)' }
                      }
                    >
                      {isPending ? 'Pending' : 'Completed'}
                    </span>
                  </span>
                  <span className="hidden sm:block text-xs" style={{ color: 'var(--text-muted)' }}>
                    {formatDateIST(tx.created_at)}
                  </span>
                  <span className="hidden sm:flex items-center gap-1 text-xs">
                    {tx.tx_hash ? (
                      <a
                        href={txExplorerUrl(tx.tx_hash)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 hover:underline"
                        style={{ color: 'var(--accent)' }}
                        title={tx.tx_hash}
                      >
                        {shortenTxHash(tx.tx_hash)}
                        <ExternalLink size={11} />
                      </a>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </span>
                  <p className="text-sm font-semibold ml-auto sm:ml-0 text-right" style={{ color: amountColor }}>
                    {sign}${Math.abs(parseFloat(tx.amount)).toFixed(2)}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
        <div className="mt-4">
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        </div>
      </div>
    </Layout>
  )
}
