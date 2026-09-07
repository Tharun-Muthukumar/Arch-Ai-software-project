import {
  ArrowDown,
  ArrowUp,
  Bot,
  Braces,
  CircleAlert,
  Database,
  Edit3,
  Link2,
  MessageSquareText,
  Plus,
  ShieldCheck,
  Trash2,
  UserRound,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { StatePanel } from '../components/workspace/StatePanel'
import { WorkspaceEditDialog, type EditField } from '../components/workspace/WorkspaceEditDialog'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type { WorkspaceEditRequest, WorkspaceEditTarget } from '../types/api'

interface ActiveEdit {
  title: string
  description: string
  edit: WorkspaceEditRequest
  fields?: EditField[]
  allowAi?: boolean
}

const textFields: EditField[] = [
  { key: 'value', label: 'Requirement text', type: 'textarea', required: true, placeholder: 'Describe one observable capability or quality.' },
]

export function RequirementWizardPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const [activeEdit, setActiveEdit] = useState<ActiveEdit | null>(null)

  if (workspaceQuery.isLoading) {
    return <WorkspaceSkeleton />
  }
  if (workspaceQuery.isError) {
    return <StatePanel badge="Backend issue" title="Could not reach the backend" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  }
  if (!workspace) {
    return <StatePanel badge="No workspace" title="No requirements available" description="Create a project brief from the overview first." actionLabel="Open overview" actionTo="/dashboard" />
  }

  const { requirements } = workspace
  const sourceLabel = requirements.analysis_source === 'ollama-pretrained'
    ? 'Interpreted from the raw brief by Ollama'
    : requirements.analysis_source === 'predefined-blueprint'
      ? 'Matched with verified domain knowledge'
      : requirements.analysis_source === 'deterministic-extraction'
        ? 'Extracted deterministically from the brief wording (medium confidence)'
        : 'Conservative extraction fallback'

  function openStringEdit(
    target: WorkspaceEditTarget,
    operation: WorkspaceEditRequest['operation'],
    value?: string,
    index?: number,
    destinationIndex?: number,
  ) {
    const label = target.replaceAll('_', ' ')
    const prefix: Partial<Record<WorkspaceEditTarget, string>> = {
      functional_requirement: 'FR',
      non_functional_requirement: 'NFR',
      constraint: 'CON',
      assumption: 'ASM',
      integration: 'INT',
      data_characteristic: 'DATA-CHAR',
    }
    setActiveEdit({
      title: `${operation === 'add' ? 'Add' : operation === 'delete' ? 'Delete' : operation === 'reorder' ? 'Reorder' : 'Edit'} ${label}`,
      description: operation === 'delete'
        ? 'ArchAI will trace dependent components and generated artifacts before removal.'
        : 'The validated change will synchronize only the affected workspace areas.',
      edit: {
        target_type: target,
        operation,
        target_id: index === undefined ? undefined : `${prefix[target]}-${String(index + 1).padStart(3, '0')}`,
        value,
        destination_index: destinationIndex,
      },
      fields: operation === 'delete' || operation === 'reorder' ? [] : textFields,
      allowAi: operation === 'add' || operation === 'update',
    })
  }

  return (
    <div className="workspace-page">
      <header className="page-heading">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="status-chip status-accent">{requirements.domain}</span>
            <span className="inline-flex items-center gap-1.5 text-xs text-muted"><Bot className="h-3.5 w-3.5" />{sourceLabel}</span>
          </div>
          <h2>Requirements model</h2>
          <p>{requirements.summary}</p>
        </div>
        <div className="page-actions">
          {workspace.clarification_plan.questions.length > 0 ? (
            <Link to={`/dashboard?workspace=${workspace.id}#clarifications`} className="button-secondary gap-2">
              <MessageSquareText className="h-4 w-4" />
              {workspace.clarification_plan.questions.length} open questions
            </Link>
          ) : null}
          <div className="completion-meter" aria-label={`${workspace.clarification_plan.completeness_score}% requirements complete`}>
            <span>{workspace.clarification_plan.completeness_score}%</span>
            <div><i style={{ width: `${workspace.clarification_plan.completeness_score}%` }} /></div>
            <small>model completeness</small>
          </div>
        </div>
      </header>

      <div className="metric-strip">
        <Metric label="Functional" value={requirements.functional_requirements.length} icon={<Braces />} />
        <Metric label="Quality" value={requirements.non_functional_requirements.length} icon={<ShieldCheck />} />
        <Metric label="Actors" value={requirements.actors.length} icon={<UserRound />} />
        <Metric label="Entities" value={requirements.domain_entities.length} icon={<Database />} />
        <Metric label="Integrations" value={requirements.integrations.length} icon={<Link2 />} />
      </div>

      {workspace.consistency_issues.length > 0 ? (
        <section className="notice notice-warning">
          <CircleAlert className="h-4 w-4 shrink-0" />
          <div><strong>Consistency review</strong><p className="mt-1">{workspace.consistency_issues[0].message}</p></div>
        </section>
      ) : null}

      <div className="editor-grid">
        <StringEditor
          title="Functional requirements"
          description="Observable capabilities the system must provide."
          prefix="FR"
          values={requirements.functional_requirements}
          empty="No functional requirements are confirmed yet."
          onAction={(operation, value, index, destination) => openStringEdit('functional_requirement', operation, value, index, destination)}
        />
        <StringEditor
          title="Non-functional requirements"
          description="Quality, security, performance, and operational expectations."
          prefix="NFR"
          values={requirements.non_functional_requirements}
          empty="No quality requirements are confirmed yet."
          onAction={(operation, value, index, destination) => openStringEdit('non_functional_requirement', operation, value, index, destination)}
        />
      </div>

      <section className="panel">
        <SectionHeader title="Actors and responsibilities" description="People, organizational roles, and active machine participants." onAdd={() => setActiveEdit(actorEdit('add'))} />
        <div className="editor-list mt-4">
          {requirements.actors.map((actor, index) => (
            <div key={`${actor.name}-${index}`} className="editor-row items-start">
              <div className="id-badge">ACT-{String(index + 1).padStart(3, '0')}</div>
              <div className="min-w-0 flex-1"><strong>{actor.name}</strong><p>{actor.description}</p></div>
              <RowActions
                onEdit={() => setActiveEdit(actorEdit('update', actor, index))}
                onDelete={() => setActiveEdit(actorEdit('delete', actor, index))}
                onUp={index > 0 ? () => setActiveEdit(actorReorder(actor, index, index - 1)) : undefined}
                onDown={index < requirements.actors.length - 1 ? () => setActiveEdit(actorReorder(actor, index, index + 1)) : undefined}
              />
            </div>
          ))}
          {requirements.actors.length === 0 ? <EmptyRow text="Actors are not yet known." /> : null}
        </div>
      </section>

      <div className="editor-grid">
        <CompactStringEditor title="Constraints" target="constraint" prefix="CON" values={requirements.constraints} onOpen={openStringEdit} />
        <CompactStringEditor title="Assumptions" target="assumption" prefix="ASM" values={requirements.assumptions} onOpen={openStringEdit} />
        <CompactStringEditor title="Integrations" target="integration" prefix="INT" values={requirements.integrations} onOpen={openStringEdit} />
        <CompactStringEditor title="Technical & data characteristics" target="data_characteristic" prefix="TECH" values={requirements.data_characteristics} onOpen={openStringEdit} />
      </div>

      <section className="panel">
        <SectionHeader title="Domain entities" description="Core concepts that anchor API, database, and diagram generation." onAdd={() => setActiveEdit(entityEdit('add'))} />
        <div className="editor-list mt-4">
          {requirements.domain_entities.map((entity, index) => (
            <div key={`${entity.name}-${index}`} className="editor-row items-start">
              <div className="id-badge">ENT-{String(index + 1).padStart(3, '0')}</div>
              <div className="min-w-0 flex-1"><strong>{entity.name}</strong><p>{entity.description}</p>{entity.attributes.length > 0 ? <div className="tag-list">{entity.attributes.map((attribute) => <span key={attribute}>{attribute}</span>)}</div> : null}</div>
              <RowActions onEdit={() => setActiveEdit(entityEdit('update', entity, index))} onDelete={() => setActiveEdit(entityEdit('delete', entity, index))} />
            </div>
          ))}
          {requirements.domain_entities.length === 0 ? <EmptyRow text="No domain entities have been confirmed." /> : null}
        </div>
      </section>

      {requirements.analysis_warnings.length > 0 ? (
        <section className="panel">
          <div className="eyebrow">Extraction notes</div>
          <ul className="mt-3 space-y-2 text-sm text-muted">{requirements.analysis_warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>
        </section>
      ) : null}

      {activeEdit ? (
        <WorkspaceEditDialog
          open
          workspace={workspace}
          title={activeEdit.title}
          description={activeEdit.description}
          edit={activeEdit.edit}
          fields={activeEdit.fields}
          allowAi={activeEdit.allowAi}
          onClose={() => setActiveEdit(null)}
        />
      ) : null}
    </div>
  )
}

function StringEditor({ title, description, prefix, values, empty, onAction }: {
  title: string
  description: string
  prefix: string
  values: string[]
  empty: string
  onAction: (operation: WorkspaceEditRequest['operation'], value?: string, index?: number, destination?: number) => void
}) {
  return (
    <section className="panel min-w-0">
      <SectionHeader title={title} description={description} onAdd={() => onAction('add', '')} />
      <div className="editor-list mt-4">
        {values.map((value, index) => (
          <div key={`${value}-${index}`} className="editor-row items-start">
            <div className="id-badge">{prefix}-{String(index + 1).padStart(3, '0')}</div>
            <p className="min-w-0 flex-1">{value}</p>
            <RowActions
              onEdit={() => onAction('update', value, index)}
              onDelete={() => onAction('delete', value, index)}
              onUp={index > 0 ? () => onAction('reorder', value, index, index - 1) : undefined}
              onDown={index < values.length - 1 ? () => onAction('reorder', value, index, index + 1) : undefined}
            />
          </div>
        ))}
        {values.length === 0 ? <EmptyRow text={empty} /> : null}
      </div>
    </section>
  )
}

function CompactStringEditor({ title, target, prefix, values, onOpen }: {
  title: string
  target: WorkspaceEditTarget
  prefix: string
  values: string[]
  onOpen: (target: WorkspaceEditTarget, operation: WorkspaceEditRequest['operation'], value?: string, index?: number, destination?: number) => void
}) {
  return (
    <section className="panel min-w-0">
      <SectionHeader title={title} description={`${values.length} confirmed`} onAdd={() => onOpen(target, 'add', '')} />
      <div className="editor-list mt-4">
        {values.map((value, index) => (
          <div key={`${value}-${index}`} className="editor-row">
            <span className="id-badge">{prefix}-{String(index + 1).padStart(3, '0')}</span>
            <p className="min-w-0 flex-1">{value}</p>
            <RowActions onEdit={() => onOpen(target, 'update', value, index)} onDelete={() => onOpen(target, 'delete', value, index)} />
          </div>
        ))}
        {values.length === 0 ? <EmptyRow text="Nothing confirmed." /> : null}
      </div>
    </section>
  )
}

function SectionHeader({ title, description, onAdd }: { title: string; description: string; onAdd: () => void }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="panel-title">{title}</h3><p className="panel-description">{description}</p></div>
      <button type="button" className="button-secondary gap-2 px-3 py-2" onClick={onAdd}><Plus className="h-4 w-4" />Add</button>
    </div>
  )
}

