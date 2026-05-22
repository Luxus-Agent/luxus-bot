import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Allows any authenticated user (including admin) through.
// AdminRoute is used separately to restrict /admin/* to admins only.
export default function ProtectedRoute({ children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return children
}
