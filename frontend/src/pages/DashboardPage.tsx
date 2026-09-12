import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, FileText, Image, Layers3, LoaderCircle, Network } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ClarificationPanel } from '../components/workspace/ClarificationPanel'
import { StatePanel } from '../components/workspace/StatePanel'
import { WorkspaceForm } from '../components/workspace/WorkspaceForm'
import {
  analyzeProjectDescription,
  answerClarifications,
  createWorkspaceStreaming,
} from '../lib/api'
import type { GenerationProgress } from '../lib/api'
import { WORKSPACE_WRITE_KEY, syncWorkspaceResult } from '../lib/workspaceSync'
import { formatUpdatedAt, getActiveWorkspace, getErrorMessage } from '../lib/utils'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import type { WorkspaceCreatePayload } from '../types/api'

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
  const [generationProgress, setGenerationProgress] = useState<GenerationProgress[]>([])
  const workspace = getActiveWorkspace(
    workspaceQuery.data,
    searchParams.get('workspace'),
  )
  const createMutation = useMutation({
    mutationKey: [...WORKSPACE_WRITE_KEY, 'create'],
    mutationFn: (payload: WorkspaceCreatePayload) => createWorkspaceStreaming(
      payload,
      (progress) => setGenerationProgress((current) => (
        current.some((item) => item.section === progress.section)
          ? current.map((item) => item.section === progress.section ? progress : item)
          : [...current, progress]
      )),
    ),
    onMutate: () => setGenerationProgress([]),
    onSuccess: (nextWorkspace) => {
      syncWorkspaceResult(queryClient, nextWorkspace)
      // Stay on the overview: Phase 2 (follow-up questions) lives here, so
      // scroll straight to it instead of sending the user to another page.
      navigate(`/dashboard?workspace=${nextWorkspace.id}#clarifications`)
      window.setTimeout(() => {
        document.getElementById('clarifications')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 150)
    },
  })

  const descriptionAnalysisMutation = useMutation({
    mutationKey: ['project-description-analysis'],
    mutationFn: analyzeProjectDescription,
  })

  const clarificationMutation = useMutation({
    mutationKey: [...WORKSPACE_WRITE_KEY, 'clarifications'],
    mutationFn: (answers: Record<string, string>) => {
      if (!workspace) {
        throw new Error('No workspace is selected.')
      }
      return answerClarifications(workspace.id, answers)
    },
    onSuccess: (nextWorkspace) => {
      syncWorkspaceResult(queryClient, nextWorkspace)
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
          isAnalyzing={descriptionAnalysisMutation.isPending}
          analysisError={descriptionAnalysisMutation.isError
            ? getErrorMessage(descriptionAnalysisMutation.error)
            : null}
          onAnalyze={(prompt) => descriptionAnalysisMutation.mutateAsync({ prompt })}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />

        <div className="panel" aria-live="polite">
          {createMutation.isPending ? (
            <div className="space-y-4">
              <div>
                <span className="pill">Generating</span>
                <h2 className="mt-2 text-xl font-semibold">Building your architecture</h2>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                  Completed sections appear here as soon as they are ready.
                </p>
              </div>
              <div className="space-y-2">
                {generationProgress.length === 0 ? (
                  <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
                    <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                    Preparing the project context…
                  </div>
                ) : null}
                {generationProgress.map((item) => (
                  <div
                    key={item.section}
                    className="rounded-md border px-3 py-2 text-sm"
                    style={{ borderColor: 'var(--card-border)', background: 'var(--bg)' }}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex items-center gap-2 capitalize">
                        <CheckCircle2 className="h-4 w-4" style={{ color: 'var(--success)' }} aria-hidden="true" />
                        {item.section.replaceAll('-', ' ')}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        {item.item_count} {item.item_count === 1 ? 'item' : 'items'}
                      </span>
                    </div>
                    {item.preview?.length ? (
                      <p className="mt-1 truncate pl-6 text-xs" style={{ color: 'var(--text-muted)' }}>
                        {item.preview.join(' · ')}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : workspace ? (
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
            <div className="flex h-full min-h-64 flex-col items-center justify-center gap-3 p-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg border" style={{ borderColor: 'var(--card-border)', background: 'var(--surface-strong)' }}>
                <Network className="h-6 w-6" style={{ color: 'var(--brand)' }} />
              </div>
              <h2 className="text-base font-semibold">Your workspace will appear here</h2>
              <p className="max-w-xs text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                Provide your requirements on the left and start generation to synthesize architectures, data models, APIs, and diagrams.
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

            <div className="panel self-start">
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
