import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Activity, TrendingUp, TrendingDown } from 'lucide-react'
import Pagination from '../components/Pagination'
import { formatDateIST } from '../utils/datetime'
import { txExplorerUrl, shortenTxHash } from '../utils/explorer'
import { ExternalLink } from 'lucide-react'

const PAGE_SIZE = 10

// NOTE: the API serializes the TransactionType enum's lowercase *values*
// (e.g. "agent_purchase"), so all keys/lists here must be lowercase to match.
const TX_COLOR = {
  deposit: 'var(--accent)', core_income: 'var(--accent)', stream_payout: 'var(--accent)',
  boost_payout: 'var(--accent)', sponsor_milestone_income: 'var(--accent)',
  transfer_in: 'var(--accent)', withdrawal: '#FF4D6A', transfer_out: '#FF4D6A',
  repurchase_hold: '#FFB547', reentry: 'var(--text-secondary)', purchase: '#FF4D6A', agent_purchase: '#FF4D6A',
  core_sent: 'var(--text-secondary)', software_fee: 'var(--text-secondary)', platform_profit: 'var(--text-secondary)', admin_generate: 'var(--accent)',
  withdrawal_refund: '#FFB547',
}

// Money actually received into a wallet
const INCOME = ['core_income', 'stream_payout', 'boost_payout', 'sponsor_milestone_income', 'transfer_in', 'deposit']
// Money actually leaving a wallet
const EXPENSE = ['withdrawal', 'transfer_out', 'purchase', 'agent_purchase']
// Informational / internal records — not a real inflow or outflow for this user
// (core_sent = audit of the 60% core split sent to upline at purchase;
//  withdrawal_refund = reversal of a failed payout, not new income)
const SYSTEM = ['repurchase_hold', 'reentry', 'core_sent', 'software_fee', 'platform_profit', 'admin_generate', 'withdrawal_refund']

const TX_GROUPS = {
  Income: INCOME,
  Expenses: EXPENSE,
  System: SYSTEM,
}

export default function Transactions() {
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState('all')
  const [filterGroup, setFilterGroup] = useState('all')
  const [page, setPage] = useState(1)

  useEffect(() => {
    api.get('/wallet/transactions')
      .then(r => setTransactions(r.data))
      .catch(() => toast.error('Failed to load transactions'))
      .finally(() => setLoading(false))
  }, [])

  const txTypes = [...new Set(transactions.map(t => t.transaction_type))]

  const totalIn = transactions
    .filter(t => INCOME.includes(t.transaction_type))
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  const totalOut = transactions
    .filter(t => EXPENSE.includes(t.transaction_type))
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  const filtered = transactions.filter(t => {
    if (filterType !== 'all' && t.transaction_type !== filterType) return false
    if (filterGroup !== 'all') {
      const groupTypes = TX_GROUPS[filterGroup] || []
      if (!groupTypes.includes(t.transaction_type)) return false
    }
    return true
  })
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

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
        <div>
          <h1 className="text-2xl font-bold text-white">Transactions</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>Complete ledger of all account activity</p>
        </div>

        {/* Totals */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
            <div className="flex items-center gap-2 mb-1">
              <Activity size={16} style={{ color: 'var(--text-secondary)' }} />
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Total Records</p>
            </div>
            <p className="text-2xl font-bold text-white">{transactions.length}</p>
          </div>
          <div className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
            <div className="flex items-center gap-2 mb-1">
              <TrendingUp size={16} style={{ color: 'var(--accent)' }} />
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Total In</p>
            </div>
            <p className="text-2xl font-bold" style={{ color: 'var(--accent)' }}>${totalIn.toFixed(2)}</p>
          </div>
          <div className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
            <div className="flex items-center gap-2 mb-1">
              <TrendingDown size={16} style={{ color: '#FF4D6A' }} />
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Total Out</p>
            </div>
            <p className="text-2xl font-bold" style={{ color: '#FF4D6A' }}>${totalOut.toFixed(2)}</p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 flex-wrap">
          <select
            value={filterGroup}
            onChange={e => { setFilterGroup(e.target.value); setFilterType('all'); setPage(1) }}
            className="px-3 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
          >
            <option value="all">All Groups</option>
            {Object.keys(TX_GROUPS).map(g => <option key={g} value={g}>{g}</option>)}
          </select>
          <select
            value={filterType}
            onChange={e => { setFilterType(e.target.value); setPage(1) }}
            className="px-3 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
          >
            <option value="all">All Types</option>
            {txTypes.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
          </select>
          <span className="px-3 py-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
            {filtered.length} record{filtered.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Table */}
        <div className="rounded-xl overflow-hidden" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          {/* Header */}
          <div
            className="hidden sm:grid grid-cols-6 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}
          >
            <span className="col-span-2">Type</span>
            <span>Tier</span>
            <span>Date</span>
            <span>Tx Hash</span>
            <span className="text-right">Amount</span>
          </div>

          {filtered.length === 0 ? (
            <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>
              <Activity size={32} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">No transactions found</p>
            </div>
          ) : (
            <div className="row-divide">
              {paginated.map(tx => {
                const isNeg = EXPENSE.includes(tx.transaction_type)
                const isIncome = INCOME.includes(tx.transaction_type)
                const sign = isNeg ? '−' : isIncome ? '+' : ''
                const amountColor = isNeg ? '#FF4D6A' : isIncome ? 'var(--accent)' : 'var(--text-secondary)'
                const color = TX_COLOR[tx.transaction_type] || 'var(--text-secondary)'
                return (
                  <div key={tx.id} className="flex sm:grid sm:grid-cols-6 items-center gap-3 px-4 py-3">
                    <div className="col-span-2 flex items-center gap-2 min-w-0">
                      <div
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
                        style={{ background: `color-mix(in srgb, ${color} 18%, transparent)`, color }}
                      >
                        {sign || '·'}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                          {tx.transaction_type.replace(/_/g, ' ')}
                        </p>
                        {tx.notes && <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>{tx.notes}</p>}
                      </div>
                    </div>
                    <span className="hidden sm:block text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {tx.agent_tier === 0 ? 'Account' : `Agent ${tx.agent_tier}`}
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
                    <p
                      className="text-sm font-semibold text-right ml-auto sm:ml-0"
                      style={{ color: amountColor }}
                    >
                      {sign}${Math.abs(parseFloat(tx.amount)).toFixed(2)}
                    </p>
                  </div>
                )
              })}
            </div>
          )}
          {filtered.length > 0 && (
            <div className="px-4 pb-3">
              <Pagination page={page} totalPages={totalPages} onChange={setPage} />
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
