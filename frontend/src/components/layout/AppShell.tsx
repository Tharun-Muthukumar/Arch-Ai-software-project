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
} from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
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
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-r p-4 lg:block" style={{ borderColor: 'var(--card-border)', background: 'var(--surface)' }}>
        <div className="mb-6">
          <h1 className="text-lg font-bold" style={{ color: 'var(--brand)' }}>ArchAI</h1>
        </div>

        <nav className="space-y-1" role="tablist" aria-label="ArchAI sections">
          {navItems.map((item) => <NavigationLink key={item.to} item={item} />)}
        </nav>

        <div className="mt-auto pt-6 text-xs" style={{ color: 'var(--text-muted)' }}>
          Local development mode
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center border-b px-6 py-3" style={{ borderColor: 'var(--card-border)', background: 'var(--surface)' }}>
          <div className="lg:hidden">
            <h1 className="text-lg font-bold" style={{ color: 'var(--brand)' }}>ArchAI</h1>
          </div>
          <div className="hidden lg:block">
            <h2 className="text-base font-semibold">Design room</h2>
          </div>
        </header>

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
