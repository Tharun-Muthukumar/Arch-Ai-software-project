import { describe, expect, it } from 'vitest'
import {
  buildCausalTrace,
  buildFocusedCausalGraph,
  filterCausalGraph,
  layoutCausalNodes,
  reduceTransitiveCausalEdges,
} from './causalGraph'
import type { CausalGraph } from '../types/api'

const graph: CausalGraph = {
  version: '6',
  orphan_node_ids: [],
  nodes: [
    {
      id: 'FR-001',
      type: 'functional_requirement',
      name: 'Operators can review observations',
      description: 'Operators can review observations',
      source: 'requirement-analysis',
      version: '1',
      metadata: { artifact: 'requirements' },
    },
    {
      id: 'FR-002',
      type: 'functional_requirement',
      name: 'Administrators can manage unrelated billing rules',
      description: 'Administrators can manage unrelated billing rules',
      source: 'requirement-analysis',
      version: '1',
      metadata: { artifact: 'requirements' },
    },
    {
      id: 'NFR-001',
      type: 'non_functional_requirement',
      name: 'Observation reviews must preserve an auditable history',
      description: 'Observation reviews must preserve an auditable history',
      source: 'requirement-analysis',
      version: '1',
      metadata: { artifact: 'requirements' },
    },
    {
      id: 'TECH-FR-001',
      type: 'technical_characteristic',
      name: 'Business capability support',
      description: 'Provide an implementation boundary.',
      source: 'deterministic-requirement-mapping',
      version: '1',
      metadata: { artifact: 'requirements', requirement_id: 'FR-001', category: 'audit' },
    },
    {
      id: 'TECH-NFR-001',
      type: 'technical_characteristic',
      name: 'Auditability and governance',
      description: 'Preserve evidence for observation reviews.',
      source: 'deterministic-requirement-mapping',
      version: '1',
      metadata: { artifact: 'requirements', requirement_id: 'NFR-001', category: 'audit' },
    },
    {
      id: 'TECH-FR-002',
      type: 'technical_characteristic',
      name: 'Billing rule support',
      description: 'Provide an isolated billing rules boundary.',
      source: 'deterministic-requirement-mapping',
      version: '1',
      metadata: { artifact: 'requirements', requirement_id: 'FR-002' },
    },
    {
      id: 'DEC-A',
      type: 'architecture_decision',
      name: 'Option A',
      description: 'Selected architecture',
      source: 'architecture-generation',
      version: '1',
      metadata: { artifact: 'architectures', architecture_id: 'a' },
    },
    {
      id: 'CMP-A-01',
      type: 'service_module',
      name: 'Observation service',
      description: 'Owns observation workflows.',
      source: 'architecture-generation',
      version: '1',
      metadata: { artifact: 'architectures', architecture_id: 'a' },
    },
    {
      id: 'DEC-B',
      type: 'architecture_decision',
      name: 'Option B',
      description: 'Unselected architecture',
      source: 'architecture-generation',
      version: '1',
      metadata: { artifact: 'architectures', architecture_id: 'b' },
    },
    {
      id: 'CMP-B-01',
      type: 'service_module',
      name: 'Other option service',
      description: 'Belongs to another option.',
      source: 'architecture-generation',
      version: '1',
      metadata: { artifact: 'architectures', architecture_id: 'b' },
    },
    {
      id: 'API-001',
      type: 'api',
      name: 'Observations',
      description: 'Observation review operations.',
      source: 'api-generation',
      version: '1',
      metadata: { artifact: 'api' },
    },
    {
      id: 'API-002',
      type: 'api',
      name: 'Billing rules',
      description: 'Billing rule operations.',
      source: 'api-generation',
      version: '1',
      metadata: { artifact: 'api' },
    },
  ],
  edges: [
    {
      id: 'EDGE-1',
      source_node_id: 'FR-001',
      target_node_id: 'TECH-FR-001',
      relationship: 'requires',
      reason: 'The requirement creates this technical need.',
    },
    {
      id: 'EDGE-2',
      source_node_id: 'TECH-FR-001',
      target_node_id: 'DEC-A',
      relationship: 'requires',
      reason: 'The architecture is evaluated against this need.',
    },
    {
      id: 'EDGE-NFR-1',
      source_node_id: 'NFR-001',
      target_node_id: 'TECH-NFR-001',
      relationship: 'requires',
      reason: 'The quality requirement creates an auditability need.',
    },
    {
      id: 'EDGE-NFR-2',
      source_node_id: 'TECH-NFR-001',
      target_node_id: 'DEC-A',
      relationship: 'requires',
      reason: 'The architecture must preserve review evidence.',
    },
    {
      id: 'EDGE-3',
      source_node_id: 'DEC-A',
      target_node_id: 'CMP-A-01',
      relationship: 'implemented_by',
      reason: 'The component implements the decision.',
    },
    {
      id: 'EDGE-4',
      source_node_id: 'FR-001',
      target_node_id: 'CMP-A-01',
      relationship: 'implemented_by',
      reason: 'The observation service implements observation review.',
    },
    {
      id: 'EDGE-5',
      source_node_id: 'FR-001',
      target_node_id: 'API-001',
      relationship: 'exposed_by',
      reason: 'The API exposes observation review.',
    },
    {
      id: 'EDGE-6',
      source_node_id: 'CMP-A-01',
      target_node_id: 'API-001',
      relationship: 'exposed_by',
      reason: 'The observation service owns this API.',
    },
    {
      id: 'EDGE-7',
      source_node_id: 'FR-002',
      target_node_id: 'TECH-FR-002',
      relationship: 'requires',
      reason: 'Billing rules create an isolated technical need.',
    },
    {
      id: 'EDGE-8',
      source_node_id: 'TECH-FR-002',
      target_node_id: 'DEC-A',
      relationship: 'requires',
      reason: 'The architecture must account for billing rules.',
    },
    {
      id: 'EDGE-9',
      source_node_id: 'FR-002',
      target_node_id: 'API-002',
      relationship: 'exposed_by',
      reason: 'The API exposes billing rule management.',
    },
    {
      id: 'EDGE-10',
      source_node_id: 'FR-002',
      target_node_id: 'CMP-A-01',
      relationship: 'implemented_by',
      reason: 'The shared module also owns unrelated billing rules.',
    },
    {
      id: 'EDGE-B-1',
      source_node_id: 'FR-001',
      target_node_id: 'CMP-B-01',
      relationship: 'implemented_by',
      reason: 'The alternate architecture also implements observation review.',
    },
    {
      id: 'EDGE-B-2',
      source_node_id: 'DEC-B',
      target_node_id: 'CMP-B-01',
      relationship: 'implemented_by',
      reason: 'The alternate component implements the alternate decision.',
    },
  ],
}

