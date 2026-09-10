import type { MetricScore } from '../types/api'

const FALLBACK_MINIMIZE_METRICS = new Set([
  'cost',
  'deployment_complexity',
  'learning_curve',
  'development_time',
  'operational_complexity',
])

export function isLowerBetter(metric: Pick<MetricScore, 'metric' | 'direction'>) {
  return metric.direction === 'minimize'
    || (!metric.direction && FALLBACK_MINIMIZE_METRICS.has(metric.metric))
}

export function metricUtility(metric: MetricScore) {
  if (metric.normalized_score != null) return metric.normalized_score
  return isLowerBetter(metric) ? 11 - metric.score : metric.score
}

export function metricDirectionLabel(metric: Pick<MetricScore, 'metric' | 'direction'>) {
  return isLowerBetter(metric) ? 'Lower is better' : 'Higher is better'
}
