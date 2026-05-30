import { createContext, useContext, useState } from 'react'
import api from '../api/client'

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
  }

  const isAdmin = user?.is_admin === true

  return (
    <AuthContext.Provider value={{ user, setUser, login, logout, isAdmin }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
