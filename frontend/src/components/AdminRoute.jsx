import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Only for the admin user. Non-admin users are sent to login, not the user dashboard.
export default function AdminRoute({ children }) {
  const { user, isAdmin } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (!isAdmin) return <Navigate to="/login" replace />
  return children
}
