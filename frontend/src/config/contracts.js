// On-chain contract config for the MLM pack-purchase payout flow.
//
// The MultiSender contract batches a single ERC20 transfer to many recipients
// (the buyer's upline + platform fee) in one transaction. Addresses come from
// env so they can differ per environment; the ABI is a committed JSON file
// (ABIs are large and not secret, so env vars are impractical for them).
import multisenderAbi from './multisenderAbi.json'

// MultiSender contract (sendERC20DifferentValue → transferFrom buyer → each recipient).
export const MULTISENDER_ADDRESS = import.meta.env.VITE_MULTISENDER_ADDRESS || ''

// Mock USDT token used for testing. Preferred source is the purchase API
// response (token_contract); this is the fallback when the API omits it.
export const USDT_ADDRESS = import.meta.env.VITE_USDT_ADDRESS || ''

// Token decimals fallback when the purchase API doesn't return `decimals`.
export const USDT_DECIMALS = Number(import.meta.env.VITE_USDT_DECIMALS || 6)

export { multisenderAbi }
