// BSC testnet for now — matches frontend/src/config/appkit.js (bscTestnet) and the
// backend's default BSC_RPC_URL. Switch to 'https://bscscan.com/tx/' (and /address/) on mainnet cutover.
const TX_EXPLORER_BASE = 'https://testnet.bscscan.com/tx/'
const ADDRESS_EXPLORER_BASE = 'https://testnet.bscscan.com/address/'

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
