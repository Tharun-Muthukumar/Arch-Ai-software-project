import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Eye,
  Laptop,
  LayoutTemplate,
  LoaderCircle,
  Monitor,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  Smartphone,
  Sparkles,
  Tablet,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { StatePanel } from '../components/workspace/StatePanel'
import { useToast } from '../components/ui/ToastProvider'
import { useWorkspaceEditing } from '../hooks/useWorkspaceEditing'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { applyProjectAction } from '../lib/api'
import { syncWorkspaceResult, WORKSPACE_WRITE_KEY } from '../lib/workspaceSync'
import { cn, getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type { PrototypeActionSpec, PrototypeComponent, PrototypeScreen } from '../types/api'

type Device = 'desktop' | 'tablet' | 'mobile'
type StudioMode = 'preview' | 'edit'

function emitSelection(screen: PrototypeScreen | null) {
  window.dispatchEvent(new CustomEvent('archai:assistant-selection', {
    detail: screen ? {
      object_type: 'prototype_screen',
      object_id: screen.id,
      name: screen.name,
    } : null,
  }))
}

export function PrototypePage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const [device, setDevice] = useState<Device>('desktop')
  const [mode, setMode] = useState<StudioMode>('preview')
  const [screenId, setScreenId] = useState('')
  const [roleId, setRoleId] = useState('all')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [editingName, setEditingName] = useState(false)
  const [screenName, setScreenName] = useState('')
  const [removePending, setRemovePending] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [newScreenName, setNewScreenName] = useState('')
  const [newScreenMode, setNewScreenMode] = useState<'visual' | 'functional'>('visual')
  const editing = useWorkspaceEditing(workspace!)

  const availableScreens = useMemo(() => {
    const screens = workspace?.prototype.screens ?? []
    if (roleId === 'all') return screens
    return screens.filter((screen) => screen.actor_ids.length === 0 || screen.actor_ids.includes(roleId))
  }, [roleId, workspace?.prototype.screens])

  const selectedScreen = availableScreens.find((screen) => screen.id === screenId)
    ?? availableScreens.find((screen) => screen.id === workspace?.prototype.start_screen_id)
    ?? availableScreens[0]

  useEffect(() => {
    if (workspace?.prototype.start_screen_id) setScreenId(workspace.prototype.start_screen_id)
  }, [workspace?.id, workspace?.prototype.start_screen_id])

  useEffect(() => {
    emitSelection(selectedScreen ?? null)
    setFeedback(null)
    setRemovePending(false)
    setEditingName(false)
    setScreenName(selectedScreen?.name ?? '')
    return () => emitSelection(null)
  }, [selectedScreen?.id])

  const regenerate = useMutation({
    mutationKey: [...WORKSPACE_WRITE_KEY, 'prototype-regenerate'],
    mutationFn: () => applyProjectAction(
      workspace!.id,
      { action: 'regenerate_affected', rationale: 'User requested prototype synchronization.' },
      workspace!.updated_at,
    ),
    onSuccess: (result) => {
      syncWorkspaceResult(queryClient, result.workspace)
      showToast({ title: 'Prototype synchronized', description: 'Screens now reflect the canonical requirements.' })
    },
    onError: (error) => showToast({ title: 'Regeneration failed', description: getErrorMessage(error), tone: 'danger' }),
  })

  if (workspaceQuery.isLoading) return <StatePanel badge="Loading" title="Preparing Prototype Studio" description="Building safe, traceable screens from the canonical project model." />
  if (workspaceQuery.isError) return <StatePanel badge="Backend issue" title="Could not load the prototype" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  if (!workspace) return <StatePanel badge="No workspace" title="No prototype available" description="Create a project before opening Prototype Studio." actionLabel="Open overview" actionTo="/dashboard" />
  if (!selectedScreen) return <StatePanel badge="Incomplete prototype" title="No screen can be displayed" description="Regenerate the prototype from the current requirement model." actionLabel="Regenerate" onAction={() => regenerate.mutate()} />

  function navigateToScreen(id: string) {
    if (availableScreens.some((screen) => screen.id === id)) setScreenId(id)
  }

  function runAction(action: PrototypeActionSpec) {
    if (action.action_type === 'navigate' && action.target_screen_id) {
      navigateToScreen(action.target_screen_id)
      return
    }
    setFeedback(action.feedback ?? `${action.label} was simulated in this design prototype.`)
  }

  function saveScreenName() {
    const name = screenName.trim()
    if (!name || name === selectedScreen.name) {
      setEditingName(false)
      return
    }
    editing.apply.mutate({
      target_type: 'prototype_screen',
      operation: 'update',
      target_id: selectedScreen.id,
      value: {
        ...selectedScreen,
        name,
        visual_overrides: { ...selectedScreen.visual_overrides, name },
      },
    }, { onSuccess: () => setEditingName(false) })
  }

  function removeScreen() {
    editing.apply.mutate({
      target_type: 'prototype_screen',
      operation: 'delete',
      target_id: selectedScreen.id,
    }, { onSuccess: () => setRemovePending(false) })
  }

  function moveScreen(destinationIndex: number) {
    editing.apply.mutate({
      target_type: 'prototype_screen',
      operation: 'reorder',
      target_id: selectedScreen.id,
      destination_index: destinationIndex,
    })
  }

  function updateTheme(value: Record<string, string>) {
    editing.apply.mutate({
      target_type: 'prototype_theme',
      operation: 'update',
      target_id: 'theme',
      value,
    })
  }

  function addScreen() {
    const name = newScreenName.trim()
    if (!name) return
    if (newScreenMode === 'functional') {
      const params = new URLSearchParams(searchParams)
      params.set('chat', 'open')
      params.set('message', `Add a prototype screen for ${name}`)
      navigate(`/prototype?${params.toString()}`)
      setAddOpen(false)
      setNewScreenName('')
      return
    }
    const id = `PROTO-SCREEN-CUSTOM-${crypto.randomUUID().slice(0, 8).toUpperCase()}`
    editing.apply.mutate({
      target_type: 'prototype_screen',
      operation: 'add',
      value: {
        id,
        name,
        route: `/${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`,
        purpose: 'Prototype-only visual exploration; no product behavior is implied.',
        layout: 'workflow',
        actor_ids: [],
        components: [{
          id: `PROTO-COMP-${crypto.randomUUID().slice(0, 8).toUpperCase()}`,
          component_type: 'details',
          title: name,
          description: 'Prototype-only content. Add a requirement before treating this as product behavior.',
          fields: [], items: [], actions: [], source_requirement_ids: [], source_entity_ids: [],
        }],
        states: ['Loading', 'Empty', 'Error'],
        source_requirement_ids: [], source_actor_ids: [], source_entity_ids: [],
        visual_overrides: { custom: 'true' },
      },
    }, {
      onSuccess: () => {
        setAddOpen(false)
        setNewScreenName('')
        setScreenId(id)
      },
    })
  }

  return (
    <div className="workspace-page prototype-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Product experience</span>
          <h2>Prototype Studio</h2>
          <p>Explore a functional, actor-aware product concept generated from validated requirements.</p>
        </div>
        <div className="page-actions">
          <div className="segmented-control" aria-label="Prototype device">
            {([
              ['desktop', Monitor], ['tablet', Tablet], ['mobile', Smartphone],
            ] as const).map(([value, Icon]) => (
              <button key={value} type="button" className={device === value ? 'is-active' : ''} onClick={() => setDevice(value)} title={`${value} viewport`}>
                <Icon className="h-4 w-4" /><span className="hidden sm:inline">{value}</span>
              </button>
            ))}
          </div>
          <div className="segmented-control" aria-label="Prototype mode">
            <button type="button" className={mode === 'preview' ? 'is-active' : ''} onClick={() => setMode('preview')}><Eye className="h-4 w-4" />Preview</button>
            <button type="button" className={mode === 'edit' ? 'is-active' : ''} onClick={() => setMode('edit')}><Pencil className="h-4 w-4" />Edit</button>
          </div>
          <button type="button" className="button-secondary" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
            {regenerate.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Regenerate affected
          </button>
        </div>
      </header>

      <div className="prototype-studio">
        <aside className="prototype-screen-rail">
          <div className="prototype-pane-heading">
            <div><span className="eyebrow">Navigation</span><h3>Screens</h3></div>
            <button className="icon-button" type="button" title="Add prototype screen" aria-label="Add prototype screen" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /></button>
          </div>
          {workspace.prototype.roles.length ? (
            <label className="block border-b px-3 py-3" style={{ borderColor: 'var(--border-subtle)' }}>
              <span className="field-label mb-1.5">View as</span>
              <select className="input-shell py-2" value={roleId} onChange={(event) => setRoleId(event.target.value)}>
                <option value="all">All validated actors</option>
                {workspace.prototype.roles.map((role) => <option key={role.actor_id} value={role.actor_id}>{role.name}</option>)}
              </select>
            </label>
          ) : null}
          <div className="prototype-screen-list">
            {availableScreens.map((screen, index) => (
              <button key={screen.id} type="button" className={cn('prototype-screen-item', selectedScreen.id === screen.id && 'is-active')} onClick={() => setScreenId(screen.id)}>
                <span className="prototype-screen-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="min-w-0 flex-1"><strong>{screen.name}</strong><small>{screen.layout}</small></span>
                <ChevronRight className="h-4 w-4" />
              </button>
            ))}
          </div>
          {workspace.prototype.warnings.length ? (
            <div className="prototype-warning"><CircleAlert className="h-4 w-4" /><span>{workspace.prototype.warnings[0]}</span></div>
          ) : null}
        </aside>

        <main className="prototype-canvas-stage">
          <div className="prototype-device-label"><Laptop className="h-3.5 w-3.5" />{device} · {workspace.prototype.theme.pattern}</div>
          <div className={cn('prototype-device', `is-${device}`, `is-${workspace.prototype.theme.density}`, `accent-${workspace.prototype.theme.accent}`, workspace.prototype.theme.accessible && 'is-accessible')}>
            <div className="prototype-app-bar">
              <div className="prototype-product-mark"><LayoutTemplate className="h-4 w-4" /></div>
              <strong>{workspace.title}</strong>
              {workspace.prototype.theme.realtime ? <span className="prototype-live"><span />Live</span> : null}
              {roleId !== 'all' ? <span className="prototype-role-label">{workspace.prototype.roles.find((role) => role.actor_id === roleId)?.name}</span> : null}
            </div>
            <div className="prototype-app-body">
              {device !== 'mobile' ? (
                <nav className="prototype-app-nav" aria-label="Prototype navigation">
                  {availableScreens.map((screen) => <button key={screen.id} type="button" className={selectedScreen.id === screen.id ? 'is-active' : ''} onClick={() => setScreenId(screen.id)}>{screen.name}</button>)}
                </nav>
              ) : null}
              <section className="prototype-screen-content">
                <div className="prototype-screen-title"><div><span>{selectedScreen.route}</span><h3>{selectedScreen.name}</h3><p>{selectedScreen.purpose}</p></div>{workspace.prototype.theme.offline ? <span className="prototype-offline">Sync ready</span> : null}</div>
                {feedback ? <div className="prototype-feedback"><CheckCircle2 className="h-4 w-4" /><span>{feedback}</span><button type="button" onClick={() => setFeedback(null)} aria-label="Dismiss prototype feedback"><X className="h-3.5 w-3.5" /></button></div> : null}
                <div className="prototype-components">
                  {selectedScreen.components.map((component) => <PrototypeComponentView key={component.id} component={component} onAction={runAction} />)}
                </div>
                {device === 'mobile' ? <nav className="prototype-mobile-nav">{availableScreens.slice(0, 4).map((screen) => <button key={screen.id} type="button" className={selectedScreen.id === screen.id ? 'is-active' : ''} onClick={() => setScreenId(screen.id)}>{screen.name}</button>)}</nav> : null}
              </section>
            </div>
          </div>
        </main>

        <aside className="prototype-inspector">
          <div className="prototype-pane-heading"><div><span className="eyebrow">Inspector</span><h3>Screen details</h3></div><Sparkles className="h-4 w-4 text-amber-300" /></div>
          <section className="prototype-inspector-section">
            <span className="eyebrow">Selected screen</span>
            {editingName ? <div className="mt-2 flex gap-2"><input className="input-shell py-2" value={screenName} maxLength={100} onChange={(event) => setScreenName(event.target.value)} /><button className="button-brand px-3" type="button" onClick={saveScreenName}>Save</button></div> : <div className="mt-2 flex items-center justify-between gap-2"><h3 className="font-semibold">{selectedScreen.name}</h3>{mode === 'edit' ? <button className="icon-button" type="button" onClick={() => setEditingName(true)} title="Rename screen"><Pencil className="h-3.5 w-3.5" /></button> : null}</div>}
            <p className="mt-2 text-xs leading-5 text-muted">{selectedScreen.purpose}</p>
            {mode === 'edit' ? <div className="mt-3 flex gap-2"><button type="button" className="button-secondary flex-1 px-2" title="Move screen up" disabled={workspace.prototype.screens.findIndex((item) => item.id === selectedScreen.id) <= 0 || editing.apply.isPending} onClick={() => moveScreen(workspace.prototype.screens.findIndex((item) => item.id === selectedScreen.id) - 1)}><ArrowUp className="h-3.5 w-3.5" />Move up</button><button type="button" className="button-secondary flex-1 px-2" title="Move screen down" disabled={workspace.prototype.screens.findIndex((item) => item.id === selectedScreen.id) >= workspace.prototype.screens.length - 1 || editing.apply.isPending} onClick={() => moveScreen(workspace.prototype.screens.findIndex((item) => item.id === selectedScreen.id) + 1)}><ArrowDown className="h-3.5 w-3.5" />Move down</button></div> : null}
          </section>
          <section className="prototype-inspector-section">
            <span className="eyebrow">Why this screen exists</span>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedScreen.source_requirement_ids.length ? selectedScreen.source_requirement_ids.map((id) => <span key={id} className="tag-chip">{id}</span>) : <span className="status-chip status-warning">Prototype only</span>}
            </div>
            {selectedScreen.source_requirement_ids.map((id) => {
              const index = Number(id.split('-')[1]) - 1
              const requirement = id.startsWith('NFR-') ? workspace.requirements.non_functional_requirements[index] : workspace.requirements.functional_requirements[index]
              return requirement ? <p key={id} className="prototype-trace-line"><strong>{id}</strong>{requirement}</p> : null
            })}
          </section>
          <section className="prototype-inspector-section">
            <span className="eyebrow">Supported states</span>
            <div className="mt-2 flex flex-wrap gap-1.5">{selectedScreen.states.map((state) => <span key={state} className="tag-chip">{state}</span>)}</div>
          </section>
          {mode === 'edit' ? <section className="prototype-inspector-section"><span className="eyebrow">Display style</span><label className="mt-3 block"><span className="field-label">Accent</span><select className="input-shell mt-1.5 py-2" value={workspace.prototype.theme.accent} onChange={(event) => updateTheme({ accent: event.target.value })}>{['cyan', 'emerald', 'amber', 'blue', 'rose'].map((accent) => <option key={accent} value={accent}>{accent}</option>)}</select></label><label className="mt-3 block"><span className="field-label">Density</span><select className="input-shell mt-1.5 py-2" value={workspace.prototype.theme.density} onChange={(event) => updateTheme({ density: event.target.value })}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label><p className="field-help">Visual only. Requirements and architecture stay unchanged.</p></section> : null}
          <button type="button" className="button-secondary w-full" onClick={() => {
            const params = new URLSearchParams(searchParams); params.set('chat', 'open'); params.set('message', 'Why does this screen exist?'); navigate(`/prototype?${params.toString()}`)
          }}><Sparkles className="h-4 w-4" />Ask AI about this</button>
          {mode === 'edit' && workspace.prototype.screens.length > 1 ? (
            removePending ? <div className="prototype-remove-confirm"><p>Remove this prototype screen only? Canonical requirements remain unchanged.</p><div><button className="button-secondary" type="button" onClick={() => setRemovePending(false)}>Cancel</button><button className="button-danger" type="button" onClick={removeScreen} disabled={editing.apply.isPending}><Trash2 className="h-4 w-4" />Remove</button></div></div>
              : <button type="button" className="button-danger w-full" onClick={() => setRemovePending(true)}><Trash2 className="h-4 w-4" />Remove screen</button>
          ) : null}
        </aside>
      </div>

      {addOpen ? <div className="modal-backdrop"><section className="modal-panel max-w-lg p-5" role="dialog" aria-modal="true" aria-labelledby="add-screen-title"><div className="flex items-start justify-between gap-3"><div><span className="eyebrow">Prototype Studio</span><h3 id="add-screen-title" className="mt-1 text-lg font-semibold">Add a screen</h3></div><button className="icon-button" type="button" onClick={() => setAddOpen(false)} aria-label="Close"><X className="h-4 w-4" /></button></div><label className="mt-5 block"><span className="field-label">Screen name</span><input className="input-shell mt-2" value={newScreenName} maxLength={100} placeholder="Booking history" onChange={(event) => setNewScreenName(event.target.value)} /></label><div className="mt-4 grid gap-2 sm:grid-cols-2"><button type="button" className={cn('prototype-change-kind', newScreenMode === 'visual' && 'is-active')} onClick={() => setNewScreenMode('visual')}><Eye className="h-4 w-4" /><strong>Prototype only</strong><span>Visual exploration. Requirements stay unchanged.</span></button><button type="button" className={cn('prototype-change-kind', newScreenMode === 'functional' && 'is-active')} onClick={() => setNewScreenMode('functional')}><Sparkles className="h-4 w-4" /><strong>Product behavior</strong><span>Open a reviewable FR plus prototype proposal.</span></button></div><div className="mt-5 flex justify-end gap-2"><button className="button-secondary" type="button" onClick={() => setAddOpen(false)}>Cancel</button><button className="button-brand" type="button" onClick={addScreen} disabled={!newScreenName.trim() || editing.apply.isPending}>{newScreenMode === 'functional' ? <Sparkles className="h-4 w-4" /> : <Plus className="h-4 w-4" />}Continue</button></div></section></div> : null}
    </div>
  )
}

