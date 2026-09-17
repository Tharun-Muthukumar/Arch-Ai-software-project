import { useMemo } from 'react'
import type { UseCaseModel } from '../../types/api'

/** A UML use case diagram drawn in correct notation.
 *
 * Mermaid has no use case diagram type. Rendering one as a flowchart drew
 * actors as plain rectangles and use cases as stadium shapes, with no system
 * boundary — so the diagram was labelled "Use Case" while using none of the
 * notation a use case diagram is defined by. UML requires:
 *
 *   - actors as stick figures, outside the system,
 *   - use cases as ellipses, inside the system boundary,
 *   - a rectangle naming the system,
 *   - plain (undirected) association lines between them.
 *
 * All four are drawn here. The backend supplies the structure; nothing in this
 * file infers an association or an actor that the model does not contain.
 */

const ACTOR_X = 82
const BOUNDARY_LEFT = 208
const USE_CASE_CX = 470
const ELLIPSE_RX = 132
const ELLIPSE_RY = 34
const ROW_HEIGHT = 86
const TOP_PADDING = 62
const BOTTOM_PADDING = 34

function wrap(label: string, perLine = 24, maxLines = 3): string[] {
  const words = label.split(/\s+/).filter(Boolean)
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (candidate.length > perLine && current) {
      lines.push(current)
      current = word
    } else {
      current = candidate
    }
    if (lines.length === maxLines) break
  }
  if (current && lines.length < maxLines) lines.push(current)
  if (!lines.length) return [label]
  const shown = lines.slice(0, maxLines)
  // Signal truncation rather than silently dropping words.
  if (words.join(' ').length > shown.join(' ').length) {
    shown[shown.length - 1] = `${shown[shown.length - 1]}…`
  }
  return shown
}

/** Where a line aimed at (towardX, towardY) leaves an ellipse's boundary.
 *
 * Association lines used to run from a fixed point beside the actor to the
 * ellipse's leftmost point, `cx - rx`. That is only the boundary for a
 * perfectly horizontal line; at any other angle the line stopped short of the
 * outline or cut across into it, which is why the lines did not look attached.
 *
 * Solving `(t·ux/rx)² + (t·uy/ry)² = 1` along the unit vector towards the
 * other shape gives the exact point where the line meets the outline, at any
 * angle.
 */
function ellipseEdge(
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  towardX: number,
  towardY: number,
): { x: number; y: number } {
  const dx = towardX - cx
  const dy = towardY - cy
  const length = Math.hypot(dx, dy)
  if (!length) return { x: cx + rx, y: cy }
  const ux = dx / length
  const uy = dy / length
  const t = 1 / Math.hypot(ux / rx, uy / ry)
  return { x: cx + ux * t, y: cy + uy * t }
}

// The stick figure's own bounds, used to start the line at the figure's edge
// rather than inside its torso. Centred slightly above the baseline because
// the glyph's head sits above it.
const ACTOR_RX = 17
const ACTOR_RY = 30
const ACTOR_CY_OFFSET = -8

/** The UML stick figure. A circle for the head, a torso, arms and two legs. */
function ActorGlyph({ x, y, name, external }: { x: number; y: number; name: string; external: boolean }) {
  const stroke = external ? 'var(--text-muted)' : 'var(--accent)'
  return (
    <g>
      <circle cx={x} cy={y - 26} r={9} fill="none" stroke={stroke} strokeWidth={1.8} />
      <line x1={x} y1={y - 17} x2={x} y2={y + 6} stroke={stroke} strokeWidth={1.8} />
      <line x1={x - 14} y1={y - 8} x2={x + 14} y2={y - 8} stroke={stroke} strokeWidth={1.8} />
      <line x1={x} y1={y + 6} x2={x - 11} y2={y + 24} stroke={stroke} strokeWidth={1.8} />
      <line x1={x} y1={y + 6} x2={x + 11} y2={y + 24} stroke={stroke} strokeWidth={1.8} />
      {wrap(name, 16, 2).map((line, index) => (
        <text
          key={`${line}-${index}`}
          x={x}
          y={y + 40 + index * 13}
          textAnchor="middle"
          fontSize={11}
          fontWeight={600}
          fill="var(--text)"
        >
          {line}
        </text>
      ))}
      {external ? (
        <text x={x} y={y - 42} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
          «external»
        </text>
      ) : null}
    </g>
  )
}

