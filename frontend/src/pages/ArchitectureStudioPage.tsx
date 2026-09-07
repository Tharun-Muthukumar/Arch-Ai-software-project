import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArchitectureFlow } from '../components/diagrams/ArchitectureFlow'
import { StatePanel } from '../components/workspace/StatePanel'
import { ADRTimeline } from '../components/workspace/ADRTimeline'
import { WorkspaceEditDialog, type EditField } from '../components/workspace/WorkspaceEditDialog'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { getActiveWorkspace, getErrorMessage, formatMetricName } from '../lib/utils'
import type { ArchitectureDecisionRecord, Workspace } from '../types/api'
import type { ArchitectureComponent, WorkspaceEditRequest } from '../types/api'

interface TimelineEntry {
  adr: ArchitectureDecisionRecord
  snapshot: Workspace
}

export function ArchitectureStudioPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(
    workspaceQuery.data,
    searchParams.get('workspace'),
  )
  const recommendedId = workspace?.recommendation.recommended_architecture_id ?? ''
  const [selectedId, setSelectedId] = useState(recommendedId)

  const [activeTimelineIndex, setActiveTimelineIndex] = useState(0)
  const [componentEdit, setComponentEdit] = useState<{
    title: string
    edit: WorkspaceEditRequest
    fields: EditField[]
  } | null>(null)
  const timelineEntries = useMemo<TimelineEntry[]>(
    () => (workspace?.adrs ?? []).map((adr) => ({ adr, snapshot: workspace! })),
    [workspace],
  )

  useEffect(() => {
    if (recommendedId) setSelectedId(recommendedId)
  }, [recommendedId, workspace?.id])

  useEffect(() => {
    if (timelineEntries.length > 0) setActiveTimelineIndex(timelineEntries.length - 1)
  }, [timelineEntries.length, workspace?.id])

  if (workspaceQuery.isLoading) {
    return <StatePanel badge="Loading" title="Loading architecture" description="Preparing the view." />
  }

  if (workspaceQuery.isError) {
    return (
      <StatePanel badge="Backend issue" title="Could not reach the backend" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
    )
  }

  if (!workspace) {
    return (
      <StatePanel badge="No workspace" title="No architecture available" description="Create a project brief from the dashboard first." actionLabel="Open Dashboard" actionTo="/dashboard" />
    )
  }

  const selected = workspace.architectures.find(a => a.id === selectedId) ?? workspace.architectures[0]
  const scorecards = workspace.comparison.scorecards
  const metrics = scorecards[0]?.metric_scores ?? []
  const componentFields: EditField[] = [
    { key: 'name', label: 'Component name', required: true },
    { key: 'responsibility', label: 'Responsibility', type: 'textarea', required: true },
    { key: 'technologies', label: 'Technologies', type: 'tags', help: 'Use only technologies that are decisions or explicit project constraints.' },
    { key: 'interactions', label: 'Relationships and interactions', type: 'tags' },
  ]

  function openComponentEdit(operation: 'add' | 'update' | 'delete', component?: ArchitectureComponent, index?: number) {
    if (!selected) return
    setComponentEdit({
      title: `${operation === 'add' ? 'Add' : operation === 'delete' ? 'Delete' : 'Edit'} architecture component`,
      edit: {
        target_type: 'architecture_component',
        operation,
        parent_id: selected.id,
        target_id: index === undefined ? undefined : `COMPONENT-${String(index + 1).padStart(3, '0')}`,
        value: (component ?? { name: '', responsibility: '', technologies: [], interactions: [] }) as unknown as Record<string, unknown>,
      },
      fields: operation === 'delete' ? [] : componentFields,
    })
  }

  return (
    <div className="workspace-page">
      <header className="page-heading">
        <div><span className="eyebrow">Decision workspace</span><h2>Architecture studio</h2><p>Explore trade-offs, inspect component responsibilities, and safely evolve the design.</p></div>
        <span className="status-chip status-success">{workspace.recommendation.confidence} confidence</span>
      </header>
      {/* Comparison table - always visible */}
      <div className="panel overflow-x-auto">
        <h3 className="text-sm font-semibold mb-3">Architecture Comparison</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b" style={{ borderColor: 'var(--card-border)' }}>
              <th className="py-2 pr-4 text-left font-medium" style={{ color: 'var(--text-muted)' }}>Metric</th>
              {scorecards.map(sc => (
                <th key={sc.architecture_id} className={`py-2 px-3 text-left font-medium ${sc.architecture_id === recommendedId ? 'text-amber-700 dark:text-amber-400' : ''}`}>
                  {sc.architecture_name}
                  {sc.architecture_id === recommendedId && <span className="ml-1 text-xs font-normal">(recommended)</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map(metric => (
              <tr key={metric.metric} className="border-b" style={{ borderColor: 'var(--card-border)' }}>
                <td className="py-2 pr-4 font-medium whitespace-nowrap">{formatMetricName(metric.metric)}</td>
                {scorecards.map(sc => {
                  const ms = sc.metric_scores.find(m => m.metric === metric.metric)
                  const score = ms?.score ?? 0
                  const maxScore = Math.max(...scorecards.map(s => (s.metric_scores.find(m => m.metric === metric.metric)?.score ?? 0)))
                  const isBest = score === maxScore && score > 0
                  return (
                    <td key={sc.architecture_id} className="py-2 px-3">
                      <span className={isBest ? 'font-bold' : ''}>
                        {score}
                      </span>
                      {isBest && <span className="ml-1 text-xs" style={{ color: 'var(--success)' }}>best</span>}
                    </td>
                  )
                })}
              </tr>
            ))}
            <tr className="font-semibold">
              <td className="py-2 pr-4">Overall</td>
              {scorecards.map(sc => (
                <td key={sc.architecture_id} className="py-2 px-3">
                  {sc.overall_score}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {/* Architecture selector */}
      <div className="panel">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h3 className="text-sm font-semibold">Details</h3>
          <div className="flex flex-wrap gap-1.5">
            {workspace.architectures.map(a => (
              <button
                key={a.id}
                type="button"
                onClick={() => setSelectedId(a.id)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  a.id === selected?.id
                    ? 'bg-amber-600 text-white'
                    : 'border hover:bg-black/5 dark:hover:bg-white/5'
                }`}
                style={{ borderColor: 'var(--card-border)' }}
              >
                {a.name}
                {a.id === recommendedId && <span className="ml-1 text-xs opacity-75">★</span>}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Selected architecture details */}
      {selected && (
        <>
          <div className="panel">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="pill">{selected.style}</span>
                  {selected.id === recommendedId && <span className="text-xs font-medium" style={{ color: 'var(--success)' }}>Recommended</span>}
                </div>
                <h2 className="mt-2 text-xl font-semibold">{selected.name}</h2>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>{selected.overview}</p>
              </div>
              <div className="flex gap-4 text-sm shrink-0">
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Complexity: </span>
                  <span className="font-medium">{selected.estimated_complexity}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Cost: </span>
                  <span className="font-medium">{selected.estimated_cost}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>API: </span>
                  <span className="font-medium">{selected.api_style}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ArchitectureFlow
                architecture={selected}
                whyHref={(component) =>
                  `/causal-graph?workspace=${encodeURIComponent(workspace.id)}&architecture=${encodeURIComponent(selected.id)}&component=${encodeURIComponent(component.name)}`
                }
                onAdd={() => openComponentEdit('add')}
                onEdit={(component, index) => openComponentEdit('update', component, index)}
                onDelete={(component, index) => openComponentEdit('delete', component, index)}
              />
            </div>
            <div className="space-y-4">
              <div className="panel">
                <h3 className="text-sm font-semibold mb-2">Why it fits</h3>
                <ul className="space-y-1.5 text-sm">
                  {workspace.recommendation.why.map(r => <li key={r}>{r}</li>)}
                </ul>
              </div>
              <div className="panel">
                <h3 className="text-sm font-semibold mb-2">Rollout</h3>
                <ul className="space-y-1.5 text-sm">
                  {workspace.recommendation.rollout_plan.map(item => <li key={item}>{item}</li>)}
                </ul>
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="panel">
              <h3 className="text-sm font-semibold mb-2">Technology stack</h3>
              <div className="flex flex-wrap gap-1.5">
                {selected.technology_stack.map(t => (
                  <span key={t} className="rounded border px-2 py-0.5 text-xs" style={{ borderColor: 'var(--card-border)', color: 'var(--text-muted)' }}>{t}</span>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3 className="text-sm font-semibold mb-2">Trade-offs</h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="font-medium mb-1">Advantages</div>
                  <ul className="space-y-1" style={{ color: 'var(--text-muted)' }}>
                    {selected.advantages.map(a => <li key={a}>{a}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="font-medium mb-1">Risks</div>
                  <ul className="space-y-1" style={{ color: 'var(--text-muted)' }}>
                    {selected.disadvantages.map(r => <li key={r}>{r}</li>)}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {timelineEntries.length > 0 && (
        <ADRTimeline
          entries={timelineEntries}
          activeIndex={activeTimelineIndex}
          onSelect={(index) => setActiveTimelineIndex(index)}
        />
      )}
      {componentEdit ? (
        <WorkspaceEditDialog
          open
          workspace={workspace}
          title={componentEdit.title}
          description="Dependencies, diagrams, scoring, and causal links are checked before this change is saved."
          edit={componentEdit.edit}
          fields={componentEdit.fields}
          onClose={() => setComponentEdit(null)}
        />
      ) : null}
    </div>
  )
}
