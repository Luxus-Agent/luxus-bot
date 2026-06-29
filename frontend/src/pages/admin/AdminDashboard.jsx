import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Users, TrendingUp, DollarSign, Zap, Activity, RefreshCw, Flame, PiggyBank, Layers } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDateTimeIST } from '../../utils/datetime'

export default function AdminDashboard() {
  const [users, setUsers] = useState([])
  const [transactions, setTransactions] = useState([])
  const [treasury, setTreasury] = useState({ account_balance: 0, total_generated: 0, total_sent: 0, total_invested: 0, total_deposited: 0, platform_profit: 0 })
  const [metrics, setMetrics] = useState({
    revenue: { core_income: 0, stream_payout: 0, boost_payout: 0, sponsor_share: 0, total_paid_to_users: 0, software_fees: 0 },
    repurchase: { count: 0, volume: 0, platform_fee: 0, reserve_held: 0 },
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/admin/users'),
      api.get('/admin/transactions'),
      api.get('/admin/treasury/summary'),
      // Revenue-engine + auto-repurchase aggregates. Non-fatal — never blank the page.
      api.get('/admin/metrics').catch(() => ({ data: null })),
    ]).then(([u, t, s, m]) => {
      setUsers(u.data)
      setTransactions(t.data)
      setTreasury(s.data)
      if (m.data) setMetrics(m.data)
    }).catch(() => toast.error('Failed to load admin data')).finally(() => setLoading(false))
  }, [])

  const activeUsers = users.filter(u => u.is_active).length
  const frozenUsers = users.filter(u => !u.is_active).length

  const recentTx = transactions.slice(0, 8)

  const txTypeBreakdown = transactions.reduce((acc, t) => {
    acc[t.transaction_type] = (acc[t.transaction_type] || 0) + 1
    return acc
  }, {})

  const TOP_TX_COLOR = {
    DEPOSIT: '#00D4B4', CORE_INCOME: '#00D4B4', STREAM_PAYOUT: '#3498DB',
    BOOST_PAYOUT: '#9B59B6', WITHDRAWAL: '#FF4D6A', TRANSFER_OUT: '#FF4D6A',
    REPURCHASE_HOLD: '#FFB547', AGENT_PURCHASE: '#FF4D6A', SPONSOR_MILESTONE_INCOME: '#00D4B4',
  }

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
          <h1 className="text-2xl font-bold text-white">Admin Overview</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>Platform-wide metrics and monitoring</p>
        </div>

        {/* Key Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { label: 'Total Users', val: users.length, sub: `${activeUsers} active`, icon: Users, color: '#3498DB' },
            { label: 'Platform Profit', val: `$${(treasury.platform_profit || 0).toFixed(2)}`, sub: 'Fees + residuals + retained', icon: DollarSign, color: '#FFB547' },
            { label: 'Total Invested', val: `$${treasury.total_invested.toFixed(2)}`, sub: 'By users in the platform', icon: TrendingUp, color: '#00FFD4' },
          ].map(({ label, val, sub, icon: Icon, color }) => (
            <div key={label} className="rounded-xl p-5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center mb-3"
                style={{ background: `${color}18` }}
              >
                <Icon size={20} style={{ color }} />
              </div>
              <p className="text-xs" style={{ color: '#8899AA' }}>{label}</p>
              <p className="text-2xl font-bold text-white mt-0.5">{val}</p>
              <p className="text-xs mt-1" style={{ color: '#4A5568' }}>{sub}</p>
            </div>
          ))}
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Transaction Breakdown */}
          <div className="rounded-xl p-5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            <h2 className="font-semibold text-white mb-4">Transaction Breakdown</h2>
            <div className="space-y-2">
              {Object.entries(txTypeBreakdown)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 8)
                .map(([type, count]) => {
                  const total = transactions.length
                  const pct = Math.round((count / total) * 100)
                  const color = TOP_TX_COLOR[type.toUpperCase()] || '#8899AA'
                  return (
                    <div key={type}>
                      <div className="flex justify-between text-xs mb-1">
                        <span style={{ color: '#8899AA' }}>{type.replace(/_/g, ' ')}</span>
                        <span style={{ color }}>{count} ({pct}%)</span>
                      </div>
                      <div className="h-1 rounded-full overflow-hidden" style={{ background: '#0E1117' }}>
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>

          {/* Recent Transactions */}
          <div className="lg:col-span-2 rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid #1E2A38' }}>
              <h2 className="font-semibold text-white">Recent Transactions</h2>
              <Link to="/admin/transactions" className="text-xs" style={{ color: '#00D4B4' }}>View All →</Link>
            </div>
            <div className="row-divide">
              {recentTx.map(tx => {
                const ttype = (tx.transaction_type || '').toUpperCase()
                const color = TOP_TX_COLOR[ttype] || '#8899AA'
                const isNeg = ['WITHDRAWAL', 'TRANSFER_OUT', 'PURCHASE', 'AGENT_PURCHASE', 'SOFTWARE_FEE'].includes(ttype)
                return (
                  <div key={tx.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white truncate">
                        {tx.transaction_type.replace(/_/g, ' ')}
                        <span style={{ color: '#8899AA' }}> · @{tx.username || `user${tx.user_id}`}</span>
                      </p>
                      <p className="text-xs truncate" style={{ color: '#4A5568' }}>
                        {tx.notes ? `${tx.notes} · ` : ''}{formatDateTimeIST(tx.created_at)}
                      </p>
                    </div>
                    <p className="text-sm font-semibold flex-shrink-0" style={{ color: isNeg ? '#FF4D6A' : '#00D4B4' }}>
                      {isNeg ? '−' : '+'}${Math.abs(parseFloat(tx.amount)).toFixed(2)}
                    </p>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Revenue Engine Breakdown */}
        <div>
          <h2 className="font-semibold text-white mb-4">Revenue Engine — Commissions Paid to Users</h2>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {[
              { label: 'Core Agent', val: metrics.revenue.core_income, icon: Zap, color: '#00D4B4' },
              { label: 'Stream Agent', val: metrics.revenue.stream_payout, icon: TrendingUp, color: '#3498DB' },
              { label: 'Boost Agent', val: metrics.revenue.boost_payout, icon: Activity, color: '#9B59B6' },
              { label: 'Sponsor Shares', val: metrics.revenue.sponsor_share, icon: Users, color: '#FFB547' },
              { label: 'Total to Users', val: metrics.revenue.total_paid_to_users, icon: DollarSign, color: '#00FFD4' },
            ].map(({ label, val, icon: Icon, color }) => (
              <div key={label} className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ background: `${color}18` }}>
                  <Icon size={18} style={{ color }} />
                </div>
                <p className="text-xs" style={{ color: '#8899AA' }}>{label}</p>
                <p className="text-xl font-bold text-white mt-0.5">${Number(val || 0).toFixed(2)}</p>
              </div>
            ))}
          </div>
          <p className="text-xs mt-2" style={{ color: '#4A5568' }}>
            Net 70% wallet credits across all engines. Software fees collected: ${Number(metrics.revenue.software_fees || 0).toFixed(2)}.
          </p>
        </div>

        {/* Auto-Repurchase & Reserve */}
        <div>
          <h2 className="font-semibold text-white mb-4">Auto-Repurchase &amp; Reserve</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'Repurchases', val: metrics.repurchase.count, money: false, icon: RefreshCw, color: '#00D4B4', sub: 'Auto re-buys executed' },
              { label: 'Repurchase Volume', val: metrics.repurchase.volume, money: true, icon: Layers, color: '#3498DB', sub: 'Total re-bought' },
              { label: 'Repurchase Platform Fees', val: metrics.repurchase.platform_fee, money: true, icon: Flame, color: '#FF4D6A', sub: 'Flat fee on auto re-buys' },
              { label: 'Reserve Held', val: metrics.repurchase.reserve_held, money: true, icon: PiggyBank, color: '#FFB547', sub: 'Awaiting next re-buy' },
            ].map(({ label, val, money, icon: Icon, color, sub }) => (
              <div key={label} className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ background: `${color}18` }}>
                  <Icon size={18} style={{ color }} />
                </div>
                <p className="text-xs" style={{ color: '#8899AA' }}>{label}</p>
                <p className="text-xl font-bold text-white mt-0.5">{money ? `$${Number(val || 0).toFixed(2)}` : Number(val || 0)}</p>
                <p className="text-xs mt-1" style={{ color: '#4A5568' }}>{sub}</p>
              </div>
            ))}
          </div>
        </div>

        {/* User Stats */}
        <div className="grid sm:grid-cols-3 gap-4">
          {[
            { label: 'Active Users', val: activeUsers, color: '#00D4B4' },
            { label: 'Frozen Users', val: frozenUsers, color: '#FF4D6A' },
            { label: 'Admin Users', val: users.filter(u => u.is_admin).length, color: '#9B59B6' },
          ].map(({ label, val, color }) => (
            <div key={label} className="rounded-xl p-4 flex items-center justify-between" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <p className="text-sm" style={{ color: '#8899AA' }}>{label}</p>
              <p className="text-xl font-bold" style={{ color }}>{val}</p>
            </div>
          ))}
        </div>
      </div>
    </Layout>
  )
}
