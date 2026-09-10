import { describe, expect, it } from 'vitest'
import { isLowerBetter, metricDirectionLabel, metricUtility } from './architectureMetrics'

describe('architecture metric direction', () => {
  it('treats burden metrics as lower-is-better', () => {
    const metric = {
      metric: 'deployment_complexity',
      score: 2,
      direction: 'minimize' as const,
      normalized_score: 9,
      explanation: 'Low deployment burden.',
    }
    expect(isLowerBetter(metric)).toBe(true)
    expect(metricDirectionLabel(metric)).toBe('Lower is better')
    expect(metricUtility(metric)).toBe(9)
  })

  it('keeps capability metrics higher-is-better', () => {
    const metric = {
      metric: 'reliability',
      score: 8,
      direction: 'maximize' as const,
      normalized_score: 8,
      explanation: 'Strong reliability capability.',
    }
    expect(isLowerBetter(metric)).toBe(false)
    expect(metricDirectionLabel(metric)).toBe('Higher is better')
    expect(metricUtility(metric)).toBe(8)
  })
})
