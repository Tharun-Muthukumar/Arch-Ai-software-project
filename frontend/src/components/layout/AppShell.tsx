import {
  BarChart3,
  BookOpenText,
  Boxes,
  ChevronDown,
  ChevronLeft,
  CircleUserRound,
  ClipboardList,
  CloudCog,
  GitBranch,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Redo2,
  ShieldAlert,
  Settings,
  Sparkles,
  Undo2,
  Users,
  X,
  Zap,
} from 'lucide-react'
import { useEffect, useState, type FocusEvent, type MouseEvent } from 'react'
import { useIsMutating } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/auth'
import { ArchitectureChatPanel } from '../workspace/ArchitectureChatPanel'
import { useWorkspaceEditing } from '../../hooks/useWorkspaceEditing'
import { useWorkspacesQuery } from '../../hooks/useWorkspaces'
import { WORKSPACE_WRITE_KEY } from '../../lib/workspaceSync'
import { cn, formatUpdatedAt, getActiveWorkspace, getErrorMessage } from '../../lib/utils'
import type { Workspace } from '../../types/api'

const navGroups = [
  {
    label: 'Workspace',
    items: [
      { to: '/dashboard', label: 'Overview', icon: LayoutDashboard },
      { to: '/wizard', label: 'Requirements', icon: ClipboardList },
      { to: '/architecture', label: 'Architecture', icon: Network },
      { to: '/interfaces', label: 'Interfaces & data', icon: Boxes },
      { to: '/causal-graph', label: 'Causal graph', icon: GitBranch },
      { to: '/diagrams', label: 'Diagrams', icon: BookOpenText },
    ],
  },
  {
    label: 'Evaluate',
    items: [
      { to: '/comparison', label: 'Comparison', icon: BarChart3 },
      { to: '/risk-detector', label: 'Risk Detector', icon: ShieldAlert },
      { to: '/blast-radius', label: 'Blast radius', icon: Zap },
      { to: '/team-fit', label: 'Team fit', icon: Users },
      { to: '/industry-twins', label: 'Industry precedents', icon: CloudCog },
    ],
  },
  {
    label: 'Library',
    items: [
      { to: '/docs', label: 'Report', icon: BookOpenText },
      { to: '/history', label: 'History', icon: History },
      { to: '/settings', label: 'Settings', icon: Settings },
    ],
  },
]

const allNavItems = navGroups.flatMap((group) => group.items)

