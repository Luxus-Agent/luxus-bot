import { useEffect, useState } from 'react'
import { UserLayout as Layout } from '../components/Layout'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Bot, Zap, TrendingUp, Activity, CheckCircle, ShoppingCart, Coins } from 'lucide-react'
import { useAppKitAccount } from '@reown/appkit/react'
import { useUsdtBalance } from '../hooks/useUsdtBalance'
import { readContract, writeContract, waitForTransactionReceipt, switchChain } from '@wagmi/core'
import { erc20Abi, parseUnits, isAddress } from 'viem'
import { bscTestnet } from '@reown/appkit/networks'
import { wagmiConfig } from '../config/appkit'
import { MULTISENDER_ADDRESS, USDT_ADDRESS, USDT_DECIMALS, multisenderAbi } from '../config/contracts'

// `price` is what the buyer pays = base + platform fee. The 60/30/10 revenue split
// runs off `base`; the flat `fee` goes straight to the platform profit wallet.
const TIERS = [
  {
    id: 1, base: 10, fee: 1, price: 11, name: 'Agent 1',
    core: '$6.00', stream: '$20.00', boost: '$5.70',
    color: 'var(--accent)', desc: 'Entry level AI agent with full revenue mechanics',
  },
  {
    id: 2, base: 20, fee: 2, price: 22, name: 'Agent 2',
    core: '$12.00', stream: '$40.00', boost: '$5.70',
    color: '#3498DB', desc: '2× multiplier — doubles all payouts',
  },
  {
    id: 3, base: 50, fee: 5, price: 55, name: 'Agent 3',
    core: '$30.00', stream: '$100.00', boost: '$5.70',
    color: '#9B59B6', desc: '5× multiplier — high-yield tier',
  },
  {
    id: 4, base: 100, fee: 11, price: 111, name: 'Agent 4',
    core: '$60.00', stream: '$200.00', boost: '$5.70',
    color: '#FFB547', desc: '10× multiplier — maximum earning potential',
  },
]

