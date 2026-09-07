import { formatMetricName } from '../../lib/utils'
import type { ComparisonResult } from '../../types/api'

interface ComparisonTableProps {
  comparison: ComparisonResult
}

export function ComparisonTable({ comparison }: ComparisonTableProps) {
  const metrics = comparison.scorecards[0]?.metric_scores ?? []

  return (
    <div className="panel overflow-x-auto">
      <div className="flex items-center justify-between gap-3">
        <span className="pill">Scorecards</span>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Higher is better · deterministic model outputs, not objective measurements</span>
      </div>

      <table className="mt-4 min-w-full text-sm">
        <thead>
          <tr className="border-b" style={{ borderColor: 'var(--card-border)' }}>
            <th className="py-2 text-left font-medium" style={{ color: 'var(--text-muted)' }}>Metric</th>
            {comparison.scorecards.map((scorecard) => (
              <th key={scorecard.architecture_id} className="py-2 text-left font-medium">
                {scorecard.architecture_name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <tr key={metric.metric} className="border-b" style={{ borderColor: 'var(--card-border)' }}>
              <td className="py-2 font-medium">{formatMetricName(metric.metric)}</td>
              {comparison.scorecards.map((scorecard) => {
                const score = scorecard.metric_scores.find(
                  (metricScore) => metricScore.metric === metric.metric,
                )
                return (
                  <td key={scorecard.architecture_id} className="py-2">
                    {score?.score ?? '-'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
