import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { formatMetricName } from '../../lib/utils'
import { chartTheme } from '../../lib/chartTheme'
import { metricUtility } from '../../lib/architectureMetrics'
import type { ComparisonResult } from '../../types/api'

interface RadarComparisonChartProps {
  comparison: ComparisonResult
}

const COLORS = ['#b45309', '#2563eb', '#16a34a']

export function RadarComparisonChart({
  comparison,
}: RadarComparisonChartProps) {
  const metrics = comparison.scorecards[0]?.metric_scores ?? []
  const data = metrics.map((metric) => {
    const row: Record<string, number | string> = {
      metric: formatMetricName(metric.metric),
    }

    for (const scorecard of comparison.scorecards) {
      const metricScore = scorecard.metric_scores.find(
        (item) => item.metric === metric.metric,
      )
      row[scorecard.architecture_name] = metricScore ? metricUtility(metricScore) : 0
    }

    return row
  })

  return (
    <div className="panel">
      <span className="pill">Score visualization</span>
      <h3 className="mt-2 font-semibold">Normalized suitability radar</h3>
      <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>Larger is better here; lower-is-better burdens are inverted only for this visualization.</p>
      <div className="mt-4 h-[320px]">
        <ResponsiveContainer>
          <RadarChart data={data}>
            <PolarGrid stroke={chartTheme.grid} />
            <PolarAngleAxis
              dataKey="metric"
              tick={{ fill: chartTheme.axis, fontSize: 11 }}
            />
            <Tooltip {...chartTheme.tooltip} />
            {comparison.scorecards.map((scorecard, index) => (
              <Radar
                key={scorecard.architecture_id}
                name={scorecard.architecture_name}
                dataKey={scorecard.architecture_name}
                stroke={COLORS[index % COLORS.length]}
                fill={COLORS[index % COLORS.length]}
                fillOpacity={0.15}
              />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
