import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Building2, Sparkles } from 'lucide-react'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { fetchTwinMatches } from '../lib/api'
import { comparisonMatrix, deploymentStack } from '../lib/insightInputs'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type { TwinMatch } from '../types/api'

const WEIGHT_STORAGE_KEY = 'archai-insight-weights'

function savedWeights(): Record<string, number> | undefined {
  try {
    const value = window.localStorage.getItem(WEIGHT_STORAGE_KEY)
    return value ? JSON.parse(value) as Record<string, number> : undefined
  } catch {
    return undefined
  }
}

function formatMetricName(metric: string) {
  return metric.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

export function IndustryTwinsPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const [matches, setMatches] = useState<TwinMatch[]>([])
  const [weights, setWeights] = useState<Record<string, number> | undefined>(savedWeights)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const recommended = useMemo(() => workspace && (workspace.architectures.find((architecture) => architecture.id === workspace.recommendation.recommended_architecture_id) ?? workspace.architectures[0]), [workspace])
  const matrix = useMemo(() => workspace ? comparisonMatrix(workspace) : {}, [workspace])
  const stack = useMemo(() => workspace ? deploymentStack(workspace) : [], [workspace])

  useEffect(() => {
    const onWeightsChanged = (event: Event) => setWeights((event as CustomEvent<Record<string, number>>).detail)
    window.addEventListener('archai:weights-changed', onWeightsChanged)
    return () => window.removeEventListener('archai:weights-changed', onWeightsChanged)
  }, [])

  useEffect(() => {
    if (!recommended) return
    let active = true
    setIsLoading(true)
    setError('')
    fetchTwinMatches({ comparison_matrix: matrix, recommended_architecture_id: recommended.id, deployment_stack: stack, weights }).then((response) => {
      if (active) setMatches(response)
    }).catch((requestError) => {
      if (active) setError(getErrorMessage(requestError))
    }).finally(() => {
      if (active) setIsLoading(false)
    })
    return () => { active = false }
  }, [matrix, recommended, stack, weights])

  if (workspaceQuery.isLoading) return <StatePanel badge="Loading" title="Loading industry precedents" description="Preparing public architecture precedents." />
  if (workspaceQuery.isError) return <StatePanel badge="Backend issue" title="Could not reach the backend" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  if (!workspace || !recommended) return <StatePanel badge="No workspace" title="No architecture available" description="Create a project brief from the dashboard first." actionLabel="Open Dashboard" actionTo="/dashboard" />

  return <div className="space-y-5">
    <div className="panel"><div className="flex items-center gap-2"><Building2 className="h-5 w-5" style={{ color: 'var(--brand)' }} /><h2 className="text-lg font-semibold">Industry Precedents</h2></div><p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>Public, high-level precedents closest to the score profile for <strong>{recommended.name}</strong>. Each match names the most similar metrics with both scores. Similarity is deterministic and updates with What-If weights.</p><p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>A similarity score is an algorithmic distance between your architecture&apos;s metric scores and our estimate for each public case — not a measurement of that company&apos;s internal systems, which are not known.</p></div>
    {isLoading && <div className="panel text-sm" style={{ color: 'var(--text-muted)' }}>Matching public case studies...</div>}
    {error && <div className="panel text-sm text-red-600 dark:text-red-300">{error}</div>}
    <div className="grid gap-4 lg:grid-cols-3">{matches.map((match, index) => <article key={match.case_study.id} className={`panel ${index === 0 ? 'border-2 border-amber-400 lg:col-span-1' : ''}`}><div className="flex items-start justify-between gap-2"><div>{index === 0 && <span className="mb-2 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-200"><Sparkles className="h-3 w-3" />Closest match</span>}<h3 className="font-semibold">{match.case_study.company}</h3><p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>{match.case_study.summary}</p></div><span className="shrink-0 rounded-full bg-green-100 px-2 py-1 text-sm font-bold text-green-800 dark:bg-green-950 dark:text-green-200">{match.similarity_score}%</span></div><p className="mt-4 text-sm">{match.rationale}</p>{match.similar_metrics && match.similar_metrics.length > 0 && <div className="mt-3 rounded-lg border p-3" style={{ borderColor: 'var(--card-border)' }}><div className="text-xs font-semibold">Most similar metrics</div><ul className="mt-2 space-y-1.5 text-xs">{match.similar_metrics.map((metric) => <li key={metric.metric} className="flex items-center justify-between gap-2"><span>{formatMetricName(metric.metric)}</span><span className="tabular-nums" style={{ color: 'var(--text-muted)' }}>you {metric.user_score}/10 · {match.case_study.company} {metric.case_score}/10{metric.delta === 0 ? ' · exact' : ` · Δ${metric.delta}`}</span></li>)}</ul></div>}<div className="mt-3 flex flex-wrap gap-1.5">{match.case_study.notable_services.map((service) => <span key={service} className={`rounded-full border px-2 py-0.5 text-xs ${match.overlap_services.includes(service) ? 'border-amber-400 bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' : ''}`} style={match.overlap_services.includes(service) ? undefined : { borderColor: 'var(--card-border)', color: 'var(--text-muted)' }}>{service}</span>)}</div><div className="mt-4 border-t pt-3 text-sm" style={{ borderColor: 'var(--card-border)' }}><span className="font-medium">Lesson: </span>{match.case_study.lesson}</div><p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>{match.case_study.source_note}</p></article>)}</div>
  </div>
}
