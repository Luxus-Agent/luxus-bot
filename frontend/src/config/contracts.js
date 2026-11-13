// On-chain contract config for the MLM pack-purchase payout flow.
//
// The MultiSender contract batches a single ERC20 transfer to many recipients
// (the buyer's upline + platform fee) in one transaction. Addresses come from
// env so they can differ per environment; the ABI is a committed JSON file
// (ABIs are large and not secret, so env vars are impractical for them).
import multisenderAbi from './multisenderAbi.json'

// MultiSender contract (sendERC20DifferentValue → transferFrom buyer → each recipient).
// BSC MAINNET deployment (chain 56). VITE_MULTISENDER_ADDRESS overrides it — a
// testnet build (VITE_CHAIN=testnet) MUST set that to its own testnet deployment,
// since this default only exists on mainnet.
const DEFAULT_MULTISENDER_ADDRESS = '0x20e0E77ed5c5c901389eAbA68dc3fC4396650C0f'
export const MULTISENDER_ADDRESS = import.meta.env.VITE_MULTISENDER_ADDRESS || DEFAULT_MULTISENDER_ADDRESS

// USDT token. Preferred source is the purchase API response (token_contract);
// falls back to VITE_USDT_ADDRESS, then BSC mainnet's official BSC-USD (USDT)
// below. Must match the backend's USDT_CONTRACT. (Testnet builds set
// VITE_USDT_ADDRESS to their mock token.)
const DEFAULT_USDT_ADDRESS = '0x55d398326f99059fF775485246999027B3197955'
export const USDT_ADDRESS = import.meta.env.VITE_USDT_ADDRESS || DEFAULT_USDT_ADDRESS

// Token decimals fallback when the purchase API doesn't return `decimals`.
// BSC mainnet USDT uses 18.
export const USDT_DECIMALS = Number(import.meta.env.VITE_USDT_DECIMALS || 18)

export { multisenderAbi }
