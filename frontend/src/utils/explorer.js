// BSC testnet for now — matches frontend/src/config/appkit.js (bscTestnet) and the
// backend's default BSC_RPC_URL. Switch to 'https://bscscan.com/tx/' on mainnet cutover.
const TX_EXPLORER_BASE = 'https://testnet.bscscan.com/tx/'

export function txExplorerUrl(txHash) {
  return `${TX_EXPLORER_BASE}${txHash}`
}

export function shortenTxHash(txHash) {
  if (!txHash) return ''
  return `${txHash.slice(0, 6)}…${txHash.slice(-4)}`
}
