export default function Logo({ size = 32, showText = true }) {
  return (
    <div className="flex items-center gap-2">
      <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="4" y="10" width="8" height="26" rx="2" style={{ fill: 'var(--accent)' }} opacity="0.7"/>
        <rect x="16" y="4" width="8" height="32" rx="2" style={{ fill: 'var(--accent)' }}/>
        <rect x="28" y="10" width="8" height="26" rx="2" style={{ fill: 'var(--accent)' }} opacity="0.7"/>
      </svg>
      {showText && (
        <span style={{ fontSize: size * 0.6, fontWeight: 700, letterSpacing: '0.15em', color: 'var(--text-primary)' }}>
          LUXUS
        </span>
      )}
    </div>
  )
}
