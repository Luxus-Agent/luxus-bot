import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import api from '../../api/client'
import toast from 'react-hot-toast'
import {
  Users, Search, UserX, UserCheck, CreditCard, MinusCircle,
  ChevronDown, ChevronUp, Eye, ShieldCheck
} from 'lucide-react'

export default function AdminUsers() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [userWallets, setUserWallets] = useState({})

  // Credit/Debit modal
  const [modal, setModal] = useState(null)
  const [modalForm, setModalForm] = useState({ agent_tier: '1', amount: '', notes: '' })
  const [modalLoading, setModalLoading] = useState(false)

  const load = () =>
    api.get('/admin/users')
      .then(r => setUsers(r.data))
      .catch(() => toast.error('Failed to load users'))
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const loadWallets = async (userId) => {
    if (userWallets[userId]) return
    try {
      const { data } = await api.get(`/admin/users/${userId}/wallets`)
      setUserWallets(prev => ({ ...prev, [userId]: data }))
    } catch {
      toast.error('Failed to load wallets')
    }
  }

  const toggleExpand = (userId) => {
    if (expanded === userId) {
      setExpanded(null)
    } else {
      setExpanded(userId)
      loadWallets(userId)
    }
  }

  const handleFreeze = async (userId, freeze) => {
    const action = freeze ? 'freeze' : 'unfreeze'
    if (!window.confirm(`${freeze ? 'Freeze' : 'Unfreeze'} this user?`)) return
    try {
      await api.post(`/admin/users/${userId}/${action}`)
      toast.success(`User ${action}d`)
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || `Failed to ${action}`)
    }
  }

  const handleCredit = async () => {
    setModalLoading(true)
    try {
      const endpoint = modal.type === 'credit' ? '/admin/wallet/credit' : '/admin/wallet/debit'
      await api.post(endpoint, {
        user_id: modal.userId,
        agent_tier: parseInt(modalForm.agent_tier),
        amount: parseFloat(modalForm.amount),
        notes: modalForm.notes || undefined,
      })
      toast.success(`Wallet ${modal.type}ed successfully`)
      setModal(null)
      setModalForm({ agent_tier: '1', amount: '', notes: '' })
      setUserWallets({})
      if (expanded) loadWallets(expanded)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Operation failed')
    } finally {
      setModalLoading(false)
    }
  }

  const filtered = users.filter(u =>
    search === '' ||
    u.username?.toLowerCase().includes(search.toLowerCase()) ||
    u.email?.toLowerCase().includes(search.toLowerCase()) ||
    String(u.id).includes(search)
  )

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
              onChange={e => setSearch(e.target.value)}
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

          <div className="divide-y" style={{ borderColor: '#1E2A38' }}>
            {filtered.map(user => (
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
                    #{user.sponsor_id || '—'}
                  </div>

                  <div className="flex items-center gap-1.5 ml-auto sm:ml-0 sm:justify-end flex-wrap">
                    <button
                      onClick={() => toggleExpand(expanded === user.id ? null : user.id)}
                      className="p-1.5 rounded-lg transition-all"
                      style={{ color: '#8899AA', background: '#0E1117' }}
                      title="View wallets"
                    >
                      {expanded === user.id ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                    </button>
                    <button
                      onClick={() => { setModal({ type: 'credit', userId: user.id, username: user.username }); setModalForm({ agent_tier: '1', amount: '', notes: '' }) }}
                      className="p-1.5 rounded-lg"
                      style={{ color: '#00D4B4', background: 'rgba(0,212,180,0.1)' }}
                      title="Credit wallet"
                    >
                      <CreditCard size={15} />
                    </button>
                    <button
                      onClick={() => { setModal({ type: 'debit', userId: user.id, username: user.username }); setModalForm({ agent_tier: '1', amount: '', notes: '' }) }}
                      className="p-1.5 rounded-lg"
                      style={{ color: '#FFB547', background: 'rgba(255,181,71,0.1)' }}
                      title="Debit wallet"
                    >
                      <MinusCircle size={15} />
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
                  </div>
                </div>

                {/* Expanded Wallets */}
                {expanded === user.id && (
                  <div className="px-5 pb-4" style={{ background: '#0A0D12' }}>
                    {!userWallets[user.id] ? (
                      <div className="py-4 flex justify-center">
                        <div className="w-6 h-6 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
                      </div>
                    ) : (
                      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2 pt-3">
                        {userWallets[user.id].map(w => (
                          <div key={w.agent_tier + w.wallet_type} className="rounded-lg px-3 py-2 text-xs" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                            <p style={{ color: '#8899AA' }}>
                              {w.wallet_type} · {w.agent_tier === 0 ? 'Account' : `Agent ${w.agent_tier}`}
                            </p>
                            <p className="text-sm font-semibold text-white">${parseFloat(w.balance).toFixed(2)}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Credit/Debit Modal */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4" style={{ background: 'rgba(0,0,0,0.8)' }}>
          <div className="w-full max-w-sm rounded-2xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
            <h3 className="text-lg font-semibold text-white mb-1 capitalize">
              {modal.type} Wallet
            </h3>
            <p className="text-sm mb-5" style={{ color: '#8899AA' }}>
              User: <span className="text-white">{modal.username}</span>
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: '#8899AA' }}>Agent Tier</label>
                <select
                  value={modalForm.agent_tier}
                  onChange={e => setModalForm(f => ({ ...f, agent_tier: e.target.value }))}
                  className="w-full px-3 py-2.5 rounded-xl text-sm outline-none"
                  style={inputStyle}
                >
                  {[1, 2, 3, 4].map(t => <option key={t} value={t}>Agent {t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: '#8899AA' }}>Amount (USD)</label>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={modalForm.amount}
                  onChange={e => setModalForm(f => ({ ...f, amount: e.target.value }))}
                  placeholder="0.00"
                  className="w-full px-3 py-2.5 rounded-xl text-sm outline-none"
                  style={inputStyle}
                />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: '#8899AA' }}>Notes (optional)</label>
                <input
                  type="text"
                  value={modalForm.notes}
                  onChange={e => setModalForm(f => ({ ...f, notes: e.target.value }))}
                  placeholder="Reason for adjustment..."
                  className="w-full px-3 py-2.5 rounded-xl text-sm outline-none"
                  style={inputStyle}
                />
              </div>
            </div>

            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setModal(null)}
                className="flex-1 py-2.5 rounded-xl text-sm"
                style={{ border: '1px solid #1E2A38', color: '#8899AA', background: 'transparent' }}
              >
                Cancel
              </button>
              <button
                onClick={handleCredit}
                disabled={modalLoading || !modalForm.amount}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold"
                style={{
                  background: modal.type === 'credit' ? '#00D4B4' : '#FFB547',
                  color: '#000',
                  opacity: (modalLoading || !modalForm.amount) ? 0.5 : 1,
                }}
              >
                {modalLoading
                  ? <div className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin mx-auto" />
                  : modal.type === 'credit' ? 'Credit' : 'Debit'
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  )
}