function Navigation({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const workspaceId = searchParams.get('workspace')
  const [hovered, setHovered] = useState<{ label: string; top: number } | null>(null)

  function showTooltip(event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>, label: string) {
    if (!compact) return
    const rect = event.currentTarget.getBoundingClientRect()
    setHovered({ label, top: rect.top + rect.height / 2 })
  }

  function hideTooltip() {
    setHovered(null)
  }

  return (
    <nav className="space-y-5" aria-label="Primary navigation">
      {navGroups.map((group) => (
        <div key={group.label}>
          {!compact ? <div className="nav-group-label">{group.label}</div> : null}
          <div className="space-y-1">
            {group.items.map((item) => {
              const Icon = item.icon
              const active = location.pathname === item.to || (item.to === '/dashboard' && location.pathname === '/')
              const to = workspaceId && !['/history', '/settings'].includes(item.to)
                ? `${item.to}?workspace=${encodeURIComponent(workspaceId)}`
                : item.to
              return (
                <NavLink
                  key={item.to}
                  to={to}
                  aria-label={item.label}
                  aria-current={active ? 'page' : undefined}
                  className={cn('nav-link', active && 'is-active', compact && 'is-compact')}
                  onClick={onNavigate}
                  onMouseEnter={(event) => showTooltip(event, item.label)}
                  onMouseLeave={hideTooltip}
                  onFocus={(event) => showTooltip(event, item.label)}
                  onBlur={hideTooltip}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  {!compact ? <span>{item.label}</span> : null}
                </NavLink>
              )
            })}
          </div>
        </div>
      ))}
      {compact && hovered ? (
        <div className="nav-instant-tooltip" style={{ top: hovered.top, transform: 'translateY(-50%)' }} role="tooltip">
          {hovered.label}
        </div>
      ) : null}
    </nav>
  )
}

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const workspaces = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaces.data, searchParams.get('workspace'))
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [assistantOpen, setAssistantOpen] = useState(
    searchParams.get('chat') === 'open' || Boolean(searchParams.get('message')),
  )
  const pageTitle = allNavItems.find((item) => item.to === location.pathname)?.label ?? 'Overview'
  const requestedArchitecture = searchParams.get('architecture')
  const assistantArchitecture = workspace?.architectures.find(
    (item) => item.id === requestedArchitecture,
  ) ?? workspace?.architectures.find(
    (item) => item.id === workspace.recommendation.recommended_architecture_id,
  ) ?? workspace?.architectures[0]

  useEffect(() => {
    if (searchParams.get('chat') === 'open' || searchParams.get('message')) {
      setAssistantOpen(true)
    }
  }, [searchParams])

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

  function selectWorkspace(workspaceId: string) {
    const next = new URLSearchParams(searchParams)
    next.set('workspace', workspaceId)
    navigate(`${location.pathname}?${next.toString()}`)
  }

  function closeAssistant() {
    setAssistantOpen(false)
    const next = new URLSearchParams(searchParams)
    next.delete('chat')
    next.delete('message')
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="app-frame">
      <aside className={cn('desktop-sidebar', sidebarCollapsed && 'is-collapsed')}>
        <div className="brand-lockup">
          <div className="brand-mark"><Sparkles className="h-4 w-4" /></div>
          {!sidebarCollapsed ? <div><strong>ArchAI</strong><span>Architecture studio</span></div> : null}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
          <Navigation compact={sidebarCollapsed} />
        </div>
        <div className="border-t p-3" style={{ borderColor: 'var(--card-border)' }}>
          <NavLink to="/profile" className={cn('profile-link', sidebarCollapsed && 'justify-center')} title={sidebarCollapsed ? 'Profile' : undefined}>
            <div className="avatar">{user?.username?.slice(0, 1).toUpperCase()}</div>
            {!sidebarCollapsed ? <div className="min-w-0"><strong>{user?.username}</strong><span>Account profile</span></div> : null}
          </NavLink>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed((current) => !current)}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            {!sidebarCollapsed ? <span>Collapse</span> : null}
          </button>
        </div>
      </aside>

      {mobileOpen ? (
        <div className="mobile-nav-backdrop" onMouseDown={() => setMobileOpen(false)}>
          <aside className="mobile-nav" onMouseDown={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b p-4" style={{ borderColor: 'var(--card-border)' }}>
              <div className="brand-lockup p-0"><div className="brand-mark"><Sparkles className="h-4 w-4" /></div><div><strong>ArchAI</strong><span>Architecture studio</span></div></div>
              <button type="button" className="icon-button" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X className="h-4 w-4" /></button>
            </div>
            <div className="overflow-y-auto p-3"><Navigation compact={false} onNavigate={() => setMobileOpen(false)} /></div>
          </aside>
        </div>
      ) : null}

      <div className="min-w-0 flex-1">
        <header className="topbar">
          <button type="button" className="icon-button lg:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu className="h-5 w-5" /></button>
          <div className="min-w-0">
            <div className="breadcrumb"><span>Design room</span><ChevronLeft className="h-3 w-3 rotate-180" /><strong>{pageTitle}</strong></div>
            <h1 className="topbar-title">{workspace?.title ?? pageTitle}</h1>
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-2">
            {workspace ? <WorkspaceRevisionControls workspace={workspace} /> : null}
            {workspace && workspaces.data && workspaces.data.length > 0 ? (
              <label className="workspace-select hidden md:flex">
                <span className="sr-only">Active workspace</span>
                <select value={workspace.id} onChange={(event) => selectWorkspace(event.target.value)}>
                  {workspaces.data.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
                </select>
                <ChevronDown className="h-3.5 w-3.5" />
              </label>
            ) : null}
            <NavLink to="/profile" className="icon-button" title="Profile" aria-label="Open profile"><CircleUserRound className="h-4 w-4" /></NavLink>
            <button type="button" className="icon-button" onClick={() => void handleLogout()} disabled={isLoggingOut} title="Log out" aria-label="Log out"><LogOut className="h-4 w-4" /></button>
          </div>
        </header>

        {logoutError ? <div className="error-strip" role="alert">{logoutError}</div> : null}
        <main className="app-main"><Outlet /></main>
      </div>

      {workspace && assistantArchitecture ? (
        <>
          {!assistantOpen ? (
            <button
              type="button"
              className="ai-assistant-fab"
              aria-label="Open AI Assistant"
              title="AI Assistant"
              onClick={() => setAssistantOpen(true)}
            >
              <Sparkles className="h-5 w-5" />
            </button>
          ) : null}
          <ArchitectureChatPanel
            key={workspace.id}
            workspace={workspace}
            architectureId={assistantArchitecture.id}
            open={assistantOpen}
            initialMessage={searchParams.get('message')}
            onClose={closeAssistant}
          />
        </>
      ) : null}
    </div>
  )
}

function WorkspaceRevisionControls({ workspace }: { workspace: Workspace }) {
  const editing = useWorkspaceEditing(workspace)
  const busy = editing.undo.isPending || editing.redo.isPending
  const syncingWrites = useIsMutating({ mutationKey: WORKSPACE_WRITE_KEY })
  return (
    <div className="revision-controls">
      {syncingWrites > 0 ? (
        <span className="save-state hidden xl:inline" role="status"><span className="save-dot" style={{ background: 'var(--warning)' }} />Syncing…</span>
      ) : (
        <span className="save-state hidden xl:inline"><span className="save-dot" />Saved {formatUpdatedAt(workspace.updated_at)}</span>
      )}
      <button type="button" className="icon-button" title="Undo last workspace change" aria-label="Undo last workspace change" disabled={!workspace.can_undo || busy} onClick={() => editing.undo.mutate()}><Undo2 className="h-4 w-4" /></button>
      <button type="button" className="icon-button" title="Redo workspace change" aria-label="Redo workspace change" disabled={!workspace.can_redo || busy} onClick={() => editing.redo.mutate()}><Redo2 className="h-4 w-4" /></button>
    </div>
  )
}
