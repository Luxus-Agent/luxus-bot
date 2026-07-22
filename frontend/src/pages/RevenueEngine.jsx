import { useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import { CoreExplainerDiagram, CoreHalfChain } from '../components/CoreRoutingViz'

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
    <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
      <h3 className="font-semibold text-white mb-1">Where Would My Purchase Go?</h3>
      <p className="text-xs mb-4" style={{ color: '#8899AA' }}>
        Pick a tier to preview where your own Core 60% would route right now — read-only, doesn't affect real payouts.
      </p>
      <div className="flex gap-2 mb-5">
        {[1, 2, 3, 4].map(t => (
          <button
            key={t}
            onClick={() => run(t)}
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={tier === t && result
              ? { background: 'rgba(0,212,180,0.18)', color: '#00D4B4', border: '1px solid rgba(0,212,180,0.5)' }
              : { background: '#0E1117', color: '#8899AA', border: '1px solid #1E2A38' }}
          >
            Agent {t}
          </button>
        ))}
      </div>

      {loading && <p className="text-xs" style={{ color: '#8899AA' }}>Simulating…</p>}
      {error && <p className="text-xs mb-4" style={{ color: '#FF4D6A' }}>{error}</p>}

      {result && !loading && (
        <div className="grid md:grid-cols-2 gap-4">
          <CoreHalfChain title={`First 30% Half — if you buy Agent ${result.buyer_tier}`} half={result.half1} />
          <CoreHalfChain title="Second 30% Half" half={result.half2} />
        </div>
      )}
    </div>
  )
}

export default function RevenueEngine() {
  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div>
          <h1 className="text-2xl font-bold text-white">Revenue Engine</h1>
          <p className="text-sm mt-1" style={{ color: '#8899AA' }}>
            How the Core Agent's compression + odd/even routing decides who your purchases pay
          </p>
        </div>

        <CoreExplainerDiagram />
        <UserCoreSimulator />
      </div>
    </Layout>
  )
}
