import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { Users, TrendingUp, DollarSign, Zap, Activity, RefreshCw, Flame, PiggyBank, Layers, Wallet, ExternalLink, AlertTriangle } from 'lucide-react'
import { addressExplorerUrl, shortenTxHash } from '../../utils/explorer'

// Only the Repurchase Reserve wallet ever broadcasts its own transaction (the
// auto-repurchase settlement, signed by REPURCHASE_SIGNER_PRIVATE_KEY per
// core/onchain.py) — so it's the only one that needs BNB for gas. Platform Fee
// and Admin Income are receive-only addresses (no signer key), so a $0 BNB
// balance there is normal, not a problem.
const GAS_WARN_BELOW = 0.01
const NEEDS_GAS_KEY = 'repurchase_reserve'
// How often to re-poll live on-chain balances while this page stays open.
const WALLET_POLL_MS = 20_000

export default function AdminDashboard() {
  const [users, setUsers] = useState([])
  const [treasury, setTreasury] = useState({ account_balance: 0, total_generated: 0, total_sent: 0, total_invested: 0, total_deposited: 0, platform_profit: 0, admin_income: 0 })
  const [metrics, setMetrics] = useState({
    revenue: { core_income: 0, stream_payout: 0, boost_payout: 0, sponsor_share: 0, total_gross_commissions: 0, total_credited_to_wallets: 0, software_fees: 0 },
    repurchase: { count: 0, volume: 0, platform_fee: 0, reserve_held: 0 },
  })
  const [onchainWallets, setOnchainWallets] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/admin/users'),
      api.get('/admin/treasury/summary'),
      // Revenue-engine + auto-repurchase aggregates. Non-fatal — never blank the page.
      api.get('/admin/metrics').catch(() => ({ data: null })),
    ]).then(([u, s, m]) => {
      setUsers(u.data)
      setTreasury(s.data)
      if (m.data) setMetrics(m.data)
    }).catch(() => toast.error('Failed to load admin data')).finally(() => setLoading(false))
  }, [])

  // Live on-chain wallet balances poll on their own timer, independent of the
  // rest of the page — these are the numbers that actually move while an admin
  // is watching (gas draining, a repurchase settlement landing), so they
  // shouldn't need a manual refresh to stay current. Non-fatal: a failed poll
  // just keeps showing the last good balances instead of blanking the section.
  useEffect(() => {
    let cancelled = false

    const fetchWallets = () => {
      api.get('/admin/treasury/onchain-wallets')
        .then(w => {
          if (cancelled) return
          setOnchainWallets(w.data.wallets || [])
        })
        .catch(() => {})
    }

    fetchWallets()
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') fetchWallets()
    }, WALLET_POLL_MS)

    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const activeUsers = users.filter(u => u.is_active).length
  const frozenUsers = users.filter(u => !u.is_active).length

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
          <h1 className="text-2xl font-bold text-white">Admin Overview</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>Platform-wide metrics and monitoring</p>
        </div>

        {/* Key Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Total Users', val: users.length, sub: `${activeUsers} active`, icon: Users, color: '#3498DB' },
            { label: 'Platform Profit', val: `$${(treasury.platform_profit || 0).toFixed(2)}`, sub: 'Fees + residuals + retained', icon: DollarSign, color: '#FFB547' },
            { label: 'Admin Income', val: `$${(treasury.admin_income || 0).toFixed(2)}`, sub: "1% Boost cut → Admin Income Wallet", icon: Wallet, color: '#9B59B6' },
            { label: 'Total Invested', val: `$${treasury.total_invested.toFixed(2)}`, sub: 'By users in the platform', icon: TrendingUp, color: 'var(--accent-glow)' },
          ].map(({ label, val, sub, icon: Icon, color }) => (
            <div key={label} className="rounded-xl p-5" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center mb-3"
                style={{ background: `color-mix(in srgb, ${color} 18%, transparent)` }}
              >
                <Icon size={20} style={{ color }} />
              </div>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</p>
              <p className="text-2xl font-bold text-white mt-0.5">{val}</p>
              <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{sub}</p>
            </div>
          ))}
        </div>

        {/* Platform Wallets — live on-chain balances */}
        <div>
          <h2 className="font-semibold text-white mb-4">Platform Wallets — Live On-Chain Balances</h2>
          <div className="grid sm:grid-cols-3 gap-4">
            {onchainWallets.map(w => {
              const lowGas = w.key === NEEDS_GAS_KEY && w.bnb_balance !== null && w.bnb_balance < GAS_WARN_BELOW
              return (
                <div key={w.key} className="rounded-xl p-5" style={{ background: 'var(--bg-panel)', border: `1px solid ${lowGas ? '#FF4D6A' : 'var(--border)'}` }}>
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: 'color-mix(in srgb, var(--accent) 18%, transparent)' }}>
                      <Wallet size={18} style={{ color: 'var(--accent)' }} />
                    </div>
                    {w.address && (
                      <a
                        href={addressExplorerUrl(w.address)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs hover:underline"
                        style={{ color: 'var(--text-muted)' }}
                        title={w.address}
                      >
                        {shortenTxHash(w.address)}
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                  <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{w.label}</p>

                  {w.error ? (
                    <p className="text-sm mt-1" style={{ color: '#FF4D6A' }}>{w.error}</p>
                  ) : (
                    <>
                      <p className="text-xl font-bold text-white mt-0.5">${(w.usdt_balance ?? 0).toFixed(2)} <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>USDT</span></p>
                      <div className="flex items-center gap-1 mt-1">
                        {lowGas && <AlertTriangle size={13} style={{ color: '#FF4D6A' }} />}
                        <p className="text-xs" style={{ color: lowGas ? '#FF4D6A' : 'var(--text-muted)' }}>
                          {(w.bnb_balance ?? 0).toFixed(4)} BNB gas{lowGas ? ' — top up soon or settlements will fail to broadcast' : ''}
                        </p>
                      </div>
                    </>
                  )}
                  {w.key !== NEEDS_GAS_KEY && (
                    <p className="text-[11px] mt-1" style={{ color: 'var(--text-muted)' }}>Receive-only — no gas needed</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Revenue Engine Breakdown */}
        <div>
          <h2 className="font-semibold text-white mb-4">Revenue Engine — Commissions Paid to Users</h2>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {[
              { label: 'Core Agent', val: metrics.revenue.core_income, icon: Zap, color: 'var(--accent)' },
              { label: 'Stream Agent', val: metrics.revenue.stream_payout, icon: TrendingUp, color: '#3498DB' },
              { label: 'Boost Agent', val: metrics.revenue.boost_payout, icon: Activity, color: '#9B59B6' },
              { label: 'Sponsor Shares', val: metrics.revenue.sponsor_share, icon: Users, color: '#FFB547' },
              { label: 'Total Commissions', val: metrics.revenue.total_gross_commissions, icon: DollarSign, color: 'var(--accent-glow)' },
            ].map(({ label, val, icon: Icon, color }) => (
              <div key={label} className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ background: `color-mix(in srgb, ${color} 18%, transparent)` }}>
                  <Icon size={18} style={{ color }} />
                </div>
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</p>
                <p className="text-xl font-bold text-white mt-0.5">${Number(val || 0).toFixed(2)}</p>
              </div>
            ))}
          </div>
          <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
            Gross commissions across all engines (before the 70/20/10 wallet split). ${Number(metrics.revenue.total_credited_to_wallets || 0).toFixed(2)} actually credited to user main wallets; ${Number(metrics.revenue.software_fees || 0).toFixed(2)} software fees collected.
          </p>
        </div>

        {/* Auto-Repurchase & Reserve */}
        <div>
          <h2 className="font-semibold text-white mb-4">Auto-Repurchase &amp; Reserve</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'Repurchases', val: metrics.repurchase.count, money: false, icon: RefreshCw, color: 'var(--accent)', sub: 'Auto re-buys executed' },
              { label: 'Repurchase Volume', val: metrics.repurchase.volume, money: true, icon: Layers, color: '#3498DB', sub: 'Total re-bought' },
              { label: 'Repurchase Platform Fees', val: metrics.repurchase.platform_fee, money: true, icon: Flame, color: '#FF4D6A', sub: 'Flat fee on auto re-buys' },
              { label: 'Reserve Held', val: metrics.repurchase.reserve_held, money: true, icon: PiggyBank, color: '#FFB547', sub: 'Awaiting next re-buy' },
            ].map(({ label, val, money, icon: Icon, color, sub }) => (
              <div key={label} className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ background: `color-mix(in srgb, ${color} 18%, transparent)` }}>
                  <Icon size={18} style={{ color }} />
                </div>
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</p>
                <p className="text-xl font-bold text-white mt-0.5">{money ? `$${Number(val || 0).toFixed(2)}` : Number(val || 0)}</p>
                <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{sub}</p>
              </div>
            ))}
          </div>
        </div>

        {/* User Stats */}
        <div className="grid sm:grid-cols-3 gap-4">
          {[
            { label: 'Active Users', val: activeUsers, color: 'var(--accent)' },
            { label: 'Frozen Users', val: frozenUsers, color: '#FF4D6A' },
            { label: 'Admin Users', val: users.filter(u => u.is_admin).length, color: '#9B59B6' },
          ].map(({ label, val, color }) => (
            <div key={label} className="rounded-xl p-4 flex items-center justify-between" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>{label}</p>
              <p className="text-xl font-bold" style={{ color }}>{val}</p>
            </div>
          ))}
        </div>
      </div>
    </Layout>
  )
}
