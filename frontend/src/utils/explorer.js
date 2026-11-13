// Explorer base follows the active chain (config/chain.js) — bscscan.com on
// mainnet (default), testnet.bscscan.com when VITE_CHAIN=testnet.
import { EXPLORER_BASE } from '../config/chain'

const TX_EXPLORER_BASE = `${EXPLORER_BASE}/tx/`
const ADDRESS_EXPLORER_BASE = `${EXPLORER_BASE}/address/`

export function txExplorerUrl(txHash) {
  return `${TX_EXPLORER_BASE}${txHash}`
}

export function addressExplorerUrl(address) {
  return `${ADDRESS_EXPLORER_BASE}${address}`
}

export function shortenTxHash(txHash) {
  if (!txHash) return ''
  return `${txHash.slice(0, 6)}…${txHash.slice(-4)}`
}
