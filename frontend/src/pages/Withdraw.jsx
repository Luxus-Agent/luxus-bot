import { useEffect, useState } from 'react'
import { UserLayout, AdminLayout } from '../components/Layout'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'
import toast from 'react-hot-toast'
import {
  ArrowUpFromLine, Plus, Trash2, CheckCircle, Clock, XCircle,
  ShieldCheck, AlertCircle, Wallet
} from 'lucide-react'
import Pagination from '../components/Pagination'
import { formatDateTimeIST } from '../utils/datetime'

const PAGE_SIZE = 10

const STATUS_COLOR = { PENDING: '#FFB547', PROCESSING: '#3498DB', SENT: '#00D4B4', FAILED: '#FF4D6A' }
const STATUS_ICON = { PENDING: Clock, PROCESSING: Clock, SENT: CheckCircle, FAILED: XCircle }

export default function Withdraw() {
  const { isAdmin } = useAuth()
  const Layout = isAdmin ? AdminLayout : UserLayout
  const [wallets, setWallets] = useState([])
  const [addresses, setAddresses] = useState([])
  const [withdrawals, setWithdrawals] = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('withdraw')
  const [historyPage, setHistoryPage] = useState(1)

  // Withdrawal form
  const [wForm, setWForm] = useState({ amount: '', wallet_address: '' })
  const [withdrawing, setWithdrawing] = useState(false)

  // Address form
  const [addrStep, setAddrStep] = useState('form') // form | otp
  const [addrForm, setAddrForm] = useState({ address: '', label: '' })
  const [addrOtp, setAddrOtp] = useState('')
  const [addrLoading, setAddrLoading] = useState(false)

  const load = () =>
    Promise.all([
      api.get('/wallet/balances'),
      api.get('/wallet/addresses'),
      api.get('/wallet/withdrawals'),
    ]).then(([wb, ab, wr]) => {
      setWallets(wb.data)
      setAddresses(ab.data)
      setWithdrawals(wr.data)
    }).catch(() => toast.error('Failed to load')).finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  // Withdrawable balance = account balance + all earnings (every MAIN wallet)
  const earnings = wallets
    .filter(w => w.wallet_type === 'main')
    .reduce((s, w) => s + parseFloat(w.balance || 0), 0)
  const accountBalance = parseFloat(wallets.find(w => w.wallet_type === 'account' && w.agent_tier === 0)?.balance || 0)
  const withdrawable = accountBalance + earnings

  const handleWithdraw = async (e) => {
    e.preventDefault()
    const amt = parseFloat(wForm.amount)
    if (amt < 10) { toast.error('Minimum withdrawal is $10'); return }
    if (amt > withdrawable) { toast.error('Insufficient balance'); return }
    setWithdrawing(true)
    try {
      await api.post('/wallet/withdraw', {
        amount: amt,
        wallet_address: wForm.wallet_address,
      })
      toast.success('Withdrawal initiated!')
      setWForm({ amount: '', wallet_address: '' })
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Withdrawal failed')
    } finally {
      setWithdrawing(false)
    }
  }

  const handleAddAddress = async (e) => {
    e.preventDefault()
    setAddrLoading(true)
    try {
      await api.post('/wallet/address', addrForm)
      setAddrStep('otp')
      toast.success('OTP sent to your email')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to add address')
    } finally {
      setAddrLoading(false)
    }
  }

  const handleVerifyAddress = async (e) => {
    e.preventDefault()
    setAddrLoading(true)
    try {
      await api.post('/wallet/address/verify', { address: addrForm.address, otp: addrOtp })
      toast.success('Address verified!')
      setAddrStep('form')
      setAddrForm({ address: '', label: '' })
      setAddrOtp('')
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'OTP verification failed')
    } finally {
      setAddrLoading(false)
    }
  }

  const handleDeleteAddress = async (id) => {
    if (!window.confirm('Remove this withdrawal address?')) return
    try {
      await api.delete(`/wallet/address/${id}`)
      toast.success('Address removed')
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to remove')
    }
  }

  const verifiedAddresses = addresses.filter(a => a.is_verified)
  const withdrawalPages = Math.max(1, Math.ceil(withdrawals.length / PAGE_SIZE))
  const paginatedWithdrawals = withdrawals.slice((historyPage - 1) * PAGE_SIZE, historyPage * PAGE_SIZE)

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: '#00D4B4' }} />
      </div>
    </Layout>
  )

  const inputStyle = {
    background: '#0E1117', border: '1px solid #1E2A38', color: '#fff',
  }

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 sm:gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Withdraw</h1>
            <p className="text-sm mt-1" style={{ color: '#8899AA' }}>Send USDT to your BEP-20 wallet address</p>
          </div>
          <div
            className="flex items-start gap-2 px-3 py-2 rounded-xl sm:flex-shrink-0"
            style={{ background: 'rgba(255,77,106,0.07)', border: '1px solid rgba(255,77,106,0.25)' }}
          >
            <AlertCircle size={14} style={{ color: '#FF4D6A' }} className="flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold leading-tight" style={{ color: '#FF4D6A' }}>BEP-20 Network Only</p>
              <p className="text-xs mt-0.5 leading-tight" style={{ color: '#8899AA' }}>
                Only use BEP-20 addresses.<br />Other networks = permanent loss.
              </p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38', width: 'fit-content' }}>
          {[
            { key: 'withdraw', label: 'Withdraw' },
            { key: 'addresses', label: 'Addresses' },
            { key: 'history', label: 'History' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className="px-5 py-2.5 text-sm font-medium transition-all"
              style={tab === key
                ? { background: '#00D4B4', color: '#000' }
                : { color: '#8899AA' }
              }
            >
              {label}
            </button>
          ))}
        </div>

        {/* Withdraw Tab */}
        {tab === 'withdraw' && (
          <div className="max-w-lg">
            {/* Account Balance Banner */}
            <div
              className="rounded-xl p-4 mb-4 flex items-center justify-between"
              style={{ background: '#141922', border: '1px solid rgba(0,212,180,0.2)' }}
            >
              <div>
                <p className="text-xs" style={{ color: '#8899AA' }}>Withdrawable Balance</p>
                <p className="text-xl font-bold" style={{ color: '#00D4B4' }}>${withdrawable.toFixed(2)}</p>
                <p className="text-xs mt-0.5" style={{ color: '#4A5568' }}>
                  ${accountBalance.toFixed(2)} balance + ${earnings.toFixed(2)} earnings
                </p>
              </div>
              <Wallet size={22} style={{ color: '#00D4B4', opacity: 0.6 }} />
            </div>

            {verifiedAddresses.length === 0 && (
              <div
                className="rounded-xl p-4 mb-4 flex gap-3 items-start"
                style={{ background: 'rgba(255,181,71,0.08)', border: '1px solid rgba(255,181,71,0.25)' }}
              >
                <AlertCircle size={18} style={{ color: '#FFB547' }} className="flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium" style={{ color: '#FFB547' }}>No verified addresses</p>
                  <p className="text-xs mt-0.5" style={{ color: '#8899AA' }}>
                    Add and verify a BEP-20 address in the Addresses tab before withdrawing.
                  </p>
                </div>
              </div>
            )}

            <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <form onSubmit={handleWithdraw} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Amount (USD)</label>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 font-semibold" style={{ color: '#8899AA' }}>$</span>
                    <input
                      type="number"
                      min="10"
                      step="0.01"
                      required
                      value={wForm.amount}
                      onChange={e => setWForm(f => ({ ...f, amount: e.target.value }))}
                      placeholder="10.00"
                      className="w-full pl-8 pr-4 py-3 rounded-xl text-sm outline-none"
                      style={inputStyle}
                      onFocus={e => e.target.style.borderColor = '#00D4B4'}
                      onBlur={e => e.target.style.borderColor = '#1E2A38'}
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Withdrawal Address</label>
                  <select
                    value={wForm.wallet_address}
                    onChange={e => setWForm(f => ({ ...f, wallet_address: e.target.value }))}
                    required
                    className="w-full px-4 py-3 rounded-xl text-sm outline-none"
                    style={inputStyle}
                    onFocus={e => e.target.style.borderColor = '#00D4B4'}
                    onBlur={e => e.target.style.borderColor = '#1E2A38'}
                  >
                    <option value="">Select a verified address</option>
                    {verifiedAddresses.map(a => (
                      <option key={a.id} value={a.address}>
                        {a.label ? `${a.label} — ` : ''}{a.address.slice(0, 10)}...{a.address.slice(-8)}
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="submit"
                  disabled={withdrawing || verifiedAddresses.length === 0}
                  className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
                  style={{
                    background: (withdrawing || verifiedAddresses.length === 0) ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                    color: (withdrawing || verifiedAddresses.length === 0) ? '#8899AA' : '#000',
                    cursor: (withdrawing || verifiedAddresses.length === 0) ? 'not-allowed' : 'pointer',
                  }}
                >
                  {withdrawing
                    ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                    : <><ArrowUpFromLine size={14} /> Withdraw Now</>
                  }
                </button>
              </form>
            </div>
          </div>
        )}

        {/* Addresses Tab */}
        {tab === 'addresses' && (
          <div className="max-w-lg space-y-4">
            {/* Add Form */}
            <div className="rounded-xl p-6" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              <h2 className="font-semibold text-white mb-4">
                {addrStep === 'form' ? 'Add Withdrawal Address' : 'Verify Address'}
              </h2>
              {addrStep === 'form' ? (
                <form onSubmit={handleAddAddress} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>BEP-20 Address</label>
                    <input
                      type="text"
                      required
                      value={addrForm.address}
                      onChange={e => setAddrForm(f => ({ ...f, address: e.target.value }))}
                      placeholder="0x..."
                      className="w-full px-4 py-3 rounded-xl text-sm outline-none font-mono"
                      style={inputStyle}
                      onFocus={e => e.target.style.borderColor = '#00D4B4'}
                      onBlur={e => e.target.style.borderColor = '#1E2A38'}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2" style={{ color: '#8899AA' }}>Label (optional)</label>
                    <input
                      type="text"
                      value={addrForm.label}
                      onChange={e => setAddrForm(f => ({ ...f, label: e.target.value }))}
                      placeholder="e.g. My Binance Wallet"
                      className="w-full px-4 py-3 rounded-xl text-sm outline-none"
                      style={inputStyle}
                      onFocus={e => e.target.style.borderColor = '#00D4B4'}
                      onBlur={e => e.target.style.borderColor = '#1E2A38'}
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={addrLoading}
                    className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
                    style={{ background: addrLoading ? 'rgba(0,212,180,0.3)' : '#00D4B4', color: addrLoading ? '#8899AA' : '#000' }}
                  >
                    {addrLoading
                      ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                      : <><Plus size={14} /> Add Address</>
                    }
                  </button>
                </form>
              ) : (
                <form onSubmit={handleVerifyAddress} className="space-y-4">
                  <div
                    className="w-14 h-14 rounded-xl flex items-center justify-center mx-auto"
                    style={{ background: 'rgba(0,212,180,0.12)', border: '1px solid rgba(0,212,180,0.3)' }}
                  >
                    <ShieldCheck size={24} style={{ color: '#00D4B4' }} />
                  </div>
                  <p className="text-sm text-center" style={{ color: '#8899AA' }}>
                    OTP sent to your email. Enter it below to verify:
                    <span className="block text-xs font-mono mt-1 text-white">{addrForm.address}</span>
                  </p>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    value={addrOtp}
                    onChange={e => setAddrOtp(e.target.value.replace(/\D/g, ''))}
                    placeholder="000000"
                    className="w-full px-4 py-3 rounded-xl text-center text-2xl font-bold tracking-widest outline-none"
                    style={inputStyle}
                    onFocus={e => e.target.style.borderColor = '#00D4B4'}
                    onBlur={e => e.target.style.borderColor = '#1E2A38'}
                  />
                  <button
                    type="submit"
                    disabled={addrLoading || addrOtp.length < 6}
                    className="w-full py-3 rounded-xl font-semibold text-sm"
                    style={{
                      background: (addrLoading || addrOtp.length < 6) ? 'rgba(0,212,180,0.3)' : '#00D4B4',
                      color: (addrLoading || addrOtp.length < 6) ? '#8899AA' : '#000',
                    }}
                  >
                    {addrLoading
                      ? <div className="w-5 h-5 rounded-full border-2 border-current border-t-transparent animate-spin mx-auto" />
                      : 'Verify Address'
                    }
                  </button>
                  <button type="button" onClick={() => { setAddrStep('form'); setAddrOtp('') }}
                    className="w-full py-2.5 rounded-xl text-sm"
                    style={{ border: '1px solid #1E2A38', color: '#8899AA', background: 'transparent' }}>
                    Cancel
                  </button>
                </form>
              )}
            </div>

            {/* Addresses List */}
            {addresses.length > 0 && (
              <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
                <div className="row-divide">
                  {addresses.map(addr => (
                    <div key={addr.id} className="flex items-center gap-3 px-4 py-3">
                      <Wallet size={18} style={{ color: addr.is_verified ? '#00D4B4' : '#4A5568' }} className="flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        {addr.label && <p className="text-sm font-medium text-white">{addr.label}</p>}
                        <p className="text-xs font-mono" style={{ color: '#8899AA' }}>
                          {addr.address.slice(0, 12)}...{addr.address.slice(-10)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span
                          className="text-xs px-2 py-0.5 rounded-full font-medium"
                          style={addr.is_verified
                            ? { background: 'rgba(0,212,180,0.12)', color: '#00D4B4' }
                            : { background: 'rgba(255,181,71,0.12)', color: '#FFB547' }
                          }
                        >
                          {addr.is_verified ? 'Verified' : 'Pending'}
                        </span>
                        <button
                          onClick={() => handleDeleteAddress(addr.id)}
                          className="p-1.5 rounded-lg"
                          style={{ color: '#FF4D6A', background: 'rgba(255,77,106,0.1)' }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* History Tab */}
        {tab === 'history' && (
          <div>
            <div className="rounded-xl overflow-hidden" style={{ background: '#141922', border: '1px solid #1E2A38' }}>
              {withdrawals.length === 0 ? (
                <div className="p-8 text-center" style={{ color: '#8899AA' }}>
                  <ArrowUpFromLine size={32} className="mx-auto mb-2 opacity-30" />
                  <p className="text-sm">No withdrawals yet</p>
                </div>
              ) : (
                <div className="row-divide">
                  {paginatedWithdrawals.map(w => {
                    const Icon = STATUS_ICON[w.status] || Clock
                    const color = STATUS_COLOR[w.status] || '#8899AA'
                    return (
                      <div key={w.id} className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          <Icon size={18} style={{ color }} className="flex-shrink-0 mt-0.5" />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-sm font-semibold text-white">${parseFloat(w.amount).toFixed(2)} USDT</p>
                              <span
                                className="text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0"
                                style={{ background: `${color}18`, color }}
                              >
                                {w.status}
                              </span>
                            </div>
                            <p className="text-xs font-mono mt-0.5" style={{ color: '#4A5568' }}>
                              {w.wallet_address.slice(0, 14)}...{w.wallet_address.slice(-8)}
                            </p>
                            <p className="text-xs mt-0.5" style={{ color: '#4A5568' }}>
                              {formatDateTimeIST(w.created_at)}
                            </p>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              {withdrawals.length > 0 && (
                <div className="px-4 pb-3">
                  <Pagination page={historyPage} totalPages={withdrawalPages} onChange={setHistoryPage} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Layout>
  )
}
