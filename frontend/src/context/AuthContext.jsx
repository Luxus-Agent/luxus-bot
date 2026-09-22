import { createContext, useContext, useState } from 'react'
import { disconnect as disconnectWallet } from '@wagmi/core'
import api from '../api/client'
import { wagmiConfig } from '../config/appkit'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const stored = localStorage.getItem('user')
      return stored ? JSON.parse(stored) : null
    } catch {
      return null
    }
  })

  const login = async (username, password) => {
    // Step 1: get token
    const { data: tokenData } = await api.post('/auth/login', { username, password })
    localStorage.setItem('token', tokenData.access_token)

    // Step 2: fetch full profile (includes is_admin, is_active, referral_code, etc.)
    const { data: profile } = await api.get('/auth/me')
    localStorage.setItem('user', JSON.stringify(profile))
    setUser(profile)

    return profile // caller uses profile.is_admin to decide redirect
  }

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setUser(null)
    // Also drop the wallet connection. It lives in wagmi/AppKit's own
    // localStorage-backed store, independent of our auth, so without this it
    // survives logout and reappears as a "connected" wallet on the next
    // user's Login/Register page.
    disconnectWallet(wagmiConfig).catch(() => {})
  }

  const isAdmin = user?.is_admin === true

  return (
    <AuthContext.Provider value={{ user, setUser, login, logout, isAdmin }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
