import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import {
  Coins, TrendingUp, Bot,
  Copy, Check, Users, ChevronRight, ChevronDown
} from 'lucide-react'
import { useUsdtBalance } from '../hooks/useUsdtBalance'
import toast from 'react-hot-toast'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { formatDateIST } from '../utils/datetime'
import EarningsBreakdown from '../components/EarningsBreakdown'

const TIER_PRICES = { 1: 10, 2: 20, 3: 50, 4: 100 }
const TIER_NAMES = { 1: 'Agent 1', 2: 'Agent 2', 3: 'Agent 3', 4: 'Agent 4' }

function StatCard({ icon: Icon, label, value, sub, color = 'var(--accent)', onClick }) {
  return (
    <div
      className="rounded-xl p-5 transition-all cursor-default"
      style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ background: `color-mix(in srgb, ${color} 18%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 30%, transparent)` }}
        >
          <Icon size={20} style={{ color }} />
        </div>
        {onClick && <ChevronRight size={16} style={{ color: 'var(--text-muted)' }} />}
      </div>
      <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{sub}</p>}
    </div>
  )
}

/** Total Earnings stat card with a click-to-expand breakdown of Completed vs Pending. */
function EarningsCard({ totalEarned, completed, pendingReserve, pendingPayout }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <div
        className="rounded-xl p-5 transition-all cursor-pointer"
        style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex items-start justify-between mb-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{ background: 'color-mix(in srgb, var(--accent-glow) 18%, transparent)', border: '1px solid color-mix(in srgb, var(--accent-glow) 30%, transparent)' }}
          >
            <TrendingUp size={20} style={{ color: 'var(--accent-glow)' }} />
          </div>
          <ChevronDown
            size={16}
            style={{ color: 'var(--text-muted)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
          />
        </div>
        <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>Total Earnings</p>
        <p className="text-2xl font-bold text-white">${totalEarned.toFixed(2)}</p>
        <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Tap for Completed vs Pending</p>
      </div>

      {open && (
        <div
          className="absolute left-0 right-0 top-full mt-2 rounded-xl z-50 p-3"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: '0 8px 32px rgba(0,0,0,0.4)' }}
        >
          <EarningsBreakdown
            totalEarned={totalEarned}
            completed={completed}
            pendingReserve={pendingReserve}
            pendingPayout={pendingPayout}
          />
        </div>
      )}
    </div>
  )
}

