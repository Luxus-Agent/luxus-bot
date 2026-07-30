import { Children, useEffect, useRef } from 'react'
import { ChevronDown } from 'lucide-react'
import { tierDisplayName } from '../utils/agentTiers'

// Shared Core Agent (compression + odd/even) visualization pieces, used by
// both the admin "Revenue Engines" page (any username) and the user-facing
// Core preview (always the logged-in user).

// --- Flow-diagram primitives -------------------------------------------------
// Alignment rule: a <Fork> is a CSS grid of equal `1fr` columns, so its centre
// is always the midpoint between the first and last branch. Since the trunk
// above it is centred in the same shrink-to-fit column, the connector drops
// exactly onto the fork's horizontal rail. Do NOT swap the grid for a flex row
// with `gap` — content-sized flex children make the branches unequal widths and
// the trunk stops lining up with the split point (the bug this replaced).

const LINE = 'var(--text-muted)'

function DiagramNode({ label, sub, color, compact = false }) {
  const size = compact ? 64 : 80
  return (
    <div className="flex flex-col items-center gap-1.5 px-2">
      <div
        className={`rounded-full flex items-center justify-center font-bold text-center leading-tight ${compact ? 'text-[10px] px-1.5' : 'text-xs px-2'}`}
        style={{
          width: size,
          height: size,
          flexShrink: 0,
          background: `color-mix(in srgb, ${color} 18%, transparent)`,
          border: `2px solid ${color}`,
          color,
        }}
      >
        {label}
      </div>
      {sub && (
        <p
          className={`text-center ${compact ? 'text-[10px] max-w-[130px]' : 'text-xs max-w-[150px]'}`}
          style={{ color: 'var(--text-secondary)' }}
        >
          {sub}
        </p>
      )}
    </div>
  )
}

// Vertical trunk segment. `note` renders inline in the middle of the line so the
// flow stays visually connected instead of breaking into floating text.
function DiagramArrow({ note, arrow = true }) {
  return (
    <div className="flex flex-col items-center">
      <div style={{ width: 2, height: 16, background: LINE }} />
      {note && (
        <p className="text-xs text-center max-w-[260px] my-1.5" style={{ color: 'var(--text-secondary)' }}>
          {note}
        </p>
      )}
      {note && <div style={{ width: 2, height: 16, background: LINE }} />}
      {arrow && <ChevronDown size={14} strokeWidth={2.5} style={{ color: LINE, marginTop: -5 }} />}
    </div>
  )
}

