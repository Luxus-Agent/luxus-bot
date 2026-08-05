import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { CorePreviewTable, DownlineColumn } from '../../components/CoreRoutingViz'
import { tierDisplayName } from '../../utils/agentTiers'

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
    <div className="rounded-xl p-6" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
      <h3 className="font-semibold text-white mb-1">Purchase Distribution Preview</h3>
      <p className="text-xs mb-4" style={{ color: 'var(--text-secondary)' }}>
        Preview how a 60% purchase commission would be distributed for any user and tier.
        This simulation does not generate actual commission payouts.
      </p>
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()}
          placeholder="Username"
          className="flex-1 px-3 py-2.5 rounded-lg text-sm outline-none"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        />
        <select
          value={tier}
          onChange={e => setTier(Number(e.target.value))}
          className="px-3 py-2.5 rounded-lg text-sm outline-none"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          {[1, 2, 3, 4].map(t => <option key={t} value={t}>{tierDisplayName(t)}</option>)}
        </select>
        <button
          onClick={run}
          disabled={loading || !username.trim()}
          className="px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50"
          style={{ background: 'var(--accent)', color: '#000' }}
        >
          {loading ? 'Simulating…' : 'Simulate'}
        </button>
      </div>

      {error && <p className="text-xs mb-4" style={{ color: '#FF4D6A' }}>{error}</p>}

      {result && <CorePreviewTable result={result} />}
    </div>
  )
}

// ── Core tab: direct downline split into odd/even (left/right) columns ───────
// DownlineColumn moved to CoreRoutingViz.jsx so the user-facing Revenue Engine
// page can share the same rendering.

function CoreDownlineTable() {
  const [username, setUsername] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    if (!username.trim()) return
    setLoading(true); setError(''); setResult(null)
    try {
      const { data } = await api.get('/admin/core/downline', { params: { username: username.trim() } })
      setResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl p-6" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
      <h3 className="font-semibold text-white mb-1">Downline Odd/Even Table</h3>
      <p className="text-xs mb-4" style={{ color: 'var(--text-secondary)' }}>
        A sponsor's direct downline, split by join order into a left/odd and right/even column
        (1st, 3rd, 5th referral on the left; 2nd, 4th on the right).
      </p>
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()}
          placeholder="Sponsor username"
          className="flex-1 px-3 py-2.5 rounded-lg text-sm outline-none"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        />
        <button
          onClick={run}
          disabled={loading || !username.trim()}
          className="px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50"
          style={{ background: 'var(--accent)', color: '#000' }}
        >
          {loading ? 'Loading…' : 'Look Up'}
        </button>
      </div>

      {error && <p className="text-xs mb-4" style={{ color: '#FF4D6A' }}>{error}</p>}

      {result && (
        result.total === 0 ? (
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>@{result.sponsor} has no direct downline yet.</p>
        ) : (
          <div className="grid md:grid-cols-2 gap-4">
            <DownlineColumn title="Left / Odd" color="var(--accent)" members={result.left_odd} />
            <DownlineColumn title="Right / Even" color="#3498DB" members={result.right_even} />
          </div>
        )
      )}
    </div>
  )
}

// ── Stream / Boost tab: queue fill state + queue contents ────────────────────

