import {
  Activity,
  ArrowDown,
  ArrowUp,
  BarChart3,
  BatteryCharging,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  CreditCard,
  Eye,
  FileText,
  Gauge,
  Home,
  Laptop,
  ListChecks,
  LoaderCircle,
  MapPin,
  Monitor,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Tablet,
  Trash2,
  UserRound,
  X,
  Zap,
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

      <div className={cn('prototype-studio', `mode-${mode}`)}>
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
          <div className={cn('prototype-device', `is-${device}`, `is-${workspace.prototype.theme.density}`, `accent-${workspace.prototype.theme.accent}`, isChargingPrototype(workspace.prototype.domain, workspace.title) && 'domain-charging', workspace.prototype.theme.accessible && 'is-accessible')}>
            <div className="prototype-app-bar">
              <div className="prototype-product-mark">{isChargingPrototype(workspace.prototype.domain, workspace.title) ? <BatteryCharging className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}</div>
              <div className="prototype-product-copy"><strong>{workspace.title}</strong><span>{workspace.prototype.domain}</span></div>
              {workspace.prototype.theme.realtime ? <span className="prototype-live"><span />Live</span> : null}
              {roleId !== 'all' ? <span className="prototype-role-label">{workspace.prototype.roles.find((role) => role.actor_id === roleId)?.name}</span> : null}
              {availableScreens.some((screen) => screen.layout === 'search') ? <button type="button" className="prototype-topbar-button" title="Search"><Search className="h-3.5 w-3.5" /></button> : null}
              <button type="button" className="prototype-user-button" title="Current prototype role"><UserRound className="h-3.5 w-3.5" /></button>
            </div>
            <div className="prototype-app-body">
              {device !== 'mobile' ? (
                <nav className="prototype-app-nav" aria-label="Prototype navigation">
                  <span className="prototype-nav-label">Product</span>
                  {availableScreens.map((screen) => <button key={screen.id} type="button" className={selectedScreen.id === screen.id ? 'is-active' : ''} onClick={() => setScreenId(screen.id)}><PrototypeNavIcon screen={screen} />{screen.name}</button>)}
                </nav>
              ) : null}
              <section className="prototype-screen-content">
                <div className="prototype-screen-title"><div><span>{selectedScreen.route}</span><h3>{selectedScreen.name}</h3><p>{selectedScreen.purpose}</p></div><div className="prototype-screen-badges">{workspace.prototype.theme.realtime && selectedScreen.layout === 'monitoring' ? <span className="prototype-context-badge"><Activity className="h-3 w-3" />Live data</span> : null}{workspace.prototype.theme.offline ? <span className="prototype-offline">Sync ready</span> : null}</div></div>
                {feedback ? <div className="prototype-feedback"><CheckCircle2 className="h-4 w-4" /><span>{feedback}</span><button type="button" onClick={() => setFeedback(null)} aria-label="Dismiss prototype feedback"><X className="h-3.5 w-3.5" /></button></div> : null}
                <div className="prototype-components">
                  {selectedScreen.components.map((component) => <PrototypeComponentView key={component.id} component={component} screen={selectedScreen} pattern={workspace.prototype.theme.pattern} realtime={workspace.prototype.theme.realtime} isCharging={isChargingPrototype(workspace.prototype.domain, workspace.title)} onAction={runAction} />)}
                </div>
                {device === 'mobile' ? <nav className="prototype-mobile-nav">{availableScreens.slice(0, 4).map((screen) => <button key={screen.id} type="button" className={selectedScreen.id === screen.id ? 'is-active' : ''} onClick={() => setScreenId(screen.id)}><PrototypeNavIcon screen={screen} />{screen.name}</button>)}</nav> : null}
              </section>
            </div>
          </div>
          <details className="prototype-coverage">
            <summary><span><ShieldCheck className="h-3.5 w-3.5" />Requirement coverage</span><small>{selectedScreen.source_requirement_ids.length} linked</small></summary>
            <div>{selectedScreen.source_requirement_ids.map((id) => {
              const index = Number(id.split('-')[1]) - 1
              const requirement = id.startsWith('NFR-') ? workspace.requirements.non_functional_requirements[index] : workspace.requirements.functional_requirements[index]
              return requirement ? <p key={id}><strong>{id}</strong>{requirement}</p> : null
            })}</div>
          </details>
        </main>

        {mode === 'edit' ? <aside className="prototype-inspector">
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
        </aside> : null}
      </div>

      {addOpen ? <div className="modal-backdrop"><section className="modal-panel max-w-lg p-5" role="dialog" aria-modal="true" aria-labelledby="add-screen-title"><div className="flex items-start justify-between gap-3"><div><span className="eyebrow">Prototype Studio</span><h3 id="add-screen-title" className="mt-1 text-lg font-semibold">Add a screen</h3></div><button className="icon-button" type="button" onClick={() => setAddOpen(false)} aria-label="Close"><X className="h-4 w-4" /></button></div><label className="mt-5 block"><span className="field-label">Screen name</span><input className="input-shell mt-2" value={newScreenName} maxLength={100} placeholder="Booking history" onChange={(event) => setNewScreenName(event.target.value)} /></label><div className="mt-4 grid gap-2 sm:grid-cols-2"><button type="button" className={cn('prototype-change-kind', newScreenMode === 'visual' && 'is-active')} onClick={() => setNewScreenMode('visual')}><Eye className="h-4 w-4" /><strong>Prototype only</strong><span>Visual exploration. Requirements stay unchanged.</span></button><button type="button" className={cn('prototype-change-kind', newScreenMode === 'functional' && 'is-active')} onClick={() => setNewScreenMode('functional')}><Sparkles className="h-4 w-4" /><strong>Product behavior</strong><span>Open a reviewable FR plus prototype proposal.</span></button></div><div className="mt-5 flex justify-end gap-2"><button className="button-secondary" type="button" onClick={() => setAddOpen(false)}>Cancel</button><button className="button-brand" type="button" onClick={addScreen} disabled={!newScreenName.trim() || editing.apply.isPending}>{newScreenMode === 'functional' ? <Sparkles className="h-4 w-4" /> : <Plus className="h-4 w-4" />}Continue</button></div></section></div> : null}
    </div>
  )
}