describe('causal graph utilities', () => {
  it('traces a component back to its originating requirement', () => {
    const trace = buildCausalTrace(graph, 'CMP-A-01')

    expect(trace?.requirements.map((node) => node.id)).toContain('FR-001')
    expect(trace?.why_it_exists).toContain('The component implements the decision.')
    expect(trace?.affected_artifacts).toContain('architectures')
  })

  it('filters architecture-specific nodes and assigns stable stages', () => {
    const filtered = filterCausalGraph(graph, 'a', 'all', '')
    const positions = layoutCausalNodes(filtered.nodes)

    expect(filtered.nodes.some((node) => node.id === 'CMP-A-01')).toBe(true)
    expect(filtered.nodes.some((node) => node.id === 'CMP-B-01')).toBe(false)
    expect(positions.find((item) => item.node.id === 'FR-001')?.position.x).toBeLessThan(
      positions.find((item) => item.node.id === 'CMP-A-01')!.position.x,
    )
  })

  it('keeps all APIs visible while focusing only the selected API causal path', () => {
    const apiFilter = filterCausalGraph(graph, 'a', 'api', '')
    const focused = buildFocusedCausalGraph(
      graph,
      apiFilter.nodes,
      apiFilter.edges,
      'API-001',
      'a',
    )
    const trace = buildCausalTrace(graph, 'API-001', focused.focusNodeIds)

    expect(apiFilter.nodes.map((node) => node.id)).toEqual(['API-001', 'API-002'])
    expect(focused.nodes.map((node) => node.id)).toContain('API-002')
    expect(focused.focusNodeIds).toContain('API-001')
    expect(focused.focusNodeIds).toContain('FR-001')
    expect(focused.focusNodeIds).toContain('NFR-001')
    expect(focused.focusNodeIds).toContain('TECH-FR-001')
    expect(focused.focusNodeIds).not.toContain('FR-002')
    expect(focused.edges.every((edge) => !edge.id.includes('EDGE-9'))).toBe(true)
    expect(trace?.requirements.map((node) => node.id)).toEqual(['FR-001', 'NFR-001'])
  })

  it('keeps the focused path within one architecture and removes visual shortcut edges', () => {
    const requirementFilter = filterCausalGraph(graph, 'a', 'functional_requirement', '')
    const focused = buildFocusedCausalGraph(
      graph,
      requirementFilter.nodes,
      requirementFilter.edges,
      'FR-001',
      'a',
    )
    const renderedEdges = reduceTransitiveCausalEdges(focused.nodes, focused.edges)

    expect(focused.focusNodeIds).toContain('CMP-A-01')
    expect(focused.focusNodeIds).not.toContain('CMP-B-01')
    expect(focused.focusNodeIds).not.toContain('DEC-B')
    expect(renderedEdges.map((edge) => edge.id)).not.toContain('EDGE-4')
    expect(renderedEdges.map((edge) => edge.id)).not.toContain('EDGE-5')
    expect(renderedEdges.map((edge) => edge.id)).toEqual(
      expect.arrayContaining(['EDGE-1', 'EDGE-2', 'EDGE-3', 'EDGE-6']),
    )
  })
})
