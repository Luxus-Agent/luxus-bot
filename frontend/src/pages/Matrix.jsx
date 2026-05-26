import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Network, CheckCircle, Clock, Users } from 'lucide-react'

const SYSTEM_TYPES = ['stream', 'boost']
const SYSTEM_COLOR = { stream: '#3498DB', boost: '#9B59B6' }
const SYSTEM_LABEL = { stream: 'Stream', boost: 'Boost' }
const TIER_PRICES = { 1: 10, 2: 20, 3: 50, 4: 100 }

function MatrixCard({ position, systemType }) {
  const color = SYSTEM_COLOR[systemType] || '#8899AA'
  const l1Pct = Math.min(100, (position.l1_filled / 3) * 100)
  const l2Pct = Math.min(100, (position.l2_filled / 9) * 100)
  const l3Pct = Math.min(100, (position.l3_filled / 27) * 100)

  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: '#141922',
        border: `1px solid ${position.completed ? color + '40' : '#1E2A38'}`,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold"
            style={{ background: `${color}18`, color }}
          >
            #{position.position_number}
          </div>
          <div>
            <p className="text-sm font-semibold text-white">
              {SYSTEM_LABEL[systemType] || systemType} Agent · Agent {position.agent_tier}
            </p>
            <p className="text-xs" style={{ color: '#4A5568' }}>
              {position.is_dummy ? 'Re-entry (dummy)' : 'Active position'}
            </p>
          </div>
        </div>
        {position.completed ? (
          <CheckCircle size={18} style={{ color: '#00D4B4' }} />
        ) : (
          <Clock size={18} style={{ color: '#FFB547' }} />
        )}
      </div>

      <div className="space-y-2">
        {[
          { label: 'L1', filled: position.l1_filled, max: 3, paid: position.l1_paid, pct: l1Pct },
          { label: 'L2', filled: position.l2_filled, max: 9, paid: position.l2_paid, pct: l2Pct },
          { label: 'L3', filled: position.l3_filled, max: 27, paid: position.l3_paid, pct: l3Pct },
        ].map(({ label, filled, max, paid, pct }) => (
          <div key={label}>
            <div className="flex justify-between text-xs mb-1">
              <span style={{ color: '#8899AA' }}>{label} ({filled}/{max})</span>
              {paid && <span style={{ color: '#00D4B4' }}>✓ Paid</span>}
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#0E1117' }}>
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${pct}%`,
                  background: paid
                    ? '#00D4B4'
                    : `linear-gradient(90deg, ${color}80, ${color})`,
                }}
              />
            </div>
          </div>
        ))}
      </div>

      {position.reentry_count > 0 && (
        <p className="text-xs mt-2" style={{ color: '#4A5568' }}>
          Re-entries generated: {position.reentry_count}
        </p>
      )}
    </div>
  )
}

export default function Matrix() {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)
  const [filterSystem, setFilterSystem] = useState('all')
  const [filterTier, setFilterTier] = useState('all')

  useEffect(() => {
    api.get('/agents/matrix')
      .then(r => setPositions(r.data))
      .catch(() => toast.error('Failed to load matrix'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = positions.filter(p => {
    if (filterSystem !== 'all' && p.system_type !== filterSystem) return false
    if (filterTier !== 'all' && p.agent_tier !== parseInt(filterTier)) return false
    return true
  })

  const streamPositions = positions.filter(p => p.system_type === 'stream')
  const boostPositions  = positions.filter(p => p.system_type === 'boost')
  const completedCount  = positions.filter(p => p.completed).length

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
          <h1 className="text-2xl font-bold text-white">Matrix Positions</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            Track your 3×3 Stream and Boost Agent matrix placements
          </p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Total Positions', val: positions.length, color: '#00D4B4' },
            { label: 'Completed', val: completedCount, color: '#00FFD4' },
            { label: 'Stream Agent', val: streamPositions.length, color: '#3498DB' },
            { label: 'Boost Agent', val: boostPositions.length, color: '#9B59B6' },
          ].map(({ label, val, color }) => (
            <div key={label} className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <p className="text-xs" style={{ color: '#8899AA' }}>{label}</p>
              <p className="text-2xl font-bold mt-1" style={{ color }}>{val}</p>
            </div>
          ))}
        </div>

        {/* Revenue Guide */}
        <div className="rounded-xl p-5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <p className="text-sm font-semibold text-white mb-3">Payout Schedule (Agent 1 — $10 tier)</p>
          <div className="grid md:grid-cols-2 gap-4 text-xs">
            <div>
              <p className="font-semibold mb-2" style={{ color: '#3498DB' }}>Stream Agent Matrix (30%)</p>
              <div className="space-y-1" style={{ color: '#8899AA' }}>
                <div className="flex justify-between"><span>L1 (3 members)</span><span className="text-white">$2.00 + 1 re-entry</span></div>
                <div className="flex justify-between"><span>L2 (9 members)</span><span className="text-white">$5.00 + 2 re-entries</span></div>
                <div className="flex justify-between"><span>L3 (27 members)</span><span className="text-white">$13.00 + 3 re-entries</span></div>
              </div>
            </div>
            <div>
              <p className="font-semibold mb-2" style={{ color: '#9B59B6' }}>Boost Agent Matrix (10%)</p>
              <div className="space-y-1" style={{ color: '#8899AA' }}>
                <div className="flex justify-between"><span>L1 (3 members)</span><span className="text-white">$0.60 + 1 re-entry</span></div>
                <div className="flex justify-between"><span>L2 (9 members)</span><span className="text-white">$1.50 + 2 re-entries</span></div>
                <div className="flex justify-between"><span>L3 (27 members)</span><span className="text-white">$4.90 + 3 re-entries</span></div>
              </div>
            </div>
          </div>
          <p className="text-xs mt-3" style={{ color: '#4A5568' }}>
            Stream re-entries go into the Boost Agent queue. Boost Agent positions earn full payouts — no dummy entries.
            10% of every payout is held in repurchase reserve.
          </p>
        </div>

        {/* Filters */}
        <div className="flex gap-2 flex-wrap">
          <select
            value={filterSystem}
            onChange={e => setFilterSystem(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
          >
            <option value="all">All Systems</option>
            <option value="stream">Stream Agent</option>
            <option value="boost">Boost Agent</option>
          </select>
          <select
            value={filterTier}
            onChange={e => setFilterTier(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
          >
            <option value="all">All Tiers</option>
            {[1, 2, 3, 4].map(t => <option key={t} value={t}>Agent {t}</option>)}
          </select>
        </div>

        {/* Positions Grid */}
        {filtered.length === 0 ? (
          <div
            className="rounded-xl p-12 text-center"
            style={{ background: '#141922', border: '1px dashed #1E2A38' }}
          >
            <Network size={40} style={{ color: '#1E2A38' }} className="mx-auto mb-3" />
            <p className="text-sm" style={{ color: '#8899AA' }}>No matrix positions yet</p>
            <p className="text-xs mt-1" style={{ color: '#4A5568' }}>Purchase an agent to enter the matrix</p>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map(p => (
              <MatrixCard key={p.id} position={p} systemType={p.system_type} />
            ))}
          </div>
        )}
      </div>
    </Layout>
  )
}