function PrototypeComponentView({ component, screen, pattern, realtime, isCharging, onAction }: { component: PrototypeComponent; screen: PrototypeScreen; pattern: string; realtime: boolean; isCharging: boolean; onAction: (action: PrototypeActionSpec) => void }) {
  const [query, setQuery] = useState('')
  const [formValues, setFormValues] = useState<Record<string, string>>({})
  const normalizedQuery = query.trim().toLowerCase()
  const visibleItems = component.items.filter((item) => item.toLowerCase().includes(normalizedQuery))
  const items = visibleItems.map(cleanPrototypeCopy)
  const actions = component.actions
  const searchEvidence = `${component.title} ${component.description ?? ''} ${component.items.join(' ')}`.toLowerCase()
  const isGeospatial = isCharging || /\b(?:map|nearby|location|station|city|geospatial)\b/.test(searchEvidence)

  if (component.component_type === 'hero') {
    return (
      <>
        <section className="prototype-product-hero">
          <div className="prototype-product-hero-copy">
            <span className="prototype-product-kicker">Interactive product concept</span>
            <h4>{component.title}</h4>
            {component.description ? <p>{component.description}</p> : null}
            <div className="prototype-actions">
              {actions.slice(0, 3).map((action, index) => <PrototypeActionButton key={action.id} action={action} primary={index === 0} onAction={onAction} />)}
            </div>
          </div>
          <div className={cn('prototype-hero-visual', isCharging && 'is-charging')}>
            <div className="prototype-hero-orbit"><div>{isCharging ? <BatteryCharging className="h-8 w-8" /> : <PrototypeNavIcon screen={screen} large />}</div></div>
            <div className="prototype-hero-signal"><span>{realtime ? 'Live capability' : 'Validated scope'}</span><strong>{cleanPrototypeCopy(items[0] ?? screen.name)}</strong></div>
            {isCharging ? <><span className="prototype-pin pin-one"><MapPin className="h-3 w-3" /></span><span className="prototype-pin pin-two"><Zap className="h-3 w-3" /></span></> : null}
          </div>
        </section>
        <section className="prototype-capability-band" aria-label="Validated product capabilities">
          {items.slice(0, 4).map((item, index) => <div key={`${item}-${index}`}><span><CheckCircle2 className="h-3.5 w-3.5" /></span><p>{item}</p></div>)}
        </section>
      </>
    )
  }

  if (component.component_type === 'search' || component.component_type === 'filter') {
    return (
      <section className="prototype-product-section prototype-search-experience">
        <div className="prototype-section-heading"><div><span>Discover</span><h4>{component.title}</h4></div><small>Preview data</small></div>
        {component.description ? <p className="prototype-section-copy">{component.description}</p> : null}
        <label className="prototype-search prototype-search-prominent"><Search className="h-4 w-4" /><input value={query} placeholder={isCharging ? 'Search city or charging station' : `Search ${component.title.toLowerCase()}`} onChange={(event) => setQuery(event.target.value)} /><button type="button" title="Use current location"><MapPin className="h-3.5 w-3.5" /></button></label>
        <div className={cn('prototype-discovery-layout', !isGeospatial && 'is-list-only')}>
          {isGeospatial ? <div className="prototype-map" aria-label="Concept map preview"><span className="prototype-map-road road-one" /><span className="prototype-map-road road-two" /><span className="prototype-map-road road-three" />{[0, 1, 2].map((index) => <button key={index} type="button" className={`prototype-map-marker marker-${index + 1}`} title={isCharging ? 'Charging station preview' : 'Location result preview'}><MapPin className="h-3.5 w-3.5" /></button>)}<div className="prototype-map-key"><MapPin className="h-3 w-3" />{isCharging ? 'Station discovery area' : 'Result area'}</div></div> : null}
          <div className="prototype-result-list">
            {(items.length ? items : [screen.purpose]).slice(0, 4).map((item, index) => <article key={`${item}-${index}`}><div className="prototype-result-icon">{isCharging ? <BatteryCharging className="h-4 w-4" /> : isGeospatial ? <MapPin className="h-4 w-4" /> : <FileText className="h-4 w-4" />}</div><div><strong>{item}</strong><span>{realtime ? 'Updates are shown live' : 'Open to review details'}</span></div>{actions[index] ? <button type="button" title={actions[index].label} onClick={() => onAction(actions[index])}><ChevronRight className="h-4 w-4" /></button> : null}</article>)}
          </div>
        </div>
      </section>
    )
  }

  if (component.component_type === 'status') {
    return (
      <section className="prototype-product-section prototype-status-experience">
        <div className="prototype-section-heading"><div><span>{realtime ? 'Live now' : 'Current state'}</span><h4>{component.title}</h4></div><span className="prototype-status-pill"><span />{realtime ? 'Live updates' : 'Current state'}</span></div>
        <div className="prototype-session-panel"><div className="prototype-session-gauge">{isCharging ? <BatteryCharging className="h-8 w-8" /> : <Gauge className="h-8 w-8" />}</div><div><span>Active workflow</span><strong>{cleanPrototypeCopy(items[0] ?? screen.purpose)}</strong><p>Status changes appear here as the confirmed workflow progresses.</p></div></div>
        <div className="prototype-timeline">{screen.states.map((state, index) => <div key={state} className={index === 0 ? 'is-current' : ''}><span>{index === 0 ? <Activity className="h-3.5 w-3.5" /> : <Clock3 className="h-3.5 w-3.5" />}</span><p><strong>{state}</strong><small>{index === 0 ? 'Current preview state' : 'Supported interface state'}</small></p></div>)}</div>
        <div className="prototype-actions">{actions.map((action, index) => <PrototypeActionButton key={action.id} action={action} primary={index === 0} onAction={onAction} />)}</div>
      </section>
    )
  }

  if (component.component_type === 'metrics') {
    return (
      <section className="prototype-product-section prototype-metrics-experience">
        <div className="prototype-section-heading"><div><span>Decision view</span><h4>{component.title}</h4></div><small>Requirement-backed</small></div>
        <div className="prototype-metric-grid">{(items.length ? items : [screen.purpose]).slice(0, 6).map((item, index) => <article key={`${item}-${index}`}><span>{index % 2 === 0 ? <BarChart3 className="h-4 w-4" /> : <Activity className="h-4 w-4" />}</span><strong>{item}</strong><div className={`prototype-metric-line line-${(index % 4) + 1}`} /></article>)}</div>
        <div className="prototype-actions">{actions.map((action, index) => <PrototypeActionButton key={action.id} action={action} primary={index === 0} onAction={onAction} />)}</div>
      </section>
    )
  }

  if (component.component_type === 'table') {
    return (
      <section className="prototype-product-section prototype-records-experience">
        <div className="prototype-section-heading"><div><span>Workspace</span><h4>{component.title}</h4></div><button type="button" className="prototype-inline-filter"><Settings2 className="h-3.5 w-3.5" />Filter</button></div>
        <div className="prototype-records-table"><div className="prototype-records-head"><span>Capability</span><span>Source</span><span>Status</span><span /></div>{(items.length ? items : [screen.purpose]).map((item, index) => <div className="prototype-record-row" key={`${item}-${index}`}><strong>{item}</strong><span>{component.source_requirement_ids[index] ?? 'Validated scope'}</span><i>In scope</i>{actions[index] ? <button type="button" title={actions[index].label} onClick={() => onAction(actions[index])}><ChevronRight className="h-4 w-4" /></button> : <span />}</div>)}</div>
      </section>
    )
  }

  const fallbackFields = component.fields.length ? component.fields : defaultPrototypeFields(screen, pattern, isCharging)
  return (
    <section className="prototype-product-section prototype-workflow-experience">
      <div className="prototype-section-heading"><div><span>{component.component_type === 'form' ? 'Complete details' : 'Workflow'}</span><h4>{component.title}</h4></div><span className="prototype-secure-label">{isCharging && screen.name.toLowerCase().includes('payment') ? <ShieldCheck className="h-3.5 w-3.5" /> : <ListChecks className="h-3.5 w-3.5" />}Validated flow</span></div>
      {component.description ? <p className="prototype-section-copy">{component.description}</p> : null}
      <div className="prototype-stepper"><span className="is-active">1 <i>Details</i></span><span>2 <i>Review</i></span><span>3 <i>Confirm</i></span></div>
      <div className="prototype-workflow-grid">
        <div className="prototype-form-grid">{fallbackFields.map((field) => <label key={field}><span>{field}</span><input value={formValues[field] ?? ''} placeholder={`Enter ${field.toLowerCase()}`} onChange={(event) => setFormValues((current) => ({ ...current, [field]: event.target.value }))} /></label>)}</div>
        <aside className="prototype-scope-summary"><span>Included in this flow</span>{(items.length ? items : [screen.purpose]).slice(0, 4).map((item, index) => <p key={`${item}-${index}`}><CheckCircle2 className="h-3.5 w-3.5" />{item}</p>)}</aside>
      </div>
      <div className="prototype-actions">{actions.map((action, index) => <PrototypeActionButton key={action.id} action={action} primary={index === 0} onAction={onAction} />)}</div>
    </section>
  )
}

