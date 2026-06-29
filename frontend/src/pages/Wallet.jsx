import { useEffect, useState } from 'react'
import { UserLayout, AdminLayout } from '../components/Layout'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'
import toast from 'react-hot-toast'
import { TrendingUp, Lock, Activity, Coins } from 'lucide-react'
import Pagination from '../components/Pagination'
import { formatDateTimeIST } from '../utils/datetime'
import { useUsdtBalance } from '../hooks/useUsdtBalance'

const PAGE_SIZE = 10

const TIER_PRICES = { 1: 10, 2: 20, 3: 50, 4: 100 }

// Transaction types are lowercase enum values from the API (e.g. "core_income",
// "agent_purchase") — keys here MUST be lowercase to match.
const TX_COLOR = {
  deposit: '#00D4B4', core_income: '#00D4B4', stream_payout: '#00D4B4',
  boost_payout: '#00D4B4', sponsor_milestone_income: '#00D4B4',
  transfer_in: '#00D4B4', withdrawal: '#FF4D6A', transfer_out: '#FF4D6A',
  repurchase_hold: '#FFB547', reentry: '#8899AA', purchase: '#FF4D6A', agent_purchase: '#FF4D6A',
}

const NEGATIVE = ['withdrawal', 'transfer_out', 'purchase', 'agent_purchase', 'repurchase_hold']

export default function Wallet() {
  const { isAdmin } = useAuth()
  const Layout = isAdmin ? AdminLayout : UserLayout
  const [wallets, setWallets] = useState([])
  const [transactions, setTransactions] = useState([])
  const [repurchase, setRepurchase] = useState({ tiers: [] })
  const [earnings, setEarnings] = useState({ total_earned: 0 })
  const [loading, setLoading] = useState(true)
  const [filterTier, setFilterTier] = useState('all')
  const [filterType, setFilterType] = useState('all')
  const [page, setPage] = useState(1)
  const { balance: usdtBalance, loading: usdtLoading, isConnected, configured } = useUsdtBalance()

  useEffect(() => {
    Promise.all([
      api.get('/wallet/balances'),
      api.get('/wallet/transactions'),
      // Per-tier reserve + the real (price + platform fee) repurchase threshold.
      api.get('/wallet/repurchase').catch(() => ({ data: { tiers: [] } })),
      // Non-fatal: a missing/failing earnings endpoint must not blank the wallet
      // page (balances + transactions) — fall back to $0.
      api.get('/wallet/earnings').catch(() => ({ data: { total_earned: 0 } })),
    ]).then(([wb, tb, rpb, eb]) => {
      setWallets(wb.data)
      setTransactions(tb.data)
      setRepurchase(rpb.data || { tiers: [] })
      setEarnings(eb.data || { total_earned: 0 })
    }).catch(() => toast.error('Failed to load wallet')).finally(() => setLoading(false))
  }, [])

  const repurchaseWallets = wallets.filter(w => w.wallet_type === 'repurchase' && w.agent_tier > 0)
  // Reserve target = pack price + platform fee (the real auto-repurchase threshold), keyed by tier.
  const repByTier = Object.fromEntries((repurchase.tiers || []).map(t => [t.agent_tier, t]))
  // Total earnings = lifetime Core/Stream/Boost income from the ledger, NOT the
  // internal main-wallet balance (which stays $0 on the on-chain rail).
  const totalEarned = Number(earnings.total_earned || 0)
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
          {/* Live on-chain wallet balance (USDT on BSC). This is the user's real
              spendable balance — on-chain purchases & commissions move here. */}
          <div className="rounded-xl p-5" style={{ background: '#141922', border: '1px solid #00D4B433' }}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: '#00D4B418' }}>
                <Coins size={18} style={{ color: '#00D4B4' }} />
              </div>
              <div>
                <p className="text-xs" style={{ color: '#8899AA' }}>Wallet Balance</p>
                <p className="text-xs" style={{ color: '#4A5568' }}>On-chain USDT (BSC)</p>
              </div>
            </div>
            <p className="text-2xl font-bold text-white">
              {!configured ? (
                <span className="text-sm" style={{ color: '#FFB547' }}>Not configured</span>
              ) : !isConnected ? (
                <span className="text-sm" style={{ color: '#8899AA' }}>Connect wallet</span>
              ) : usdtLoading ? (
                <span className="text-sm" style={{ color: '#8899AA' }}>Loading…</span>
              ) : usdtBalance == null ? (
                <span className="text-sm" style={{ color: '#8899AA' }}>—</span>
              ) : (
                `$${usdtBalance.toFixed(2)}`
              )}
            </p>
          </div>
          {[
            { label: 'Total Earnings', val: totalEarned, icon: TrendingUp, color: '#00FFD4', sub: 'Commissions paid on-chain' },
            { label: 'Repurchase Reserve', val: totalRep, icon: Lock, color: '#FFB547', sub: 'Auto-hold (internal)' },
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
              const rep = repByTier[tier]
              const rBal = rep ? rep.reserve : parseFloat(rw?.balance || 0)
              // Target the real threshold (price + platform fee), not the bare price.
              const rTarget = rep ? rep.threshold : TIER_PRICES[tier]
              const rFee = rep ? rep.platform_fee : 0
              const progress = rep ? rep.progress_percent : Math.min(100, (rBal / TIER_PRICES[tier]) * 100)
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
                        <span className="text-white">${rBal.toFixed(2)} / ${rTarget.toFixed(2)}</span>
                      </div>
                      <div className="h-1 rounded-full overflow-hidden" style={{ background: '#1E2A38' }}>
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${progress}%`, background: 'linear-gradient(90deg, #FFB547, #FFD700)' }}
                        />
                      </div>
                      {rFee > 0 && (
                        <p className="text-right mt-1" style={{ color: '#4A5568', fontSize: '10px' }}>
                          target incl. ${rFee.toFixed(2)} platform fee
                        </p>
                      )}
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
              <div className="row-divide">
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
                          {' • '}{formatDateTimeIST(tx.created_at)}
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
