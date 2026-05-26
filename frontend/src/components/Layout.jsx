import { useState, useRef, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Logo from './Logo'
import {
  LayoutDashboard, Wallet, ArrowDownToLine, ArrowUpFromLine,
  Users, BarChart3, History, Bot, Network, LogOut, Menu, X,
  ChevronRight, Send, ShieldCheck, User
} from 'lucide-react'

const userNav = [
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/agents',    label: 'Buy Agents', icon: Bot },
  { path: '/matrix',   label: 'Matrix',      icon: Network },
  { path: '/wallet',   label: 'Wallet',      icon: Wallet },
  { path: '/deposit',  label: 'Deposit',     icon: ArrowDownToLine },
  { path: '/transfer', label: 'Transfer',    icon: Send },
  { path: '/withdraw', label: 'Withdraw',    icon: ArrowUpFromLine },
  { path: '/transactions', label: 'Transactions', icon: History },
]

const adminNav = [
  { path: '/admin',              label: 'Overview',     icon: LayoutDashboard },
  { path: '/admin/users',        label: 'Users',        icon: Users },
  { path: '/admin/transactions', label: 'Transactions', icon: BarChart3 },
  { path: '/admin/withdrawals',  label: 'Withdrawals',  icon: ArrowUpFromLine },
  { divider: 'My Account' },
  { path: '/wallet',   label: 'Wallet',   icon: Wallet },
  { path: '/withdraw', label: 'Withdraw', icon: ArrowUpFromLine },
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

function AppShell({ nav, children, badge }) {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#080B10' }}>
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
