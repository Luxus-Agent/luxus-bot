import { useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import { CorePreviewTable } from '../components/CoreRoutingViz'
import { tierDisplayName } from '../utils/agentTiers'

// Same simulation as the admin "Revenue Engines" page's Core tab, scoped to
// the logged-in user — no username field, since it always previews the
// current user's own next purchase. Stream/Boost aren't shown here; those
// matrix queues are platform-wide, not something an individual user routes.
function UserCoreSimulator() {
  const [tier, setTier] = useState(1)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const run = async (t) => {
    setTier(t)
    setLoading(true); setError(''); setResult(null)
    try {
      const { data } = await api.get('/wallet/core-preview', { params: { tier: t } })
      setResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Preview failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl p-6" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
      <h3 className="font-semibold text-white mb-1">Purchase Distribution Preview</h3>
      <p className="text-xs mb-4" style={{ color: 'var(--text-secondary)' }}>
        Preview how your 60% purchase commission would be distributed for the selected tier.
        This simulation does not generate actual commission payouts.
      </p>
      <div className="flex gap-2 mb-5">
        {[1, 2, 3, 4].map(t => (
          <button
            key={t}
            onClick={() => run(t)}
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={tier === t && result
              ? { background: 'rgba(var(--accent-rgb),0.18)', color: 'var(--accent)', border: '1px solid rgba(var(--accent-rgb),0.5)' }
              : { background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}
          >
            {tierDisplayName(t)}
          </button>
        ))}
      </div>

      {loading && <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Simulating…</p>}
      {error && <p className="text-xs mb-4" style={{ color: '#FF4D6A' }}>{error}</p>}

      {result && !loading && <CorePreviewTable result={result} />}
    </div>
  )
}

export default function RevenueEngine() {
  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div>
          <h1 className="text-2xl font-bold text-white">Revenue Engine</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
            How the Core Agent's compression + odd/even routing decides who your purchases pay
          </p>
        </div>

        <UserCoreSimulator />
      </div>
    </Layout>
  )
}
