import { LoaderCircle } from 'lucide-react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/auth'

export function ProtectedRoute() {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <LoaderCircle className="h-6 w-6 animate-spin" aria-hidden="true" />
        <span className="ml-3 text-sm text-muted">Checking your session...</span>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname + location.search }} />
  }

  return <Outlet />
}
