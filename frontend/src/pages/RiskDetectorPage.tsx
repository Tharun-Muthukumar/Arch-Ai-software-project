import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  GitBranch,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  ShieldAlert,
  Zap,
} from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { analyzeArchitectureRisks } from '../lib/api'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type {
  ArchitectureRisk,
  ArchitectureRiskAnalysis,
  RiskCategory,
  RiskSeverity,
} from '../types/api'

type RiskFilter = RiskSeverity | 'all'
type CategoryFilter = RiskCategory | 'all'

const severityOrder: RiskSeverity[] = ['critical', 'high', 'medium', 'low', 'informational']

function analysisStorageKey(workspaceId: string, architectureId: string) {
  return `archai-risk-analysis:${workspaceId}:${architectureId}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStoredRisk(value: unknown) {
  return isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    typeof value.category === 'string' &&
    typeof value.severity === 'string' &&
    typeof value.description === 'string' &&
    typeof value.evidence === 'string' &&
    typeof value.impact === 'string' &&
    typeof value.recommendation === 'string' &&
    typeof value.confidence === 'number' &&
    typeof value.needs_verification === 'boolean' &&
    Array.isArray(value.affected_components) &&
    Array.isArray(value.related_node_ids)
}

function isStoredSummary(value: unknown) {
  return isRecord(value) &&
    ['critical', 'high', 'medium', 'low', 'informational'].every(
      (severity) => typeof value[severity] === 'number',
    )
}

function loadAnalysis(workspaceId: string, architectureId: string) {
  try {
    const raw = window.sessionStorage.getItem(analysisStorageKey(workspaceId, architectureId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    return (
      isRecord(parsed) &&
      parsed.workspace_id === workspaceId &&
      parsed.architecture_id === architectureId &&
      typeof parsed.analyzed_workspace_updated_at === 'string' &&
      typeof parsed.overview === 'string' &&
      typeof parsed.overall_risk === 'string' &&
      isStoredSummary(parsed.summary) &&
      Array.isArray(parsed.risks) &&
      parsed.risks.every(isStoredRisk)
    ) ? parsed as unknown as ArchitectureRiskAnalysis : null
  } catch {
    return null
  }
}

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

function RiskCard({
  risk,
  workspaceId,
  architectureId,
}: {
  risk: ArchitectureRisk
  workspaceId: string
  architectureId: string
}) {
  const navigate = useNavigate()
  const component = risk.affected_components[0]
  const workspaceQuery = `workspace=${encodeURIComponent(workspaceId)}`
  const componentQuery = component ? `&component=${encodeURIComponent(component)}` : ''

  return (
    <article className="risk-card">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`risk-badge risk-${risk.severity}`}>{risk.severity}</span>
            <span className="text-[10px] font-semibold uppercase text-muted">{label(risk.category)}</span>
            {risk.needs_verification ? <span className="pill">Needs verification</span> : null}
          </div>
          <h3 className="mt-2 text-base font-semibold">{risk.title}</h3>
          <p className="mt-1 text-sm leading-6 text-muted">{risk.description}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] font-semibold uppercase text-muted">Confidence</div>
          <div className="mt-1 text-sm font-semibold">{Math.round(risk.confidence * 100)}%</div>
        </div>
      </div>

      {risk.affected_components.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {risk.affected_components.map((item) => <span key={item} className="tag-chip">{item}</span>)}
        </div>
      ) : null}

      <div className="risk-detail-grid">
        <div><h4>Evidence</h4><p>{risk.evidence}</p></div>
        <div><h4>Potential impact</h4><p>{risk.impact}</p></div>
        <div><h4>Recommendation</h4><p>{risk.recommendation}</p></div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 border-t pt-3" style={{ borderColor: 'var(--border-subtle)' }}>
        {component ? (
          <button type="button" className="button-secondary gap-2" onClick={() => navigate(`/blast-radius?${workspaceQuery}${componentQuery}`)}>
            <Zap className="h-3.5 w-3.5" />
            View Blast Radius
          </button>
        ) : null}
        {risk.related_node_ids.length || component ? (
          <button type="button" className="button-secondary gap-2" onClick={() => navigate(`/causal-graph?${workspaceQuery}&architecture=${encodeURIComponent(architectureId)}${componentQuery}`)}>
            <GitBranch className="h-3.5 w-3.5" />
            View Causal Graph
          </button>
        ) : null}
        <button
          type="button"
          className="button-secondary gap-2"
          onClick={() => navigate(`/risk-detector?${workspaceQuery}&architecture=${encodeURIComponent(architectureId)}&chat=open&message=${encodeURIComponent(`How should I address the ${risk.title} risk identified by the Risk Detector?`)}`)}
        >
          <MessageSquareText className="h-3.5 w-3.5" />
          Ask AI Assistant
        </button>
      </div>
    </article>
  )
}

export function RiskDetectorPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const recommendedId = workspace?.recommendation.recommended_architecture_id ?? ''
  const requestedArchitectureId = searchParams.get('architecture')
  const architectureId = workspace?.architectures.some((item) => item.id === requestedArchitectureId)
    ? requestedArchitectureId!
    : recommendedId
  const [analysis, setAnalysis] = useState<ArchitectureRiskAnalysis | null>(null)
  const [severityFilter, setSeverityFilter] = useState<RiskFilter>('all')
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all')
  const activeAnalysisKeyRef = useRef(`${workspace?.id ?? ''}:${architectureId}`)
  activeAnalysisKeyRef.current = `${workspace?.id ?? ''}:${architectureId}`

  function storeAnalysis(result: ArchitectureRiskAnalysis) {
    window.sessionStorage.setItem(
      analysisStorageKey(result.workspace_id, result.architecture_id),
      JSON.stringify(result),
    )
    if (activeAnalysisKeyRef.current === `${result.workspace_id}:${result.architecture_id}`) {
      setAnalysis(result)
    }
  }

  useEffect(() => {
    if (!workspace?.id || !architectureId) {
      setAnalysis(null)
      return
    }
    setAnalysis(loadAnalysis(workspace.id, architectureId))
    setSeverityFilter('all')
    setCategoryFilter('all')
  }, [architectureId, workspace?.id])

  const deepAnalysisMutation = useMutation({
    mutationFn: () => analyzeArchitectureRisks(workspace!.id, architectureId, true),
    onSuccess: storeAnalysis,
  })

  const analysisMutation = useMutation({
    mutationFn: () => analyzeArchitectureRisks(workspace!.id, architectureId, false),
    onSuccess: (result) => {
      storeAnalysis(result)
      if (activeAnalysisKeyRef.current === `${result.workspace_id}:${result.architecture_id}`) {
        deepAnalysisMutation.mutate()
      }
    },
  })
  const analysisBusy = analysisMutation.isPending || deepAnalysisMutation.isPending

  const stale = Boolean(
    analysis && workspace &&
    new Date(analysis.analyzed_workspace_updated_at).getTime() !== new Date(workspace.updated_at).getTime(),
  )
  const categories = useMemo(
    () => Array.from(new Set((analysis?.risks ?? []).map((risk) => risk.category))),
    [analysis],
  )
  const visibleRisks = useMemo(
    () => (analysis?.risks ?? []).filter((risk) =>
      (severityFilter === 'all' || risk.severity === severityFilter) &&
      (categoryFilter === 'all' || risk.category === categoryFilter),
    ),
    [analysis, categoryFilter, severityFilter],
  )

  if (workspaceQuery.isLoading) {
    return <StatePanel badge="Loading" title="Loading Risk Detector" description="Preparing the current architecture." />
  }
  if (workspaceQuery.isError) {
    return <StatePanel badge="Backend issue" title="Could not load Risk Detector" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  }
  if (!workspace || !architectureId) {
    return <StatePanel badge="No architecture" title="No architecture available" description="Generate an architecture first to analyze reliability, scalability, security, and operational risks." actionLabel="Open Dashboard" actionTo="/dashboard" />
  }

  return (
    <div className="workspace-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Architecture analysis</span>
          <h2>Architecture Risk Detector</h2>
          <p>Identify reliability, scalability, security, cost, and operational risks in your architecture.</p>
        </div>
        <div className="page-actions">
          <label>
            <span className="sr-only">Architecture option</span>
            <select
              className="input-shell min-w-56"
              value={architectureId}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams)
                next.set('architecture', event.target.value)
                setSearchParams(next)
              }}
            >
              {workspace.architectures.map((architecture) => <option key={architecture.id} value={architecture.id}>{architecture.name}</option>)}
            </select>
          </label>
          <button type="button" className="button-brand gap-2" disabled={analysisBusy} onClick={() => analysisMutation.mutate()}>
            {analysisBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : analysis ? <RefreshCw className="h-4 w-4" /> : <ShieldAlert className="h-4 w-4" />}
            {analysisMutation.isPending ? 'Running fast checks...' : deepAnalysisMutation.isPending ? 'AI review running...' : analysis ? 'Re-run Analysis' : 'Analyze Architecture'}
          </button>
        </div>
      </header>

      {analysisMutation.isError ? (
        <div className="notice notice-danger" role="alert">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <div><strong>Risk analysis failed.</strong><div>{getErrorMessage(analysisMutation.error)}</div></div>
        </div>
      ) : null}

      {deepAnalysisMutation.isError && analysis ? (
        <div className="notice notice-warning" role="status">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <div><strong>Fast checks are available.</strong><div>The deeper AI review could not complete; you can retry without losing these results.</div></div>
        </div>
      ) : null}

      {deepAnalysisMutation.isPending && analysis ? (
        <div className="notice" role="status">
          <LoaderCircle className="h-4 w-4 shrink-0 animate-spin" />
          <div><strong>Structured results are ready.</strong><div>Qwen is adding a deeper evidence-grounded review in the background.</div></div>
        </div>
      ) : null}

      {stale ? (
        <div className="notice notice-warning" role="status">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1"><strong>Architecture changed since this analysis.</strong><div>Re-run the analysis before relying on these findings.</div></div>
          <button type="button" className="button-secondary gap-2" disabled={analysisBusy} onClick={() => analysisMutation.mutate()}>
            <RefreshCw className="h-3.5 w-3.5" /> Re-run
          </button>
        </div>
      ) : null}

      {!analysis && !analysisMutation.isPending ? (
        <div className="empty-feature-state min-h-[360px]">
          <ShieldAlert className="h-8 w-8" />
          <div><h3>No risk analysis yet</h3><p>Analyze the selected architecture when you are ready. Results are not generated repeatedly in the background.</p></div>
          <button type="button" className="button-brand gap-2" onClick={() => analysisMutation.mutate()}><ShieldAlert className="h-4 w-4" />Analyze Architecture</button>
        </div>
      ) : null}

      {analysisMutation.isPending && !analysis ? (
        <div className="empty-feature-state min-h-[360px]" role="status">
          <LoaderCircle className="h-8 w-8 animate-spin" />
          <div><h3>Analyzing architecture risks...</h3><p>Reviewing structured components, dependencies, deployment choices, and project requirements.</p></div>
        </div>
      ) : null}

      {analysis ? (
        <>
          <section className="panel">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2"><span className="eyebrow">Architecture health</span><span className={`risk-badge risk-${analysis.overall_risk}`}>Overall {analysis.overall_risk}</span></div>
                <p className="mt-2 max-w-4xl text-sm leading-6 text-muted">{analysis.overview}</p>
              </div>
              <ArrowRight className="hidden h-5 w-5 shrink-0 text-muted lg:block" />
            </div>
            <div className="risk-summary-grid mt-4">
              {severityOrder.map((severity) => <div key={severity}><span>{severity}</span><strong>{analysis.summary[severity]}</strong></div>)}
            </div>
          </section>

          <div className="panel flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
            <div className="text-xs font-semibold text-muted">Filter findings</div>
            <select className="input-shell sm:w-48" aria-label="Risk severity" value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value as RiskFilter)}>
              <option value="all">All severities</option>
              {severityOrder.map((severity) => <option key={severity} value={severity}>{label(severity)}</option>)}
            </select>
            <select className="input-shell sm:w-56" aria-label="Risk category" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value as CategoryFilter)}>
              <option value="all">All categories</option>
              {categories.map((category) => <option key={category} value={category}>{label(category)}</option>)}
            </select>
            <div className="ml-auto text-xs text-muted">{visibleRisks.length} of {analysis.risks.length} findings</div>
          </div>

          <div className="space-y-3">
            {visibleRisks.map((risk) => <RiskCard key={risk.id} risk={risk} workspaceId={workspace.id} architectureId={analysis.architecture_id} />)}
            {visibleRisks.length === 0 ? <div className="empty-row">No risks match these filters.</div> : null}
          </div>
        </>
      ) : null}
    </div>
  )
}