function QueueList({ slots, color }) {
  return (
    <div className="max-h-72 overflow-y-auto pr-1">
      <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
        Head position {slots.head_position} pays out once {slots.threshold} more members join behind it.
      </p>
      <div className="space-y-1">
        {slots.slots.map(s => (
          <div key={s.position_number} className="flex items-center gap-2">
            <div
              className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ background: s.is_head ? color : 'var(--border)', border: s.is_head ? 'none' : '1px solid var(--border-subtle)' }}
            />
            <div
              className="flex-1 flex items-center justify-between px-3 py-2 rounded-lg text-xs"
              style={{
                background: s.is_head ? `color-mix(in srgb, ${color} 12%, transparent)` : 'var(--bg-surface)',
                border: `1px solid ${s.is_head ? `color-mix(in srgb, ${color} 50%, transparent)` : 'var(--border)'}`,
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
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: `color-mix(in srgb, ${color} 20%, transparent)`, color }}>
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

// Single vertical stack of every position in a level's queue, in true arrival
// order, with curved connectors linking each paying position to the re-entry
// slot(s) it spawned — the client's own "How matrix queue work?" spec diagram.
function MatrixFlowDiagram({ systemType, tier, level, color }) {
  const [flow, setFlow] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(''); setFlow(null)
    api.get('/admin/matrix/queue-flow', { params: { system_type: systemType, tier, level } })
      .then(r => { if (!cancelled) setFlow(r.data) })
      .catch(err => { if (!cancelled) setError(err.response?.data?.detail || 'Failed to load flow') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [systemType, tier, level])

  if (loading) return <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Loading…</p>
  if (error) return <p className="text-xs" style={{ color: '#FF4D6A' }}>{error}</p>
  if (!flow || flow.slots.length === 0) return <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No entries yet.</p>

  const rowH = 34
  const rowGap = 5
  const stride = rowH + rowGap
  const height = flow.slots.length * stride - rowGap
  const yFor = pos => (pos - 1) * stride + rowH / 2

  const arcs = flow.slots
    .filter(s => s.spawned_from != null)
    .map(s => ({ from: s.spawned_from, to: s.position_number }))
    .sort((a, b) => a.to - b.to)
  const gutter = 22
  const svgWidth = gutter + Math.max(1, arcs.length) * 14

  return (
    <div className="max-h-[28rem] overflow-y-auto pr-1">
      <div className="flex gap-1">
        <svg width={svgWidth} height={height} className="flex-shrink-0">
          {arcs.map((a, i) => {
            const y1 = yFor(a.from)
            const y2 = yFor(a.to)
            const x0 = svgWidth
            const xC = svgWidth - (gutter + i * 14)
            return (
              <path
                key={`${a.from}-${a.to}`}
                d={`M ${x0} ${y1} C ${xC} ${y1}, ${xC} ${y2}, ${x0} ${y2}`}
                fill="none"
                stroke={color}
                strokeOpacity="0.5"
                strokeWidth="1.5"
              />
            )
          })}
        </svg>
        <div className="flex-1" style={{ display: 'flex', flexDirection: 'column', gap: rowGap }}>
          {flow.slots.map(s => (
            <div
              key={s.position_number}
              className="flex items-center justify-between px-3 rounded-lg text-xs"
              style={{
                height: rowH,
                flexShrink: 0,
                background: s.is_head
                  ? `color-mix(in srgb, ${color} 16%, transparent)`
                  : `color-mix(in srgb, ${color} 8%, transparent)`,
                border: `1px solid ${s.is_head ? `color-mix(in srgb, ${color} 55%, transparent)` : 'var(--border)'}`,
              }}
            >
              <span className="text-white font-medium">#{s.position_number} · @{s.username}</span>
              <div className="flex items-center gap-1.5">
                {s.is_reentry && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: 'rgba(255,181,71,0.12)', color: '#FFB547' }}>
                    RE-ENTRY
                  </span>
                )}
                {s.is_paid && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)' }}>
                    PAID
                  </span>
                )}
                {s.is_head && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: `color-mix(in srgb, ${color} 20%, transparent)`, color }}>
                    NEXT TO PAY
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function LevelCard({ label, data, color, systemType, tier }) {
  const [expanded, setExpanded] = useState(false)
  const [slots, setSlots] = useState(null)
  const [loadingSlots, setLoadingSlots] = useState(false)
  const [flowOpen, setFlowOpen] = useState(false)

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
    <div className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-white">{label}</p>
        <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>{data.filled}/{data.threshold} new joins</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden mb-3" style={{ background: 'var(--bg-surface)' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${data.percent}%`, background: color }} />
      </div>
      <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 text-xs mb-3" style={{ color: 'var(--text-secondary)' }}>
        <p>Wallet payout: <span className="text-white">${data.wallet_amount.toFixed(2)}</span></p>
        <p>Completions: <span className="text-white">{data.completions}</span></p>
        <p>Re-entry: <span className="text-white">${data.reentry_amount.toFixed(2)} × {data.reentry_count}</span></p>
        <p>Total joined: <span className="text-white">{data.total_joined}</span></p>
      </div>
      {data.sponsor_on_completion > 0 && (
        <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>Sponsor share on completion: ${data.sponsor_on_completion.toFixed(2)}</p>
      )}
      <div className="flex items-center gap-4">
        <button onClick={toggle} className="text-xs font-medium" style={{ color }}>
          {expanded ? 'Hide Queue ↑' : 'View Queue ↓'}
        </button>
        <button onClick={() => setFlowOpen(v => !v)} className="text-xs font-medium" style={{ color }}>
          {flowOpen ? 'Hide Flow View ↑' : 'Flow View ↓'}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--border)' }}>
          {loadingSlots ? (
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Loading…</p>
          ) : slots && slots.slots.length ? (
            <QueueList slots={slots} color={color} />
          ) : (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No entries yet.</p>
          )}
        </div>
      )}

      {flowOpen && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--border)' }}>
          <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
            Full queue in arrival order — curved lines link each paying position to the re-entry it spawned.
          </p>
          <MatrixFlowDiagram systemType={systemType} tier={tier} level={data.level} color={color} />
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
                ? { background: `color-mix(in srgb, ${color} 18%, transparent)`, color, border: `1px solid color-mix(in srgb, ${color} 50%, transparent)` }
                : { background: 'var(--bg-panel)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}
            >
              {tierDisplayName(t)}
            </button>
          ))}
        </div>
      )}
      {tiers.length === 1 && (
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Boost runs a single global queue (always {tierDisplayName(1)}) — no per-tier split.</p>
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
  { key: 'core', label: 'Core Agent', color: 'var(--accent)' },
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
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
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
                ? { background: `color-mix(in srgb, ${t.color} 18%, transparent)`, color: t.color, border: `1px solid color-mix(in srgb, ${t.color} 50%, transparent)` }
                : { background: 'var(--bg-panel)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="w-8 h-8 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: 'var(--accent)' }} />
          </div>
        ) : (
          <>
            {tab === 'core' && (
              <div className="space-y-4">
                <CoreSimulator />
                <CoreDownlineTable />
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
