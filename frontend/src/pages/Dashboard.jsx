import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import {
  Coins, TrendingUp, Bot,
  Copy, Check, Users, ChevronRight
} from 'lucide-react'
import { useUsdtBalance } from '../hooks/useUsdtBalance'
import toast from 'react-hot-toast'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { formatDateIST } from '../utils/datetime'

const TIER_PRICES = { 1: 10, 2: 20, 3: 50, 4: 100 }
const TIER_NAMES = { 1: 'Agent 1', 2: 'Agent 2', 3: 'Agent 3', 4: 'Agent 4' }

function StatCard({ icon: Icon, label, value, sub, color = '#00D4B4', onClick }) {
  return (
    <div
      className="rounded-xl p-5 transition-all cursor-default"
      style={{ background: '#141922', border: '1px solid #1E2A38' }}
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ background: `${color}18`, border: `1px solid ${color}30` }}
        >
          <Icon size={20} style={{ color }} />
        </div>
        {onClick && <ChevronRight size={16} style={{ color: '#4A5568' }} />}
      </div>
      <p className="text-xs font-medium mb-1" style={{ color: '#8899AA' }}>{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs mt-1" style={{ color: '#4A5568' }}>{sub}</p>}
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const [wallets, setWallets] = useState([])
  const [purchases, setPurchases] = useState([])
  const [income, setIncome] = useState({ total: 0, buckets: [] })
  const [repurchase, setRepurchase] = useState({ tiers: [] })
  const [earnings, setEarnings] = useState({ total_earned: 0 })
  const [referralCount, setReferralCount] = useState(0)
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
      api.get('/wallet/earnings').catch(() => ({ data: { total_earned: 0 } })),
    ]).then(([wb, pb, rb, ib, rpb, eb]) => {
      setWallets(wb.data)
      setPurchases(pb.data)
      setReferralCount(rb.data.count || 0)
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
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
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
              Welcome back, <span style={{ color: '#00D4B4' }}>{user?.username}</span>
            </h1>
            <p className="text-sm mt-1" style={{ color: '#8899AA' }}>Here's your revenue overview</p>
          </div>
          <div
            className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
            style={{ background: '#141922', border: '1px solid #1E2A38' }}
          >
            <div>
              <p className="text-xs" style={{ color: '#8899AA' }}>Your Username (share to invite)</p>
              <p className="text-sm font-bold tracking-widest text-white">{user?.username}</p>
            </div>
            <button
              onClick={copyRef}
              className="p-2 rounded-lg transition-all"
              style={{ background: 'rgba(0,212,180,0.1)', color: '#00D4B4' }}
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
            color="#00D4B4"
          />
          <StatCard
            icon={TrendingUp}
            label="Total Earnings"
            value={`$${totalEarned.toFixed(2)}`}
            sub="Commissions paid on-chain"
            color="#00FFD4"
          />
          <StatCard
            icon={Users}
            label="Direct Referrals"
            value={referralCount}
            sub="Users you invited"
            color="#9B59B6"
          />
          <StatCard
            icon={Bot}
            label="Highest Agent"
            value={highestTier ? TIER_NAMES[highestTier] : 'None'}
            sub={highestTier ? `$${TIER_PRICES[highestTier]} tier` : 'No agents yet'}
            color="#FFB547"
          />
        </div>

        {/* Active Agents + Quick Actions */}
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Active Agent Cards */}
          <div className="lg:col-span-2">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-white">Active Agents</h2>
              <Link to="/agents" className="text-xs font-medium" style={{ color: '#00D4B4' }}>
                Buy More →
              </Link>
            </div>

            {activePurchases.length === 0 ? (
              <div
                className="rounded-xl p-8 text-center"
                style={{ background: '#141922', border: '1px dashed #1E2A38' }}
              >
                <Bot size={40} style={{ color: '#1E2A38' }} className="mx-auto mb-3" />
                <p className="text-sm" style={{ color: '#8899AA' }}>No active agents yet</p>
                <Link to="/agents">
                  <button
                    className="mt-4 px-6 py-2 rounded-xl text-sm font-semibold"
                    style={{ background: '#00D4B4', color: '#000' }}
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
                      style={{ background: '#0E1117', border: '1px solid #1E2A38' }}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold"
                            style={{ background: 'rgba(0,212,180,0.15)', color: '#00D4B4' }}
                          >
                            A{tier}
                          </div>
                          <div>
                            <p className="text-sm font-semibold text-white">{TIER_NAMES[tier]}</p>
                            <p className="text-xs" style={{ color: '#8899AA' }}>${TIER_PRICES[tier]} — {tierPurchases.length}x active</p>
                          </div>
                        </div>
                        <span
                          className="text-xs px-2 py-0.5 rounded-full font-medium"
                          style={{ background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }}
                        >
                          ACTIVE
                        </span>
                      </div>
                      <div className="space-y-2 text-xs">
                        <div className="flex justify-between" style={{ color: '#8899AA' }}>
                          <span>Main Wallet</span>
                          <span className="text-white font-medium">${parseFloat(mainW?.balance || 0).toFixed(2)}</span>
                        </div>
                        <div>
                          <div className="flex justify-between mb-1" style={{ color: '#8899AA' }}>
                            <span>Repurchase Reserve</span>
                            <span className="text-white">${repBal.toFixed(2)} / ${repTarget.toFixed(2)}</span>
                          </div>
                          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1E2A38' }}>
                            <div
                              className="h-full rounded-full transition-all"
                              style={{ width: `${progress}%`, background: 'linear-gradient(90deg, #00D4B4, #00FFD4)' }}
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

          {/* Quick Actions */}
          <div>
            <h2 className="font-semibold text-white mb-4">Quick Actions</h2>
            <div className="space-y-2">
              {[
                { to: '/agents', icon: Bot, label: 'Buy Agent', sub: 'Purchase a tier', color: '#9B59B6' },
              ].map(({ to, icon: Icon, label, sub, color }) => (
                <Link key={to} to={to}>
                  <div
                    className="flex items-center gap-3 p-3 rounded-xl transition-all"
                    style={{ background: '#141922', border: '1px solid #1E2A38' }}
                    onMouseEnter={e => e.currentTarget.style.borderColor = color + '60'}
                    onMouseLeave={e => e.currentTarget.style.borderColor = '#1E2A38'}
                  >
                    <div
                      className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: `${color}18` }}
                    >
                      <Icon size={18} style={{ color }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white">{label}</p>
                      <p className="text-xs" style={{ color: '#8899AA' }}>{sub}</p>
                    </div>
                    <ChevronRight size={16} style={{ color: '#4A5568' }} />
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </div>

        {/* Cumulative Income (all-time running total) */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white">Cumulative Income</h2>
            <span className="text-xs font-medium" style={{ color: '#8899AA' }}>All time</span>
          </div>
          <div className="rounded-xl p-4 sm:p-5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            <div className="flex items-baseline gap-2 mb-4">
              <span className="text-2xl font-bold" style={{ color: '#00D4B4' }}>
                ${Number(income.total || 0).toFixed(2)}
              </span>
              <span className="text-xs" style={{ color: '#8899AA' }}>earned to date</span>
            </div>
            <div style={{ width: '100%', height: 240 }}>
              <ResponsiveContainer>
                <AreaChart data={incomeChart} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="incomeFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00D4B4" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#00D4B4" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1E2A38" vertical={false} />
                  <XAxis
                    dataKey="label"
                    interval="preserveStartEnd"
                    minTickGap={16}
                    tick={{ fill: '#4A5568', fontSize: 11 }}
                    axisLine={{ stroke: '#1E2A38' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: '#4A5568', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={52}
                    tickFormatter={(v) => `$${v}`}
                  />
                  <Tooltip
                    contentStyle={{ background: '#0E1117', border: '1px solid #1E2A38', borderRadius: 8 }}
                    labelStyle={{ color: '#8899AA' }}
                    itemStyle={{ color: '#00D4B4' }}
                    formatter={(v) => [`$${Number(v).toFixed(2)}`, 'Total earned']}
                  />
                  <Area
                    type="monotone"
                    dataKey="amount"
                    stroke="#00D4B4"
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
