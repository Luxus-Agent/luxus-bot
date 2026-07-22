import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { CoreExplainerDiagram, CoreHalfChain } from '../../components/CoreRoutingViz'

const LEVEL_LABELS = { 1: 'Level 1 (3)', 2: 'Level 2 (9)', 3: 'Level 3 (27)' }

// ── Core tab: static explainer + live routing simulator (any username) ───────

function CoreSimulator() {
  const [username, setUsername] = useState('')
  const [tier, setTier] = useState(1)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    if (!username.trim()) return
    setLoading(true); setError(''); setResult(null)
    try {
      const { data } = await api.get('/admin/core/simulate', { params: { username: username.trim(), tier } })
      setResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Simulation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
      <h3 className="font-semibold text-white mb-1">Live Routing Simulator</h3>
      <p className="text-xs mb-4" style={{ color: '#8899AA' }}>
        Preview where a purchase's Core 60% would land right now for any user — read-only, never affects real payouts.
      </p>
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()}
          placeholder="Username"
          className="flex-1 px-3 py-2.5 rounded-lg text-sm outline-none"
          style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
        />
        <select
          value={tier}
          onChange={e => setTier(Number(e.target.value))}
          className="px-3 py-2.5 rounded-lg text-sm outline-none"
          style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
        >
          {[1, 2, 3, 4].map(t => <option key={t} value={t}>Agent {t}</option>)}
        </select>
        <button
          onClick={run}
          disabled={loading || !username.trim()}
          className="px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50"
          style={{ background: '#00D4B4', color: '#000' }}
        >
          {loading ? 'Simulating…' : 'Simulate'}
        </button>
      </div>

      {error && <p className="text-xs mb-4" style={{ color: '#FF4D6A' }}>{error}</p>}

      {result && (
        <div className="grid md:grid-cols-2 gap-4">
          <CoreHalfChain title={`First 30% Half — @${result.buyer} buys Agent ${result.buyer_tier}`} half={result.half1} />
          <CoreHalfChain title="Second 30% Half" half={result.half2} />
        </div>
      )}
    </div>
  )
}

// ── Stream / Boost tab: queue fill state + queue contents ────────────────────

function QueueList({ slots, color }) {
  return (
    <div className="max-h-72 overflow-y-auto pr-1">
      <p className="text-xs mb-3" style={{ color: '#4A5568' }}>
        Head position {slots.head_position} pays out once {slots.threshold} more members join behind it.
      </p>
      <div className="space-y-1">
        {slots.slots.map(s => (
          <div key={s.position_number} className="flex items-center gap-2">
            <div
              className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ background: s.is_head ? color : '#1E2A38', border: s.is_head ? 'none' : '1px solid #2A3A4A' }}
            />
            <div
              className="flex-1 flex items-center justify-between px-3 py-2 rounded-lg text-xs"
              style={{
                background: s.is_head ? `${color}12` : '#0E1117',
                border: `1px solid ${s.is_head ? color + '50' : '#1E2A38'}`,
              }}
            >
              <span className="text-white font-medium">#{s.position_number} · @{s.username}</span>
              <div className="flex items-center gap-2">
                {s.is_dummy && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: 'rgba(255,181,71,0.12)', color: '#FFB547' }}>
                    RE-ENTRY
                  </span>
                )}
                {s.is_head && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: `${color}20`, color }}>
                    NEXT TO PAY
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function LevelCard({ label, data, color, systemType, tier }) {
  const [expanded, setExpanded] = useState(false)
  const [slots, setSlots] = useState(null)
  const [loadingSlots, setLoadingSlots] = useState(false)

  const toggle = async () => {
    if (!expanded && !slots) {
      setLoadingSlots(true)
      try {
        const { data: sd } = await api.get('/admin/matrix/queue-slots', {
          params: { system_type: systemType, tier, level: data.level },
        })
        setSlots(sd)
      } catch {
        toast.error('Failed to load queue')
      } finally {
        setLoadingSlots(false)
      }
    }
    setExpanded(v => !v)
  }

  return (
    <div className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-white">{label}</p>
        <span className="text-xs" style={{ color: '#8899AA' }}>{data.filled}/{data.threshold} new joins</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden mb-3" style={{ background: '#0E1117' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${data.percent}%`, background: color }} />
      </div>
      <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 text-xs mb-3" style={{ color: '#8899AA' }}>
        <p>Wallet payout: <span className="text-white">${data.wallet_amount.toFixed(2)}</span></p>
        <p>Completions: <span className="text-white">{data.completions}</span></p>
        <p>Re-entry: <span className="text-white">${data.reentry_amount.toFixed(2)} × {data.reentry_count}</span></p>
        <p>Total joined: <span className="text-white">{data.total_joined}</span></p>
      </div>
      {data.sponsor_on_completion > 0 && (
        <p className="text-xs mb-3" style={{ color: '#4A5568' }}>Sponsor share on completion: ${data.sponsor_on_completion.toFixed(2)}</p>
      )}
      <button onClick={toggle} className="text-xs font-medium" style={{ color }}>
        {expanded ? 'Hide Queue ↑' : 'View Queue ↓'}
      </button>

      {expanded && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid #1E2A38' }}>
          {loadingSlots ? (
            <p className="text-xs" style={{ color: '#8899AA' }}>Loading…</p>
          ) : slots && slots.slots.length ? (
            <QueueList slots={slots} color={color} />
          ) : (
            <p className="text-xs" style={{ color: '#4A5568' }}>No entries yet.</p>
          )}
        </div>
      )}
    </div>
  )
}

