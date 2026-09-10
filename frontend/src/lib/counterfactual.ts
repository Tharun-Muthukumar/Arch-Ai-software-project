import type { CounterfactualChange, CounterfactualVariable } from '../types/api'

export type CounterfactualFormValues = Record<CounterfactualVariable, string | boolean>

const NUMERIC_VARIABLES = new Set<CounterfactualVariable>([
  'expected_users',
  'peak_traffic_multiplier',
  'availability_percent',
  'latency_ms',
  'team_size',
  'geographic_regions',
  'data_volume_multiplier',
  'growth_rate_percent',
])

export function buildCounterfactualChanges(
  values: CounterfactualFormValues,
): CounterfactualChange[] {
  const changes: CounterfactualChange[] = []
  for (const [variable, rawValue] of Object.entries(values) as [CounterfactualVariable, string | boolean][]) {
    if (typeof rawValue === 'boolean') {
      if (rawValue) changes.push({ variable, hypothetical_value: true })
      continue
    }
    const value = rawValue.trim()
    if (!value) continue
    const hypotheticalValue = NUMERIC_VARIABLES.has(variable) ? Number(value) : value
    if (typeof hypotheticalValue === 'number' && !Number.isFinite(hypotheticalValue)) continue
    changes.push({ variable, hypothetical_value: hypotheticalValue })
  }
  return changes
}

export function formatCounterfactualVariable(variable: string) {
  return variable.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
}