/** Direct Referrals stat card with a click-to-expand dropdown listing every referral. */
function ReferralsCard({ count, referrals }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <div
        className="rounded-xl p-5 transition-all cursor-pointer"
        style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex items-start justify-between mb-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(155,89,182,0.1)', border: '1px solid rgba(155,89,182,0.19)' }}
          >
            <Users size={20} style={{ color: '#9B59B6' }} />
          </div>
          <ChevronDown
            size={16}
            style={{ color: 'var(--text-muted)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
          />
        </div>
        <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>Direct Referrals</p>
        <p className="text-2xl font-bold text-white">{count}</p>
        <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Users you invited</p>
      </div>

      {open && (
        <div
          className="absolute left-0 right-0 top-full mt-2 rounded-xl overflow-hidden z-50 max-h-64 overflow-y-auto"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: '0 8px 32px rgba(0,0,0,0.4)' }}
        >
          {referrals.length === 0 ? (
            <p className="px-4 py-3 text-xs" style={{ color: 'var(--text-muted)' }}>No referrals yet</p>
          ) : (
            <div className="row-divide">
              {referrals.map(r => (
                <div key={r.username} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-sm text-white truncate">@{r.username}</span>
                  <span
                    className="text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ml-2"
                    style={{
                      background: r.is_active ? 'rgba(var(--accent-rgb),0.12)' : 'rgba(255,77,106,0.12)',
                      color: r.is_active ? 'var(--accent)' : '#FF4D6A',
                    }}
                  >
                    {r.is_active ? 'Active' : 'Frozen'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const [wallets, setWallets] = useState([])
  const [purchases, setPurchases] = useState([])
  const [income, setIncome] = useState({ total: 0, buckets: [] })
  const [repurchase, setRepurchase] = useState({ tiers: [] })
  const [earnings, setEarnings] = useState({ total_earned: 0, completed: 0, pending_reserve: 0, pending_payout: 0 })
  const [referralCount, setReferralCount] = useState(0)
  const [referrals, setReferrals] = useState([])
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const { balance: usdtBalance, loading: usdtLoading, isConnected, configured } = useUsdtBalance()

  useEffect(() => {
    Promise.all([
      api.get('/wallet/balances'),
      api.get('/agents/purchases'),
      api.get('/auth/referrals'),
      api.get('/wallet/income/daily'),
      // Per-tier reserve + the real (price + platform fee) repurchase threshold.
      api.get('/wallet/repurchase').catch(() => ({ data: { tiers: [] } })),
      // Non-fatal: a missing/failing earnings endpoint must not blank the whole
      // dashboard (agents, wallets, etc.) — fall back to $0.
      api.get('/wallet/earnings').catch(() => ({ data: { total_earned: 0, completed: 0, pending_reserve: 0, pending_payout: 0 } })),
    ]).then(([wb, pb, rb, ib, rpb, eb]) => {
      setWallets(wb.data)
      setPurchases(pb.data)
      setReferralCount(rb.data.count || 0)
      setReferrals(rb.data.referrals || [])
      setIncome(ib.data || { total: 0, buckets: [] })
      setRepurchase(rpb.data || { tiers: [] })
      setEarnings(eb.data || { total_earned: 0 })
    }).catch(() => toast.error('Failed to load dashboard')).finally(() => setLoading(false))
  }, [])

  // Total earnings come from the ledger (Core/Stream/Boost income), NOT internal
  // wallet balances — on the on-chain rail commissions are paid to users' own
  // wallets on-chain, so internal wallets stay $0.
  const totalEarned = Number(earnings.total_earned || 0)
  const activePurchases = purchases.filter(p => p.status === 'active')
  const highestTier = purchases.length ? Math.max(...purchases.map(p => p.agent_tier)) : 0
  // Reserve target = pack price + platform fee (the real auto-repurchase threshold), keyed by tier.
  const repByTier = Object.fromEntries((repurchase.tiers || []).map(t => [t.agent_tier, t]))

  const copyRef = () => {
    const name = user?.username
    if (!name) return
    navigator.clipboard.writeText(name)
    setCopied(true)
    toast.success('Username copied!')
    setTimeout(() => setCopied(false), 2000)
  }

  // Cumulative income series: one point per IST day, amount = running lifetime
  // total up to that day (climbs from the past to the present).
  const incomeChart = (income.buckets || []).map(b => ({
    label: formatDateIST(b.hour),
    amount: Number(b.amount) || 0,
  }))

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
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">
              Welcome back, <span style={{ color: 'var(--accent)' }}>{user?.username}</span>
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>Here's your revenue overview</p>
          </div>
          <div
            className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
            style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
          >
            <div>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Your Username (share to invite)</p>
              <p className="text-sm font-bold tracking-widest text-white">{user?.username}</p>
            </div>
            <button
              onClick={copyRef}
              className="p-2 rounded-lg transition-all"
              style={{ background: 'rgba(var(--accent-rgb),0.1)', color: 'var(--accent)' }}
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </button>
          </div>
        </div>

        {/* Key Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            icon={Coins}
            label="Wallet Balance"
            value={
              !configured ? 'Not set'
                : !isConnected ? 'Connect'
                : usdtLoading ? '…'
                : usdtBalance == null ? '—'
                : `$${usdtBalance.toFixed(2)}`
            }
            sub="On-chain USDT (BSC)"
            color="var(--accent)"
          />
          <EarningsCard
            totalEarned={totalEarned}
            completed={Number(earnings.completed || 0)}
            pendingReserve={Number(earnings.pending_reserve || 0)}
            pendingPayout={Number(earnings.pending_payout || 0)}
          />
          <ReferralsCard count={referralCount} referrals={referrals} />
          <StatCard
            icon={Bot}
            label="Highest Agent"
            value={highestTier ? TIER_NAMES[highestTier] : 'None'}
            sub={highestTier ? `$${TIER_PRICES[highestTier]} tier` : 'No agents yet'}
            color="#FFB547"
          />
        </div>

        {/* Active Agents */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white">Active Agents</h2>
            <Link to="/agents" className="text-xs font-medium" style={{ color: 'var(--accent)' }}>
              Buy More →
            </Link>
          </div>

          {activePurchases.length === 0 ? (
            <div
              className="rounded-xl p-8 text-center"
              style={{ background: 'var(--bg-panel)', border: '1px dashed var(--border)' }}
            >
              <Bot size={40} style={{ color: 'var(--border)' }} className="mx-auto mb-3" />
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>No active agents yet</p>
              <Link to="/agents">
                <button
                  className="mt-4 px-6 py-2 rounded-xl text-sm font-semibold"
                  style={{ background: 'var(--accent)', color: '#000' }}
                >
                  Purchase Your First Agent
                </button>
              </Link>
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 gap-3">
              {[1, 2, 3, 4].map(tier => {
                const tierPurchases = activePurchases.filter(p => p.agent_tier === tier)
                if (tierPurchases.length === 0) return null
                const mainW = wallets.find(w => w.wallet_type === 'main' && w.agent_tier === tier)
                const repW = wallets.find(w => w.wallet_type === 'repurchase' && w.agent_tier === tier)
                const rep = repByTier[tier]
                const repBal = rep ? rep.reserve : parseFloat(repW?.balance || 0)
                // Target the real threshold (price + platform fee), not the bare price.
                const repTarget = rep ? rep.threshold : TIER_PRICES[tier]
                const progress = rep ? rep.progress_percent : Math.min(100, (repBal / TIER_PRICES[tier]) * 100)
                return (
                  <div
                    key={tier}
                    className="rounded-xl p-4"
                    style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <div
                          className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold"
                          style={{ background: 'rgba(var(--accent-rgb),0.15)', color: 'var(--accent)' }}
                        >
                          A{tier}
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-white">{TIER_NAMES[tier]}</p>
                          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>${TIER_PRICES[tier]} — {tierPurchases.length}x active</p>
                        </div>
                      </div>
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-medium"
                        style={{ background: 'rgba(var(--accent-rgb),0.12)', color: 'var(--accent)' }}
                      >
                        ACTIVE
                      </span>
                    </div>
                    <div className="space-y-2 text-xs">
                      <div className="flex justify-between" style={{ color: 'var(--text-secondary)' }}>
                        <span>Main Wallet</span>
                        <span className="text-white font-medium">${parseFloat(mainW?.balance || 0).toFixed(2)}</span>
                      </div>
                      <div>
                        <div className="flex justify-between mb-1" style={{ color: 'var(--text-secondary)' }}>
                          <span>Repurchase Reserve</span>
                          <span className="text-white">${repBal.toFixed(2)} / ${repTarget.toFixed(2)}</span>
                        </div>
                        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--border)' }}>
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${progress}%`, background: 'linear-gradient(90deg, var(--accent), var(--accent-glow))' }}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Cumulative Income (all-time running total) */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white">Cumulative Income</h2>
            <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>All time</span>
          </div>
          <div className="rounded-xl p-4 sm:p-5" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
            <div className="flex items-baseline gap-2 mb-4">
              <span className="text-2xl font-bold" style={{ color: 'var(--accent)' }}>
                ${Number(income.total || 0).toFixed(2)}
              </span>
              <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>earned to date</span>
            </div>
            <div style={{ width: '100%', height: 240 }}>
              <ResponsiveContainer>
                <AreaChart data={incomeChart} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="incomeFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    interval="preserveStartEnd"
                    minTickGap={16}
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={{ stroke: 'var(--border)' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={52}
                    tickFormatter={(v) => `$${v}`}
                  />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8 }}
                    labelStyle={{ color: 'var(--text-secondary)' }}
                    itemStyle={{ color: 'var(--accent)' }}
                    formatter={(v) => [`$${Number(v).toFixed(2)}`, 'Total earned']}
                  />
                  <Area
                    type="monotone"
                    dataKey="amount"
                    stroke="var(--accent)"
                    strokeWidth={2}
                    fill="url(#incomeFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
