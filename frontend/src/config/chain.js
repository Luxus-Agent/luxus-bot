// Single source of truth for which BNB Smart Chain network the app talks to.
//
// Defaults to BSC MAINNET (chain 56). Set VITE_CHAIN=testnet in frontend/.env
// to point a dev build at BSC testnet (chain 97) instead. Must agree with the
// backend's BSC_RPC_URL / USDT_CONTRACT / USDT_DECIMALS.
import { bsc, bscTestnet } from '@reown/appkit/networks'

export const IS_TESTNET = import.meta.env.VITE_CHAIN === 'testnet'
export const activeChain = IS_TESTNET ? bscTestnet : bsc
export const EXPLORER_BASE = IS_TESTNET ? 'https://testnet.bscscan.com' : 'https://bscscan.com'
export const CHAIN_LABEL = IS_TESTNET ? 'BNB Smart Chain Testnet' : 'BNB Smart Chain'
