import logoMark from '../assets/logo.png'
import logoTextDark from '../assets/logo-text-dark.png'
import logoTextLight from '../assets/logo-text-light.png'
import { useTheme } from '../context/ThemeContext'

export default function Logo({ size = 32, showText = true }) {
  const { theme } = useTheme()
  const textHeight = size * 0.6
  return (
    <div className="flex items-center gap-2">
      <img src={logoMark} alt="" height={size} style={{ height: size, width: 'auto' }} />
      {showText && (
        <img
          src={theme === 'light' ? logoTextLight : logoTextDark}
          alt="LUXUS"
          height={textHeight}
          style={{ height: textHeight, width: 'auto' }}
        />
      )}
    </div>
  )
}