function PrototypeComponentView({ component, onAction }: { component: PrototypeComponent; onAction: (action: PrototypeActionSpec) => void }) {
  const [query, setQuery] = useState('')
  const [formValues, setFormValues] = useState<Record<string, string>>({})
  const normalizedQuery = query.trim().toLowerCase()
  const visibleItems = component.items.filter((item) => item.toLowerCase().includes(normalizedQuery))
  return (
    <article className={cn('prototype-component', `type-${component.component_type}`)}>
      <div className="prototype-component-heading"><div><span className="eyebrow">{component.component_type}</span><h4>{component.title}</h4></div><span className="prototype-trace-count">{component.source_requirement_ids.length} traced</span></div>
      {component.description ? <p className="prototype-component-copy">{component.description}</p> : null}
      {component.component_type === 'search' || component.component_type === 'filter' ? <label className="prototype-search"><Search className="h-4 w-4" /><input value={query} placeholder={`Search ${component.title.toLowerCase()}`} onChange={(event) => setQuery(event.target.value)} /></label> : null}
      {component.fields.length ? <div className="prototype-form-grid">{component.fields.map((field) => <label key={field}><span>{field}</span><input value={formValues[field] ?? ''} placeholder={`Enter ${field.toLowerCase()}`} onChange={(event) => setFormValues((current) => ({ ...current, [field]: event.target.value }))} /></label>)}</div> : null}
      {visibleItems.length ? <div className={component.component_type === 'table' ? 'prototype-table' : 'prototype-item-grid'}>{visibleItems.map((item, index) => <div key={`${item}-${index}`} className="prototype-data-item"><span>{String(index + 1).padStart(2, '0')}</span><p>{item}</p>{component.component_type === 'status' ? <i>Current</i> : null}</div>)}</div> : null}
      {component.actions.length ? <div className="prototype-actions">{component.actions.map((action) => <button type="button" key={action.id} className={action.action_type === 'navigate' ? 'prototype-action-secondary' : 'prototype-action-primary'} onClick={() => onAction(action)}>{action.label}{action.action_type === 'navigate' ? <ChevronRight className="h-4 w-4" /> : <Send className="h-3.5 w-3.5" />}</button>)}</div> : null}
    </article>
  )
}