function PrototypeActionButton({ action, primary, onAction }: { action: PrototypeActionSpec; primary: boolean; onAction: (action: PrototypeActionSpec) => void }) {
  return <button type="button" className={primary ? 'prototype-action-primary' : 'prototype-action-secondary'} onClick={() => onAction(action)}>{action.label}{action.action_type === 'navigate' ? <ChevronRight className="h-4 w-4" /> : <Send className="h-3.5 w-3.5" />}</button>
}

function PrototypeNavIcon({ screen, large = false }: { screen: PrototypeScreen; large?: boolean }) {
  const text = `${screen.name} ${screen.layout}`.toLowerCase()
  const className = large ? 'h-8 w-8' : 'h-3.5 w-3.5'
  if (text.includes('search') || text.includes('explore')) return <MapPin className={className} />
  if (text.includes('book') || text.includes('schedule')) return <CalendarDays className={className} />
  if (text.includes('payment') || text.includes('bill')) return <CreditCard className={className} />
  if (text.includes('live') || text.includes('monitor') || text.includes('session')) return <Activity className={className} />
  if (text.includes('report') || text.includes('analytic')) return <BarChart3 className={className} />
  if (text.includes('operation') || text.includes('admin')) return <Settings2 className={className} />
  if (text.includes('account') || text.includes('profile')) return <UserRound className={className} />
  if (screen.layout === 'records') return <FileText className={className} />
  return <Home className={className} />
}

