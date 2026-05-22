import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Bot, Zap, TrendingUp, Activity, CheckCircle, Clock, ShoppingCart } from 'lucide-react'

const TIERS = [
  {
    id: 1, price: 10, name: 'Agent 1',
    proactive: '$3.00', proportion: '$35.00', speculation: '$10.80',
    color: '#00D4B4', desc: 'Entry level AI agent with full revenue mechanics',
  },
  {
    id: 2, price: 20, name: 'Agent 2',
    proactive: '$6.00', proportion: '$70.00', speculation: '$21.60',
    color: '#3498DB', desc: '2× multiplier — doubles all payouts',
  },
  {
    id: 3, price: 50, name: 'Agent 3',
    proactive: '$15.00', proportion: '$175.00', speculation: '$54.00',
    color: '#9B59B6', desc: '5× multiplier — high-yield tier',
  },
  {
    id: 4, price: 100, name: 'Agent 4',
    proactive: '$30.00', proportion: '$350.00', speculation: '$108.00',
    color: '#FFB547', desc: '10× multiplier — maximum earning potential',
  },
]

export default function AgentPurchase() {
  const [purchases, setPurchases] = useState([])
  const [accountBalance, setAccountBalance] = useState(0)
  const [loading, setLoading] = useState(true)
  const [purchasing, setPurchasing] = useState(null)

  useEffect(() => {
    Promise.all([
      api.get('/agents/purchases'),
      api.get('/deposit/balance'),
    ]).then(([p, b]) => {
      setPurchases(p.data)
      setAccountBalance(parseFloat(b.data.balance))
    }).catch(() => toast.error('Failed to load')).finally(() => setLoading(false))
  }, [])

  const handlePurchase = async (tierId, price) => {
    if (accountBalance < price) {
      toast.error(`Insufficient balance. You need $${price} but have $${accountBalance.toFixed(2)}`)
      return
    }
    if (!window.confirm(`Purchase Agent ${tierId} for $${price}? This will deduct from your account balance.`)) return
    setPurchasing(tierId)
    try {
      await api.post('/agents/purchase', { agent_tier: tierId })
      toast.success(`Agent ${tierId} purchased and activating!`)
      const [p, b] = await Promise.all([api.get('/agents/purchases'), api.get('/deposit/balance')])
      setPurchases(p.data)
      setAccountBalance(parseFloat(b.data.balance))
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Purchase failed')
    } finally {
      setPurchasing(null)
    }
  }

  const tierCount = (tier) => purchases.filter(p => p.agent_tier === tier && p.status === 'active').length

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
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Buy AI Agents</h1>
            <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
              Purchase triggers 3 parallel revenue mechanisms automatically
            </p>
          </div>
          <div
            className="px-4 py-3 rounded-xl"
            style={{ background: '#141922', border: '1px solid #1E2A38' }}
          >
            <p className="text-xs" style={{ color: '#8899AA' }}>Account Balance</p>
            <p className="text-xl font-bold" style={{ color: '#00D4B4' }}>${accountBalance.toFixed(2)}</p>
          </div>
        </div>

        {/* Revenue Split Info */}
        <div className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <p className="text-sm font-semibold text-white mb-3">Revenue Split on Every Purchase</p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'ProActive', pct: '60%', desc: '30% sponsor + 30% supreme', icon: Zap, color: '#00D4B4' },
              { label: 'Proportion', pct: '30%', desc: '3×3 matrix queue', icon: TrendingUp, color: '#3498DB' },
              { label: 'Speculation', pct: '10%', desc: '3×3 matrix queue', icon: Activity, color: '#9B59B6' },
            ].map(({ label, pct, desc, icon: Icon, color }) => (
              <div key={label} className="rounded-lg p-3 text-center" style={{ background: '#0E1117' }}>
                <Icon size={18} className="mx-auto mb-1" style={{ color }} />
                <p className="text-xs font-bold" style={{ color }}>{pct}</p>
                <p className="text-xs font-medium text-white">{label}</p>
                <p className="text-xs mt-0.5" style={{ color: '#4A5568' }}>{desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Agent Tier Cards */}
        <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {TIERS.map(tier => {
            const count = tierCount(tier.id)
            const canAfford = accountBalance >= tier.price
            const isBuying = purchasing === tier.id
            return (
              <div
                key={tier.id}
                className="rounded-xl overflow-hidden transition-all"
                style={{ background: '#141922', border: `1px solid ${tier.color}30` }}
              >
                {/* Header */}
                <div className="p-4 pb-3" style={{ background: `${tier.color}0A` }}>
                  <div className="flex items-center justify-between mb-2">
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center"
                      style={{ background: `${tier.color}20`, border: `1px solid ${tier.color}40` }}
                    >
                      <Bot size={20} style={{ color: tier.color }} />
                    </div>
                    {count > 0 && (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-semibold"
                        style={{ background: `${tier.color}20`, color: tier.color }}
                      >
                        {count}x ACTIVE
                      </span>
                    )}
                  </div>
                  <h3 className="text-lg font-bold text-white">{tier.name}</h3>
                  <p className="text-2xl font-bold" style={{ color: tier.color }}>${tier.price}</p>
                  <p className="text-xs mt-1" style={{ color: '#8899AA' }}>{tier.desc}</p>
                </div>

                {/* Payouts */}
                <div className="px-4 py-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: '#4A5568' }}>Max Payouts</p>
                  {[
                    { label: 'ProActive Total', val: tier.proactive },
                    { label: 'Proportion Total', val: tier.proportion },
                    { label: 'Speculation Total', val: tier.speculation },
                  ].map(({ label, val }) => (
                    <div key={label} className="flex justify-between text-xs">
                      <span style={{ color: '#8899AA' }}>{label}</span>
                      <span className="font-semibold text-white">{val}</span>
                    </div>
                  ))}
                </div>

                {/* Button */}
                <div className="px-4 pb-4">
                  <button
                    onClick={() => handlePurchase(tier.id, tier.price)}
                    disabled={isBuying || !canAfford}
                    className="w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all"
                    style={{
                      background: isBuying ? `${tier.color}40` : canAfford ? tier.color : '#1E2A38',
                      color: canAfford && !isBuying ? '#000' : '#4A5568',
                      cursor: isBuying || !canAfford ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {isBuying ? (
                      <div className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
                    ) : !canAfford ? (
                      <>Insufficient Balance</>
                    ) : (
                      <><ShoppingCart size={14} /> Purchase</>
                    )}
                  </button>
                  {!canAfford && (
                    <p className="text-xs mt-1.5 text-center" style={{ color: '#4A5568' }}>
                      Need ${(tier.price - accountBalance).toFixed(2)} more
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Purchase History */}
        {purchases.length > 0 && (
          <div>
            <h2 className="font-semibold text-white mb-4">Purchase History</h2>
            <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
                {purchases.map(p => (
                  <div key={p.id} className="flex items-center gap-3 px-4 py-3">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
                      style={{ background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }}
                    >
                      A{p.agent_tier}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white">Agent {p.agent_tier} — ${parseFloat(p.price).toFixed(2)}</p>
                      <p className="text-xs" style={{ color: '#4A5568' }}>
                        {new Date(p.created_at).toLocaleString()}
                      </p>
                    </div>
                    <span
                      className="text-xs px-2 py-0.5 rounded-full font-medium flex items-center gap-1 flex-shrink-0"
                      style={p.status === 'active'
                        ? { background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }
                        : { background: 'rgba(255,181,71,0.12)', color: '#FFB547' }
                      }
                    >
                      {p.status === 'active' ? <CheckCircle size={11} /> : <Clock size={11} />}
                      {p.status.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  )
}