// Equal-width branch columns + a horizontal rail that spans first-centre to
// last-centre, with a drop line into each branch.
function DiagramFork({ children }) {
  const branches = Children.toArray(children)
  const last = branches.length - 1
  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${branches.length}, 1fr)` }}>
      {branches.map((branch, i) => (
        <div key={i} className="relative flex flex-col items-center pt-5 px-2">
          <span
            className="absolute top-0"
            style={{
              height: 2,
              background: LINE,
              left: i === 0 ? 'calc(50% - 1px)' : 0,
              right: i === last ? 'calc(50% - 1px)' : 0,
            }}
          />
          <span className="absolute top-0" style={{ left: 'calc(50% - 1px)', width: 2, height: 20, background: LINE }} />
          {branch}
        </div>
      ))}
    </div>
  )
}

function DiagramBranch({ label, children }) {
  return (
    <div className="flex flex-col items-center">
      <span
        className="px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
      >
        {label}
      </span>
      <div style={{ width: 2, height: 12, background: LINE }} />
      <ChevronDown size={14} strokeWidth={2.5} style={{ color: LINE, marginTop: -5, marginBottom: 4 }} />
      {children}
    </div>
  )
}

export function CoreExplainerDiagram() {
  // The tree is symmetric around its trunk, so when it's too wide to fit the
  // panel (narrow screens) scroll position 0 shows only the empty left margin.
  // Start the scroll centred on the trunk instead.
  const scrollRef = useRef(null)
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollLeft = Math.max(0, (el.scrollWidth - el.clientWidth) / 2)
  }, [])

  return (
    <div className="rounded-xl p-6" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
      <h3 className="font-semibold text-white mb-1">How Your Commission Is Distributed</h3>
      <p className="text-xs mb-6" style={{ color: 'var(--text-secondary)' }}>
        Each 30% share is routed independently through the sponsor network. Sponsors with the
        required agent tier may receive the commission, while others have it passed to the next
        eligible sponsor based on the routing rules.
      </p>

      <div ref={scrollRef} className="overflow-x-auto pb-2">
        <div className="flex flex-col items-center w-max mx-auto">
          <DiagramNode label="Buyer" sub="purchases a tier" color="var(--accent)" />
          <DiagramArrow />
          <DiagramNode label="Purchase Complete" color="var(--accent)" />
          <DiagramArrow note="60% Core Commission — splits into two 30% shares, routed independently" />
          <DiagramNode label="First 30% Share" sub="starts at the Direct Sponsor" color="#3498DB" />
          <DiagramArrow />
          <DiagramNode label="Required Agent?" sub="active, not frozen, tier ≥ buyer's tier" color="var(--text-secondary)" />
          <div style={{ width: 2, height: 18, background: LINE }} />

          <DiagramFork>
            <DiagramBranch label="Yes">
              <DiagramNode label="Odd / Even" sub="checked at this sponsor" color="#3498DB" />
              <div style={{ width: 2, height: 18, background: LINE }} />
              <DiagramFork>
                <DiagramBranch label="Odd">
                  <DiagramNode label="Credited" sub="paid to wallet" color="var(--accent)" />
                </DiagramBranch>
                <DiagramBranch label="Even">
                  <DiagramNode label="Pass Up" sub="try the next eligible sponsor" color="#FFB547" />
                  <div style={{ width: 2, height: 18, background: LINE }} />
                  <DiagramFork>
                    <DiagramBranch label="Eligible above">
                      <DiagramNode compact label="Next Eligible" sub="repeats Odd/Even there" color="#3498DB" />
                    </DiagramBranch>
                    <DiagramBranch label="None above">
                      <DiagramNode compact label="Keeps It" sub="stays with this sponsor" color="var(--accent)" />
                    </DiagramBranch>
                  </DiagramFork>
                </DiagramBranch>
              </DiagramFork>
            </DiagramBranch>

            <DiagramBranch label="No">
              <DiagramNode label="Next Sponsor" sub="required-agent check repeats" color="var(--text-secondary)" />
            </DiagramBranch>
          </DiagramFork>
        </div>
      </div>

      <div className="max-w-lg mx-auto mt-6 space-y-2">
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
  )
}

const PLATFORM_PROFIT_TEXT = 'No eligible upline — retained as platform profit'

function fmtAmount(n) {
  const num = Number(n)
  return Number.isInteger(num) ? `${num}` : num.toFixed(2)
}

// "both → @admin ($6, merged)" / "@dhanush ($3) + @admin ($3)" / "@dhanush ($3) + platform profit ($3)"
function formatHypothetical(half1, half2) {
  const r1 = half1.recipient
  const r2 = half2.recipient
  if (!r1 && !r2) return PLATFORM_PROFIT_TEXT
  if (r1 && r1 === r2) {
    const total = Number(half1.amount) + Number(half2.amount)
    return `both → @${r1} ($${fmtAmount(total)}, merged)`
  }
  const part = (recipient, amount) => (recipient ? `@${recipient} ($${fmtAmount(amount)})` : `platform profit ($${fmtAmount(amount)})`)
  return `${part(r1, half1.amount)} + ${part(r2, half2.amount)}`
}

// "@dhanush ($3) + @admin ($3)"
function formatActual(recipients) {
  if (recipients.length === 0) return PLATFORM_PROFIT_TEXT
  return recipients.map(r => `@${r.username} ($${fmtAmount(r.amount)})`).join(' + ')
}

// Single-row "Purchase | Recipients (both halves)" table — the plain,
// no-diagram view of one buyer/tier Core preview result (hypothetical or,
// for an already-owned tier, the actual recorded outcome).
export function CorePreviewTable({ result }) {
  const purchaseLabel = result.actual
    ? `@${result.buyer} already bought ${tierDisplayName(result.buyer_tier)}`
    : `@${result.buyer} buys ${tierDisplayName(result.buyer_tier)}`
  const recipientsText = result.actual
    ? formatActual(result.recipients)
    : formatHypothetical(result.half1, result.half2)

  return (
    <div className="overflow-x-auto rounded-lg" style={{ border: '1px solid var(--border)' }}>
      <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: 'var(--bg-surface)' }}>
            <th className="text-left px-4 py-2.5 font-semibold" style={{ color: 'var(--text-secondary)' }}>Purchase</th>
            <th className="text-left px-4 py-2.5 font-semibold" style={{ color: 'var(--text-secondary)' }}>Recipients (both halves)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)', borderTop: '1px solid var(--border)' }}>{purchaseLabel}</td>
            <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)', borderTop: '1px solid var(--border)' }}>{recipientsText}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