export default function AgentPurchase() {
  const [purchases, setPurchases] = useState([])
  const [accountBalance, setAccountBalance] = useState(0)
  const [loading, setLoading] = useState(true)
  const [purchasing, setPurchasing] = useState(null)
  const [confirmTier, setConfirmTier] = useState(null)  // tier awaiting confirm-modal approval
  const { address, isConnected } = useAppKitAccount()
  const { balance: usdtBalance, loading: usdtLoading, configured: usdtConfigured, refetch: refetchUsdtBalance } = useUsdtBalance()

  // Account (spendable) balance lives in the 'account' wallet from /wallet/balances.
  const accountBalanceFrom = (wallets) =>
    parseFloat((wallets || []).find(w => w.wallet_type === 'account' && w.agent_tier === 0)?.balance || 0) || 0

  useEffect(() => {
    Promise.all([
      api.get('/agents/purchases'),
      api.get('/wallet/balances'),
    ]).then(([p, b]) => {
      setPurchases(p.data)
      setAccountBalance(accountBalanceFrom(b.data))
    }).catch(() => toast.error('Failed to load')).finally(() => setLoading(false))
  }, [])

  // Pre-flight checks, then open the in-app confirm modal.
  const requestPurchase = (tier) => {
    if (isOwned(tier.id)) {
      toast.error(`You already own Agent ${tier.id}. Each agent can be purchased once.`)
      return
    }
    if (!isUnlocked(tier.id)) {
      toast.error(`Purchase Agent ${tier.id - 1} before Agent ${tier.id}.`)
      return
    }
    if (!isConnected || !address) {
      toast.error('Connect your wallet to purchase.')
      return
    }
    if (!MULTISENDER_ADDRESS || !isAddress(MULTISENDER_ADDRESS)) {
      toast.error('Payout contract is not configured. Set VITE_MULTISENDER_ADDRESS.')
      return
    }
    setConfirmTier(tier)
  }

  // Runs the on-chain payment once the user confirms in the modal.
  const executePurchase = async (tier) => {
    const tierId = tier.id
    const price = tier.price
    setPurchasing(tierId)
    let purchaseId
    let txHash
    let txConfirmed = false
    try {
      // 1) Ask the backend for the payout split (recipients + amounts).
      const { data } = await api.post('/distribution/pack/purchase', {
        pack_name: tier?.name,
        agent_tier: tierId,
        amount: price,
      })
      purchaseId = data.purchase_id ?? data.id
      const decimals = Number(data.decimals ?? USDT_DECIMALS)
      const token = data.token_contract || data.token_address || USDT_ADDRESS
      if (!token || !isAddress(token)) {
        throw new Error('No valid USDT token address from server (set VITE_USDT_ADDRESS).')
      }

      // Recipients to pay = everyone except the buyer, with a positive amount.
      const recipients = (data.recipients || []).filter(
        r => r.role !== 'buyer' && Number(r.amount) > 0 && isAddress(r.wallet_address),
      )
      if (recipients.length === 0) throw new Error('No payout recipients returned by server.')

      const to = recipients.map(r => r.wallet_address)
      const values = recipients.map(r => parseUnits(String(r.amount), decimals))
      const total = values.reduce((sum, v) => sum + v, 0n)

      // 2) Make sure the wallet is on BNB testnet.
      try {
        await switchChain(wagmiConfig, { chainId: bscTestnet.id })
      } catch {
        throw new Error('Switch your wallet to BNB Smart Chain Testnet and try again.')
      }

      // 3) Approve the MultiSender to pull `total` USDT, only if needed.
      const allowance = await readContract(wagmiConfig, {
        address: token,
        abi: erc20Abi,
        functionName: 'allowance',
        args: [address, MULTISENDER_ADDRESS],
      })
      if (allowance < total) {
        toast.loading('Approve USDT spending in your wallet…', { id: 'approve' })
        const approveHash = await writeContract(wagmiConfig, {
          address: token,
          abi: erc20Abi,
          functionName: 'approve',
          args: [MULTISENDER_ADDRESS, total],
        })
        await waitForTransactionReceipt(wagmiConfig, { hash: approveHash })
        toast.dismiss('approve')
      }

      // 4) Batch the payout in a single transaction.
      toast.loading('Confirm the payment in your wallet…', { id: 'send' })
      txHash = await writeContract(wagmiConfig, {
        address: MULTISENDER_ADDRESS,
        abi: multisenderAbi,
        functionName: 'sendERC20DifferentValue',
        args: [token, to, values],
      })
      const receipt = await waitForTransactionReceipt(wagmiConfig, { hash: txHash })
      toast.dismiss('send')
      // waitForTransactionReceipt resolves even when a tx reverts — verify it succeeded.
      if (receipt.status !== 'success') {
        throw new Error('Transaction reverted on-chain.')
      }
      txConfirmed = true

      // 5) Mark the purchase as paid — send the on-chain tx hash to the backend.
      await api.post('/distribution/pack/status', {
        purchase_id: purchaseId,
        status: 'success',
        tx_hash: txHash,
      })

      toast.success(`Agent ${tierId} purchased!`)
      refetchUsdtBalance()
      const [p, b] = await Promise.all([api.get('/agents/purchases'), api.get('/wallet/balances')])
      setPurchases(p.data)
      setAccountBalance(accountBalanceFrom(b.data))
    } catch (err) {
      toast.dismiss('approve')
      toast.dismiss('send')
      // If the on-chain payment didn't go through, tell the backend it failed.
      if (purchaseId && !txConfirmed) {
        api.post('/distribution/pack/status', {
          purchase_id: purchaseId,
          status: 'failed',
          tx_hash: txHash || null,
          failure_reason: (err?.shortMessage || err?.message || 'Payment failed').slice(0, 200),
        }).catch(() => {})
      }
      const msg = err?.shortMessage || err?.response?.data?.detail || err?.message || 'Purchase failed'
      toast.error(msg)
    } finally {
      setPurchasing(null)
    }
  }

  // One purchase per tier, bought in order. A tier is "owned" once a purchase
  // record exists (pending or active); the next tier unlocks only after the
  // previous one is owned.
  const ownedTiers = new Set(purchases.map(p => p.agent_tier))
  const isOwned = (tier) => ownedTiers.has(tier)
  const isUnlocked = (tier) => tier === 1 || ownedTiers.has(tier - 1)

  if (loading) return (
    <Layout>
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 rounded-full border-2 border-transparent animate-spin" style={{ borderTopColor: 'var(--accent)' }} />
      </div>
    </Layout>
  )

  return (
    <Layout>
      <div className="space-y-6 fade-in">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Buy AI Agents</h1>
            <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
              Purchase triggers 3 parallel revenue mechanisms automatically
            </p>
          </div>
          <div
            className="px-4 py-3 rounded-xl flex items-center gap-3"
            style={{ background: 'var(--bg-panel)', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}
          >
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: 'rgba(var(--accent-rgb), 0.094)' }}>
              <Coins size={18} style={{ color: 'var(--accent)' }} />
            </div>
            <div>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Wallet Balance</p>
              <p className="text-xl font-bold" style={{ color: 'var(--accent)' }}>
                {!usdtConfigured ? (
                  <span className="text-sm" style={{ color: '#FFB547' }}>Not configured</span>
                ) : !isConnected ? (
                  <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>Connect wallet</span>
                ) : usdtLoading ? (
                  <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading…</span>
                ) : usdtBalance == null ? (
                  <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>—</span>
                ) : (
                  `$${usdtBalance.toFixed(2)}`
                )}
              </p>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>On-chain USDT (BSC)</p>
            </div>
          </div>
        </div>

        {/* Revenue Split Info */}
        <div className="rounded-xl p-4" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}>
          <p className="text-sm font-semibold text-white mb-3">Revenue Split on Every Purchase</p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Core Agent', pct: '60%', icon: Zap, color: 'var(--accent)' },
              { label: 'Stream Agent', pct: '30%', icon: TrendingUp, color: '#3498DB' },
              { label: 'Boost Agent', pct: '10%', icon: Activity, color: '#9B59B6' },
            ].map(({ label, pct, icon: Icon, color }) => (
              <div key={label} className="rounded-lg p-3 text-center" style={{ background: 'var(--bg-surface)' }}>
                <Icon size={18} className="mx-auto mb-1" style={{ color }} />
                <p className="text-xs font-bold" style={{ color }}>{pct}</p>
                <p className="text-xs font-medium text-white">{label}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Agent Tier Cards */}
        <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {TIERS.map(tier => {
            const owned = isOwned(tier.id)
            const unlocked = isUnlocked(tier.id)
            const isBuying = purchasing === tier.id
            const disabled = owned || !unlocked || !isConnected || isBuying
            return (
              <div
                key={tier.id}
                className="rounded-xl overflow-hidden transition-all"
                style={{ background: 'var(--bg-panel)', border: `1px solid color-mix(in srgb, ${tier.color} 30%, transparent)` }}
              >
                {/* Header */}
                <div className="p-4 pb-3" style={{ background: `color-mix(in srgb, ${tier.color} 4%, transparent)` }}>
                  <div className="flex items-center justify-between mb-2">
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center"
                      style={{ background: `color-mix(in srgb, ${tier.color} 20%, transparent)`, border: `1px solid color-mix(in srgb, ${tier.color} 40%, transparent)` }}
                    >
                      <Bot size={20} style={{ color: tier.color }} />
                    </div>
                    {owned ? (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-semibold"
                        style={{ background: `color-mix(in srgb, ${tier.color} 20%, transparent)`, color: tier.color }}
                      >
                        OWNED
                      </span>
                    ) : !unlocked && (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-semibold"
                        style={{ background: 'var(--border)', color: 'var(--text-muted)' }}
                      >
                        LOCKED
                      </span>
                    )}
                  </div>
                  <h3 className="text-lg font-bold text-white">{tier.name}</h3>
                  <p className="text-2xl font-bold" style={{ color: tier.color }}>${tier.price}</p>
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>${tier.base} + ${tier.fee} platform fee</p>
                  <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{tier.desc}</p>
                </div>

                {/* Payouts */}
                <div className="px-4 py-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-muted)' }}>Max Payouts</p>
                  {[
                    { label: 'Core Agent Total', val: tier.core },
                    { label: 'Stream Agent Total', val: tier.stream },
                    { label: 'Boost Agent Total', val: tier.boost },
                  ].map(({ label, val }) => (
                    <div key={label} className="flex justify-between text-xs">
                      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                      <span className="font-semibold text-white">{val}</span>
                    </div>
                  ))}
                </div>

                {/* Button */}
                <div className="px-4 pb-4">
                  <button
                    onClick={() => requestPurchase(tier)}
                    disabled={disabled}
                    className="w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all"
                    style={{
                      background: isBuying ? `color-mix(in srgb, ${tier.color} 40%, transparent)` : (owned ? `color-mix(in srgb, ${tier.color} 20%, transparent)` : (unlocked && isConnected ? tier.color : 'var(--border)')),
                      color: owned ? tier.color : (unlocked && isConnected && !isBuying ? '#000' : 'var(--text-muted)'),
                      cursor: disabled ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {isBuying ? (
                      <div className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
                    ) : owned ? (
                      <><CheckCircle size={14} /> Owned</>
                    ) : !unlocked ? (
                      <>Buy Agent {tier.id - 1} first</>
                    ) : !isConnected ? (
                      <>Connect Wallet</>
                    ) : (
                      <><ShoppingCart size={14} /> Purchase</>
                    )}
                  </button>
                  {!owned && unlocked && !isConnected && (
                    <p className="text-xs mt-1.5 text-center" style={{ color: 'var(--text-muted)' }}>
                      Connect your wallet to purchase
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Purchase confirmation modal */}
        {confirmTier && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
            <div
              className="absolute inset-0"
              style={{ background: 'rgba(0,0,0,0.75)' }}
              onClick={() => setConfirmTier(null)}
            />
            <div
              className="relative w-full max-w-sm rounded-2xl p-6"
              style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}
            >
              <div className="flex items-center gap-3 mb-3">
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ background: 'rgba(var(--accent-rgb),0.12)', color: 'var(--accent)' }}
                >
                  <ShoppingCart size={20} />
                </div>
                <h2 className="text-lg font-bold text-white">Confirm purchase</h2>
              </div>
              <p className="text-sm mb-5" style={{ color: 'var(--text-secondary)' }}>
                Buy <span className="text-white font-semibold">{confirmTier.name}</span> for{' '}
                <span className="text-white font-semibold">${confirmTier.price}</span>{' '}
                <span style={{ color: 'var(--text-muted)' }}>(${confirmTier.base} + ${confirmTier.fee} platform fee)</span>?
                Payment is sent on-chain in USDT from your connected wallet to the referral payout addresses.
              </p>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setConfirmTier(null)}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold transition-all"
                  style={{ background: 'var(--border)', color: 'var(--text-secondary)' }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => { const t = confirmTier; setConfirmTier(null); executePurchase(t) }}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all"
                  style={{ background: 'var(--accent)', color: '#000' }}
                >
                  <ShoppingCart size={14} /> Confirm
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  )
}
