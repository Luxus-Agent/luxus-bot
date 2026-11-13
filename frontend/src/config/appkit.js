// Reown AppKit (WalletConnect) setup.
//
// Importing this module initializes AppKit as a side effect: it registers the
// <appkit-button> / <appkit-account-button> web components and the connect
// modal, and builds the wagmi config the rest of the app consumes.
//
// The project ID comes from VITE_REOWN_PROJECT_ID (see .env.example). Get one
// free at https://cloud.reown.com — wallet connect stays inert until it's set.
import { createAppKit } from '@reown/appkit/react'
import { WagmiAdapter } from '@reown/appkit-adapter-wagmi'
import { activeChain } from './chain'

export const projectId = import.meta.env.VITE_REOWN_PROJECT_ID || ''

if (!projectId) {
  console.warn(
    '[AppKit] VITE_REOWN_PROJECT_ID is not set — wallet connect is disabled until you add it to .env',
  )
}

// BNB Smart Chain mainnet by default; VITE_CHAIN=testnet switches to testnet
// (see ./chain.js).
export const networks = [activeChain]

export const wagmiAdapter = new WagmiAdapter({
  networks,
  projectId,
  ssr: false,
})

export const wagmiConfig = wagmiAdapter.wagmiConfig

const metadata = {
  name: 'Luxus',
  description: 'Luxus — AI agent revenue sharing platform',
  url: typeof window !== 'undefined' ? window.location.origin : 'https://luxus.app',
  icons: ['https://avatars.githubusercontent.com/u/179229932'],
}

// Always initialize AppKit so the React hooks (useAppKit, useAppKitAccount…)
// have their context, even before a project ID is set. Without a valid ID the
// modal just can't open a WalletConnect session — it won't crash the app.
export const appKit = createAppKit({
  adapters: [wagmiAdapter],
  networks,
  projectId,
  metadata,
  features: {
    analytics: false,
    email: false,
    socials: false,
  },
  themeMode: 'dark',
  themeVariables: {
    '--w3m-accent': 'var(--accent)',
    '--w3m-border-radius-master': '2px',
  },
  includeWalletIds: [
    "c57ca95b47569778a828d19178114f4db188b89b763c899ba0be274e97267d96",

    "20459438007b75f4f4acb98bf29aa3b800550309646d375da5fd4aac6c2a2c66",
    "8a0ee50d1f22f6651afcae7eb4253e52a3310b90af5daef78a8c4929a9bb99d4"
  ]
})
