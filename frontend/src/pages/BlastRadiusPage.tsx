import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Zap, RotateCcw, Shield, ArrowRight, ChevronDown, ChevronUp } from 'lucide-react'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import { simulateBlastRadius, fetchResilienceRecommendations, applyMitigations } from '../lib/api'
import type { BlastRadiusResult, ResilienceRecommendation } from '../types/api'

const CATEGORY_COLORS: Record<string, string> = {
  isolation: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  redundancy: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  resilience: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
}

export function BlastRadiusPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))

  const [result, setResult] = useState<BlastRadiusResult | null>(null)
  const [loadingComponent, setLoadingComponent] = useState<string | null>(null)
  const [rippleOrigin, setRippleOrigin] = useState<string | null>(null)
  const [comparisonResults, setComparisonResults] = useState<Record<string, number>>({})

  // Resilience recommendations state
  const [recommendations, setRecommendations] = useState<ResilienceRecommendation[]>([])
  const [selectedMitigations, setSelectedMitigations] = useState<Set<string>>(new Set())
  const [modifiedResult, setModifiedResult] = useState<BlastRadiusResult | null>(null)
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [loadingApply, setLoadingApply] = useState(false)
  const [showBeforeAfter, setShowBeforeAfter] = useState(false)
  const [recommendationsExpanded, setRecommendationsExpanded] = useState(true)

  const recommended = useMemo(() => {
    if (!workspace) return null
    return workspace.architectures.find(a => a.id === workspace.recommendation.recommended_architecture_id) ?? workspace.architectures[0]
  }, [workspace])

  const comparisonMatrix = useMemo(() => {
    if (!workspace) return {}
    const matrix: Record<string, Record<string, number>> = {}
    for (const sc of workspace.comparison.scorecards) {
      matrix[sc.architecture_id] = {}
      for (const ms of sc.metric_scores) {
        matrix[sc.architecture_id][ms.metric] = ms.score
      }
    }
    return matrix
  }, [workspace])

  const handleComponentClick = useCallback(async (componentName: string) => {
    if (!recommended || !workspace) return

    if (result?.failed_component === componentName) {
      resetAll()
      return
    }

    setLoadingComponent(componentName)
    setRippleOrigin(null)
    resetResilienceState()

    try {
      const blastResult = await simulateBlastRadius({
        architecture: recommended,
        failed_component: componentName,
        comparison_matrix: comparisonMatrix,
      })
      setResult(blastResult)
      setRippleOrigin(componentName)

      // Fetch resilience recommendations (non-blocking)
      setLoadingRecommendations(true)
      fetchResilienceRecommendations({
        blast_result: blastResult,
        architecture: recommended,
      }).then(recs => {
        setRecommendations(recs)
      }).catch(() => {}).finally(() => setLoadingRecommendations(false))

      // Fire comparison calls for other architectures (non-blocking)
      const otherArchs = workspace.architectures.filter(a => a.id !== recommended.id)
      for (const arch of otherArchs) {
        const role = recommended.components.find(c => c.name === componentName)?.responsibility
        const matchingComponent = arch.components.find(c => {
          const cLower = c.name.toLowerCase()
          const rLower = (role ?? '').toLowerCase()
          return cLower.includes(componentName.toLowerCase().split(' ')[0]) ||
                 rLower.includes(c.name.toLowerCase().split(' ')[0])
        })
        if (matchingComponent) {
          simulateBlastRadius({
            architecture: arch,
            failed_component: matchingComponent.name,
            comparison_matrix: comparisonMatrix,
          }).then(otherResult => {
            setComparisonResults(prev => ({ ...prev, [arch.id]: otherResult.severity_score }))
          }).catch(() => {})
        }
      }
    } catch {
      // Silently handle errors
    } finally {
      setLoadingComponent(null)
    }
  }, [recommended, workspace, comparisonMatrix, result])

  const resetResilienceState = useCallback(() => {
    setRecommendations([])
    setSelectedMitigations(new Set())
    setModifiedResult(null)
    setShowBeforeAfter(false)
  }, [])

  const resetAll = useCallback(() => {
    setResult(null)
    setRippleOrigin(null)
    setComparisonResults({})
    resetResilienceState()
  }, [resetResilienceState])

  const toggleMitigation = useCallback((id: string) => {
    setSelectedMitigations(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
    // Clear previous apply result when toggles change
    setModifiedResult(null)
    setShowBeforeAfter(false)
  }, [])

  const handleApplyMitigations = useCallback(async () => {
    if (!result || !recommended || selectedMitigations.size === 0) return

    setLoadingApply(true)
    try {
      const modified = await applyMitigations({
        blast_result: result,
        selected_mitigation_ids: Array.from(selectedMitigations),
        architecture: recommended,
      })
      setModifiedResult(modified)
      setShowBeforeAfter(true)
    } catch {
      // Silently handle errors
    } finally {
      setLoadingApply(false)
    }
  }, [result, recommended, selectedMitigations])

  const totalSeverityReduction = useMemo(() => {
    return recommendations
      .filter(r => selectedMitigations.has(r.id))
      .reduce((sum, r) => sum + r.severity_reduction, 0)
  }, [recommendations, selectedMitigations])

  // Clear ripple after animation completes
  useEffect(() => {
    if (!rippleOrigin) return
    const timer = setTimeout(() => setRippleOrigin(null), 800)
    return () => clearTimeout(timer)
  }, [rippleOrigin])

  if (workspaceQuery.isLoading) {
    return <StatePanel badge="Loading" title="Loading blast radius" description="Preparing the simulator." />
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

  if (!recommended) {
    return (
      <StatePanel badge="No recommendation" title="No recommended architecture" description="Complete the comparison step first." actionLabel="Open Dashboard" actionTo="/dashboard" />
    )
  }

  const getStatusStyle = (componentName: string, overrideResult?: BlastRadiusResult | null) => {
    const r = overrideResult ?? result
    if (!r) return 'border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-amber-400 dark:hover:border-amber-500 cursor-pointer'

    const status = r.statuses.find(s => s.component === componentName)
    if (componentName === r.failed_component) {
      return 'border-2 border-red-500 bg-red-50 dark:bg-red-950/50 ring-2 ring-red-300 dark:ring-red-700'
    }
    if (status?.status === 'down') {
      return 'border-2 border-red-400 bg-red-50 dark:bg-red-950/30'
    }
    if (status?.status === 'degraded') {
      return 'border-2 border-amber-400 bg-amber-50 dark:bg-amber-950/30'
    }
    return 'border border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-950/20'
  }

  const getStatusIcon = (componentName: string, overrideResult?: BlastRadiusResult | null) => {
    const r = overrideResult ?? result
    if (!r) return null
    if (componentName === r.failed_component) {
      return <Zap className="h-4 w-4 text-red-500 shrink-0" />
    }
    const status = r.statuses.find(s => s.component === componentName)
    if (status?.status === 'down') return <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
    if (status?.status === 'degraded') return <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
    return null
  }

  const getSeverityColor = (score: number) => {
    if (score <= 3) return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
    if (score <= 6) return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200'
    return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
  }

  const renderComponentGrid = (overrideResult: BlastRadiusResult | null, label?: string) => (
    <div className="panel">
      {label && <h3 className="text-sm font-semibold mb-3">{label}</h3>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {recommended.components.map(component => {
          const r = overrideResult
          const isLoading = !overrideResult && loadingComponent === component.name

          return (
            <div
              key={component.name}
              className={`relative rounded-lg p-2.5 text-left transition-all duration-200 ${getStatusStyle(component.name, overrideResult)} ${!overrideResult && isLoading ? 'animate-pulse' : ''}`}
            >
              <div className="flex items-start gap-2">
                {getStatusIcon(component.name, overrideResult)}
                <div className="min-w-0">
                  <div className="text-xs font-medium truncate">{component.name}</div>
                  <div className="mt-0.5 text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>
                    {component.technologies.slice(0, 2).join(', ')}
                  </div>
                </div>
              </div>
              {r && r.failed_component !== component.name && (() => {
                const status = r.statuses.find(s => s.component === component.name)
                if (status?.reason) {
                  return (
                    <div className="mt-1 text-[10px] leading-tight" style={{ color: 'var(--text-muted)' }}>
                      {status.reason}
                    </div>
                  )
                }
                return null
              })()}
            </div>
          )
        })}
      </div>
    </div>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="panel">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5" style={{ color: 'var(--brand)' }} />
          <h2 className="text-lg font-semibold">Blast Radius Simulator</h2>
        </div>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
          Click any component in <strong>{recommended.name}</strong> to simulate a failure and see
          which other components would be affected. All computations are deterministic and rule-based.
        </p>
      </div>

      {/* Component grid */}
      <div className="panel">
        <h3 className="text-sm font-semibold mb-4">Architecture components</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {recommended.components.map(component => {
            const isLoading = loadingComponent === component.name
            const hasResult = result !== null
            const isClickable = !hasResult || result?.failed_component !== component.name

            return (
              <button
                key={component.name}
                type="button"
                onClick={() => { if (isClickable && !isLoading) void handleComponentClick(component.name) }}
                disabled={isLoading}
                className={`relative rounded-lg p-3 text-left transition-all duration-200 ${getStatusStyle(component.name)} ${isLoading ? 'animate-pulse' : ''} ${isClickable && !isLoading && !hasResult ? 'hover:shadow-md' : ''} ${rippleOrigin === component.name ? 'blast-ripple' : ''}`}
              >
                <div className="flex items-start gap-2">
                  {getStatusIcon(component.name)}
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{component.name}</div>
                    <div className="mt-0.5 text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                      {component.technologies.slice(0, 2).join(', ')}
                    </div>
                  </div>
                </div>
                {result && result.failed_component !== component.name && (
                  (() => {
                    const status = result.statuses.find(s => s.component === component.name)
                    if (status?.reason) {
                      return (
                        <div className="mt-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
                          {status.reason}
                        </div>
                      )
                    }
                    return null
                  })()
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Results panel */}
      {result && (
        <>
          {/* Impact summary */}
          <div className="panel">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold">Impact summary</h3>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                  {result.impact_summary}
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <div className="text-center">
                  <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>Severity</div>
                  <div className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-bold ${getSeverityColor(result.severity_score)}`}>
                    {result.severity_score}/10
                  </div>
                </div>
                <button
                  type="button"
                  onClick={resetAll}
                  className="button-secondary flex items-center gap-1.5 text-xs"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset
                </button>
              </div>
            </div>
          </div>

          {/* Resilience Recommendations */}
          {(recommendations.length > 0 || loadingRecommendations) && (
            <div className="panel">
              <button
                type="button"
                onClick={() => setRecommendationsExpanded(!recommendationsExpanded)}
                className="w-full flex items-center justify-between"
              >
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4" style={{ color: 'var(--brand)' }} />
                  <h3 className="text-sm font-semibold">Resilience Recommendations</h3>
                  {selectedMitigations.size > 0 && (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                      {selectedMitigations.size} selected
                    </span>
                  )}
                </div>
                {recommendationsExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>

              {recommendationsExpanded && (
                <div className="mt-4 space-y-3">
                  {loadingRecommendations && (
                    <div className="text-xs py-2" style={{ color: 'var(--text-muted)' }}>
                      Analyzing failure patterns...
                    </div>
                  )}

                  {!loadingRecommendations && recommendations.length === 0 && (
                    <div className="text-xs py-2" style={{ color: 'var(--text-muted)' }}>
                      No additional mitigations applicable for this failure scenario.
                    </div>
                  )}

                  {recommendations.map(rec => (
                    <div
                      key={rec.id}
                      className={`flex items-start gap-3 rounded-lg border p-3 transition-all cursor-pointer ${
                        selectedMitigations.has(rec.id)
                          ? 'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-950/30'
                          : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                      }`}
                      onClick={() => toggleMitigation(rec.id)}
                    >
                      <input
                        type="checkbox"
                        checked={selectedMitigations.has(rec.id)}
                        onChange={() => toggleMitigation(rec.id)}
                        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        onClick={(e) => e.stopPropagation()}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium">{rec.name}</span>
                          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${CATEGORY_COLORS[rec.category] ?? 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200'}`}>
                            {rec.category}
                          </span>
                          <span className="text-[10px] font-medium text-green-700 dark:text-green-300">
                            -{rec.severity_reduction} severity
                          </span>
                        </div>
                        <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                          {rec.description}
                        </p>
                      </div>
                    </div>
                  ))}

                  {/* Apply button + running total */}
                  {selectedMitigations.size > 0 && (
                    <div className="flex items-center justify-between pt-2 border-t border-gray-200 dark:border-gray-700">
                      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        <span className="font-medium">Total reduction:</span>{' '}
                        <span className="text-green-700 dark:text-green-300 font-semibold">
                          -{totalSeverityReduction.toFixed(1)} points
                        </span>
                        <span className="ml-2">
                          ({result.severity_score.toFixed(1)} → {Math.max(0, result.severity_score - totalSeverityReduction).toFixed(1)})
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleApplyMitigations()}
                        disabled={loadingApply}
                        className="button-primary flex items-center gap-1.5 text-xs"
                      >
                        {loadingApply ? 'Applying...' : 'Compare Before / After'}
                        {!loadingApply && <ArrowRight className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Before / After comparison */}
          {showBeforeAfter && modifiedResult && (
            <div className="panel">
              <h3 className="text-sm font-semibold mb-3">Before / After comparison</h3>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {/* Before */}
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>Before</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${getSeverityColor(result.severity_score)}`}>
                      {result.severity_score}/10
                    </span>
                  </div>
                  {renderComponentGrid(result)}
                </div>
                {/* After */}
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>After</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${getSeverityColor(modifiedResult.severity_score)}`}>
                      {modifiedResult.severity_score}/10
                    </span>
                    {modifiedResult.severity_score < result.severity_score && (
                      <span className="text-[10px] font-medium text-green-700 dark:text-green-300">
                        (-{(result.severity_score - modifiedResult.severity_score).toFixed(1)})
                      </span>
                    )}
                  </div>
                  {renderComponentGrid(modifiedResult)}
                </div>
              </div>

              {/* Status change summary */}
              <div className="mt-4 pt-3 border-t border-gray-200 dark:border-gray-700">
                <h4 className="text-xs font-semibold mb-2">Status changes</h4>
                <div className="space-y-1">
                  {modifiedResult.statuses.map((afterStatus, idx) => {
                    const beforeStatus = result.statuses[idx]
                    if (!beforeStatus || beforeStatus.status === afterStatus.status) return null
                    return (
                      <div key={afterStatus.component} className="flex items-center gap-2 text-xs">
                        <span className="font-medium">{afterStatus.component}</span>
                        <span className={beforeStatus.status === 'down' ? 'text-red-500' : 'text-amber-500'}>
                          {beforeStatus.status}
                        </span>
                        <ArrowRight className="h-3 w-3" style={{ color: 'var(--text-muted)' }} />
                        <span className={afterStatus.status === 'degraded' ? 'text-amber-600 dark:text-amber-400' : 'text-green-600 dark:text-green-400'}>
                          {afterStatus.status}
                        </span>
                        {afterStatus.reason && (
                          <span style={{ color: 'var(--text-muted)' }}>({afterStatus.reason})</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Cross-architecture comparison */}
          {Object.keys(comparisonResults).length > 0 && (
            <div className="panel">
              <h3 className="text-sm font-semibold mb-3">Cross-architecture comparison</h3>
              <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
                How the same failure role would impact other architecture styles:
              </p>
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <span className="text-sm w-48 truncate">{recommended.name}</span>
                  <div className="flex-1 h-5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${getSeverityColor(result.severity_score)}`}
                      style={{ width: `${result.severity_score * 10}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium w-12 text-right">{result.severity_score}</span>
                </div>
                {workspace.architectures
                  .filter(a => a.id !== recommended.id && comparisonResults[a.id] !== undefined)
                  .map(arch => {
                    const score = comparisonResults[arch.id]
                    return (
                      <div key={arch.id} className="flex items-center gap-3">
                        <span className="text-sm w-48 truncate" style={{ color: 'var(--text-muted)' }}>{arch.name}</span>
                        <div className="flex-1 h-5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${getSeverityColor(score)}`}
                            style={{ width: `${score * 10}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium w-12 text-right">{score}</span>
                      </div>
                    )
                  })}
              </div>
            </div>
          )}
        </>
      )}

      {/* Instructions when no result */}
      {!result && (
        <div className="panel border-dashed" style={{ borderColor: 'var(--card-border)' }}>
          <div className="text-center py-8">
            <Zap className="h-8 w-8 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              Click a component above to simulate a failure and see the blast radius.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
