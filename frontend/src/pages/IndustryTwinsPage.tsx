import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Building2, Sparkles } from 'lucide-react'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { fetchTwinMatches } from '../lib/api'
import { comparisonMatrix, deploymentStack } from '../lib/insightInputs'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type { TwinMatch } from '../types/api'

function savedWeights(workspaceId?: string): Record<string, number> | undefined {
  if (!workspaceId) return undefined
  try {
    const value = window.localStorage.getItem(`archai-insight-weights:${workspaceId}`)
    return value ? JSON.parse(value) as Record<string, number> : undefined
  } catch {
    return undefined
  }
}

function formatMetricName(metric: string) {
  return metric.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function similarityText(match: TwinMatch, dimension: string, value: number | null | undefined) {
  return match.dimension_evidence?.[dimension] === false || value == null
    ? 'insufficient public evidence'
    : `${Math.round(value)}%`
}

function matchLabel(match: TwinMatch) {
  if (match.match_strength === 'strong') return 'Strong domain match'
  if (match.match_strength === 'domain-relevant') return 'Domain-relevant precedent'
  if (match.match_strength === 'best-available') return 'Best available match (weak domain evidence)'
  return 'Architecture precedent only'
}

export function IndustryTwinsPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const [matches, setMatches] = useState<TwinMatch[]>([])
  const [weights, setWeights] = useState<Record<string, number> | undefined>()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const recommended = useMemo(() => workspace && (workspace.architectures.find((architecture) => architecture.id === workspace.recommendation.recommended_architecture_id) ?? workspace.architectures[0]), [workspace])
  const matrix = useMemo(() => workspace ? comparisonMatrix(workspace) : {}, [workspace])
  const stack = useMemo(() => workspace ? deploymentStack(workspace) : [], [workspace])

  useEffect(() => {
    const onWeightsChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ workspaceId: string; weights: Record<string, number> }>).detail
      if (detail.workspaceId === workspace?.id) setWeights(detail.weights)
    }
    window.addEventListener('archai:weights-changed', onWeightsChanged)
    return () => window.removeEventListener('archai:weights-changed', onWeightsChanged)
  }, [workspace?.id])

  useEffect(() => {
    setMatches([])
    setWeights(savedWeights(workspace?.id))
  }, [workspace?.id])

  useEffect(() => {
    if (!recommended) return
    let active = true
    setIsLoading(true)
    setError('')
    fetchTwinMatches({
      comparison_matrix: matrix,
      recommended_architecture_id: recommended.id,
      deployment_stack: stack,
      weights,
      domain: workspace?.requirements.domain ?? '',
      domain_signals: workspace?.requirements.domain_entities.map((entity) => entity.name) ?? [],
      capability_signals: workspace?.requirements.domain_workflows.flatMap((item) => [item.name, item.description]) ?? [],
      workload_signals: workspace ? [
        ...workspace.requirements.non_functional_requirements,
        workspace.requirements.project_profile?.workload_variability ?? '',
      ] : [],
      data_signals: workspace?.requirements.technical_characteristics?.map((item) => `${item.category} ${item.value}`) ?? [],
      reliability_signals: workspace?.requirements.non_functional_requirements ?? [],
      integration_signals: workspace?.requirements.integration_details?.flatMap((item) => [
        item.name, item.interaction_mode, ...item.protocol, ...item.data_formats,
      ]) ?? [],
      project_profile: workspace?.requirements.project_profile,
    }).then((response) => {
      if (active) setMatches(response)
    }).catch((requestError) => {
      if (active) setError(getErrorMessage(requestError))
    }).finally(() => {
      if (active) setIsLoading(false)
    })
    return () => { active = false }
  }, [matrix, recommended, stack, weights, workspace])

  if (workspaceQuery.isLoading) return <StatePanel badge="Loading" title="Loading industry precedents" description="Preparing public architecture precedents." />
  if (workspaceQuery.isError) return <StatePanel badge="Backend issue" title="Could not reach the backend" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  if (!workspace || !recommended) return <StatePanel badge="No workspace" title="No architecture available" description="Create a project brief from the dashboard first." actionLabel="Open Dashboard" actionTo="/dashboard" />

  return <div className="space-y-5">
    <div className="panel"><div className="flex items-center gap-2"><Building2 className="h-5 w-5" style={{ color: 'var(--brand)' }} /><h2 className="text-lg font-semibold">Industry &amp; Architecture Precedents</h2></div><p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>Public, high-level precedents ranked by domain evidence first, then by the decision profile for <strong>{recommended.name}</strong>. When no strong domain precedent exists, the first card is explicitly marked as the best available weak match.</p><p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>Every percentage is algorithmic similarity, not a factual measurement or a claim about private company systems. Industry, architecture, and technology precedent scores are evaluated separately.</p></div>
    {isLoading && <div className="panel text-sm" style={{ color: 'var(--text-muted)' }}>Matching public case studies...</div>}
    {error && <div className="panel text-sm text-red-600 dark:text-red-300">{error}</div>}
    <div className="grid gap-4 lg:grid-cols-3">{matches.map((match, index) => <article key={match.case_study.id} className={`panel ${index === 0 ? 'border-2 border-amber-400 lg:col-span-1' : ''}`}><div className="flex items-start justify-between gap-2"><div><span className="mb-2 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-200"><Sparkles className="h-3 w-3" />{matchLabel(match)}</span><h3 className="font-semibold">{match.case_study.company}</h3><p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>{match.case_study.summary}</p></div><span className="shrink-0 rounded-full bg-green-100 px-2 py-1 text-sm font-bold text-green-800 dark:bg-green-950 dark:text-green-200">Industry {similarityText(match, 'industry', match.industry_similarity)}</span></div><div className="mt-3 grid grid-cols-2 gap-1.5 text-xs" style={{ color: 'var(--text-muted)' }}><strong>Overall model {Math.round(match.similarity_score)}%</strong><strong>Architecture {similarityText(match, 'architecture', match.architecture_precedent_similarity)}</strong><span>Technology {similarityText(match, 'technology', match.technology_precedent_similarity)}</span><span>Domain {similarityText(match, 'domain', match.domain_similarity)}</span><span>Capabilities {similarityText(match, 'capability', match.capability_similarity)}</span><span>Workload {similarityText(match, 'workload', match.workload_similarity)}</span><span>Scale {similarityText(match, 'scale', match.scale_similarity)}</span><span>Data {similarityText(match, 'data', match.data_similarity)}</span><span>Reliability {similarityText(match, 'reliability', match.reliability_similarity)}</span><span>Integrations {similarityText(match, 'integration', match.integration_similarity)}</span></div><p className="mt-4 text-sm">{match.rationale}</p>{match.similar_metrics && match.similar_metrics.length > 0 && <div className="mt-3 rounded-lg border p-3" style={{ borderColor: 'var(--card-border)' }}><div className="text-xs font-semibold">Most similar metrics</div><ul className="mt-2 space-y-1.5 text-xs">{match.similar_metrics.map((metric) => <li key={metric.metric} className="flex items-center justify-between gap-2"><span>{formatMetricName(metric.metric)}</span><span className="tabular-nums" style={{ color: 'var(--text-muted)' }}>you {metric.user_score}/10 · {match.case_study.company} {metric.case_score}/10{metric.delta === 0 ? ' · exact' : ` · Δ${metric.delta}`}</span></li>)}</ul></div>}<div className="mt-3 flex flex-wrap gap-1.5">{match.case_study.notable_services.map((service) => <span key={service} className={`rounded-full border px-2 py-0.5 text-xs ${match.overlap_services.includes(service) ? 'border-amber-400 bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' : ''}`} style={match.overlap_services.includes(service) ? undefined : { borderColor: 'var(--card-border)', color: 'var(--text-muted)' }}>{service}</span>)}</div><div className="mt-4 border-t pt-3 text-sm" style={{ borderColor: 'var(--card-border)' }}><span className="font-medium">Lesson: </span>{match.case_study.lesson}</div><p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>{match.evidence_notice} Evidence type: {match.case_study.evidence_type ?? 'public engineering summary'} ({match.case_study.evidence_confidence ?? 'medium'} confidence). {match.case_study.source_note}</p></article>)}</div>
  </div>
}
