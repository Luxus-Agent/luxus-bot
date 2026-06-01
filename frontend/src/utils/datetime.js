// Date/time helpers — display everything in Indian Standard Time (IST).
//
// The backend stores naive UTC timestamps (Python `datetime.utcnow()`) and
// serializes them WITHOUT a timezone suffix, e.g. "2026-06-01T11:03:09".
// JavaScript's `new Date(...)` would parse such a string as *local* time and
// never apply the UTC→IST offset, so timestamps showed up ~5h30m early.
// We normalize the value to a real UTC instant, then format it in Asia/Kolkata.

const IST = 'Asia/Kolkata'

function toUTCDate(value) {
  if (!value) return null
  if (value instanceof Date) return value
  let s = String(value).trim()
  const hasTime = s.includes('T') || s.includes(' ')
  const hasTZ = /[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)
  // Only a datetime (not a bare date) needs the explicit UTC marker.
  if (hasTime && !hasTZ) s = s.replace(' ', 'T') + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? null : d
}

// "01/06/2026, 04:33:09 pm" — date + time in IST
export function formatDateTimeIST(value) {
  const d = toUTCDate(value)
  if (!d) return ''
  return d.toLocaleString('en-IN', {
    timeZone: IST,
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true,
  })
}

// "01/06/2026" — date only, in IST
export function formatDateIST(value) {
  const d = toUTCDate(value)
  if (!d) return ''
  return d.toLocaleDateString('en-IN', {
    timeZone: IST, day: '2-digit', month: '2-digit', year: 'numeric',
  })
}

// Time only, in IST. Pass options to override (e.g. hour12).
export function formatTimeIST(value, opts = {}) {
  const d = toUTCDate(value)
  if (!d) return ''
  return d.toLocaleTimeString('en-IN', {
    timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: false, ...opts,
  })
}
