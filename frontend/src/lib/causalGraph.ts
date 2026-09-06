import type {
  CausalGraph,
  CausalGraphEdge,
  CausalGraphNode,
  CausalGraphTrace,
  CausalRelationshipType,
  CausalNodeType,
} from '../types/api'

export const causalTypeLabels: Record<CausalNodeType, string> = {
  user_requirement: 'User brief',
  functional_requirement: 'Functional requirement',
  non_functional_requirement: 'Non-functional requirement',
  constraint: 'Constraint',
  assumption: 'Assumption',
  technical_characteristic: 'Technical need',
  architecture_decision: 'Architecture decision',
  architecture_component: 'Component',
  service_module: 'Service / module',
  api: 'API',
  database_entity: 'Data entity',
  integration: 'Integration',
  infrastructure: 'Infrastructure',
  risk: 'Risk',
  cost: 'Cost',
  adr: 'ADR',
  diagram: 'Diagram',
}

export const causalTypeColors: Record<CausalNodeType, string> = {
  user_requirement: '#f59e0b',
  functional_requirement: '#38bdf8',
  non_functional_requirement: '#2dd4bf',
  constraint: '#fb7185',
  assumption: '#a78bfa',
  technical_characteristic: '#22c55e',
  architecture_decision: '#f97316',
  architecture_component: '#60a5fa',
  service_module: '#818cf8',
  api: '#06b6d4',
  database_entity: '#14b8a6',
  integration: '#eab308',
  infrastructure: '#94a3b8',
  risk: '#ef4444',
  cost: '#f59e0b',
  adr: '#c084fc',
  diagram: '#64748b',
}

export const causalRelationshipLabels: Record<CausalRelationshipType, string> = {
  requires: 'requires',
  satisfies: 'addresses',
  caused_by: 'leads to',
  implemented_by: 'implemented by',
  depends_on: 'depends on',
  stores_in: 'stores data in',
  exposed_by: 'exposed through',
  deployed_on: 'deployed on',
  mitigates: 'mitigates',
  constrained_by: 'constrained by',
  affects: 'affects',
}

const requirementTypes = new Set<CausalNodeType>([
  'user_requirement',
  'functional_requirement',
  'non_functional_requirement',
  'constraint',
  'assumption',
])
const componentTypes = new Set<CausalNodeType>([
  'architecture_component',
  'service_module',
])

const stageByType: Record<CausalNodeType, number> = {
  user_requirement: 0,
  functional_requirement: 1,
  non_functional_requirement: 1,
  constraint: 1,
  assumption: 1,
  technical_characteristic: 2,
  architecture_decision: 3,
  architecture_component: 4,
  service_module: 4,
  api: 5,
  database_entity: 6,
  integration: 5,
  infrastructure: 7,
  risk: 8,
  cost: 8,
  adr: 8,
  diagram: 8,
}

export function filterCausalGraph(
  graph: CausalGraph,
  architectureId: string,
  type: CausalNodeType | 'all',
  search: string,
) {
  const architectureNodes = graph.nodes.filter((node) => {
    const nodeArchitecture = node.metadata.architecture_id
    return !nodeArchitecture || nodeArchitecture === architectureId
  })
  const architectureNodeIds = new Set(architectureNodes.map((node) => node.id))
  const architectureEdges = graph.edges.filter(
    (edge) =>
      architectureNodeIds.has(edge.source_node_id) &&
      architectureNodeIds.has(edge.target_node_id),
  )

  let visibleIds = new Set(
    architectureNodes
      .filter((node) => type === 'all' || node.type === type)
      .map((node) => node.id),
  )

  const query = search.trim().toLowerCase()
  if (query) {
    const matches = new Set(
      architectureNodes
        .filter((node) =>
          `${node.id} ${node.name} ${node.description}`.toLowerCase().includes(query),
        )
        .map((node) => node.id),
    )
    const neighborhood = new Set(matches)
    architectureEdges.forEach((edge) => {
      if (matches.has(edge.source_node_id)) neighborhood.add(edge.target_node_id)
      if (matches.has(edge.target_node_id)) neighborhood.add(edge.source_node_id)
    })
    visibleIds = new Set([...visibleIds].filter((id) => neighborhood.has(id)))
  }

  const nodes = architectureNodes.filter((node) => visibleIds.has(node.id))
  const edges = architectureEdges.filter(
    (edge) => visibleIds.has(edge.source_node_id) && visibleIds.has(edge.target_node_id),
  )
  return { nodes, edges }
}