function RowActions({ onEdit, onDelete, onUp, onDown }: { onEdit: () => void; onDelete: () => void; onUp?: () => void; onDown?: () => void }) {
  return (
    <div className="row-actions">
      {onUp ? <button type="button" className="icon-button" title="Move up" aria-label="Move up" onClick={onUp}><ArrowUp className="h-3.5 w-3.5" /></button> : null}
      {onDown ? <button type="button" className="icon-button" title="Move down" aria-label="Move down" onClick={onDown}><ArrowDown className="h-3.5 w-3.5" /></button> : null}
      <button type="button" className="icon-button" title="Edit" aria-label="Edit" onClick={onEdit}><Edit3 className="h-3.5 w-3.5" /></button>
      <button type="button" className="icon-button danger-hover" title="Delete" aria-label="Delete" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></button>
    </div>
  )
}

function EmptyRow({ text }: { text: string }) {
  return <div className="empty-row">{text}</div>
}

function Metric({ label, value, icon }: { label: string; value: number; icon: ReactNode }) {
  return <div className="metric-item"><span>{icon}</span><div><strong>{value}</strong><small>{label}</small></div></div>
}

function actorEdit(operation: 'add' | 'update' | 'delete', actor = { name: '', description: '' }, index?: number): ActiveEdit {
  return {
    title: `${operation === 'add' ? 'Add' : operation === 'delete' ? 'Delete' : 'Edit'} actor`,
    description: 'Actor changes are traced into responsibilities, permissions, APIs, and use-case diagrams.',
    edit: { target_type: 'actor', operation, target_id: index === undefined ? undefined : `ACTOR-${String(index + 1).padStart(3, '0')}`, value: actor },
    fields: operation === 'delete' ? [] : [
      { key: 'name', label: 'Actor name', required: true, placeholder: 'Dispatcher' },
      { key: 'description', label: 'Responsibilities', type: 'textarea', required: true, placeholder: 'What this actor does and owns.' },
    ],
  }
}

