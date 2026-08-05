import { tierDisplayName } from '../utils/agentTiers'

// Shared Core Agent visualization pieces, used by both the admin "Revenue
// Engines" page (any username) and the user-facing Core preview (always the
// logged-in user).

// Direct-downline odd/even column — one side (left/odd or right/even) of the
// Downline Odd/Even Table, shared by the admin (any sponsor) and user
// (self-scoped) Revenue Engine pages.
export function DownlineColumn({ title, color, members }) {
  return (
    <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color }}>{title}</p>
      {members.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>None</p>
      ) : (
        <div className="space-y-1.5">
          {members.map(m => (
            <div
              key={m.username}
              className="flex items-center justify-between px-3 py-2 rounded-lg text-xs"
              style={{ background: `color-mix(in srgb, ${color} 8%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 25%, transparent)` }}
            >
              <span className="text-white font-medium">#{m.position} · @{m.username}</span>
              <div className="flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
                <span>{m.highest_active_tier > 0 ? tierDisplayName(m.highest_active_tier) : 'No agent'}</span>
                {!m.is_active && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: 'rgba(255,77,106,0.12)', color: '#FF4D6A' }}>
                    FROZEN
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
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
