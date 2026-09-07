import { Edit3, ExternalLink, StickyNote } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { MermaidDiagram } from '../components/diagrams/MermaidDiagram'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import { WorkspaceEditDialog } from '../components/workspace/WorkspaceEditDialog'

const diagramOrder = [
  'use_case', 'activity', 'sequence', 'class', 'er', 'component', 'deployment',
]

const diagramLabels: Record<string, string> = {
  use_case: 'Use Case',
  activity: 'Activity',
  sequence: 'Sequence',
  class: 'Class',
  er: 'ER',
  component: 'Component',
  deployment: 'Deployment',
}

export function DiagramsPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(
    workspaceQuery.data,
    searchParams.get('workspace'),
  )
  const diagramKeys = useMemo(
    () =>
      workspace
        ? diagramOrder.filter((diagramKey) => workspace.diagrams[diagramKey])
        : [],
    [workspace],
  )
  const [selectedKey, setSelectedKey] = useState('use_case')
  const [editingNote, setEditingNote] = useState(false)

  useEffect(() => {
    if (!diagramKeys.length) return
    if (!diagramKeys.includes(selectedKey)) {
      setSelectedKey(diagramKeys[0])
    }
  }, [diagramKeys, selectedKey])

  if (workspaceQuery.isLoading) {
    return <StatePanel badge="Loading" title="Loading diagrams" description="Preparing the diagram suite." />
  }

  if (workspaceQuery.isError) {
    return (
      <StatePanel
        badge="Backend issue"
        title="Could not reach the backend"
        description={getErrorMessage(workspaceQuery.error)}
        tone="danger"
        actionLabel="Retry"
        onAction={() => void workspaceQuery.refetch()}
      />
    )
  }

  if (!workspace) {
    return (
      <StatePanel
        badge="No workspace"
        title="No diagrams available"
        description="Create a project brief from the dashboard first."
        actionLabel="Open Dashboard"
        actionTo="/dashboard"
      />
    )
  }

  const activeDiagram =
    workspace.diagrams[selectedKey] ?? workspace.diagrams[diagramKeys[0]]
  const layout = workspace.diagram_layouts[selectedKey] ?? {}
  const note = typeof layout.note === 'string' ? layout.note : ''
  const modelRoute = ['er', 'class'].includes(selectedKey)
    ? `/interfaces?workspace=${workspace.id}&section=data`
    : selectedKey === 'deployment'
      ? `/interfaces?workspace=${workspace.id}&section=deployment`
      : selectedKey === 'component'
        ? `/architecture?workspace=${workspace.id}`
        : `/wizard?workspace=${workspace.id}`

  return (
    <div className="workspace-page">
      <header className="page-heading">
        <div><span className="eyebrow">Synchronized views</span><h2>Diagram workspace</h2><p>Inspect generated views and route architectural edits back to the canonical model.</p></div>
        <div className="page-actions"><Link to={modelRoute} className="button-secondary gap-2"><ExternalLink className="h-4 w-4" />Edit underlying model</Link><button type="button" className="button-secondary gap-2" onClick={() => setEditingNote(true)}><StickyNote className="h-4 w-4" />Visual note</button></div>
      </header>

      <div className="segmented-control flex-wrap" role="tablist" aria-label="Diagram types">
        {diagramKeys.map((diagramKey) => (
          <button
            key={diagramKey}
            type="button"
            role="tab"
            aria-selected={diagramKey === selectedKey}
            onClick={() => setSelectedKey(diagramKey)}
            className={diagramKey === selectedKey ? 'is-active' : ''}
          >
            {diagramLabels[diagramKey] ?? diagramKey.replaceAll('_', ' ')}
          </button>
        ))}
      </div>

      <div className="notice notice-info"><Edit3 className="h-4 w-4 shrink-0" /><p><strong>Model edits</strong> regenerate affected diagrams. Visual notes are presentation-only and never change architecture decisions.</p></div>

      {note ? <div className="diagram-note"><StickyNote className="h-4 w-4" /><span>{note}</span><button type="button" className="icon-button ml-auto" title="Edit note" aria-label="Edit visual note" onClick={() => setEditingNote(true)}><Edit3 className="h-3.5 w-3.5" /></button></div> : null}

      {activeDiagram ? <MermaidDiagram artifact={activeDiagram} /> : null}

      {editingNote ? (
        <WorkspaceEditDialog
          open
          workspace={workspace}
          title={`Visual note for ${diagramLabels[selectedKey] ?? selectedKey}`}
          description="This changes diagram presentation metadata only. It does not regenerate or alter the architecture."
          edit={{ target_type: 'diagram_layout', operation: 'update', target_id: selectedKey, value: { ...layout, note } }}
          fields={[{ key: 'note', label: 'Diagram note', type: 'textarea', placeholder: 'Record presentation context or review notes.' }]}
          onClose={() => setEditingNote(false)}
        />
      ) : null}
    </div>
  )
}