export function UseCaseDiagram({ model }: { model: UseCaseModel }) {
  const layout = useMemo(() => {
    // Group the use cases by their actor before placing them. Drawn in
    // requirement order the two actors' use cases interleave, so every
    // association line crosses several others and the diagram is hard to
    // follow. Grouping is the usual way a use case diagram is laid out, and
    // traceability is unaffected: each ellipse still carries its requirement
    // id. Ties break on the original order, so the layout is deterministic.
    const actorOrder = new Map(model.actors.map((actor, index) => [actor.id, index]))
    const ordered = model.use_cases
      .map((useCase, index) => ({ useCase, index }))
      .sort((left, right) => {
        const leftActor = left.useCase.actor_ids[0]
        const rightActor = right.useCase.actor_ids[0]
        // Use cases with no confirmed actor go last, where no line reaches.
        const leftRank = leftActor === undefined
          ? Number.MAX_SAFE_INTEGER
          : actorOrder.get(leftActor) ?? Number.MAX_SAFE_INTEGER - 1
        const rightRank = rightActor === undefined
          ? Number.MAX_SAFE_INTEGER
          : actorOrder.get(rightActor) ?? Number.MAX_SAFE_INTEGER - 1
        if (leftRank !== rightRank) return leftRank - rightRank
        return left.index - right.index
      })
      .map((entry) => entry.useCase)

    const useCases = ordered.map((useCase, index) => ({
      ...useCase,
      cy: TOP_PADDING + index * ROW_HEIGHT + ELLIPSE_RY,
    }))
    const byId = new Map(useCases.map((useCase) => [useCase.id, useCase]))

    // Place each actor at the vertical centre of the use cases it is
    // associated with, which keeps association lines short and mostly
    // uncrossed without needing a layout engine.
    const actors = model.actors.map((actor, index) => {
      const owned = useCases.filter((useCase) => useCase.actor_ids.includes(actor.id))
      const cy = owned.length
        ? owned.reduce((total, useCase) => total + useCase.cy, 0) / owned.length
        : TOP_PADDING + index * ROW_HEIGHT + ELLIPSE_RY
      return { ...actor, cy }
    })

    // Separate actors that landed on top of each other.
    actors.sort((left, right) => left.cy - right.cy)
    for (let index = 1; index < actors.length; index += 1) {
      const minimum = actors[index - 1].cy + 84
      if (actors[index].cy < minimum) actors[index].cy = minimum
    }

    const contentBottom = Math.max(
      useCases.length ? useCases[useCases.length - 1].cy + ELLIPSE_RY : TOP_PADDING,
      actors.length ? actors[actors.length - 1].cy + 48 : TOP_PADDING,
    )
    return {
      actors,
      useCases,
      byId,
      height: contentBottom + BOTTOM_PADDING + (model.omitted_use_case_count ? 30 : 0),
      boundaryBottom: (useCases.length ? useCases[useCases.length - 1].cy + ELLIPSE_RY : TOP_PADDING) + 22,
    }
  }, [model])

  const width = 760
  const unassigned = layout.useCases.filter((useCase) => !useCase.actor_ids.length).length

  return (
    <div className="use-case-diagram">
      <svg
        viewBox={`0 0 ${width} ${layout.height}`}
        width="100%"
        role="img"
        aria-label={`UML use case diagram for ${model.system_name}`}
      >
        {/* System boundary */}
        <rect
          x={BOUNDARY_LEFT}
          y={30}
          width={width - BOUNDARY_LEFT - 24}
          height={layout.boundaryBottom - 30}
          rx={6}
          fill="none"
          stroke="var(--card-border)"
          strokeWidth={1.4}
        />
        <text x={BOUNDARY_LEFT + 16} y={50} fontSize={11.5} fontWeight={600} fill="var(--text-muted)">
          {model.system_name}
        </text>

        {/* Associations, drawn first so the shapes sit on top. Each end is
            computed on the boundary of the shape it touches, so the line
            meets the stick figure and the ellipse exactly. */}
        {layout.useCases.map((useCase) =>
          useCase.actor_ids.map((actorId) => {
            const actor = layout.actors.find((candidate) => candidate.id === actorId)
            if (!actor) return null
            const actorCy = actor.cy + ACTOR_CY_OFFSET
            const from = ellipseEdge(
              ACTOR_X,
              actorCy,
              ACTOR_RX,
              ACTOR_RY,
              USE_CASE_CX,
              useCase.cy,
            )
            const to = ellipseEdge(
              USE_CASE_CX,
              useCase.cy,
              ELLIPSE_RX,
              ELLIPSE_RY,
              ACTOR_X,
              actorCy,
            )
            return (
              <line
                key={`${useCase.id}-${actorId}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="var(--assoc-line)"
                strokeWidth={1.3}
                strokeLinecap="round"
              />
            )
          }),
        )}

        {layout.actors.map((actor) => (
          <ActorGlyph
            key={actor.id}
            x={ACTOR_X}
            y={actor.cy}
            name={actor.name}
            external={!['human', 'organizational'].includes(actor.actor_type)}
          />
        ))}

        {layout.useCases.map((useCase) => {
          const associated = useCase.actor_ids.length > 0
          const lines = wrap(useCase.label)
          return (
            <g key={useCase.id}>
              <ellipse
                cx={USE_CASE_CX}
                cy={useCase.cy}
                rx={ELLIPSE_RX}
                ry={ELLIPSE_RY}
                fill="var(--brand-soft)"
                stroke={associated ? 'var(--brand)' : 'var(--text-muted)'}
                strokeWidth={1.4}
                strokeDasharray={associated ? undefined : '4 3'}
              />
              <text
                x={USE_CASE_CX}
                y={useCase.cy - 6 - (lines.length - 1) * 6}
                textAnchor="middle"
                fontSize={9}
                fontFamily="'JetBrains Mono', Consolas, monospace"
                fill="var(--brand-strong)"
              >
                {useCase.requirement_id}
              </text>
              {lines.map((line, index) => (
                <text
                  key={`${useCase.id}-line-${index}`}
                  x={USE_CASE_CX}
                  y={useCase.cy + 7 + index * 12 - (lines.length - 1) * 6}
                  textAnchor="middle"
                  fontSize={10.5}
                  fill="var(--text)"
                >
                  {line}
                </text>
              ))}
            </g>
          )
        })}

        {model.omitted_use_case_count ? (
          <text
            x={USE_CASE_CX}
            y={layout.boundaryBottom + 22}
            textAnchor="middle"
            fontSize={10}
            fill="var(--text-muted)"
          >
            {`+${model.omitted_use_case_count} further requirement(s) not drawn`}
          </text>
        ) : null}
      </svg>

      <div className="use-case-legend">
        <span><i className="legend-actor" />Actor (outside the system)</span>
        <span><i className="legend-usecase" />Use case associated with an actor</span>
        {unassigned ? (
          <span><i className="legend-unassigned" />{unassigned} with no confirmed actor</span>
        ) : null}
      </div>
    </div>
  )
}