export function buildFocusedCausalGraph(
  graph: CausalGraph,
  baseNodes: CausalGraphNode[],
  baseEdges: CausalGraphEdge[],
  selectedNodeId: string,
  architectureId = '',
) {
  if (!selectedNodeId) {
    return { nodes: baseNodes, edges: baseEdges, focusNodeIds: new Set<string>() }
  }
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]))
  const selected = nodeById.get(selectedNodeId)
  if (!selected) {
    return { nodes: baseNodes, edges: baseEdges, focusNodeIds: new Set<string>() }
  }

  const isArchitectureCompatible = (nodeId: string) => {
    const nodeArchitecture = nodeById.get(nodeId)?.metadata.architecture_id
    return !architectureId || !nodeArchitecture || nodeArchitecture === architectureId
  }
  const focusNodeIds = new Set<string>([selectedNodeId])
  const directEdges = graph.edges.filter((edge) => {
    const isDirect =
      edge.source_node_id === selectedNodeId || edge.target_node_id === selectedNodeId
    if (!isDirect) return false
    if (
      !isArchitectureCompatible(edge.source_node_id) ||
      !isArchitectureCompatible(edge.target_node_id)
    ) return false
    const neighborId =
      edge.source_node_id === selectedNodeId ? edge.target_node_id : edge.source_node_id
    const neighborType = nodeById.get(neighborId)?.type
    if (!neighborType) return false
    if (requirementTypes.has(selected.type)) {
      return !['adr', 'diagram', 'risk', 'cost'].includes(neighborType)
    }
    if (componentTypes.has(selected.type)) {
      return !['adr', 'diagram', 'risk', 'cost'].includes(neighborType)
    }
    return true
  })
  directEdges.forEach((edge) => {
    focusNodeIds.add(edge.source_node_id)
    focusNodeIds.add(edge.target_node_id)
  })

  const relevantComponents = graph.nodes.filter(
    (node) =>
      componentTypes.has(node.type) &&
      focusNodeIds.has(node.id) &&
      isArchitectureCompatible(node.id),
  )
  const includeComponentRequirements = componentTypes.has(selected.type)
  relevantComponents.forEach((component) => {
    focusNodeIds.add(component.id)
    graph.edges
      .filter(
        (edge) =>
          edge.target_node_id === component.id &&
          isArchitectureCompatible(edge.source_node_id) &&
          ((includeComponentRequirements &&
            requirementTypes.has(nodeById.get(edge.source_node_id)?.type as CausalNodeType)) ||
            nodeById.get(edge.source_node_id)?.type === 'architecture_decision'),
      )
      .forEach((edge) => focusNodeIds.add(edge.source_node_id))
  })

  const requirementIds = new Set(
    [...focusNodeIds].filter((id) => {
      const type = nodeById.get(id)?.type
      return type ? requirementTypes.has(type) && type !== 'user_requirement' : false
    }),
  )
  const relevantCategories = new Set<string>()
  const requirementTextKeys = new Set(
    [...requirementIds]
      .map((id) => nodeById.get(id)?.name)
      .filter((value): value is string => Boolean(value))
      .map(normalizeText),
  )
  graph.nodes.forEach((node) => {
    if (
      node.type === 'technical_characteristic' &&
      requirementIds.has(String(node.metadata.requirement_id ?? ''))
    ) {
      focusNodeIds.add(node.id)
      const category = String(node.metadata.category ?? '')
      if (!['', 'capability', 'quality', 'constraint', 'assumption'].includes(category)) {
        relevantCategories.add(category)
      }
    }
  })

  graph.nodes.forEach((technical) => {
    if (
      technical.type !== 'technical_characteristic' ||
      !relevantCategories.has(String(technical.metadata.category ?? ''))
    ) return
    const requirementId = String(technical.metadata.requirement_id ?? '')
    const requirement = nodeById.get(requirementId)
    if (
      requirement?.type === 'non_functional_requirement' &&
      !requirementTextKeys.has(normalizeText(requirement.name))
    ) {
      focusNodeIds.add(requirementId)
      focusNodeIds.add(technical.id)
      requirementTextKeys.add(normalizeText(requirement.name))
    }
  })

  const baseIds = new Set(baseNodes.map((node) => node.id))
  const visibleIds = new Set([...baseIds, ...focusNodeIds])
  const nodes = graph.nodes.filter((node) => visibleIds.has(node.id))
  const edges = graph.edges.filter(
    (edge) =>
      focusNodeIds.has(edge.source_node_id) && focusNodeIds.has(edge.target_node_id),
  )
  return { nodes, edges, focusNodeIds }
}

export function layoutCausalNodes(nodes: CausalGraphNode[]) {
  const stageOffsets = new Map<number, number>()
  return nodes.map((node) => {
    const stage = stageByType[node.type]
    const y = stageOffsets.get(stage) ?? 0
    const estimatedLines = Math.max(1, Math.ceil(node.name.length / 32))
    const estimatedHeight = Math.max(76, 48 + estimatedLines * 15)
    stageOffsets.set(stage, y + estimatedHeight + 28)
    return {
      node,
      position: { x: stage * 270, y },
      estimatedHeight,
    }
  })
}

