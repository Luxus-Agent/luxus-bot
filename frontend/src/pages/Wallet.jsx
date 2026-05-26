import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Wallet as WalletIcon, TrendingUp, Lock, Activity } from 'lucide-react'
import Pagination from '../components/Pagination'

const PAGE_SIZE = 10

const TIER_PRICES = { 1: 10, 2: 20, 3: 50, 4: 100 }

const TX_COLOR = {
  DEPOSIT: '#00D4B4', CORE_INCOME: '#00D4B4', STREAM_PAYOUT: '#00D4B4',
  BOOST_PAYOUT: '#00D4B4', SPONSOR_MILESTONE_INCOME: '#00D4B4',
  TRANSFER_IN: '#00D4B4', WITHDRAWAL: '#FF4D6A', TRANSFER_OUT: '#FF4D6A',
  REPURCHASE_HOLD: '#FFB547', REENTRY: '#8899AA', PURCHASE: '#FF4D6A', AGENT_PURCHASE: '#FF4D6A',
}

const NEGATIVE = ['WITHDRAWAL', 'TRANSFER_OUT', 'PURCHASE', 'AGENT_PURCHASE', 'REPURCHASE_HOLD']

export default function Wallet() {
  const [wallets, setWallets] = useState([])
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [filterTier, setFilterTier] = useState('all')
  const [filterType, setFilterType] = useState('all')
  const [page, setPage] = useState(1)

  useEffect(() => {
    Promise.all([
      api.get('/wallet/balances'),
      api.get('/wallet/transactions'),
    ]).then(([wb, tb]) => {
      setWallets(wb.data)
      setTransactions(tb.data)
    }).catch(() => toast.error('Failed to load wallet')).finally(() => setLoading(false))
  }, [])

  const mainWallets = wallets.filter(w => w.wallet_type === 'main' && w.agent_tier > 0)
  const repurchaseWallets = wallets.filter(w => w.wallet_type === 'repurchase' && w.agent_tier > 0)
  const accountWallet = wallets.find(w => w.wallet_type === 'account')
  const totalMain = mainWallets.reduce((s, w) => s + parseFloat(w.balance), 0)
  const totalRep = repurchaseWallets.reduce((s, w) => s + parseFloat(w.balance), 0)

  const txTypes = [...new Set(transactions.map(t => t.transaction_type))]
  const filtered = transactions.filter(t => {
    if (filterTier !== 'all' && t.agent_tier !== parseInt(filterTier)) return false
    if (filterType !== 'all' && t.transaction_type !== filterType) return false
    return true
  })
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

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
        <div>
          <h1 className="text-2xl font-bold text-white">Wallet</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>Balance overview and transaction history</p>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { label: 'Account Balance', val: accountWallet?.balance || 0, icon: WalletIcon, color: '#00D4B4', sub: 'Spendable balance' },
            { label: 'Total Earnings', val: totalMain, icon: TrendingUp, color: '#00FFD4', sub: 'Main wallet sum' },
            { label: 'Repurchase Reserve', val: totalRep, icon: Lock, color: '#FFB547', sub: 'Auto-hold 10%' },
          ].map(({ label, val, icon: Icon, color, sub }) => (
            <div key={label} className="rounded-xl p-5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: `${color}18` }}>
                  <Icon size={18} style={{ color }} />
                </div>
                <div>
                  <p className="text-xs" style={{ color: '#8899AA' }}>{label}</p>
                  <p className="text-xs" style={{ color: '#4A5568' }}>{sub}</p>
                </div>
              </div>
              <p className="text-2xl font-bold text-white">${parseFloat(val).toFixed(2)}</p>
            </div>
          ))}
        </div>

        {/* Per-Tier Wallets */}
        <div>
          <h2 className="font-semibold text-white mb-4">Per-Tier Balances</h2>
          <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map(tier => {
              const mw = wallets.find(w => w.agent_tier === tier && w.wallet_type === 'main')
              const rw = wallets.find(w => w.agent_tier === tier && w.wallet_type === 'repurchase')
              const mBal = parseFloat(mw?.balance || 0)
              const rBal = parseFloat(rw?.balance || 0)
              const progress = Math.min(100, (rBal / TIER_PRICES[tier]) * 100)
              return (
                <div key={tier} className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                  <div className="flex items-center gap-2 mb-3">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold"
                      style={{ background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }}
                    >A{tier}</div>
                    <div>
                      <p className="text-sm font-semibold text-white">Agent {tier}</p>
                      <p className="text-xs" style={{ color: '#4A5568' }}>${TIER_PRICES[tier]}/tier</p>
                    </div>
                  </div>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span style={{ color: '#8899AA' }}>Main</span>
                      <span className="font-semibold text-white">${mBal.toFixed(2)}</span>
                    </div>
                    <div>
                      <div className="flex justify-between mb-1">
                        <span style={{ color: '#8899AA' }}>Repurchase</span>
                        <span className="text-white">${rBal.toFixed(2)}</span>
                      </div>
                      <div className="h-1 rounded-full overflow-hidden" style={{ background: '#1E2A38' }}>
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${progress}%`, background: 'linear-gradient(90deg, #FFB547, #FFD700)' }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Transactions */}
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <h2 className="font-semibold text-white">Transaction History</h2>
            <div className="flex gap-2">
              <select
                value={filterTier}
                onChange={e => { setFilterTier(e.target.value); setPage(1) }}
                className="px-3 py-1.5 rounded-lg text-xs outline-none"
                style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
              >
                <option value="all">All Tiers</option>
                {[0, 1, 2, 3, 4].map(t => <option key={t} value={t}>{t === 0 ? 'Account' : `Agent ${t}`}</option>)}
              </select>
              <select
                value={filterType}
                onChange={e => { setFilterType(e.target.value); setPage(1) }}
                className="px-3 py-1.5 rounded-lg text-xs outline-none"
                style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
              >
                <option value="all">All Types</option>
                {txTypes.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
          </div>

          <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            {filtered.length === 0 ? (
              <div className="p-8 text-center" style={{ color: '#8899AA' }}>
                <Activity size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">No transactions found</p>
              </div>
            ) : (
              <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
                {paginated.map(tx => {
                  const isNeg = NEGATIVE.includes(tx.transaction_type)
                  const color = TX_COLOR[tx.transaction_type] || '#8899AA'
                  return (
                    <div key={tx.id} className="flex items-center gap-3 px-4 py-3">
                      <div
                        className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
                        style={{ background: `${color}18`, color }}
                      >
                        {isNeg ? '−' : '+'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                          {tx.transaction_type.replace(/_/g, ' ')}
                        </p>
                        <p className="text-xs" style={{ color: '#4A5568' }}>
                          {tx.agent_tier === 0 ? 'Account' : `Agent ${tx.agent_tier}`}
                          {tx.notes ? ` • ${tx.notes}` : ''}
                          {' • '}{new Date(tx.created_at).toLocaleString()}
                        </p>
                      </div>
                      <p className="text-sm font-semibold flex-shrink-0" style={{ color: isNeg ? '#FF4D6A' : '#00D4B4' }}>
                        {isNeg ? '−' : '+'}${Math.abs(parseFloat(tx.amount)).toFixed(2)}
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
      </div>
    </Layout>
  )
}