function actorReorder(actor: { name: string; description: string }, index: number, destination: number): ActiveEdit {
  return {
    title: `Move ${actor.name}`,
    description: 'Review the identifier and diagram impact of changing actor order.',
    edit: { target_type: 'actor', operation: 'reorder', target_id: `ACTOR-${String(index + 1).padStart(3, '0')}`, destination_index: destination },
    fields: [],
  }
}

function entityEdit(operation: 'add' | 'update' | 'delete', entity = { name: '', description: '', attributes: [] as string[] }, index?: number): ActiveEdit {
  return {
    title: `${operation === 'add' ? 'Add' : operation === 'delete' ? 'Delete' : 'Edit'} domain entity`,
    description: 'Domain concepts influence persistence, APIs, diagrams, and service ownership.',
    edit: { target_type: 'domain_entity', operation, target_id: index === undefined ? undefined : `ENTITY-HINT-${String(index + 1).padStart(3, '0')}`, value: entity },
    fields: operation === 'delete' ? [] : [
      { key: 'name', label: 'Entity name', required: true, placeholder: 'Delivery' },
      { key: 'description', label: 'Meaning', type: 'textarea', required: true },
      { key: 'attributes', label: 'Important attributes', type: 'tags' },
    ],
  }
}

function WorkspaceSkeleton() {
  return <div className="workspace-page"><div className="skeleton h-24" /><div className="metric-strip"><div className="skeleton h-14" /><div className="skeleton h-14" /><div className="skeleton h-14" /></div><div className="editor-grid"><div className="skeleton h-96" /><div className="skeleton h-96" /></div></div>
}