export function reduceTransitiveCausalEdges(
  nodes: CausalGraphNode[],
  edges: CausalGraphEdge[],
) {
  const nodeIds = new Set(nodes.map((node) => node.id))
  const relevantEdges = edges.filter(
    (edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id),
  )

  return relevantEdges.filter(
    (edge) => !hasAlternatePath(edge.source_node_id, edge.target_node_id, edge, relevantEdges),
  )
}

function hasAlternatePath(
  sourceId: string,
  targetId: string,
  omittedEdge: CausalGraphEdge,
  edges: CausalGraphEdge[],
) {
  const adjacency = new Map<string, string[]>()
  edges.forEach((edge) => {
    if (
      edge.source_node_id === omittedEdge.source_node_id &&
      edge.target_node_id === omittedEdge.target_node_id
    ) return
    adjacency.set(edge.source_node_id, [
      ...(adjacency.get(edge.source_node_id) ?? []),
      edge.target_node_id,
    ])
  })

  const seen = new Set([sourceId])
  const queue = [...(adjacency.get(sourceId) ?? [])]
  while (queue.length > 0) {
    const current = queue.shift()!
    if (current === targetId) return true
    if (seen.has(current)) continue
    seen.add(current)
    queue.push(...(adjacency.get(current) ?? []))
  }
  return false
}

export function buildCausalTrace(
  graph: CausalGraph,
  nodeId: string,
  focusedNodeIds?: Set<string>,
): CausalGraphTrace | null {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]))
  const selected = nodeById.get(nodeId)
  if (!selected) return null

  const traceGraph = focusedNodeIds?.size
    ? {
        ...graph,
        nodes: graph.nodes.filter((node) => focusedNodeIds.has(node.id)),
        edges: graph.edges.filter(
          (edge) =>
            focusedNodeIds.has(edge.source_node_id) && focusedNodeIds.has(edge.target_node_id),
        ),
      }
    : graph
  const upstream = walk(traceGraph, nodeId, true)
  const downstream = walk(traceGraph, nodeId, false)
  const directRequirementIds = new Set(
    traceGraph.edges
      .filter((edge) => edge.target_node_id === nodeId)
      .map((edge) => edge.source_node_id),
  )
  const directRequirements = traceGraph.nodes.filter(
    (node) => directRequirementIds.has(node.id) && requirementTypes.has(node.type),
  )
  const upstreamRequirements = upstream.filter(
    (node) => requirementTypes.has(node.type) && node.type !== 'user_requirement',
  )
  const requirements = requirementTypes.has(selected.type)
    ? [selected]
    : [...directRequirements, ...upstreamRequirements]
  const relatedAdrs = [...upstream, ...downstream].filter(
    (node) => node.type === 'adr',
  )
  const why = traceGraph.edges
    .filter((edge) => edge.target_node_id === nodeId)
    .map((edge) => edge.reason)

  return {
    selected_node: selected,
    why_it_exists:
      why.length > 0
        ? [...new Set(why)]
        : ['No upstream causal relationship has been recorded for this node.'],
    requirements: uniqueRequirementNodes(requirements),
    upstream,
    downstream,
    related_adrs: uniqueNodes(relatedAdrs),
    affected_artifacts: [
      ...new Set(
        [selected, ...downstream]
          .map((node) => node.metadata.artifact)
          .filter((value): value is string => typeof value === 'string'),
      ),
    ],
  }
}

function walk(graph: CausalGraph, startId: string, reverse: boolean) {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]))
  const adjacency = new Map<string, string[]>()
  graph.edges.forEach((edge) => {
    const source = reverse ? edge.target_node_id : edge.source_node_id
    const target = reverse ? edge.source_node_id : edge.target_node_id
    adjacency.set(source, [...(adjacency.get(source) ?? []), target])
  })

  const seen = new Set([startId])
  const queue = [...(adjacency.get(startId) ?? [])]
  const result: CausalGraphNode[] = []
  while (queue.length > 0) {
    const current = queue.shift()!
    if (seen.has(current)) continue
    seen.add(current)
    const node = nodeById.get(current)
    if (node) result.push(node)
    queue.push(...(adjacency.get(current) ?? []))
  }
  return result
}

function uniqueNodes(nodes: CausalGraphNode[]) {
  return [...new Map(nodes.map((node) => [node.id, node])).values()]
}

function uniqueRequirementNodes(nodes: CausalGraphNode[]) {
  const seen = new Set<string>()
  return nodes.filter((node) => {
    const key = normalizeText(node.name)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function normalizeText(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}
