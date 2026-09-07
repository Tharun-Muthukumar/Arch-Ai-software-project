import {
  Braces,
  Cloud,
  Database,
  Edit3,
  ExternalLink,
  KeyRound,
  Network,
  Plus,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { StatePanel } from '../components/workspace/StatePanel'
import { WorkspaceEditDialog, type EditField } from '../components/workspace/WorkspaceEditDialog'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { cn, getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type { ApiEndpoint, DatabaseEntity, WorkspaceEditRequest } from '../types/api'

type Section = 'api' | 'data' | 'deployment'

interface ActiveEdit {
  title: string
  description: string
  edit: WorkspaceEditRequest
  fields: EditField[]
}

export function InterfacesDataPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const requestedSection = searchParams.get('section') as Section | null
  const section: Section = ['api', 'data', 'deployment'].includes(requestedSection ?? '') ? requestedSection! : 'api'
  const [activeEdit, setActiveEdit] = useState<ActiveEdit | null>(null)

  if (workspaceQuery.isLoading) return <StatePanel badge="Loading" title="Loading interface model" description="Preparing APIs, data, and deployment details." />
  if (workspaceQuery.isError) return <StatePanel badge="Backend issue" title="Could not load interface model" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  if (!workspace) return <StatePanel badge="No workspace" title="No interface model available" description="Create a project brief from the overview first." actionLabel="Open overview" actionTo="/dashboard" />

  const selectedArchitecture = workspace.architectures.find((item) => item.id === workspace.recommendation.recommended_architecture_id) ?? workspace.architectures[0]
  const serviceOptions = [
    { label: 'Not assigned', value: '' },
    ...(selectedArchitecture?.components ?? []).map((component) => ({ label: component.name, value: component.name })),
  ]

  function changeSection(next: Section) {
    const params = new URLSearchParams(searchParams)
    params.set('section', next)
    setSearchParams(params)
  }

  function endpointEdit(operation: 'add' | 'update' | 'delete', groupIndex: number, endpoint?: ApiEndpoint, endpointIndex?: number) {
    const value: ApiEndpoint = endpoint ?? {
      method: 'GET', path: '/', purpose: '', auth_required: null,
      request_description: '', response_description: '', service: null,
      requirement_ids: [], request_example: {}, response_example: {},
    }
    setActiveEdit({
      title: `${operation === 'add' ? 'Add' : operation === 'delete' ? 'Delete' : 'Edit'} API endpoint`,
      description: 'The contract is validated for method, path, ownership, duplicates, and requirement traceability.',
      edit: {
        target_type: 'api_endpoint', operation, parent_id: String(groupIndex),
        target_id: endpointIndex === undefined ? undefined : `ENDPOINT-${String(endpointIndex + 1).padStart(3, '0')}`,
        value: value as unknown as Record<string, unknown>,
      },
      fields: operation === 'delete' ? [] : [
        { key: 'method', label: 'HTTP method', type: 'select', options: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((method) => ({ label: method, value: method })) },
        { key: 'path', label: 'Path', required: true, placeholder: '/orders/{order_id}' },
        { key: 'purpose', label: 'Purpose', type: 'textarea', required: true },
        { key: 'request_description', label: 'Request description', type: 'textarea', placeholder: 'Inputs, validation, and important semantics.' },
        { key: 'response_description', label: 'Response description', type: 'textarea', placeholder: 'Success result and meaningful failure behavior.' },
        { key: 'service', label: 'Owning component', type: 'select', options: serviceOptions },
        { key: 'requirement_ids', label: 'Associated requirement IDs', type: 'tags', placeholder: 'FR-001, NFR-002' },
        { key: 'auth_required', label: 'Authentication required', type: 'checkbox', help: 'Enable only when this contract requires an authenticated principal.' },
      ],
    })
  }

  function entityEdit(operation: 'add' | 'update' | 'delete', entity?: DatabaseEntity, index?: number) {
    const value: DatabaseEntity = entity ?? {
      name: '', description: '', fields: [
        { name: 'id', data_type: 'uuid', nullable: false, indexed: true, description: 'Stable primary identifier.' },
      ],
    }
    setActiveEdit({
      title: `${operation === 'add' ? 'Add' : operation === 'delete' ? 'Delete' : 'Edit'} database entity`,
      description: 'Relationships are checked before save; deleting an entity also removes relationships that can no longer be valid.',
      edit: {
        target_type: 'database_entity', operation,
        target_id: index === undefined ? undefined : `ENTITY-${String(index + 1).padStart(3, '0')}`,
        value: value as unknown as Record<string, unknown>,
      },
      fields: operation === 'delete' ? [] : [
        { key: 'name', label: 'Entity name', required: true, placeholder: 'orders' },
        { key: 'description', label: 'Description', type: 'textarea', required: true },
        { key: 'fields', label: 'Attributes', type: 'database-fields' },
      ],
    })
  }

  function deploymentEdit() {
    setActiveEdit({
      title: 'Edit deployment plan',
      description: 'Numerical values remain user-controlled. ArchAI does not invent replica counts, regions, or availability targets.',
      edit: { target_type: 'deployment', operation: 'update', target_id: 'deployment', value: workspace!.deployment_plan as unknown as Record<string, unknown> },
      fields: [
        { key: 'deployment_model', label: 'Deployment model', required: true },
        { key: 'replicas', label: 'Replicas', type: 'number', help: 'Leave empty when the required count is unknown.' },
        { key: 'regions', label: 'Regions', type: 'tags', help: 'Only add regions explicitly selected for this project.' },
        { key: 'deployment_strategy', label: 'Deployment strategy', placeholder: 'Rolling, blue/green, canary, or undecided' },
        { key: 'availability_configuration', label: 'Availability configuration', type: 'textarea', placeholder: 'Known failover or redundancy requirements.' },
        { key: 'target_stack', label: 'Target stack', type: 'tags' },
        { key: 'docker_services', label: 'Container services', type: 'tags' },
        { key: 'kubernetes_modules', label: 'Orchestration modules', type: 'tags' },
        { key: 'scaling_strategy', label: 'Scaling strategy', type: 'tags' },
        { key: 'observability', label: 'Observability', type: 'tags' },
        { key: 'security_controls', label: 'Security controls', type: 'tags' },
        { key: 'cloud_recommendation', label: 'Infrastructure recommendation', type: 'textarea', required: true },
      ],
    })
  }

  return (
    <div className="workspace-page">
      <header className="page-heading">
        <div><span className="eyebrow">Implementation model</span><h2>Interfaces & data</h2><p>Edit contracts, persistence, and runtime choices without disconnecting them from the architecture.</p></div>
        <Link to={`/causal-graph?workspace=${workspace.id}`} className="button-secondary gap-2"><Network className="h-4 w-4" />Explore dependencies</Link>
      </header>

      <div className="segmented-control" role="tablist" aria-label="Implementation model sections">
        <button type="button" role="tab" aria-selected={section === 'api'} className={cn(section === 'api' && 'is-active')} onClick={() => changeSection('api')}><Braces className="h-4 w-4" />API contracts</button>
        <button type="button" role="tab" aria-selected={section === 'data'} className={cn(section === 'data' && 'is-active')} onClick={() => changeSection('data')}><Database className="h-4 w-4" />Data model</button>
        <button type="button" role="tab" aria-selected={section === 'deployment'} className={cn(section === 'deployment' && 'is-active')} onClick={() => changeSection('deployment')}><Cloud className="h-4 w-4" />Deployment</button>
      </div>

      {section === 'api' ? (
        <div className="space-y-4">
          <div className="metric-strip">
            <Metric label="Style" value={workspace.api_design.style} />
            <Metric label="Groups" value={workspace.api_design.groups.length} />
            <Metric label="Endpoints" value={workspace.api_design.groups.reduce((total, group) => total + group.endpoints.length, 0)} />
            <Metric label="Authentication" value={workspace.api_design.authentication_strategy} />
          </div>
          {workspace.api_design.groups.map((group, groupIndex) => (
            <section key={`${group.name}-${groupIndex}`} className="panel">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="flex items-center gap-2"><span className="id-badge">API-{String(groupIndex + 1).padStart(3, '0')}</span><h3 className="panel-title">{group.name}</h3></div><p className="panel-description mt-1">{group.description}</p></div>
                <div className="flex gap-2">
                  <Link to={`/causal-graph?workspace=${workspace.id}&component=${encodeURIComponent(group.name)}`} className="icon-button" title="Explain API dependencies" aria-label={`Explain ${group.name}`}><ExternalLink className="h-4 w-4" /></Link>
                  <button type="button" className="button-secondary gap-2 px-3 py-2" onClick={() => endpointEdit('add', groupIndex)}><Plus className="h-4 w-4" />Endpoint</button>
                </div>
              </div>
              <div className="data-table-wrap mt-4">
                <table className="data-table">
                  <thead><tr><th>Method</th><th>Path & purpose</th><th>Owner</th><th>Requirements</th><th><span className="sr-only">Actions</span></th></tr></thead>
                  <tbody>
                    {group.endpoints.map((endpoint, endpointIndex) => (
                      <tr key={`${endpoint.method}-${endpoint.path}-${endpointIndex}`}>
                        <td data-label="Method"><span className={`method-badge method-${endpoint.method.toLowerCase()}`}>{endpoint.method}</span></td>
                        <td data-label="Contract"><code>{endpoint.path}</code><p>{endpoint.purpose}</p></td>
                        <td data-label="Owner">{endpoint.service || <span className="text-muted">Unassigned</span>}</td>
                        <td data-label="Requirements">{endpoint.requirement_ids.length > 0 ? <div className="tag-list">{endpoint.requirement_ids.map((id) => <span key={id}>{id}</span>)}</div> : <span className="text-muted">Inferred</span>}</td>
                        <td data-label="Actions"><div className="row-actions justify-end"><button type="button" className="icon-button" title="Edit endpoint" aria-label={`Edit ${endpoint.method} ${endpoint.path}`} onClick={() => endpointEdit('update', groupIndex, endpoint, endpointIndex)}><Edit3 className="h-3.5 w-3.5" /></button><button type="button" className="icon-button danger-hover" title="Delete endpoint" aria-label={`Delete ${endpoint.method} ${endpoint.path}`} onClick={() => endpointEdit('delete', groupIndex, endpoint, endpointIndex)}><Trash2 className="h-3.5 w-3.5" /></button></div></td>
                      </tr>
                    ))}
                    {group.endpoints.length === 0 ? <tr><td colSpan={5}><div className="empty-row">No endpoints in this API group.</div></td></tr> : null}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
          {workspace.api_design.groups.length === 0 ? (
            <section className="empty-feature-state">
              <Braces className="h-6 w-6" />
              <div><h3>No API contracts generated yet</h3><p>Answer the open architecture questions or add specific functional requirements before defining endpoint contracts.</p></div>
              <Link to={`/wizard?workspace=${workspace.id}`} className="button-secondary">Open requirements</Link>
            </section>
          ) : null}
        </div>
      ) : null}

      {section === 'data' ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><span className="eyebrow">{workspace.database_design.database_engine}</span><h3 className="mt-1 text-lg font-semibold">Canonical data model</h3></div><button type="button" className="button-brand gap-2" onClick={() => entityEdit('add')}><Plus className="h-4 w-4" />Add entity</button></div>
          <div className="entity-grid">
            {workspace.database_design.entities.map((entity, index) => (
              <section key={`${entity.name}-${index}`} className="panel min-w-0">
                <div className="flex items-start justify-between gap-3"><div><span className="id-badge">DATA-{String(index + 1).padStart(3, '0')}</span><h3 className="panel-title mt-2">{entity.name}</h3><p className="panel-description">{entity.description}</p></div><div className="row-actions"><button type="button" className="icon-button" title="Edit entity" aria-label={`Edit ${entity.name}`} onClick={() => entityEdit('update', entity, index)}><Edit3 className="h-3.5 w-3.5" /></button><button type="button" className="icon-button danger-hover" title="Delete entity" aria-label={`Delete ${entity.name}`} onClick={() => entityEdit('delete', entity, index)}><Trash2 className="h-3.5 w-3.5" /></button></div></div>
                <div className="field-list mt-4">{entity.fields.map((field) => <div key={field.name}><code>{field.name}</code><span>{field.data_type}{field.nullable ? ' · nullable' : ''}</span>{field.indexed ? <KeyRound className="h-3.5 w-3.5" aria-label="Indexed" /> : null}</div>)}</div>
              </section>
            ))}
          </div>
          <section className="panel"><h3 className="panel-title">Validated relationships</h3><div className="mt-3 flex flex-wrap gap-2">{workspace.database_design.relationships.map((relation, index) => <span key={`${relation.source}-${relation.target}-${index}`} className="relationship-chip">{relation.source} <b>{relation.relationship}</b> {relation.target}</span>)}</div>{workspace.database_design.relationships.length === 0 ? <div className="empty-row mt-3">No relationships are recorded.</div> : null}</section>
        </div>
      ) : null}

      {section === 'deployment' ? (
        <div className="space-y-4">
          <section className="panel">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><span className="eyebrow">Runtime plan</span><h3 className="panel-title mt-1">{workspace.deployment_plan.deployment_model}</h3><p className="panel-description">{workspace.deployment_plan.cloud_recommendation}</p></div><button type="button" className="button-brand gap-2" onClick={deploymentEdit}><Edit3 className="h-4 w-4" />Edit deployment</button></div>
            <div className="deployment-facts mt-5">
              <Fact label="Replicas" value={workspace.deployment_plan.replicas?.toString() || 'Unknown'} />
              <Fact label="Regions" value={workspace.deployment_plan.regions.length > 0 ? workspace.deployment_plan.regions.join(', ') : 'Unknown'} />
              <Fact label="Strategy" value={workspace.deployment_plan.deployment_strategy || 'Not decided'} />
              <Fact label="Availability" value={workspace.deployment_plan.availability_configuration || 'Not specified'} />
            </div>
          </section>
          <div className="editor-grid">
            <ReadOnlyList title="Target stack" values={workspace.deployment_plan.target_stack} icon={<Cloud />} />
            <ReadOnlyList title="Scaling" values={workspace.deployment_plan.scaling_strategy} icon={<Network />} />
            <ReadOnlyList title="Observability" values={workspace.deployment_plan.observability} icon={<Braces />} />
            <ReadOnlyList title="Security controls" values={workspace.deployment_plan.security_controls} icon={<ShieldCheck />} />
          </div>
        </div>
      ) : null}

      {activeEdit ? <WorkspaceEditDialog open workspace={workspace} title={activeEdit.title} description={activeEdit.description} edit={activeEdit.edit} fields={activeEdit.fields} onClose={() => setActiveEdit(null)} /> : null}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-item"><div><strong className="text-sm">{value}</strong><small>{label}</small></div></div>
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function ReadOnlyList({ title, values, icon }: { title: string; values: string[]; icon: React.ReactNode }) {
  return <section className="panel"><div className="flex items-center gap-2 text-muted">{icon}<h3 className="panel-title text-ink">{title}</h3></div><ul className="mt-3 space-y-2 text-sm text-muted">{values.map((value) => <li key={value}>{value}</li>)}</ul>{values.length === 0 ? <div className="empty-row mt-3">Not specified.</div> : null}</section>
}
