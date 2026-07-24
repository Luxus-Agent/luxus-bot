import { ChevronDown, ChevronRight } from 'lucide-react'

// Shared Core Agent (compression + odd/even) visualization pieces, used by
// both the admin "Revenue Engines" page (any username) and the user-facing
// Core preview (always the logged-in user).

function DiagramNode({ label, sub, color }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div
        className="w-20 h-20 rounded-full flex items-center justify-center text-xs font-bold text-center px-2"
        style={{ background: `color-mix(in srgb, ${color} 18%, transparent)`, border: `2px solid ${color}`, color }}
      >
        {label}
      </div>
      {sub && <p className="text-xs text-center max-w-[140px]" style={{ color: 'var(--text-secondary)' }}>{sub}</p>}
    </div>
  )
}

function DiagramArrow({ label }) {
  return (
    <div className="flex flex-col items-center">
      <div style={{ width: 2, height: 18, background: 'var(--text-muted)' }} />
      <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} />
      {label && <p className="text-xs text-center max-w-[220px] mt-1" style={{ color: 'var(--text-secondary)' }}>{label}</p>}
    </div>
  )
}

export function CoreExplainerDiagram() {
  return (
    <div className="rounded-xl p-6" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
      <h3 className="font-semibold text-white mb-1">How Your Commission Is Distributed</h3>
      <p className="text-xs mb-6" style={{ color: 'var(--text-secondary)' }}>
        Each 30% share is routed independently through the sponsor network. Sponsors with the
        required agent tier may receive the commission, while others have it passed to the next
        eligible sponsor based on the routing rules.
      </p>
      <div className="flex flex-col items-center">
        <DiagramNode label="Buyer" sub="purchases a tier" color="var(--accent)" />
        <DiagramArrow />
        <DiagramNode label="Purchase Complete" color="var(--accent)" />
        <DiagramArrow label="60% Core Commission — splits into two 30% shares, routed independently" />
        <DiagramNode label="First 30% Share" sub="starts at the Direct Sponsor" color="#3498DB" />
        <DiagramArrow />
        <DiagramNode label="Required Agent?" sub="active, not frozen, tier ≥ buyer's tier" color="var(--text-secondary)" />
        <div className="flex items-start gap-12 mt-1">
          <div className="flex flex-col items-center">
            <DiagramArrow label="Yes" />
            <DiagramNode label="Odd / Even" sub="checked at this sponsor" color="#3498DB" />
            <div className="flex items-start gap-8 mt-1">
              <div className="flex flex-col items-center">
                <DiagramArrow label="Odd" />
                <DiagramNode label="Credited" sub="paid to wallet" color="var(--accent)" />
              </div>
              <div className="flex flex-col items-center">
                <DiagramArrow label="Even" />
                <DiagramNode label="Pass Up" sub="try the next eligible sponsor" color="#FFB547" />
                <div className="flex items-start gap-8 mt-1">
                  <div className="flex flex-col items-center">
                    <DiagramArrow label="Eligible sponsor above" />
                    <DiagramNode label="Next Eligible" sub="repeats Odd/Even there" color="#3498DB" />
                  </div>
                  <div className="flex flex-col items-center">
                    <DiagramArrow label="None above" />
                    <DiagramNode label="Keeps It" sub="stays with this sponsor" color="var(--accent)" />
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="flex flex-col items-center">
            <DiagramArrow label="No" />
            <DiagramNode label="Next Sponsor" sub="required-agent check repeats" color="var(--text-secondary)" />
          </div>
        </div>
        <div className="max-w-lg mt-5 space-y-2">
          <p className="text-xs text-center" style={{ color: 'var(--text-primary)' }}>
            If no sponsor up the entire chain ever qualifies, that 30% share is retained as platform
            profit instead of being credited back to the buyer.
          </p>
          <p className="text-xs text-center" style={{ color: 'var(--text-primary)' }}>
            The second 30% share runs these same rules again, but starts its search one level above
            wherever the first share ended up — not back at the Direct Sponsor.
          </p>
        </div>
      </div>
    </div>
  )
}

function ChainPill({ label, tone }) {
  const palette = {
    skip: { bg: 'rgba(var(--text-muted-rgb),0.15)', color: 'var(--text-secondary)', border: '1px solid var(--border)' },
    candidate: { bg: 'rgba(52,152,219,0.12)', color: '#3498DB', border: '1px solid rgba(52,152,219,0.4)' },
    kept: { bg: 'rgba(var(--accent-rgb),0.12)', color: 'var(--accent)', border: '1px solid rgba(var(--accent-rgb),0.4)' },
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
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>✕ {s.reason}</span>
          <ChevronRight size={12} style={{ color: 'var(--text-muted)' }} />
        </div>
      ))}
    </div>
  )
}

export function CoreHalfChain({ title, half }) {
  return (
    <div className="rounded-lg p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <p className="text-xs font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>{title}</p>

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
                background: half.parity === 'odd' ? 'rgba(var(--accent-rgb),0.12)' : 'rgba(255,181,71,0.12)',
                color: half.parity === 'odd' ? 'var(--accent)' : '#FFB547',
              }}
            >
              {half.parity} (route #{half.route_count_after})
            </span>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--text-secondary)' }}>
            {half.parity === 'odd' ? 'Keeps the amount.' : 'Passes it up (compressed) to the next eligible upline.'}
          </p>

          {half.parity === 'even' && <SkipChain items={half.passup_skipped} />}
          {half.passup_fallback_to_candidate && (
            <p className="text-xs mb-3" style={{ color: 'var(--text-secondary)' }}>No eligible upline above — falls back to the candidate.</p>
          )}

          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>Credited to:</span>
            <ChainPill label={`@${half.recipient}`} tone="kept" />
          </div>
        </>
      )}
    </div>
  )
}
