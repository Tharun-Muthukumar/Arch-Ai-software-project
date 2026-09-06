import {
  BarChart3,
  ClipboardList,
  FileText,
  Home,
  Image,
  LayoutDashboard,
  Network,
  Settings,
  Users,
  Building2,
  DollarSign,
  Zap,
  GitBranch,
  History,
  LogOut,
  CircleUserRound,
} from 'lucide-react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { getErrorMessage } from '../../lib/utils'
import { cn } from '../../lib/utils'

const navItems = [
  { to: '/', label: 'Overview', icon: Home },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/wizard', label: 'Requirements', icon: ClipboardList },
  { to: '/architecture', label: 'Architecture', icon: Network },
  { to: '/causal-graph', label: 'Causal Graph', icon: GitBranch },
  { to: '/comparison', label: 'Comparison', icon: BarChart3 },
  { to: '/blast-radius', label: 'Blast Radius', icon: Zap },
  { to: '/team-fit', label: 'Team Fit', icon: Users },
  { to: '/industry-twins', label: 'Industry Twins', icon: Building2 },
  { to: '/budget', label: 'Budget', icon: DollarSign },
  { to: '/diagrams', label: 'Diagrams', icon: Image },
  { to: '/docs', label: 'Report', icon: FileText },
  { to: '/history', label: 'History', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function NavigationLink({ item, compact = false }: { item: (typeof navItems)[number]; compact?: boolean }) {
  const location = useLocation()
  const isActive = item.to === '/' ? location.pathname === '/' : location.pathname === item.to
  const Icon = item.icon
  return <NavLink key={item.to} to={item.to} end={item.to === '/'} role="tab" aria-selected={isActive} className={cn(
    'flex items-center rounded-lg border-b-2 border-transparent transition',
    compact ? 'gap-1.5 whitespace-nowrap px-3 py-1.5 text-xs' : 'gap-2.5 px-3 py-2 text-sm',
    isActive
      ? 'border-amber-400 bg-amber-500/15 font-bold text-amber-300 shadow-sm'
      : 'font-medium text-slate-400 hover:bg-white/5 hover:text-slate-200',
  )}>
    <Icon className={compact ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
    {item.label}
  </NavLink>
}

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  async function handleLogout() {
    if (isLoggingOut) return
    setLogoutError(null)
    setIsLoggingOut(true)
    try {
      await logout()
      navigate('/sign-in', { replace: true })
    } catch (error) {
      setLogoutError(getErrorMessage(error, 'Logout failed. Please try again.'))
    } finally {
      setIsLoggingOut(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r p-4 lg:flex" style={{ borderColor: 'var(--card-border)', background: 'var(--surface)' }}>
        <div className="mb-6">
          <h1 className="text-lg font-bold" style={{ color: 'var(--brand)' }}>ArchAI</h1>
        </div>

        <nav className="space-y-1" role="tablist" aria-label="ArchAI sections">
          {navItems.map((item) => <NavigationLink key={item.to} item={item} />)}
        </nav>

        <div className="mt-auto border-t pt-4" style={{ borderColor: 'var(--card-border)' }}>
          <NavLink to="/profile" className="flex min-w-0 items-center gap-2 rounded-md px-2 py-2 hover:bg-white/5">
            <CircleUserRound className="h-5 w-5 shrink-0 text-amber-400" />
            <div className="min-w-0"><p className="truncate text-sm font-medium">{user?.username}</p><p className="truncate text-xs text-muted">Profile</p></div>
          </NavLink>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-4 py-3 sm:px-6" style={{ borderColor: 'var(--card-border)', background: 'var(--surface)' }}>
          <div className="lg:hidden">
            <h1 className="text-lg font-bold" style={{ color: 'var(--brand)' }}>ArchAI</h1>
          </div>
          <div className="hidden lg:block">
            <h2 className="text-base font-semibold">Design room</h2>
          </div>
          <div className="flex items-center gap-2">
            <NavLink to="/profile" className="button-secondary gap-2 px-3 py-2">
              <CircleUserRound className="h-4 w-4" />
              <span className="hidden sm:inline">{user?.username}</span>
            </NavLink>
            <button
              type="button"
              className="button-secondary px-3 py-2"
              onClick={() => void handleLogout()}
              disabled={isLoggingOut}
              title="Log out"
              aria-label="Log out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        {logoutError ? (
          <div className="border-b border-red-800 bg-red-950/50 px-6 py-2 text-sm text-red-300" role="alert">
            {logoutError}
          </div>
        ) : null}

        <div className="flex lg:hidden">
          <nav className="flex gap-1 overflow-x-auto px-4 py-2" role="tablist" aria-label="ArchAI sections">
            {navItems.map((item) => <NavigationLink key={item.to} item={item} compact />)}
          </nav>
        </div>

        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
