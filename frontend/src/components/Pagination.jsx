import { ChevronLeft, ChevronRight } from 'lucide-react'

const BTN = {
  base: {
    minWidth: 32, height: 32, borderRadius: 8, fontSize: 13, fontWeight: 500,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    cursor: 'pointer', border: '1px solid #1E2A38', background: '#141922', color: '#8899AA',
    padding: '0 8px',
  },
  active: { background: '#00D4B4', color: '#000', borderColor: '#00D4B4' },
  disabled: { opacity: 0.35, cursor: 'not-allowed' },
}

export default function Pagination({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null

  const pages = []
  const delta = 1
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - delta && i <= page + delta)) {
      pages.push(i)
    }
  }

  const withEllipsis = []
  let prev = null
  for (const p of pages) {
    if (prev !== null && p - prev > 1) withEllipsis.push('...')
    withEllipsis.push(p)
    prev = p
  }

  return (
    <div className="flex items-center justify-between pt-3" style={{ borderTop: '1px solid #1E2A38' }}>
      <p className="text-xs" style={{ color: '#4A5568' }}>
        Page {page} of {totalPages}
      </p>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page === 1}
          style={{ ...BTN.base, ...(page === 1 ? BTN.disabled : {}) }}
        >
          <ChevronLeft size={14} />
        </button>

        {withEllipsis.map((p, i) =>
          p === '...' ? (
            <span key={`e${i}`} style={{ color: '#4A5568', fontSize: 13, padding: '0 2px' }}>…</span>
          ) : (
            <button
              key={p}
              onClick={() => onChange(p)}
              style={{ ...BTN.base, ...(p === page ? BTN.active : {}) }}
            >
              {p}
            </button>
          )
        )}

        <button
          onClick={() => onChange(page + 1)}
          disabled={page === totalPages}
          style={{ ...BTN.base, ...(page === totalPages ? BTN.disabled : {}) }}
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
