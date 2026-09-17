import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { UseCaseDiagram } from './UseCaseDiagram'
import type { UseCaseModel } from '../../types/api'

/** Two actors whose use cases interleave in requirement order — the shape
 *  that made every association line cross several others. */
const model: UseCaseModel = {
  system_name: 'EV Charging Booking Platform',
  actors: [
    { id: 'ACT-001', name: 'Driver', actor_type: 'human' },
    { id: 'ACT-002', name: 'Payment Gateway', actor_type: 'external-system' },
  ],
  use_cases: [
    { id: 'UC-001', label: 'Station discovery', requirement_id: 'FR-001', actor_ids: ['ACT-001'] },
    { id: 'UC-002', label: 'Settle a payment', requirement_id: 'FR-002', actor_ids: ['ACT-002'] },
    { id: 'UC-003', label: 'Slot reservations', requirement_id: 'FR-003', actor_ids: ['ACT-001'] },
    { id: 'UC-004', label: 'Refund a booking', requirement_id: 'FR-004', actor_ids: ['ACT-002'] },
    { id: 'UC-005', label: 'Cancellation of a booking', requirement_id: 'FR-005', actor_ids: [] },
  ],
  omitted_use_case_count: 2,
}

function svgOf(container: HTMLElement) {
  const svg = container.querySelector('svg')
  expect(svg).not.toBeNull()
  return svg as SVGSVGElement
}

/** Association paths only — stick figures still use primitive lines. */
function associations(svg: SVGSVGElement) {
  return Array.from(svg.querySelectorAll<SVGPathElement>('path[data-association="true"]'))
}

function endpoints(path: SVGPathElement) {
  const values = (path.getAttribute('d') ?? '').match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? []
  expect(values).toHaveLength(5)
  return {
    x1: values[0],
    y1: values[1],
    laneX: values[2],
    y2: values[3],
    x2: values[4],
  }
}

describe('UseCaseDiagram', () => {
  it('draws UML notation: stick figures, ellipses and a system boundary', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    const svg = svgOf(container)
    // One head circle per actor.
    expect(svg.querySelectorAll('circle')).toHaveLength(2)
    expect(svg.querySelectorAll('ellipse')).toHaveLength(5)
    // Exactly one rect: the system boundary.
    expect(svg.querySelectorAll('rect')).toHaveLength(1)
    expect(svg.textContent).toContain('EV Charging Booking Platform')
  })

  it('draws one association per declared actor link and no more', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    const expected = model.use_cases.reduce(
      (total, useCase) => total + useCase.actor_ids.length,
      0,
    )
    expect(associations(svgOf(container))).toHaveLength(expected)
  })

  it('ends every association exactly on its ellipse outline', () => {
    // The bug: lines ran to `cx - rx`, the ellipse's leftmost point, which is
    // only on the outline for a horizontal line. At any other angle the line
    // stopped short or cut inside, so it did not look attached.
    const { container } = render(<UseCaseDiagram model={model} />)
    const svg = svgOf(container)
    const ellipses = Array.from(svg.querySelectorAll('ellipse')).map((node) => ({
      cx: Number(node.getAttribute('cx')),
      cy: Number(node.getAttribute('cy')),
      rx: Number(node.getAttribute('rx')),
      ry: Number(node.getAttribute('ry')),
    }))

    for (const path of associations(svg)) {
      const { x2, y2 } = endpoints(path)
      // The endpoint must satisfy the ellipse equation for one of the drawn
      // ellipses: ((x-cx)/rx)^2 + ((y-cy)/ry)^2 === 1.
      const onSomeOutline = ellipses.some((ellipse) => {
        const value =
          ((x2 - ellipse.cx) / ellipse.rx) ** 2 + ((y2 - ellipse.cy) / ellipse.ry) ** 2
        return Math.abs(value - 1) < 0.02
      })
      expect(onSomeOutline).toBe(true)
    }
  })

  it('starts every association clear of the actor glyph, never inside it', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    const svg = svgOf(container)
    for (const path of associations(svg)) {
      const { x1 } = endpoints(path)
      // The glyph is centred at x=88 with a half-width of 14, so a path that
      // begins at or left of the torso is starting inside the figure.
      expect(x1).toBeGreaterThan(88)
    }
  })

  it('routes associations outside the boundary before entering each use case', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    for (const path of associations(svgOf(container))) {
      const { x1, laneX, x2 } = endpoints(path)
      expect(laneX).toBeGreaterThan(x1)
      expect(laneX).toBeLessThan(250)
      expect(x2).toBeGreaterThan(250)
    }
  })

  it('groups use cases by actor so association lines do not cross', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    const svg = svgOf(container)
    // Read the requirement ids in the order they are drawn.
    const drawn = Array.from(svg.querySelectorAll('text'))
      .map((node) => node.textContent ?? '')
      .filter((text) => /^FR-\d+$/.test(text))
    // Driver's two, then the gateway's two, then the unassigned one — not the
    // interleaved requirement order the model supplies.
    expect(drawn).toEqual(['FR-001', 'FR-003', 'FR-002', 'FR-004', 'FR-005'])
  })

  it('marks a use case with no confirmed actor instead of inventing a link', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    const dashed = Array.from(svgOf(container).querySelectorAll('ellipse')).filter((node) =>
      node.getAttribute('stroke-dasharray'),
    )
    expect(dashed).toHaveLength(1)
    expect(container.textContent).toContain('1 with no confirmed actor')
  })

  it('reports omitted requirements rather than hiding them', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    expect(container.textContent).toContain('+2 further requirement(s) not drawn')
  })

  it('stereotypes a non-human actor', () => {
    const { container } = render(<UseCaseDiagram model={model} />)
    expect(container.textContent).toContain('«external»')
  })
})
