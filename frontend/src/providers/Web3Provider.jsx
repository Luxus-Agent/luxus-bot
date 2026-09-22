// Wraps the app with the wagmi + React Query context that Reown AppKit needs.
// Importing ../config/appkit also initializes AppKit (registers web components
// and the connect modal).
import { WagmiProvider } from 'wagmi'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { wagmiConfig } from '../config/appkit'

const queryClient = new QueryClient()

export default function Web3Provider({ children }) {
  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </WagmiProvider>
  )
}
