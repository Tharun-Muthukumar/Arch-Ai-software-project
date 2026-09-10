import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
} from 'recharts'
import { reweightArchitectures } from '../../lib/api'
import { formatMetricName } from '../../lib/utils'
import { chartTheme } from '../../lib/chartTheme'
import { metricUtility } from '../../lib/architectureMetrics'
import type {
  ComparisonResult,
  ArchitectureScorecard,
} from '../../types/api'

interface WhatIfPlaygroundProps {
  workspaceId: string
  comparison: ComparisonResult
  onRankingChange?: (scorecards: ArchitectureScorecard[]) => void
}

const METRICS = [
  'scalability', 'performance', 'maintainability', 'security',
  'cost', 'reliability', 'availability', 'deployment_complexity',
  'learning_curve', 'development_time', 'fault_isolation', 'operational_complexity',
] as const

const DEFAULT_WEIGHTS: Record<string, number> = Object.fromEntries(
  METRICS.map((m) => [m, 1.0]),
)
const weightStorageKey = (workspaceId: string) => `archai-insight-weights:${workspaceId}`

// No budget-driven presets: Cost remains only as an architecture trade-off
// slider alongside the other criteria. Exploratory reweighting is manual so
// saved recommendations are never silently replaced by a preset.

const COLORS = ['#b45309', '#2563eb', '#16a34a', '#9333ea', '#dc2626']

export function WhatIfPlayground({ workspaceId, comparison, onRankingChange }: WhatIfPlaygroundProps) {
  const [weights, setWeights] = useState<Record<string, number>>(() => {
    try {
      const saved = window.localStorage.getItem(weightStorageKey(workspaceId))
      return saved ? JSON.parse(saved) as Record<string, number> : DEFAULT_WEIGHTS
    } catch {
      return DEFAULT_WEIGHTS
    }
  })
  const [rankedScorecards, setRankedScorecards] = useState<ArchitectureScorecard[]>(
    comparison.scorecards,
  )
  const [isPending, setIsPending] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const matrix = useMemo(() => {
    const m: Record<string, Record<string, number>> = {}
    for (const sc of comparison.scorecards) {
      m[sc.architecture_id] = {}
      for (const ms of sc.metric_scores) {
        m[sc.architecture_id][ms.metric] = ms.score
      }
    }
    return m
  }, [comparison])

  const fetchReweighted = useCallback(
    async (currentWeights: Record<string, number>) => {
      window.localStorage.setItem(weightStorageKey(workspaceId), JSON.stringify(currentWeights))
      window.dispatchEvent(new CustomEvent('archai:weights-changed', {
        detail: { workspaceId, weights: currentWeights },
      }))
      setIsPending(true)
      try {
        const result = await reweightArchitectures({
          matrix,
          weights: { weights: currentWeights },
        })
        setRankedScorecards(result)
        onRankingChange?.(result)
      } catch {
        // Silently ignore — keep previous ranking on network failure
      } finally {
        setIsPending(false)
      }
    },
    [matrix, onRankingChange, workspaceId],
  )

  const handleWeightChange = useCallback(
    (metric: string, value: number) => {
      const next = { ...weights, [metric]: value }
      setWeights(next)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => fetchReweighted(next), 150)
    },
    [weights, fetchReweighted],
  )

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // Resync instantly when the workspace regenerates (edits, clarifications):
  // the ranking must reflect the new scorecards, not the previous revision.
  useEffect(() => {
    setRankedScorecards(comparison.scorecards)
  }, [comparison])

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(weightStorageKey(workspaceId))
      setWeights(saved ? JSON.parse(saved) as Record<string, number> : DEFAULT_WEIGHTS)
    } catch {
      setWeights(DEFAULT_WEIGHTS)
    }
  }, [workspaceId])

  const resetWeights = useCallback(() => {
    setWeights(DEFAULT_WEIGHTS)
    fetchReweighted(DEFAULT_WEIGHTS)
  }, [fetchReweighted])

  const radarData = useMemo(() => {
    return METRICS.map((metric) => {
      const row: Record<string, number | string> = { metric: formatMetricName(metric) }
      for (const sc of rankedScorecards) {
        const ms = sc.metric_scores.find((m) => m.metric === metric)
        row[sc.architecture_name] = ms ? metricUtility(ms) : 0
      }
      return row
    })
  }, [rankedScorecards])

  const barData = useMemo(() => {
    return rankedScorecards.map((sc) => ({
      name: sc.architecture_name,
      score: sc.overall_score,
    }))
  }, [rankedScorecards])

  return (
    <div className="space-y-4">
      <div className="panel">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="pill">What-If Playground</span>
            <h3 className="mt-2 font-semibold">Adjust criteria weights</h3>
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              Drag sliders to explore how different priorities change the architecture ranking.
            </p>
            <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
              This is an exploratory ranking. It does not silently replace the saved recommendation or ADR.
            </p>
          </div>
          {isPending && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Updating…
            </span>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={resetWeights}
            className="button-secondary text-xs"
          >
            Reset weights
          </button>
        </div>

        <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          {METRICS.map((metric) => (
            <label key={metric} className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium">{formatMetricName(metric)}</span>
                <span
                  className="tabular-nums"
                  style={{ color: 'var(--text-muted)', minWidth: '2rem', textAlign: 'right' }}
                >
                  {weights[metric]?.toFixed(1) ?? '1.0'}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={3}
                step={0.1}
                value={weights[metric] ?? 1.0}
                onChange={(e) => handleWeightChange(metric, parseFloat(e.target.value))}
                className="w-full accent-amber-600"
              />
            </label>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <h3 className="text-sm font-semibold mb-2">Radar comparison</h3>
          <p className="mb-2 text-xs" style={{ color: 'var(--text-muted)' }}>Normalized suitability: larger is better after direction-aware conversion.</p>
          <div className="h-[320px]">
            <ResponsiveContainer>
              <RadarChart data={radarData}>
                <PolarGrid stroke={chartTheme.grid} />
                <PolarAngleAxis
                  dataKey="metric"
                  tick={{ fill: chartTheme.axis, fontSize: 10 }}
                />
                <Tooltip {...chartTheme.tooltip} />
                {rankedScorecards.map((sc, index) => (
                  <Radar
                    key={sc.architecture_id}
                    name={sc.architecture_name}
                    dataKey={sc.architecture_name}
                    stroke={COLORS[index % COLORS.length]}
                    fill={COLORS[index % COLORS.length]}
                    fillOpacity={0.12}
                  />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel">
          <h3 className="text-sm font-semibold mb-2">Exploratory ranking by weighted score</h3>
          <div className="h-[320px]">
            <ResponsiveContainer>
              <BarChart data={barData} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" domain={[0, 10]} stroke={chartTheme.axis} tickLine={{ stroke: chartTheme.axis }} tick={{ fill: chartTheme.axis, fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={120}
                  stroke={chartTheme.axis}
                  tickLine={{ stroke: chartTheme.axis }}
                  tick={{ fill: chartTheme.axis, fontSize: 11 }}
                />
                <Tooltip {...chartTheme.tooltip} />
                <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                  {barData.map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
