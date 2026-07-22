import { ChevronDown, ChevronRight } from 'lucide-react'

// Shared Core Agent (compression + odd/even) visualization pieces, used by
// both the admin "Revenue Engines" page (any username) and the user-facing
// Core preview (always the logged-in user).

function DiagramNode({ label, sub, color }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div
        className="w-20 h-20 rounded-full flex items-center justify-center text-xs font-bold text-center px-2"
        style={{ background: `${color}18`, border: `2px solid ${color}`, color }}
      >
        {label}
      </div>
      {sub && <p className="text-xs text-center max-w-[140px]" style={{ color: '#8899AA' }}>{sub}</p>}
    </div>
  )
}

function DiagramArrow({ label }) {
  return (
    <div className="flex flex-col items-center">
      <div style={{ width: 2, height: 18, background: '#2A3A4A' }} />
      <ChevronDown size={14} style={{ color: '#2A3A4A' }} />
      {label && <p className="text-xs text-center max-w-[220px] mt-1" style={{ color: '#4A5568' }}>{label}</p>}
    </div>
  )
}

export function CoreExplainerDiagram() {
  return (
    <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
      <h3 className="font-semibold text-white mb-1">How Core Routing Works</h3>
      <p className="text-xs mb-6" style={{ color: '#8899AA' }}>
        Compression picks the nearest eligible upline for each 30% half; odd/even then decides whether
        that upline keeps it or it passes further up the sponsor chain.
      </p>
      <div className="flex flex-col items-center">
        <DiagramNode label="Buyer" sub="purchases a tier" color="#00D4B4" />
        <DiagramArrow label="60% Core → two 30% halves, walk up the sponsor chain" />
        <DiagramNode label="Eligible Upline" sub="compression: highest active tier ≥ buyer's tier" color="#3498DB" />
        <div className="flex items-start gap-12 mt-1">
          <div className="flex flex-col items-center">
            <DiagramArrow label="Odd count" />
            <DiagramNode label="Credited" sub="kept — paid to wallet" color="#00D4B4" />
          </div>
          <div className="flex flex-col items-center">
            <DiagramArrow label="Even count" />
            <DiagramNode label="Passed Up" sub="next eligible upline (compressed)" color="#FFB547" />
          </div>
        </div>
      </div>
    </div>
  )
}

function ChainPill({ label, tone }) {
  const palette = {
    skip: { bg: 'rgba(74,85,104,0.15)', color: '#8899AA', border: '1px solid #1E2A38' },
    candidate: { bg: 'rgba(52,152,219,0.12)', color: '#3498DB', border: '1px solid rgba(52,152,219,0.4)' },
    kept: { bg: 'rgba(0,212,180,0.12)', color: '#00D4B4', border: '1px solid rgba(0,212,180,0.4)' },
    platform: { bg: 'rgba(255,77,106,0.12)', color: '#FF4D6A', border: '1px solid rgba(255,77,106,0.4)' },
  }
  const style = palette[tone] || palette.skip
  return (
    <span
      className="px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap"
      style={{ background: style.bg, color: style.color, border: style.border }}
    >
      {label}
    </span>
  )
}

function SkipChain({ items }) {
  if (!items.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-3">
      {items.map(s => (
        <div key={s.username} className="flex items-center gap-1.5">
          <ChainPill label={`@${s.username}`} tone="skip" />
          <span className="text-xs" style={{ color: '#4A5568' }}>✕ {s.reason}</span>
          <ChevronRight size={12} style={{ color: '#2A3A4A' }} />
        </div>
      ))}
    </div>
  )
}

export function CoreHalfChain({ title, half }) {
  return (
    <div className="rounded-lg p-4" style={{ background: '#0E1117', border: '1px solid #1E2A38' }}>
      <p className="text-xs font-semibold mb-3" style={{ color: '#8899AA' }}>{title}</p>

      <SkipChain items={half.compression_skipped} />

      {!half.candidate ? (
        <ChainPill label="No eligible upline — folds into platform profit" tone="platform" />
      ) : (
        <>
          <div className="flex items-center gap-2 mb-3">
            <ChainPill label={`@${half.candidate}`} tone="candidate" />
            <span
              className="text-xs px-2 py-0.5 rounded-full font-bold uppercase"
              style={{
                background: half.parity === 'odd' ? 'rgba(0,212,180,0.12)' : 'rgba(255,181,71,0.12)',
                color: half.parity === 'odd' ? '#00D4B4' : '#FFB547',
              }}
            >
              {half.parity} (route #{half.route_count_after})
            </span>
          </div>
          <p className="text-xs mb-3" style={{ color: '#8899AA' }}>
            {half.parity === 'odd' ? 'Keeps the amount.' : 'Passes it up (compressed) to the next eligible upline.'}
          </p>

          {half.parity === 'even' && <SkipChain items={half.passup_skipped} />}
          {half.passup_fallback_to_candidate && (
            <p className="text-xs mb-3" style={{ color: '#4A5568' }}>No eligible upline above — falls back to the candidate.</p>
          )}

          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: '#8899AA' }}>Credited to:</span>
            <ChainPill label={`@${half.recipient}`} tone="kept" />
          </div>
        </>
      )}
    </div>
  )
}
