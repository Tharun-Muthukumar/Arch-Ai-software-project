import { MessageSquareText } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'

export function RequirementWizardPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(
    workspaceQuery.data,
    searchParams.get('workspace'),
  )

  if (workspaceQuery.isLoading) {
    return <StatePanel badge="Loading" title="Loading requirements" description="Preparing the overview." />
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
        title="No requirements available"
        description="Create a project brief from the dashboard first."
        actionLabel="Open Dashboard"
        actionTo="/dashboard"
      />
    )
  }

  const { requirements } = workspace

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="panel">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="pill">{requirements.domain}</span>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {requirements.analysis_source === 'ollama-pretrained'
                  ? 'Extracted from the raw brief by Ollama'
                  : requirements.analysis_source === 'predefined-blueprint'
                    ? 'Matched predefined domain knowledge'
                    : 'Conservative fallback'}
              </span>
            </div>
            <h2 className="mt-1 text-lg font-semibold">{workspace.title}</h2>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span>{requirements.actors.length} actors</span>
            <span>&middot;</span>
            <span>{requirements.functional_requirements.length} functional</span>
            <span>&middot;</span>
            <span>{workspace.clarification_plan.completeness_score}% complete</span>
            {workspace.clarification_plan.questions.length > 0 && (
              <Link
                to={`/dashboard?workspace=${workspace.id}#clarifications`}
                className="button-secondary gap-1.5 text-xs"
              >
                <MessageSquareText className="h-3.5 w-3.5" aria-hidden="true" />
                Answer {workspace.clarification_plan.questions.length} questions
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Actors + Functional Requirements side by side */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <h3 className="text-sm font-semibold mb-2">Actors</h3>
          <ul className="space-y-2">
            {requirements.actors.map((actor) => (
              <li key={actor.name} className="flex gap-2 text-sm">
                <span className="font-medium shrink-0">{actor.name}</span>
                <span style={{ color: 'var(--text-muted)' }}>- {actor.description}</span>
              </li>
            ))}
          </ul>
          {requirements.actors.length === 0 && (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Actors are not yet known.</p>
          )}
        </div>

        <div className="panel">
          <h3 className="text-sm font-semibold mb-2">Functional Requirements</h3>
          <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
            {requirements.functional_requirements.map((req, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0" style={{ color: 'var(--brand)' }}>{i + 1}.</span>
                <span>{req}</span>
              </li>
            ))}
          </ul>
          {requirements.functional_requirements.length === 0 && (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              No functional requirements were confirmed. Add more detail to the brief.
            </p>
          )}
        </div>
      </div>

      {/* Non-functional + Constraints side by side */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <h3 className="text-sm font-semibold mb-2">Non-Functional Requirements</h3>
          <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
            {requirements.non_functional_requirements.map((req, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0" style={{ color: 'var(--brand)' }}>{i + 1}.</span>
                <span>{req}</span>
              </li>
            ))}
          </ul>
          {requirements.non_functional_requirements.length === 0 && (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              No non-functional requirements were confirmed yet.
            </p>
          )}
        </div>

        <div className="panel">
          <h3 className="text-sm font-semibold mb-2">Constraints</h3>
          <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
            {requirements.constraints.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0" style={{ color: 'var(--brand)' }}>&bull;</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
          {requirements.constraints.length === 0 && (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              No constraints were specified.
            </p>
          )}

          {requirements.assumptions.length > 0 && (
            <>
              <h3 className="text-sm font-semibold mt-4 mb-2">Assumptions</h3>
              <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                {requirements.assumptions.map((a, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="shrink-0" style={{ color: 'var(--brand)' }}>&bull;</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      {(requirements.domain_entities.length > 0
        || requirements.integrations.length > 0
        || requirements.data_characteristics.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="panel">
            <h3 className="mb-2 text-sm font-semibold">Domain Entities</h3>
            <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
              {requirements.domain_entities.map((entity) => <li key={entity.name}>{entity.name}</li>)}
            </ul>
          </div>
          <div className="panel">
            <h3 className="mb-2 text-sm font-semibold">Integrations</h3>
            {requirements.integrations.length > 0 ? (
              <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                {requirements.integrations.map((integration) => <li key={integration}>{integration}</li>)}
              </ul>
            ) : <p className="text-sm" style={{ color: 'var(--text-muted)' }}>None confirmed.</p>}
          </div>
          <div className="panel">
            <h3 className="mb-2 text-sm font-semibold">Data Characteristics</h3>
            {requirements.data_characteristics.length > 0 ? (
              <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                {requirements.data_characteristics.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Not specified.</p>}
          </div>
        </div>
      )}

      {requirements.analysis_warnings.length > 0 && (
        <div className="panel border-amber-500/50">
          <h3 className="mb-2 text-sm font-semibold">Extraction Warnings</h3>
          <ul className="space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
            {requirements.analysis_warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
