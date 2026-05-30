import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Bot, Activity, CheckCircle, Clock } from 'lucide-react'

const TIER_PRICES = { 1: 10, 2: 20, 3: 50, 4: 100 }

// Gross payout per level (base $10 tier). Stream scales by tier multiplier;
// Stream total = $2 + $5 + $13 = $20 = 200% of the $10 price.
const STREAM_LEVELS = [
  { key: 'l1', label: 'L1', max: 3, amount: 2 },
  { key: 'l2', label: 'L2', max: 9, amount: 5 },
  { key: 'l3', label: 'L3', max: 27, amount: 13 },
]
// Boost is a single global queue (always tier 1). Total = $0.60 + $1.50 + $4.90 = $7.00.
const BOOST_LEVELS = [
  { key: 'l1', label: 'L1', max: 3, amount: 0.60 },
  { key: 'l2', label: 'L2', max: 9, amount: 1.50 },
  { key: 'l3', label: 'L3', max: 27, amount: 4.90 },
]

function aggregateLevels(positions, config) {
  const posCount = positions.length
  return config.map(L => {
    const filled = positions.reduce((s, p) => s + (p[`${L.key}_filled`] || 0), 0)
    const paidCount = positions.filter(p => p[`${L.key}_paid`]).length
    return {
      label: L.label,
      filled,
      max: L.max * Math.max(1, posCount),
      paid: posCount > 0 && paidCount === posCount,
    }
  })
}

function ProgressCard({ icon: Icon, title, subtitle, color, owned, pct, bigValue, bigSuffix, detail, levels }) {
  return (
    <div
      className="rounded-xl p-4 flex flex-col"
      style={{ background: '#141922', border: `1px solid ${owned ? color + '40' : '#1E2A38'}` }}
    >
      <div className="flex items-center gap-2 mb-3">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ background: `${color}18`, border: `1px solid ${color}30` }}
        >
          <Icon size={18} style={{ color }} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white truncate">{title}</p>
          <p className="text-xs" style={{ color: '#4A5568' }}>{subtitle}</p>
        </div>
      </div>

      {!owned ? (
        <div className="flex-1 flex flex-col items-center justify-center py-8 text-center">
          <Clock size={22} style={{ color: '#1E2A38' }} className="mb-2" />
          <p className="text-xs" style={{ color: '#4A5568' }}>Not in queue yet</p>
        </div>
      ) : (
        <>
          <div className="flex items-end gap-1.5">
            <span className="text-2xl font-bold leading-none" style={{ color }}>{bigValue}</span>
            <span className="text-xs mb-0.5" style={{ color: '#8899AA' }}>{bigSuffix}</span>
          </div>
          <p className="text-xs mt-1 mb-3" style={{ color: '#8899AA' }}>{detail}</p>

          <div className="h-2 rounded-full overflow-hidden mb-3" style={{ background: '#0E1117' }}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${Math.min(100, pct)}%`, background: `linear-gradient(90deg, ${color}80, ${color})` }}
            />
          </div>

          <div className="space-y-1.5 mt-auto">
            {levels.map(l => (
              <div key={l.label} className="flex items-center justify-between text-xs">
                <span style={{ color: '#8899AA' }}>{l.label} ({l.filled}/{l.max})</span>
                {l.paid
                  ? <CheckCircle size={12} style={{ color: '#00D4B4' }} />
                  : <Clock size={12} style={{ color: '#4A5568' }} />}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default function Matrix() {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/agents/matrix')
      .then(r => setPositions(r.data))
      .catch(() => toast.error('Failed to load progress'))
      .finally(() => setLoading(false))
  }, [])

  // ── Per-agent Stream coverage of the 200% cap ──────────────────────────────
  const agents = [1, 2, 3, 4].map(tier => {
    const mult = TIER_PRICES[tier] / 10
    // Only real entries count toward coverage — dummy re-entries just fill the queue.
    const sp = positions.filter(p => p.system_type === 'stream' && p.agent_tier === tier && !p.is_dummy)
    const posCount = Math.max(1, sp.length)
    const earned = sp.reduce(
      (s, p) => s + (p.l1_paid ? 2 : 0) + (p.l2_paid ? 5 : 0) + (p.l3_paid ? 13 : 0),
      0,
    ) * mult
    const cap = 20 * mult * posCount               // 200% of price, per active position
    const pct = cap > 0 ? (earned / cap) * 100 : 0
    return {
      tier,
      owned: sp.length > 0,
      pct,
      earned,
      cap,
      levels: aggregateLevels(sp, STREAM_LEVELS),
    }
  })

  // ── Boost agent (single global queue) ──────────────────────────────────────
  const bp = positions.filter(p => p.system_type === 'boost')
  const boostEarned = bp.reduce(
    (s, p) => s + (p.l1_paid ? 0.60 : 0) + (p.l2_paid ? 1.50 : 0) + (p.l3_paid ? 4.90 : 0),
    0,
  )
  const boostCompleted = bp.filter(p => p.completed).length
  const boostPct = bp.length > 0 ? (boostCompleted / bp.length) * 100 : 0

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
          <h1 className="text-2xl font-bold text-white">Queue Progress</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            How much of each agent's 200% Stream return you've covered, plus your Boost queue
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
          {agents.map(a => (
            <ProgressCard
              key={a.tier}
              icon={Bot}
              title={`Agent ${a.tier}`}
              subtitle={`$${TIER_PRICES[a.tier]} · target $${(TIER_PRICES[a.tier] * 2).toFixed(0)}`}
              color="#00D4B4"
              owned={a.owned}
              pct={a.pct}
              bigValue={`${a.pct.toFixed(0)}%`}
              bigSuffix="of 200%"
              detail={`$${a.earned.toFixed(2)} of $${a.cap.toFixed(2)} earned`}
              levels={a.levels}
            />
          ))}

          <ProgressCard
            icon={Activity}
            title="Boost Agent"
            subtitle="Global queue"
            color="#9B59B6"
            owned={bp.length > 0}
            pct={boostPct}
            bigValue={`$${boostEarned.toFixed(2)}`}
            bigSuffix="earned"
            detail={`${bp.length} position${bp.length === 1 ? '' : 's'} · ${boostCompleted} completed`}
            levels={aggregateLevels(bp, BOOST_LEVELS)}
          />
        </div>
      </div>
    </Layout>
  )
}
