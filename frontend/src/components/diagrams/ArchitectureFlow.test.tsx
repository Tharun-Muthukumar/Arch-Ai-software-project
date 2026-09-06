import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ArchitectureFlow } from './ArchitectureFlow'

describe('ArchitectureFlow', () => {
  it('links each component to its causal explanation', () => {
    render(
      <MemoryRouter>
        <ArchitectureFlow
          architecture={{
            id: 'modular',
            name: 'Modular option',
            style: 'Modular',
            overview: 'One deployable with internal boundaries.',
            components: [
              {
                name: 'Observation Core',
                responsibility: 'Owns observation workflows.',
                technologies: ['Python'],
                interactions: [],
              },
            ],
            data_flow: [],
            technology_stack: ['Python'],
            database: 'Relational database',
            api_style: 'REST',
            deployment: 'Containers',
            advantages: [],
            disadvantages: [],
            suitable_scenarios: [],
            estimated_complexity: 'Medium',
            estimated_cost: 'Low',
            maintenance: 'Moderate',
          }}
          whyHref={(component) => `/causal-graph?component=${component.name}`}
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /why does this exist/i })).toHaveAttribute(
      'href',
      '/causal-graph?component=Observation Core',
    )
  })
})
