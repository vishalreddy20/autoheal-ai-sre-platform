import { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

interface Props {
  children: ReactNode
  /** If provided, only users with this role may access the route. */
  requiredRole?: 'viewer' | 'operator'
}

export function ProtectedRoute({ children, requiredRole }: Props) {
  const { isAuthenticated, user } = useAuthStore()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (requiredRole && user?.role !== requiredRole) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        gap: '1rem',
        color: 'rgba(255,255,255,0.6)',
        fontFamily: "'Inter', sans-serif",
      }}>
        <div style={{ fontSize: '2.5rem' }}>🔒</div>
        <h2 style={{ color: '#fff', margin: 0, fontWeight: 600 }}>Access Restricted</h2>
        <p style={{ margin: 0, fontSize: '0.9rem' }}>
          This page requires the <strong style={{ color: '#00D4AA' }}>{requiredRole}</strong> role.
          You are signed in as <strong style={{ color: '#6366f1' }}>{user?.role}</strong>.
        </p>
      </div>
    )
  }

  return <>{children}</>
}