function MatrixTab({ systemType, color, tiers, overview }) {
  const [tier, setTier] = useState(tiers[0])
  const tierData = overview?.[systemType]?.[String(tier)] || []

  return (
    <div className="space-y-4">
      {tiers.length > 1 && (
        <div className="flex gap-2">
          {tiers.map(t => (
            <button
              key={t}
              onClick={() => setTier(t)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={tier === t
                ? { background: `${color}18`, color, border: `1px solid ${color}50` }
                : { background: '#141922', color: '#8899AA', border: '1px solid #1E2A38' }}
            >
              Agent {t}
            </button>
          ))}
        </div>
      )}
      {tiers.length === 1 && (
        <p className="text-xs" style={{ color: '#4A5568' }}>Boost runs a single global queue (always Agent 1) — no per-tier split.</p>
      )}
      <div className="grid md:grid-cols-3 gap-4">
        {tierData.map(levelData => (
          <LevelCard
            key={levelData.level}
            label={LEVEL_LABELS[levelData.level]}
            data={levelData}
            color={color}
            systemType={systemType}
            tier={tier}
          />
        ))}
      </div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'core', label: 'Core Agent', color: '#00D4B4' },
  { key: 'stream', label: 'Stream Agent', color: '#3498DB' },
  { key: 'boost', label: 'Boost Agent', color: '#9B59B6' },
]

export default function AdminRevenueEngines() {
  const [tab, setTab] = useState('core')
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/admin/matrix/overview')
      .then(r => setOverview(r.data))
      .catch(() => toast.error('Failed to load matrix overview'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div>
          <h1 className="text-2xl font-bold text-white">Revenue Engines</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            Core compression/odd-even routing and Stream/Boost matrix queues
          </p>
        </div>

        <div className="flex gap-2">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className="px-4 py-2 rounded-lg text-sm font-semibold transition-all"
              style={tab === t.key
                ? { background: `${t.color}18`, color: t.color, border: `1px solid ${t.color}50` }
                : { background: '#141922', color: '#8899AA', border: '1px solid #1E2A38' }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="w-8 h-8 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
          </div>
        ) : (
          <>
            {tab === 'core' && (
              <div className="space-y-4">
                <CoreExplainerDiagram />
                <CoreSimulator />
              </div>
            )}
            {tab === 'stream' && <MatrixTab systemType="stream" color="#3498DB" tiers={[1, 2, 3, 4]} overview={overview} />}
            {tab === 'boost' && <MatrixTab systemType="boost" color="#9B59B6" tiers={[1]} overview={overview} />}
          </>
        )}
      </div>
    </Layout>
  )
}