function cleanPrototypeCopy(value: string) {
  const cleaned = value
    .replace(/^(?:support|enable|allow|provide)\s+/i, '')
    .trim()
  return cleaned ? cleaned[0].toUpperCase() + cleaned.slice(1) : value
}

function defaultPrototypeFields(screen: PrototypeScreen, pattern: string, isCharging: boolean) {
  const text = `${screen.name} ${screen.purpose}`.toLowerCase()
  if (text.includes('account') || text.includes('login') || text.includes('authentication')) return [text.includes('email') ? 'Email' : 'Account identifier', text.includes('password') ? 'Password' : 'Credential']
  if (text.includes('payment') || text.includes('refund')) return [isCharging || pattern === 'scheduling' ? 'Booking reference' : 'Reference', 'Payment method']
  if (text.includes('cancel')) return [isCharging || pattern === 'scheduling' ? 'Booking reference' : 'Reference']
  if (/\b(?:book|booking|reservation|reserve|schedule|appointment|slot)\b/.test(text)) return isCharging ? ['Station', 'Date', 'Time slot'] : ['Selection', 'Date', 'Time']
  return ['Details']
}

function isChargingPrototype(domain: string, title: string) {
  return /\b(?:ev|electric vehicle|charging|charger)\b/i.test(`${domain} ${title}`)
}
