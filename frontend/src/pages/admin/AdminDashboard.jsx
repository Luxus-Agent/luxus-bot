import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Users, BarChart3, ArrowUpFromLine, Activity, TrendingUp, DollarSign } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function AdminDashboard() {
  const [users, setUsers] = useState([])
  const [transactions, setTransactions] = useState([])
  const [withdrawals, setWithdrawals] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/admin/users'),
      api.get('/admin/transactions'),
      api.get('/admin/withdrawals'),
    ]).then(([u, t, w]) => {
      setUsers(u.data)
      setTransactions(t.data)
      setWithdrawals(w.data)
    }).catch(() => toast.error('Failed to load admin data')).finally(() => setLoading(false))
  }, [])

  const activeUsers = users.filter(u => u.is_active).length
  const frozenUsers = users.filter(u => !u.is_active).length
  const pendingWithdrawals = withdrawals.filter(w => w.status === 'PENDING').length
  const totalWithdrawn = withdrawals
    .filter(w => w.status === 'SENT')
    .reduce((s, w) => s + parseFloat(w.amount), 0)

  const recentTx = transactions.slice(0, 8)
  const recentWithdrawals = withdrawals.slice(0, 5)

  const txTypeBreakdown = transactions.reduce((acc, t) => {
    acc[t.transaction_type] = (acc[t.transaction_type] || 0) + 1
    return acc
  }, {})

  const TOP_TX_COLOR = {
    DEPOSIT: '#00D4B4', PROACTIVE_INCOME: '#00D4B4', PROPORTION_PAYOUT: '#3498DB',
    SPECULATION_PAYOUT: '#9B59B6', WITHDRAWAL: '#FF4D6A', TRANSFER_OUT: '#FF4D6A',
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
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Total Users', val: users.length, sub: `${activeUsers} active`, icon: Users, color: '#00D4B4' },
            { label: 'Transactions', val: transactions.length, sub: 'All time', icon: Activity, color: '#3498DB' },
            { label: 'Pending Withdrawals', val: pendingWithdrawals, sub: 'Awaiting payout', icon: ArrowUpFromLine, color: '#FFB547' },
            { label: 'Total Withdrawn', val: `$${totalWithdrawn.toFixed(0)}`, sub: 'USDT sent', icon: DollarSign, color: '#00FFD4' },
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
                  const color = TOP_TX_COLOR[type] || '#8899AA'
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
            <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
              {recentTx.map(tx => {
                const color = TOP_TX_COLOR[tx.transaction_type] || '#8899AA'
                const isNeg = ['WITHDRAWAL', 'TRANSFER_OUT', 'PURCHASE', 'AGENT_PURCHASE'].includes(tx.transaction_type)
                return (
                  <div key={tx.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white truncate">
                        {tx.transaction_type.replace(/_/g, ' ')}
                      </p>
                      <p className="text-xs" style={{ color: '#4A5568' }}>
                        User #{tx.user_id} · Agent {tx.agent_tier || 'Acct'} · {new Date(tx.created_at).toLocaleString()}
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

        {/* Pending Withdrawals */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white">Recent Withdrawals</h2>
            <Link to="/admin/withdrawals" className="text-xs" style={{ color: '#00D4B4' }}>View All →</Link>
          </div>
          <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            {recentWithdrawals.length === 0 ? (
              <div className="p-6 text-center text-sm" style={{ color: '#8899AA' }}>No withdrawals</div>
            ) : (
              <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
                {recentWithdrawals.map(w => {
                  const statusColor = { PENDING: '#FFB547', PROCESSING: '#3498DB', SENT: '#00D4B4', FAILED: '#FF4D6A' }
                  const color = statusColor[w.status] || '#8899AA'
                  return (
                    <div key={w.id} className="flex items-center gap-3 px-5 py-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white">${parseFloat(w.amount).toFixed(2)} USDT</p>
                        <p className="text-xs font-mono" style={{ color: '#4A5568' }}>
                          User #{w.user_id} · {w.wallet_address.slice(0, 10)}...
                        </p>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <span
                          className="text-xs px-2 py-0.5 rounded-full font-medium"
                          style={{ background: `${color}18`, color }}
                        >
                          {w.status}
                        </span>
                        <p className="text-xs mt-0.5" style={{ color: '#4A5568' }}>
                          {new Date(w.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
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
