import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import { useAuth } from '../../context/AuthContext'
import Pagination from '../../components/Pagination'
import api from '../../api/client'
import toast from 'react-hot-toast'
import {
  Search, UserX, UserCheck, ChevronDown, ChevronUp, ShieldCheck,
  Bot, Wallet, TrendingUp
} from 'lucide-react'

const PAGE_SIZE = 10

export default function AdminUsers() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(null)
  const [summaries, setSummaries] = useState({})

  const load = () =>
    api.get('/admin/users')
      .then(r => setUsers(r.data))
      .catch(() => toast.error('Failed to load users'))
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const loadSummary = async (userId) => {
    if (!userId || summaries[userId]) return
    try {
      const { data } = await api.get(`/admin/users/${userId}/summary`)
      setSummaries(prev => ({ ...prev, [userId]: data }))
    } catch {
      toast.error('Failed to load user details')
    }
  }

  const toggleExpand = (userId) => {
    if (expanded === userId) {
      setExpanded(null)
    } else {
      setExpanded(userId)
      loadSummary(userId)
    }
  }

  const handleFreeze = async (userId, freeze) => {
    const action = freeze ? 'freeze' : 'unfreeze'
    if (!window.confirm(`${freeze ? 'Freeze' : 'Unfreeze'} this user? ${freeze ? 'They will be blocked from all platform activity until unfrozen.' : ''}`)) return
    try {
      await api.post(`/admin/users/${userId}/${action}`)
      toast.success(`User ${action}d`)
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || `Failed to ${action}`)
    }
  }

  const filtered = users.filter(u =>
    search === '' ||
    u.username?.toLowerCase().includes(search.toLowerCase()) ||
    u.email?.toLowerCase().includes(search.toLowerCase()) ||
    String(u.id).includes(search)
  )
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
      </div>
    </Layout>
  )

  const inputStyle = { background: '#0E1117', border: '1px solid #1E2A38', color: '#fff' }

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">User Management</h1>
            <p className="text-sm mt-1" style={{ color: '#8899AA' }}>{users.length} total users</p>
          </div>
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#4A5568' }} />
            <input
              type="text"
              placeholder="Search users..."
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              className="pl-9 pr-4 py-2.5 rounded-xl text-sm outline-none w-64"
              style={inputStyle}
              onFocus={e => e.target.style.borderColor = '#00D4B4'}
              onBlur={e => e.target.style.borderColor = '#1E2A38'}
            />
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          {/* Table Header */}
          <div
            className="hidden sm:grid grid-cols-5 px-5 py-3 text-xs font-semibold uppercase tracking-wider"
            style={{ background: '#0E1117', color: '#4A5568', borderBottom: '1px solid #1E2A38' }}
          >
            <span className="col-span-2">User</span>
            <span>Status</span>
            <span>Sponsor</span>
            <span className="text-right">Actions</span>
          </div>

          <div className="row-divide">
            {paginated.map(user => {
              const isSelf = user.id === currentUser?.id
              const isAdminRow = user.is_admin
              const summary = summaries[user.id]
              return (
                <div key={user.id}>
                  {/* User Row */}
                  <div className="flex sm:grid sm:grid-cols-5 items-center gap-3 px-5 py-3">
                    <div className="col-span-2 flex items-center gap-3 min-w-0">
                      <div
                        className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
                        style={{ background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }}
                      >
                        {(user.username || 'U')[0].toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-medium text-white truncate">{user.username}</p>
                          {user.is_admin && <ShieldCheck size={12} style={{ color: '#00D4B4' }} />}
                        </div>
                        <p className="text-xs truncate" style={{ color: '#4A5568' }}>{user.email}</p>
                      </div>
                    </div>

                    <div className="hidden sm:block">
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-medium"
                        style={user.is_active
                          ? { background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }
                          : { background: 'rgba(255,77,106,0.12)', color: '#FF4D6A' }
                        }
                      >
                        {user.is_active ? 'Active' : 'Frozen'}
                      </span>
                    </div>

                    <div className="hidden sm:block text-xs" style={{ color: '#8899AA' }}>
                      {user.sponsor_username ? `@${user.sponsor_username}` : '—'}
                    </div>

                    <div className="flex items-center gap-1.5 ml-auto sm:ml-0 sm:justify-end flex-wrap">
                      {/* Admin rows have no details / freeze controls */}
                      {isAdminRow ? (
                        <span className="text-xs" style={{ color: '#2A3A4A' }}>—</span>
                      ) : (
                        <>
                          <button
                            onClick={() => toggleExpand(user.id)}
                            className="p-1.5 rounded-lg transition-all"
                            style={{ color: '#8899AA', background: '#0E1117' }}
                            title="View details"
                          >
                            {expanded === user.id ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                          </button>
                          <button
                            onClick={() => handleFreeze(user.id, user.is_active)}
                            className="p-1.5 rounded-lg"
                            style={user.is_active
                              ? { color: '#FF4D6A', background: 'rgba(255,77,106,0.1)' }
                              : { color: '#00D4B4', background: 'rgba(0,212,180,0.1)' }
                            }
                            title={user.is_active ? 'Freeze user' : 'Unfreeze user'}
                          >
                            {user.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Expanded summary (regular users only) */}
                  {!isAdminRow && expanded === user.id && (
                    <div className="px-5 pb-4" style={{ background: '#0A0D12' }}>
                      {!summary ? (
                        <div className="py-4 flex justify-center">
                          <div className="w-6 h-6 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-3">
                          <div className="rounded-lg px-3 py-2.5 flex items-center gap-2.5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                            <Bot size={16} style={{ color: '#00D4B4' }} className="flex-shrink-0" />
                            <div>
                              <p className="text-xs" style={{ color: '#8899AA' }}>Agents Bought</p>
                              <p className="text-sm font-semibold text-white">{summary.agents_count}</p>
                            </div>
                          </div>
                          <div className="rounded-lg px-3 py-2.5 flex items-center gap-2.5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                            <Wallet size={16} style={{ color: '#FFB547' }} className="flex-shrink-0" />
                            <div>
                              <p className="text-xs" style={{ color: '#8899AA' }}>Account Balance</p>
                              <p className="text-sm font-semibold text-white">${summary.account_balance.toFixed(2)}</p>
                            </div>
                          </div>
                          <div className="rounded-lg px-3 py-2.5 flex items-center gap-2.5" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                            <TrendingUp size={16} style={{ color: '#00FFD4' }} className="flex-shrink-0" />
                            <div>
                              <p className="text-xs" style={{ color: '#8899AA' }}>Revenue Generated</p>
                              <p className="text-sm font-semibold text-white">${summary.revenue_generated.toFixed(2)}</p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
        <div className="mt-4">
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        </div>
      </div>
    </Layout>
  )
}
