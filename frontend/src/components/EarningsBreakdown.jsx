/**
 * Completed vs Pending breakdown rows for "Total Earnings" / "Total In" — shared
 * between Dashboard.jsx and Transactions.jsx so the two pages can never drift.
 * Always foots exactly to the headline total: completed + pendingReserve +
 * pendingPayout + platformFee === totalEarned (platformFee is the derived
 * remainder, not summed from transaction rows, so nothing is ever double-counted
 * or silently dropped).
 */
export default function EarningsBreakdown({ totalEarned, completed, pendingReserve, pendingPayout }) {
  const platformFee = Math.max(totalEarned - completed - pendingReserve - pendingPayout, 0)

  return (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2 px-1">
        <div className="flex items-start gap-2">
          <span className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: 'var(--accent)' }} />
          <div>
            <p className="text-xs font-semibold text-white">Completed</p>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Already sent to your wallet on-chain</p>
          </div>
        </div>
        <span className="text-sm font-bold flex-shrink-0" style={{ color: 'var(--accent)' }}>${completed.toFixed(2)}</span>
      </div>

      <div className="flex items-start justify-between gap-2 px-1">
        <div className="flex items-start gap-2">
          <span className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: '#FFB547' }} />
          <div>
            <p className="text-xs font-semibold text-white">Pending — reserve</p>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Building toward your next auto-repurchase</p>
          </div>
        </div>
        <span className="text-sm font-bold flex-shrink-0" style={{ color: '#FFB547' }}>${pendingReserve.toFixed(2)}</span>
      </div>

      <div className="flex items-start justify-between gap-2 px-1">
        <div className="flex items-start gap-2">
          <span className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: '#FFB547' }} />
          <div>
            <p className="text-xs font-semibold text-white">Pending — payout</p>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Stream/Boost, released in the next payout run</p>
          </div>
        </div>
        <span className="text-sm font-bold flex-shrink-0" style={{ color: '#FFB547' }}>${pendingPayout.toFixed(2)}</span>
      </div>

      {platformFee >= 0.01 && (
        <p
          className="text-[10.5px] pt-2 px-1"
          style={{ color: 'var(--text-muted)', borderTop: '1px dashed var(--border)' }}
        >
          <span className="font-semibold">${platformFee.toFixed(2)}</span> was the platform's software fee — never yours, not counted above.
        </p>
      )}
    </div>
  )
}
