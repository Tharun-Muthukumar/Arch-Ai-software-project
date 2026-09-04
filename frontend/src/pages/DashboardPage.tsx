import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Image, Layers3, Network } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ClarificationPanel } from '../components/workspace/ClarificationPanel'
import { StatePanel } from '../components/workspace/StatePanel'
import { WorkspaceForm } from '../components/workspace/WorkspaceForm'
import {
  answerClarifications,
  createWorkspace,
  getApiBaseUrl,
} from '../lib/api'
import { formatUpdatedAt, getActiveWorkspace, getErrorMessage } from '../lib/utils'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import type { Workspace, WorkspaceCreatePayload } from '../types/api'

const resultLinks = [
  { to: '/wizard', label: 'Requirements', icon: Layers3 },
  { to: '/architecture', label: 'Architecture', icon: Network },
  { to: '/diagrams', label: 'Diagrams', icon: Image },
  { to: '/docs', label: 'Report', icon: FileText },
]

export function DashboardPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(
    workspaceQuery.data,
    searchParams.get('workspace'),
  )
  const createMutation = useMutation({
    mutationFn: (payload: WorkspaceCreatePayload) => createWorkspace(payload),
    onSuccess: (nextWorkspace) => {
      queryClient.setQueryData<Workspace[]>(
        ['workspaces', getApiBaseUrl()],
        (currentWorkspaces) => {
          const remainingWorkspaces = (currentWorkspaces ?? []).filter(
            (item) => item.id !== nextWorkspace.id,
          )
          return [nextWorkspace, ...remainingWorkspaces]
        },
      )
      void queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/wizard?workspace=${nextWorkspace.id}`)
    },
  })

  const clarificationMutation = useMutation({
    mutationFn: (answers: Record<string, string>) => {
      if (!workspace) {
        throw new Error('No workspace is selected.')
      }
      return answerClarifications(workspace.id, answers)
    },
    onSuccess: (nextWorkspace) => {
      queryClient.setQueryData<Workspace[]>(
        ['workspaces', getApiBaseUrl()],
        (currentWorkspaces) => {
          const remainingWorkspaces = (currentWorkspaces ?? []).filter(
            (item) => item.id !== nextWorkspace.id,
          )
          return [nextWorkspace, ...remainingWorkspaces]
        },
      )
      void queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/wizard?workspace=${nextWorkspace.id}`)
    },
  })

  return (
    <div className="space-y-4">
      {workspaceQuery.isError ? (
        <StatePanel
          badge="Backend issue"
          title="Could not reach the backend"
          description={getErrorMessage(workspaceQuery.error)}
          tone="danger"
          actionLabel="Retry"
          onAction={() => void workspaceQuery.refetch()}
        />
      ) : null}

      {createMutation.isError ? (
        <StatePanel
          badge="Create failed"
          title="Workspace could not be generated"
          description={getErrorMessage(createMutation.error)}
          tone="danger"
          actionLabel="Dismiss"
          onAction={() => createMutation.reset()}
        />
      ) : null}

      {clarificationMutation.isError ? (
        <StatePanel
          badge="Update failed"
          title="Clarification answers could not be applied"
          description={getErrorMessage(clarificationMutation.error)}
          tone="danger"
          actionLabel="Dismiss"
          onAction={() => clarificationMutation.reset()}
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <WorkspaceForm
          isPending={createMutation.isPending}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />

        <div className="panel">
          {workspace ? (
            <div className="space-y-4">
              <div>
                <span className="pill">{workspace.requirements.domain}</span>
                <h2 className="mt-2 text-xl font-semibold">{workspace.title}</h2>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                  {workspace.requirements.summary}
                </p>
              </div>

              <div className="flex gap-4 text-sm">
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Recommended: </span>
                  <span className="font-medium">{workspace.recommendation.recommended_architecture_name}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Updated: </span>
                  <span className="font-medium">{formatUpdatedAt(workspace.updated_at)}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {resultLinks.map((item) => {
                  const Icon = item.icon
                  return (
                    <Link
                      key={item.to}
                      to={`${item.to}?workspace=${workspace.id}`}
                      className="button-secondary flex items-center gap-1.5 text-xs"
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {item.label}
                    </Link>
                  )
                })}
              </div>
            </div>
          ) : (
            <div>
              <h2 className="text-xl font-semibold">Your workspace will appear here</h2>
              <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>
                Enter the brief on the left to get started.
              </p>
            </div>
          )}
        </div>
      </div>

      {workspace ? (
        <div id="clarifications">
          <ClarificationPanel
            workspace={workspace}
            isPending={clarificationMutation.isPending}
            onSubmit={(answers) => clarificationMutation.mutate(answers)}
          />
        </div>
      ) : null}

      {workspace ? (
        <div id="workspace-results" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="panel">
              <span className="pill">Decision</span>
              <h3 className="mt-2 text-lg font-semibold">
                {workspace.recommendation.recommended_architecture_name}
              </h3>
              <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>
                {workspace.recommendation.decision_summary}
              </p>
              <ul className="mt-3 space-y-1 text-sm">
                {workspace.recommendation.why.slice(0, 3).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>

            <div className="panel">
              <span className="pill">Quick stats</span>
              <div className="mt-3 grid grid-cols-3 gap-3 text-center text-sm">
                <div>
                  <div className="text-lg font-semibold">{workspace.architectures.length}</div>
                  <div style={{ color: 'var(--text-muted)' }}>Architectures</div>
                </div>
                <div>
                  <div className="text-lg font-semibold">{Object.keys(workspace.diagrams).length}</div>
                  <div style={{ color: 'var(--text-muted)' }}>Diagrams</div>
                </div>
                <div>
                  <div className="text-lg font-semibold">{workspace.clarification_plan.completeness_score}%</div>
                  <div style={{ color: 'var(--text-muted)' }}>Complete</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
