import { useEffect, useState } from 'react'
import { AdminLayout as Layout } from '../../components/Layout'
import Pagination from '../../components/Pagination'
import api from '../../api/client'
import toast from 'react-hot-toast'
import { ArrowUpFromLine, Search, RefreshCw, Clock, CheckCircle, XCircle, Loader } from 'lucide-react'

const PAGE_SIZE = 10

const STATUS_COLOR = { PENDING: '#FFB547', PROCESSING: '#3498DB', SENT: '#00D4B4', FAILED: '#FF4D6A' }
const STATUS_ICON = { PENDING: Clock, PROCESSING: Loader, SENT: CheckCircle, FAILED: XCircle }

export default function AdminWithdrawals() {
  const [withdrawals, setWithdrawals] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')
  const [page, setPage] = useState(1)

  const load = () =>
    api.get('/admin/withdrawals')
      .then(r => setWithdrawals(r.data))
      .catch(() => toast.error('Failed to load'))
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const filtered = withdrawals.filter(w => {
    if (filterStatus !== 'all' && w.status !== filterStatus) return false
    if (search && !String(w.user_id).includes(search) && !w.wallet_address.includes(search)) return false
    return true
  })
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const pending = withdrawals.filter(w => w.status === 'PENDING').length
  const sent = withdrawals.filter(w => w.status === 'SENT').length
  const failed = withdrawals.filter(w => w.status === 'FAILED').length
  const totalSent = withdrawals.filter(w => w.status === 'SENT').reduce((s, w) => s + parseFloat(w.amount), 0)

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
      </div>
    </Layout>
  )

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Withdrawal Queue</h1>
            <p className="text-sm mt-1" style={{ color: '#8899AA' }}>{withdrawals.length} total withdrawal requests</p>
          </div>
          <div className="flex gap-2">
            <button onClick={load} className="p-2 rounded-xl" style={{ background: '#141922', border: '1px solid #1E2A38', color: '#8899AA' }}>
              <RefreshCw size={16} />
            </button>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#4A5568' }} />
              <input
                type="text"
                placeholder="Search..."
                value={search}
                onChange={e => { setSearch(e.target.value); setPage(1) }}
                className="pl-8 pr-4 py-2 rounded-xl text-sm outline-none w-44"
                style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
              />
            </div>
            <select
              value={filterStatus}
              onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
              className="px-3 py-2 rounded-xl text-sm outline-none"
              style={{ background: '#141922', border: '1px solid #1E2A38', color: '#fff' }}
            >
              <option value="all">All Status</option>
              {['PENDING', 'PROCESSING', 'SENT', 'FAILED'].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Pending', val: pending, color: '#FFB547' },
            { label: 'Sent', val: sent, color: '#00D4B4' },
            { label: 'Failed', val: failed, color: '#FF4D6A' },
            { label: 'Total Sent', val: `$${totalSent.toFixed(2)}`, color: '#00FFD4' },
          ].map(({ label, val, color }) => (
            <div key={label} className="rounded-xl p-4" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <p className="text-xs" style={{ color: '#8899AA' }}>{label}</p>
              <p className="text-2xl font-bold mt-1" style={{ color }}>{val}</p>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
          <div
            className="hidden sm:grid grid-cols-6 px-5 py-3 text-xs font-semibold uppercase tracking-wider"
            style={{ background: '#0E1117', color: '#4A5568', borderBottom: '1px solid #1E2A38' }}
          >
            <span>User</span>
            <span>Amount</span>
            <span>Tier</span>
            <span className="col-span-2">Address</span>
            <span className="text-right">Status</span>
          </div>

          <div className="row-divide">
            {filtered.length === 0 ? (
              <div className="p-8 text-center" style={{ color: '#8899AA' }}>
                <ArrowUpFromLine size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">No withdrawals found</p>
              </div>
            ) : paginated.map(w => {
              const color = STATUS_COLOR[w.status] || '#8899AA'
              const Icon = STATUS_ICON[w.status] || Clock
              return (
                <div key={w.id} className="px-5 py-4">
                  <div className="flex sm:grid sm:grid-cols-6 items-start gap-3">
                    <span className="text-sm font-medium text-white">#{w.user_id}</span>
                    <span className="text-sm font-semibold" style={{ color: '#00D4B4' }}>
                      ${parseFloat(w.amount).toFixed(2)}
                    </span>
                    <span className="hidden sm:block text-xs" style={{ color: '#8899AA' }}>Agent {w.agent_tier}</span>
                    <span className="hidden sm:block col-span-2 text-xs font-mono truncate" style={{ color: '#4A5568' }}>
                      {w.wallet_address}
                    </span>
                    <div className="ml-auto sm:ml-0 sm:text-right">
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-medium inline-flex items-center gap-1"
                        style={{ background: `${color}18`, color }}
                      >
                        <Icon size={11} />
                        {w.status}
                      </span>
                      <p className="text-xs mt-1" style={{ color: '#4A5568' }}>
                        {new Date(w.created_at).toLocaleString()}
                      </p>
                    </div>
                  </div>
                  {w.failure_reason && (
                    <p className="text-xs mt-2 px-2 py-1 rounded" style={{ background: 'rgba(255,77,106,0.08)', color: '#FF4D6A' }}>
                      Failure: {w.failure_reason}
                    </p>
                  )}
                  {w.nowpayments_payout_id && (
                    <p className="text-xs mt-1" style={{ color: '#4A5568' }}>
                      Payout ID: {w.nowpayments_payout_id}
                    </p>
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
