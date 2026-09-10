import { describe, expect, it } from 'vitest'
import { buildCounterfactualChanges } from './counterfactual'

describe('buildCounterfactualChanges', () => {
  it('keeps only explicit hypothetical values and preserves numeric types', () => {
    const changes = buildCounterfactualChanges({
      expected_users: '2000000',
      peak_traffic_multiplier: '10',
      availability_percent: '99.99',
      latency_ms: '',
      team_size: '5',
      geographic_regions: '',
      realtime_required: true,
      compliance_level: '',
      data_volume_multiplier: '',
      growth_rate_percent: '',
    })

    expect(changes).toContainEqual({ variable: 'expected_users', hypothetical_value: 2_000_000 })
    expect(changes).toContainEqual({ variable: 'availability_percent', hypothetical_value: 99.99 })
    expect(changes).toContainEqual({ variable: 'realtime_required', hypothetical_value: true })
    expect(changes.some((change) => change.variable === 'latency_ms')).toBe(false)
  })
})
