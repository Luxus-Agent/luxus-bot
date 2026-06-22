import { useState, useRef, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'
import toast from 'react-hot-toast'
import Logo from './Logo'
import { useAppKitAccount, useDisconnect } from '@reown/appkit/react'
import {
  LayoutDashboard, Wallet,
  Users, BarChart3, History, Bot, Network, LogOut, Menu, X,
  ChevronRight, ShieldCheck, User, ShieldAlert, Lock, Unlock, AlertTriangle
} from 'lucide-react'

const userNav = [
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/agents',    label: 'Buy Agents', icon: Bot },
  { path: '/matrix',   label: 'Queue',       icon: Network },
  { path: '/wallet',   label: 'Wallet',      icon: Wallet },
  { path: '/transactions', label: 'Transactions', icon: History },
]

const adminNav = [
  { path: '/admin',              label: 'Overview',     icon: LayoutDashboard },
  { path: '/admin/users',        label: 'Users',        icon: Users },
  { path: '/admin/transactions', label: 'Transactions', icon: BarChart3 },
]

function SidebarNav({ nav, onClose }) {
  const location = useLocation()

  return (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="px-6 py-5 border-b" style={{ borderColor: '#1E2A38' }}>
        <Logo size={26} />
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {nav.map((item, i) => {
          if (item.divider) {
            return (
              <div key={`divider-${i}`} className="pt-4 pb-1 px-3">
                <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#2A3A4A' }}>
                  {item.divider}
                </p>
              </div>
            )
          }
          const { path, label, icon: Icon } = item
          const active = location.pathname === path
          return (
            <Link
              key={path}
              to={path}
              onClick={onClose}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-sm font-medium"
              style={active
                ? { background: 'rgba(0,212,180,0.1)', color: '#00D4B4', borderLeft: '2px solid #00D4B4', paddingLeft: '10px' }
                : { color: '#8899AA', borderLeft: '2px solid transparent' }
              }
            >
              <Icon size={17} />
              <span>{label}</span>
              {active && <ChevronRight size={13} className="ml-auto opacity-50" />}
            </Link>
          )
        })}
      </nav>

      {/* User info strip — no logout button, logout is in topbar dropdown */}
      <div className="px-3 pb-4 pt-2 border-t" style={{ borderColor: '#1E2A38' }}>
        <UserInfoStrip />
      </div>
    </div>
  )
}

function UserInfoStrip() {
  const { user } = useAuth()
  return (
    <div className="px-3 py-2.5 rounded-lg" style={{ background: '#0E1117' }}>
      <p className="text-xs" style={{ color: '#4A5568' }}>Signed in as</p>
      <p className="text-sm font-semibold text-white truncate">{user?.username}</p>
      <p className="text-xs truncate" style={{ color: '#4A5568' }}>{user?.email}</p>
    </div>
  )
}

function ProfileDropdown({ user, isAdmin, logout, navigate }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all"
        style={{
          background: open ? 'rgba(0,212,180,0.25)' : 'rgba(0,212,180,0.12)',
          color: '#00D4B4',
          border: '1px solid rgba(0,212,180,0.2)',
        }}
      >
        {(user?.username || 'U')[0].toUpperCase()}
      </button>

      {open && (
        <div
          className="absolute right-0 top-10 w-52 rounded-xl overflow-hidden z-50"
          style={{ background: '#141922', border: '1px solid #1E2A38', boxShadow: '0 8px 32px rgba(0,0,0,0.4)' }}
        >
          {/* User info */}
          <div className="px-4 py-3 border-b" style={{ borderColor: '#1E2A38' }}>
            <div className="flex items-center gap-2 mb-1">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                style={{ background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }}
              >
                {(user?.username || 'U')[0].toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-white truncate">{user?.username}</p>
                <p className="text-xs truncate" style={{ color: '#4A5568' }}>{user?.email}</p>
              </div>
            </div>
            {isAdmin && (
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold mt-1"
                style={{ background: 'rgba(0,212,180,0.1)', color: '#00D4B4', border: '1px solid rgba(0,212,180,0.25)' }}
              >
                <ShieldCheck size={11} /> ADMIN
              </span>
            )}
          </div>

          {/* Profile action */}
          <div className="p-1.5">
            <button
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all"
              style={{ color: '#8899AA' }}
              onMouseEnter={e => e.currentTarget.style.background = '#1E2A38'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              onClick={() => { setOpen(false); navigate('/profile') }}
            >
              <User size={15} />
              Profile
            </button>

            <div className="my-1" style={{ height: '1px', background: '#1E2A38' }} />

            <button
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all"
              style={{ color: '#FF4D6A' }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,77,106,0.08)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              onClick={() => { setOpen(false); logout(); navigate('/login') }}
            >
              <LogOut size={15} />
              Sign Out
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Banner shown across every page while the platform is globally frozen. */
function FrozenBanner({ reason, isAdmin }) {
  return (
    <div
      className="flex items-center gap-3 px-5 py-2.5 flex-shrink-0"
      style={{ background: 'rgba(255,77,106,0.12)', borderBottom: '1px solid rgba(255,77,106,0.35)' }}
    >
      <AlertTriangle size={16} style={{ color: '#FF4D6A' }} className="flex-shrink-0" />
      <p className="text-xs sm:text-sm" style={{ color: '#FF8095' }}>
        <span className="font-semibold" style={{ color: '#FF4D6A' }}>Platform frozen.</span>{' '}
        {isAdmin
          ? 'All user agent purchases are paused. Use the “Frozen” button to resume.'
          : 'Agent purchases are temporarily paused. Please try again later.'}
        {/* Reason is admin-only — the public status endpoint never sends it to users. */}
        {reason ? <span style={{ color: '#8899AA' }}> — {reason}</span> : null}
      </p>
    </div>
  )
}

/** Admin-only kill switch: freeze/unfreeze all user money-movement flows. */
function PlatformFreezeControl({ frozen, onChanged }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [reason, setReason] = useState('')

  const submit = async () => {
    setLoading(true)
    try {
      if (frozen) {
        await api.post('/admin/platform/unfreeze')
        toast.success('Platform resumed — user flows are live again')
      } else {
        await api.post('/admin/platform/freeze', { reason: reason.trim() || null })
        toast.success('Platform frozen — all user flows are paused')
      }
      setOpen(false)
      setReason('')
      onChanged?.()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Action failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={frozen ? 'Platform is frozen — click to resume' : 'Freeze all user activity'}
        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all"
        style={frozen
          ? { background: 'rgba(255,77,106,0.15)', color: '#FF4D6A', border: '1px solid rgba(255,77,106,0.45)' }
          : { background: 'rgba(255,181,71,0.10)', color: '#FFB547', border: '1px solid rgba(255,181,71,0.30)' }
        }
      >
        {frozen ? <Lock size={13} /> : <ShieldAlert size={13} />}
        <span className="hidden sm:inline">{frozen ? 'Frozen' : 'Freeze'}</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.75)' }} onClick={() => !loading && setOpen(false)} />
          <div
            className="relative w-full max-w-md rounded-2xl p-6"
            style={{ background: '#141922', border: '1px solid #1E2A38', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}
          >
            <div className="flex items-center gap-3 mb-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                style={frozen
                  ? { background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }
                  : { background: 'rgba(255,77,106,0.12)', color: '#FF4D6A' }}
              >
                {frozen ? <Unlock size={20} /> : <ShieldAlert size={20} />}
              </div>
              <h2 className="text-lg font-bold text-white">
                {frozen ? 'Resume platform?' : 'Freeze platform?'}
              </h2>
            </div>

            <p className="text-sm mb-4" style={{ color: '#8899AA' }}>
              {frozen
                ? 'This will immediately re-enable agent purchases for all users.'
                : 'This is an emergency stop. While frozen, all users are blocked from agent purchases. Read-only access stays available. Only you can resume.'}
            </p>

            {!frozen && (
              <div className="mb-4">
                <label className="block text-xs font-medium mb-1.5" style={{ color: '#8899AA' }}>
                  Reason (optional)
                </label>
                <input
                  type="text"
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                  placeholder="e.g. Suspicious activity under investigation"
                  className="w-full px-3 py-2.5 rounded-lg text-sm outline-none"
                  style={{ background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }}
                  onFocus={e => e.target.style.borderColor = '#FF4D6A'}
                  onBlur={e => e.target.style.borderColor = '#1E2A38'}
                />
              </div>
            )}

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setOpen(false)}
                disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-medium transition-all"
                style={{ background: '#1E2A38', color: '#8899AA' }}
              >
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-bold transition-all flex items-center gap-2"
                style={frozen
                  ? { background: '#00D4B4', color: '#000' }
                  : { background: '#FF4D6A', color: '#fff' }}
              >
                {loading
                  ? <div className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
                  : (frozen ? <Unlock size={15} /> : <Lock size={15} />)}
                {frozen ? 'Resume Platform' : 'Freeze Platform'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/**
 * Enforces that the wallet connected in-app matches the address the user
 * registered with (from /auth/me). A matching wallet stays connected; any other
 * wallet is disconnected with a clear prompt to reconnect the registered one.
 */
function WalletGuard() {
  const { user } = useAuth()
  const { address, isConnected } = useAppKitAccount()
  const { disconnect } = useDisconnect()
  const registered = user?.wallet_address

  useEffect(() => {
    if (!isConnected || !address || !registered) return
    if (address.toLowerCase() !== registered.toLowerCase()) {
      disconnect()
      const short = `${registered.slice(0, 6)}…${registered.slice(-4)}`
      toast.error(
        `This isn't the wallet linked to your account. Please connect the wallet you registered with (${short}).`,
        { duration: 6000 },
      )
    }
  }, [address, isConnected, registered, disconnect])

  return null
}

function AppShell({ nav, children, badge }) {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [platform, setPlatform] = useState({ is_frozen: false, frozen_reason: null })

  const refreshPlatform = () => {
    // Admins read the full status (includes the internal reason); regular users
    // hit the public endpoint, which never exposes the reason.
    const url = isAdmin ? '/admin/platform/status' : '/platform/status'
    api.get(url)
      .then(r => setPlatform(r.data))
      .catch(() => {})
  }

  useEffect(() => {
    refreshPlatform()
    const id = setInterval(refreshPlatform, 20000)  // keep banner in sync across sessions
    return () => clearInterval(id)
  }, [isAdmin])

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#080B10' }}>
      {/* Disconnect any wallet that isn't the user's registered address */}
      <WalletGuard />

      {/* Desktop sidebar */}
      <aside
        className="hidden lg:flex flex-col w-60 flex-shrink-0"
        style={{ background: '#0E1117', borderRight: '1px solid #1E2A38' }}
      >
        <SidebarNav nav={nav} onClose={() => {}} />
      </aside>

      {/* Mobile sidebar */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="absolute inset-0"
            style={{ background: 'rgba(0,0,0,0.75)' }}
            onClick={() => setOpen(false)}
          />
          <aside
            className="relative z-10 flex flex-col w-64"
            style={{ background: '#0E1117', borderRight: '1px solid #1E2A38' }}
          >
            <button
              className="absolute top-4 right-4 p-1.5 rounded-lg"
              style={{ color: '#4A5568' }}
              onClick={() => setOpen(false)}
            >
              <X size={18} />
            </button>
            <SidebarNav nav={nav} onClose={() => setOpen(false)} />
          </aside>
        </div>
      )}

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Topbar */}
        <header
          className="flex items-center gap-3 px-5 py-3.5 flex-shrink-0"
          style={{ background: '#0E1117', borderBottom: '1px solid #1E2A38' }}
        >
          <button
            className="lg:hidden p-1.5 rounded-lg"
            style={{ color: '#8899AA' }}
            onClick={() => setOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div className="lg:hidden">
            <Logo size={22} />
          </div>

          <div className="ml-auto flex items-center gap-2">
            {/* Reown AppKit wallet widget — Connect when disconnected, account when connected */}
            <appkit-button balance="hide" size="sm" />
            {isAdmin && (
              <PlatformFreezeControl frozen={platform.is_frozen} onChanged={refreshPlatform} />
            )}
            {badge && (
              <span
                className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold"
                style={{ background: 'rgba(0,212,180,0.1)', color: '#00D4B4', border: '1px solid rgba(0,212,180,0.25)' }}
              >
                {badge}
              </span>
            )}
            <ProfileDropdown user={user} isAdmin={isAdmin} logout={logout} navigate={navigate} />
          </div>
        </header>

        {/* Global freeze banner */}
        {platform.is_frozen && <FrozenBanner reason={platform.frozen_reason} isAdmin={isAdmin} />}

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-5 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}

/** Layout for regular users */
export function UserLayout({ children }) {
  return <AppShell nav={userNav}>{children}</AppShell>
}

/** Layout for the admin */
export function AdminLayout({ children }) {
  return <AppShell nav={adminNav} badge="ADMIN">{children}</AppShell>
}

/** Default export — kept for any files still importing Layout directly */
export default UserLayout
