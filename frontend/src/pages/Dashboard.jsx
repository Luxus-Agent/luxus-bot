import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import {
  Wallet, TrendingUp, Bot, ArrowDownToLine, ArrowUpFromLine,
  Copy, Check, Users, Zap, Activity, ChevronRight
} from 'lucide-react'
import toast from 'react-hot-toast'

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
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    Promise.all([
      api.get('/wallet/balances'),
      api.get('/agents/purchases'),
      api.get('/wallet/transactions'),
    ]).then(([wb, pb, tb]) => {
      setWallets(wb.data)
      setPurchases(pb.data)
      setTransactions(tb.data.slice(0, 5))
    }).catch(() => toast.error('Failed to load dashboard')).finally(() => setLoading(false))
  }, [])

  const mainWallets = wallets.filter(w => w.wallet_type === 'MAIN')
  const accountWallet = wallets.find(w => w.wallet_type === 'ACCOUNT' && w.agent_tier === 0)
  const totalMain = mainWallets.reduce((s, w) => s + parseFloat(w.balance), 0)
  const activePurchases = purchases.filter(p => p.status === 'active')

  const copyRef = () => {
    const name = user?.username
    if (!name) return
    navigator.clipboard.writeText(name)
    setCopied(true)
    toast.success('Username copied!')
    setTimeout(() => setCopied(false), 2000)
  }

  const txTypeColor = {
    DEPOSIT: '#00D4B4',
    CORE_INCOME: '#00D4B4',
    STREAM_PAYOUT: '#00D4B4',
    BOOST_PAYOUT: '#00D4B4',
    SPONSOR_MILESTONE_INCOME: '#00D4B4',
    TRANSFER_IN: '#00D4B4',
    WITHDRAWAL: '#FF4D6A',
    TRANSFER_OUT: '#FF4D6A',
    REPURCHASE_HOLD: '#FFB547',
    REENTRY: '#8899AA',
    PURCHASE: '#FF4D6A',
    AGENT_PURCHASE: '#FF4D6A',
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
            icon={Wallet}
            label="Account Balance"
            value={`$${parseFloat(accountWallet?.balance || 0).toFixed(2)}`}
            sub="Available to spend"
            color="#00D4B4"
          />
          <StatCard
            icon={TrendingUp}
            label="Total Earnings"
            value={`$${totalMain.toFixed(2)}`}
            sub="Across all wallets"
            color="#00FFD4"
          />
          <StatCard
            icon={Bot}
            label="Active Agents"
            value={activePurchases.length}
            sub={`of ${purchases.length} purchased`}
            color="#9B59B6"
          />
          <StatCard
            icon={Activity}
            label="Transactions"
            value={transactions.length > 0 ? `${transactions.length}+` : '0'}
            sub="Recent activity"
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
                  const mainW = wallets.find(w => w.wallet_type === 'MAIN' && w.agent_tier === tier)
                  const repW = wallets.find(w => w.wallet_type === 'REPURCHASE' && w.agent_tier === tier)
                  const repBal = parseFloat(repW?.balance || 0)
                  const progress = Math.min(100, (repBal / TIER_PRICES[tier]) * 100)
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
                            <span className="text-white">${repBal.toFixed(2)} / ${TIER_PRICES[tier]}</span>
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
                { to: '/deposit', icon: ArrowDownToLine, label: 'Deposit USDT', sub: 'Top up account', color: '#00D4B4' },
                { to: '/agents', icon: Bot, label: 'Buy Agent', sub: 'Purchase a tier', color: '#9B59B6' },
                { to: '/withdraw', icon: ArrowUpFromLine, label: 'Withdraw', sub: 'Send to wallet', color: '#FFB547' },
                { to: '/matrix', icon: Users, label: 'View Matrix', sub: 'Track positions', color: '#3498DB' },
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

        {/* Recent Transactions */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white">Recent Transactions</h2>
            <Link to="/transactions" className="text-xs font-medium" style={{ color: '#00D4B4' }}>View All →</Link>
          </div>
          <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            {transactions.length === 0 ? (
              <div className="p-8 text-center" style={{ color: '#8899AA' }}>
                <Activity size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">No transactions yet</p>
              </div>
            ) : (
              <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
                {transactions.map(tx => {
                  const isPositive = !['WITHDRAWAL', 'TRANSFER_OUT', 'PURCHASE', 'AGENT_PURCHASE', 'REPURCHASE_HOLD'].includes(tx.transaction_type)
                  return (
                    <div key={tx.id} className="flex items-center gap-3 px-4 py-3">
                      <div
                        className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
                        style={{
                          background: `${txTypeColor[tx.transaction_type] || '#8899AA'}18`,
                          color: txTypeColor[tx.transaction_type] || '#8899AA'
                        }}
                      >
                        {isPositive ? '+' : '-'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                          {tx.transaction_type.replace(/_/g, ' ')}
                        </p>
                        <p className="text-xs" style={{ color: '#4A5568' }}>
                          Agent {tx.agent_tier || 'Account'} • {new Date(tx.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      <p
                        className="text-sm font-semibold flex-shrink-0"
                        style={{ color: isPositive ? '#00D4B4' : '#FF4D6A' }}
                      >
                        {isPositive ? '+' : '-'}${Math.abs(parseFloat(tx.amount)).toFixed(2)}
                      </p>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  )
}
