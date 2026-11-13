import { useCallback, useEffect, useState } from 'react'
import { useAppKitAccount } from '@reown/appkit/react'
import { readContract } from '@wagmi/core'
import { erc20Abi, formatUnits, isAddress } from 'viem'
import { activeChain } from '../config/chain'
import { wagmiConfig } from '../config/appkit'
import { USDT_ADDRESS, USDT_DECIMALS } from '../config/contracts'

// How often to silently re-poll the on-chain balance while connected, so it
// stays live without the caller needing to trigger `refetch` manually. Paused
// while the tab is in the background to avoid wasted RPC calls.
const BALANCE_POLL_MS = 20_000

// Reads the connected wallet's live on-chain USDT balance (chain from config/chain.js — BSC mainnet by default).
//
// This is the user's real spendable balance — on-chain pack purchases and the
// commissions they earn move USDT directly in/out of this wallet, never through
// the internal app wallets. Returns null when not connected or USDT isn't
// configured (set VITE_USDT_ADDRESS). Decimals are read on-chain (the token may
// use 18, not the env fallback), falling back to USDT_DECIMALS.
export function useUsdtBalance() {
  const { address, isConnected } = useAppKitAccount()
  const [balance, setBalance] = useState(null)
  const [loading, setLoading] = useState(false)

  const configured = !!(USDT_ADDRESS && isAddress(USDT_ADDRESS))

  const refetch = useCallback(async () => {
    if (!isConnected || !address || !configured) {
      setBalance(null)
      return
    }
    setLoading(true)
    try {
      const [raw, decimals] = await Promise.all([
        readContract(wagmiConfig, {
          address: USDT_ADDRESS,
          abi: erc20Abi,
          functionName: 'balanceOf',
          args: [address],
          chainId: activeChain.id,
        }),
        readContract(wagmiConfig, {
          address: USDT_ADDRESS,
          abi: erc20Abi,
          functionName: 'decimals',
          chainId: activeChain.id,
        }).catch(() => USDT_DECIMALS),
      ])
      setBalance(parseFloat(formatUnits(raw, Number(decimals))))
    } catch {
      setBalance(null)
    } finally {
      setLoading(false)
    }
  }, [address, isConnected, configured])

  useEffect(() => { refetch() }, [refetch])

  useEffect(() => {
    if (!isConnected || !configured) return
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') refetch()
    }, BALANCE_POLL_MS)
    return () => clearInterval(id)
  }, [isConnected, configured, refetch])

  return { balance, loading, refetch, isConnected, configured }
}
