import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Link2, Search, X } from 'lucide-react'
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Position,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeMouseHandler,
  useStoreApi,
} from 'reactflow'
import { useSearchParams } from 'react-router-dom'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { getCausalGraph } from '../lib/api'
import {
  buildCausalTrace,
  buildFocusedCausalGraph,
  causalRelationshipLabels,
  causalTypeColors,
  causalTypeLabels,
  filterCausalGraph,
  layoutCausalNodes,
  reduceTransitiveCausalEdges,
} from '../lib/causalGraph'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type {
  CausalGraphEdge,
  CausalGraphNode,
  CausalNodeType,
} from '../types/api'

const filterTypes: Array<CausalNodeType | 'all'> = [
  'all',
  'functional_requirement',
  'non_functional_requirement',
  'technical_characteristic',
  'architecture_decision',
  'architecture_component',
  'service_module',
  'api',
  'database_entity',
  'integration',
  'infrastructure',
  'risk',
  'adr',
  'diagram',
]
const compactRelationshipLabels: Record<CausalGraphEdge['relationship'], string> = {
  requires: 'requires',
  satisfies: 'addresses',
  caused_by: 'causes',
  implemented_by: 'via',
  depends_on: 'depends on',
  stores_in: 'stores in',
  exposed_by: 'exposed by',
  deployed_on: 'runs on',
  mitigates: 'mitigates',
  constrained_by: 'constrains',
  affects: 'affects',
}
function handleReactFlowError(code: string, message: string) {
  if (code !== '002') console.warn(`[React Flow ${code}] ${message}`)
}

export function CausalGraphPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const graphQuery = useQuery({
    queryKey: ['causal-graph', workspace?.id],
    queryFn: () => getCausalGraph(workspace!.id),
    enabled: Boolean(workspace?.id),
    initialData: workspace?.causal_graph ?? undefined,
  })
  // Prefer the workspace copy: every mutation (clarifications, edits, change
  // requests) refreshes the workspaces cache, while this page's separate query
  // key is only invalidated on some paths and would otherwise render a stale
  // graph after the architecture changes.
  const graph = workspace?.causal_graph ?? graphQuery.data
  const requestedArchitecture = searchParams.get('architecture')
  const requestedComponent = searchParams.get('component')
  const [architectureId, setArchitectureId] = useState('')
  const [typeFilter, setTypeFilter] = useState<CausalNodeType | 'all'>('all')
  const [search, setSearch] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [hoveredNodeId, setHoveredNodeId] = useState('')
  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_, node) => {
      setHoveredNodeId('')
      setSelectedNodeId(node.id)
    },
    [],
  )
  const handleNodeMouseEnter = useCallback<NodeMouseHandler>(
    (_, node) => setHoveredNodeId(node.id),
    [],
  )
  const handleNodeMouseLeave = useCallback<NodeMouseHandler>((_, node) => {
    setHoveredNodeId((current) => (current === node.id ? '' : current))
  }, [])

  useEffect(() => {
    if (!workspace) return
    const validRequested = workspace.architectures.some(
      (architecture) => architecture.id === requestedArchitecture,
    )
    setArchitectureId(
      validRequested
        ? requestedArchitecture!
        : workspace.recommendation.recommended_architecture_id,
    )
  }, [requestedArchitecture, workspace])

  useEffect(() => {
    if (!graph || selectedNodeId || !requestedComponent) return
    const requestedNode = requestedComponent
      ? graph.nodes.find(
          (node) =>
            node.name === requestedComponent &&
            (!requestedArchitecture ||
              node.metadata.architecture_id === requestedArchitecture),
        )
      : null
    setSelectedNodeId(requestedNode?.id ?? '')
  }, [graph, requestedArchitecture, requestedComponent, selectedNodeId])

  const filtered = useMemo(
    () =>
      graph
        ? filterCausalGraph(graph, architectureId, typeFilter, search)
        : { nodes: [], edges: [] },
    [architectureId, graph, search, typeFilter],
  )
  const focused = useMemo(
    () =>
      graph
        ? buildFocusedCausalGraph(
            graph,
            filtered.nodes,
            filtered.edges,
            selectedNodeId,
            architectureId,
          )
        : { nodes: [], edges: [], focusNodeIds: new Set<string>() },
    [filtered.edges, filtered.nodes, graph, selectedNodeId],
  )
  const detailNodeId = selectedNodeId || hoveredNodeId
  const detailFocus = useMemo(
    () =>
      graph && detailNodeId && detailNodeId !== selectedNodeId
        ? buildFocusedCausalGraph(
            graph,
            filtered.nodes,
            filtered.edges,
            detailNodeId,
            architectureId,
          )
        : focused,
    [architectureId, detailNodeId, filtered.edges, filtered.nodes, focused, graph, selectedNodeId],
  )
  const flowNodes = useMemo<Node[]>(
    () =>
      layoutCausalNodes(focused.nodes).map(({ node, position, estimatedHeight }) => {
        const isSelected = node.id === selectedNodeId
        const isDimmed = Boolean(selectedNodeId) && !focused.focusNodeIds.has(node.id)
        return {
          id: node.id,
          position,
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          data: {
            label: (
              <div className="flex min-h-full flex-col items-center justify-center gap-1">
                <span className="font-mono text-[10px] text-slate-300">{node.id}</span>
                <span className="break-words text-center text-[11px] font-medium leading-4">
                  {node.name}
                </span>
              </div>
            ),
          },
          ariaLabel: `${causalTypeLabels[node.type]} ${node.name}`,
          zIndex: isDimmed ? 1 : 3,
          style: {
            width: 220,
            minHeight: estimatedHeight,
            padding: '10px 12px',
            borderRadius: 6,
            border: `2px solid ${causalTypeColors[node.type]}`,
            background: '#131c2d',
            color: '#f8fafc',
            overflow: 'visible',
            overflowWrap: 'anywhere',
            whiteSpace: 'normal',
            opacity: isDimmed ? 0.22 : 1,
            transition: 'opacity 150ms ease, box-shadow 150ms ease',
            boxShadow:
              isSelected ? '0 0 0 3px #ef444488' : 'none',
          },
        }
      }),
    [focused.focusNodeIds, focused.nodes, selectedNodeId],
  )
  const flowEdges = useMemo<Edge[]>(
    () => {
      const renderedEdges = selectedNodeId
        ? reduceTransitiveCausalEdges(focused.nodes, focused.edges)
        : focused.edges
      return renderedEdges.map((edge) => {
        const isFocusedPath = Boolean(selectedNodeId)
        const touchesSelection =
          edge.source_node_id === selectedNodeId || edge.target_node_id === selectedNodeId
        return {
          id: edge.id,
          source: edge.source_node_id,
          target: edge.target_node_id,
          type: 'smoothstep',
          label: isFocusedPath ? compactRelationshipLabels[edge.relationship] : undefined,
          animated: false,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isFocusedPath ? '#ef4444' : '#64748b',
          },
          style: {
            stroke: isFocusedPath ? '#ef4444' : '#64748b',
            strokeWidth: isFocusedPath ? (touchesSelection ? 2.75 : 2) : 1,
            opacity: isFocusedPath ? 0.95 : 0.42,
          },
          pathOptions: { borderRadius: 10, offset: 22 },
          labelStyle: { fill: '#f8fafc', fontSize: 9, fontWeight: 600 },
          labelBgStyle: { fill: '#0b1120', fillOpacity: 0.9 },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 3,
          zIndex: 0,
        }
      })
    },
    [focused.edges, focused.nodes, selectedNodeId],
  )
  const trace = useMemo(
    () =>
      graph && detailNodeId
        ? buildCausalTrace(graph, detailNodeId, detailFocus.focusNodeIds)
        : null,
    [detailFocus.focusNodeIds, detailNodeId, graph],
  )

  if (workspaceQuery.isLoading || graphQuery.isLoading) {
    return <StatePanel badge="Loading" title="Building causal graph" description="Loading validated architecture relationships." />
  }
  if (workspaceQuery.isError || graphQuery.isError) {
    const error = workspaceQuery.error ?? graphQuery.error
    return <StatePanel badge="Backend issue" title="Could not load the causal graph" description={getErrorMessage(error)} tone="danger" actionLabel="Retry" onAction={() => void graphQuery.refetch()} />
  }
  if (!workspace || !graph) {
    return <StatePanel badge="No workspace" title="No causal graph available" description="Create a project brief from the dashboard first." actionLabel="Open Dashboard" actionTo="/dashboard" />
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="section-title">Causal graph</h2>
          <p className="mt-1 text-sm text-muted">
            {graph.nodes.length} nodes · {graph.edges.length} validated relationships
          </p>
        </div>
        {graph.orphan_node_ids.length > 0 && (
          <div className="flex items-center gap-2 text-sm text-amber-300">
            <AlertTriangle className="h-4 w-4" />
            {graph.orphan_node_ids.length} unjustified components
          </div>
        )}
      </div>

      <div className="panel flex flex-col gap-3 p-3 md:flex-row md:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search graph</span>
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
          <input
            className="input-shell pl-9"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search IDs, requirements, components"
          />
        </label>
        <select
          className="input-shell md:w-56"
          aria-label="Architecture option"
          value={architectureId}
          onChange={(event) => {
            setArchitectureId(event.target.value)
            setHoveredNodeId('')
            setSelectedNodeId('')
          }}
        >
          {workspace.architectures.map((architecture) => (
            <option key={architecture.id} value={architecture.id}>
              {architecture.name}
            </option>
          ))}
        </select>
        <select
          className="input-shell md:w-56"
          aria-label="Node type"
          value={typeFilter}
          onChange={(event) => {
            setTypeFilter(event.target.value as CausalNodeType | 'all')
            setHoveredNodeId('')
            setSelectedNodeId('')
          }}
        >
          {filterTypes.map((type) => (
            <option key={type} value={type}>
              {type === 'all' ? 'All node types' : causalTypeLabels[type]}
            </option>
          ))}
        </select>
        <button
          type="button"
          title="Clear graph filters"
          aria-label="Clear graph filters"
          className="button-secondary h-10 w-10 px-0"
          onClick={() => {
            setSearch('')
            setTypeFilter('all')
            setHoveredNodeId('')
            setSelectedNodeId('')
          }}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {selectedNodeId && (
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <Link2 className="h-4 w-4 shrink-0 text-red-400" />
          <span className="truncate text-muted">
            Focused path: {graph.nodes.find((node) => node.id === selectedNodeId)?.name}
          </span>
          <button
            type="button"
            title="Clear focused path"
            aria-label="Clear focused path"
            className="button-secondary ml-auto h-8 w-8 shrink-0 px-0"
            onClick={() => setSelectedNodeId('')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_430px]">
        <div className="panel min-w-0 overflow-hidden p-0" style={{ height: '72vh', minHeight: 560 }}>
          {flowNodes.length > 0 ? (
            <ReactFlowProvider>
              <ReactFlowErrorBoundary>
                <ReactFlow
                  key={`${architectureId}-${typeFilter}-${search}-${selectedNodeId}`}
                  nodes={flowNodes}
                  edges={flowEdges}
                  onError={handleReactFlowError}
                  onNodeClick={handleNodeClick}
                  onNodeMouseEnter={handleNodeMouseEnter}
                  onNodeMouseLeave={handleNodeMouseLeave}
                  onPaneClick={() => {
                    setHoveredNodeId('')
                    setSelectedNodeId('')
                  }}
                  fitView
                  fitViewOptions={{ padding: 0.15 }}
                  minZoom={0.15}
                  maxZoom={1.8}
                >
                  <Background color="#334155" gap={22} />
                  <Controls />
                  <MiniMap
                    nodeColor={(node) => {
                      const source = graph.nodes.find((item) => item.id === node.id)
                      return source ? causalTypeColors[source.type] : '#64748b'
                    }}
                    maskColor="rgba(11, 17, 32, 0.72)"
                  />
                </ReactFlow>
              </ReactFlowErrorBoundary>
            </ReactFlowProvider>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted">
              No nodes match the current filters.
            </div>
          )}
        </div>

        <CausalDetailPanel
          trace={trace}
          graphNodes={graph.nodes}
          focusedEdges={detailFocus.edges}
          onSelect={(id) => {
            setHoveredNodeId('')
            setSelectedNodeId(id)
          }}
        />
      </div>
    </div>
  )
}

function ReactFlowErrorBoundary({ children }: { children: ReactNode }) {
  const store = useStoreApi()
  const [ready, setReady] = useState(false)
  useLayoutEffect(() => {
    store.setState({ onError: handleReactFlowError })
    setReady(true)
  }, [store])
  return ready ? children : null
}

function CausalDetailPanel({
  trace,
  graphNodes,
  focusedEdges,
  onSelect,
}: {
  trace: ReturnType<typeof buildCausalTrace>
  graphNodes: CausalGraphNode[]
  focusedEdges: CausalGraphEdge[]
  onSelect: (id: string) => void
}) {
  if (!trace) {
    return <div className="panel text-sm text-muted">No causal path selected.</div>
  }

  const nodeById = new Map(graphNodes.map((node) => [node.id, node]))
  const relatedNodes = uniqueNodes([trace.selected_node, ...trace.upstream, ...trace.downstream])
  const technicalNeeds = relatedNodes.filter(
    (node) => node.type === 'technical_characteristic',
  )
  const implementationNodes = relatedNodes.filter((node) =>
    ['architecture_decision', 'architecture_component', 'service_module'].includes(node.type),
  )
  const connections = [...focusedEdges]
    .sort((left, right) => {
      const leftDirect =
        left.source_node_id === trace.selected_node.id ||
        left.target_node_id === trace.selected_node.id
      const rightDirect =
        right.source_node_id === trace.selected_node.id ||
        right.target_node_id === trace.selected_node.id
      return Number(rightDirect) - Number(leftDirect)
    })
    .map((edge) => ({
      edge,
      source: nodeById.get(edge.source_node_id),
      target: nodeById.get(edge.target_node_id),
    }))
    .filter(
      (connection): connection is {
        edge: CausalGraphEdge
        source: CausalGraphNode
        target: CausalGraphNode
      } => Boolean(connection.source && connection.target),
    )

  return (
    <aside className="panel max-h-[72vh] overflow-y-auto">
      <div className="flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ background: causalTypeColors[trace.selected_node.type] }}
        />
        <span className="text-xs font-medium uppercase text-muted">
          {causalTypeLabels[trace.selected_node.type]}
        </span>
      </div>
      <h3 className="mt-2 text-base font-semibold">{trace.selected_node.name}</h3>
      <div className="mt-1 font-mono text-xs text-muted">{trace.selected_node.id}</div>
      <p className="mt-3 text-sm leading-6 text-muted">{trace.selected_node.description}</p>

      <DetailSection title="Why it exists">
        <p className="text-sm leading-6">
          {purposeSummary(trace.selected_node, trace.requirements, implementationNodes)}
        </p>
        <ul className="mt-3 space-y-2 border-l-2 border-red-500 pl-3 text-xs leading-5 text-muted">
          {trace.why_it_exists.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      </DetailSection>

      <NodeLinks title="Corresponding requirements" nodes={trace.requirements} onSelect={onSelect} />

      <DetailSection title="Technical consequences">
        {technicalNeeds.length > 0 ? (
          <div className="space-y-3">
            {technicalNeeds.map((node) => (
              <div key={node.id}>
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[11px] text-green-300">{node.id}</span>
                  <span className="text-sm font-medium">{node.name}</span>
                </div>
                <p className="mt-1 text-xs leading-5 text-muted">{node.description}</p>
                {typeof node.metadata.requirement_text === 'string' && (
                  <p className="mt-1 text-xs leading-5 text-slate-300">
                    Derived from: {node.metadata.requirement_text}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <span className="text-sm text-muted">No separate technical consequence is recorded.</span>
        )}
      </DetailSection>

      <MetadataDetails node={trace.selected_node} />

      <NodeLinks title="Architecture path" nodes={implementationNodes} onSelect={onSelect} />

      <DetailSection title="Connection flow">
        {connections.length > 0 ? (
          <div className="space-y-4">
            {connections.map(({ edge, source, target }) => (
              <div key={edge.id} className="border-l-2 border-red-500 pl-3">
                <div className="flex min-w-0 items-center gap-2 text-xs font-medium">
                  <button type="button" className="min-w-0 truncate text-left hover:text-white" onClick={() => onSelect(source.id)}>
                    {source.name}
                  </button>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-red-400" />
                  <button type="button" className="min-w-0 truncate text-left hover:text-white" onClick={() => onSelect(target.id)}>
                    {target.name}
                  </button>
                </div>
                <div className="mt-1 text-[11px] font-semibold uppercase text-red-300">
                  {causalRelationshipLabels[edge.relationship]}
                </div>
                <p className="mt-1 text-xs leading-5 text-muted">{edge.reason}</p>
              </div>
            ))}
          </div>
        ) : (
          <span className="text-sm text-muted">No validated connection is recorded.</span>
        )}
      </DetailSection>

      <DetailSection title="Affected artifacts">
        <div className="flex flex-wrap gap-1.5">
          {trace.affected_artifacts.length > 0 ? trace.affected_artifacts.map((artifact) => (
            <span key={artifact} className="pill">{artifact}</span>
          )) : <span className="text-sm text-muted">None recorded.</span>}
        </div>
      </DetailSection>
    </aside>
  )
}

function NodeLinks({
  title,
  nodes,
  onSelect,
}: {
  title: string
  nodes: CausalGraphNode[]
  onSelect: (id: string) => void
}) {
  return (
    <DetailSection title={title}>
      {nodes.length > 0 ? (
        <div className="space-y-1.5">
          {uniqueNodes(nodes).map((node) => (
            <button
              key={node.id}
              type="button"
              onClick={() => onSelect(node.id)}
              className="block w-full border-l-2 px-2 py-2 text-left hover:bg-white/5"
              style={{ borderColor: causalTypeColors[node.type] }}
            >
              <span className="block text-[11px] font-medium uppercase text-muted">
                {causalTypeLabels[node.type]} · <span className="font-mono">{node.id}</span>
              </span>
              <span className="mt-0.5 block text-xs leading-5">{node.name}</span>
            </button>
          ))}
        </div>
      ) : (
        <span className="text-sm text-muted">None recorded.</span>
      )}
    </DetailSection>
  )
}

function MetadataDetails({ node }: { node: CausalGraphNode }) {
  const endpoints = readEndpointDetails(node.metadata.endpoint_details)
  const technologies = readStringList(node.metadata.technologies)
  const interactions = readStringList(node.metadata.interactions)
  const fields = readStringList(node.metadata.fields)
  const targetStack = readStringList(node.metadata.target_stack)
  const securityControls = readStringList(node.metadata.security_controls)
  const hasDetails =
    endpoints.length > 0 ||
    technologies.length > 0 ||
    interactions.length > 0 ||
    fields.length > 0 ||
    targetStack.length > 0 ||
    securityControls.length > 0 ||
    typeof node.metadata.scaling_strategy === 'string' ||
    typeof node.metadata.database_engine === 'string'

  if (!hasDetails) return null

  return (
    <DetailSection title="Implementation details">
      {endpoints.length > 0 && (
        <div className="space-y-3">
          {endpoints.map((endpoint) => (
            <div key={`${endpoint.method}-${endpoint.path}`}>
              <div className="flex min-w-0 items-center gap-2">
                <span className="shrink-0 font-mono text-[11px] font-semibold text-cyan-300">
                  {endpoint.method}
                </span>
                <span className="min-w-0 break-all font-mono text-xs">{endpoint.path}</span>
              </div>
              <p className="mt-1 text-xs leading-5 text-muted">{endpoint.purpose}</p>
              <span className="mt-1 block text-[11px] text-slate-300">
                {endpoint.authRequired ? 'Authentication required' : 'No endpoint authentication recorded'}
              </span>
            </div>
          ))}
        </div>
      )}
      <MetadataList label="Technologies" values={technologies} />
      <MetadataList label="Interactions" values={interactions} />
      <MetadataList label="Fields" values={fields} />
      <MetadataList label="Deployment stack" values={targetStack} />
      <MetadataList label="Security controls" values={securityControls} />
      {typeof node.metadata.database_engine === 'string' && (
        <MetadataList label="Database engine" values={[node.metadata.database_engine]} />
      )}
      {typeof node.metadata.scaling_strategy === 'string' && (
        <MetadataList label="Scaling strategy" values={[node.metadata.scaling_strategy]} />
      )}
    </DetailSection>
  )
}

function MetadataList({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null
  return (
    <div className="mt-3">
      <div className="text-[11px] font-semibold uppercase text-muted">{label}</div>
      <ul className="mt-1 space-y-1 text-xs leading-5">
        {values.map((value) => <li key={value}>{value}</li>)}
      </ul>
    </div>
  )
}

function purposeSummary(
  node: CausalGraphNode,
  requirements: CausalGraphNode[],
  implementationNodes: CausalGraphNode[],
) {
  const requirementCount = uniqueNodes(requirements).length
  const ownerCount = implementationNodes.filter((item) =>
    ['architecture_component', 'service_module'].includes(item.type),
  ).length
  const requirementPhrase = `${requirementCount} corresponding requirement${requirementCount === 1 ? '' : 's'}`

  if (node.type === 'api') {
    return requirementCount > 0
      ? `This API exposes behavior required by ${requirementPhrase}${ownerCount > 0 ? ` and is connected to ${ownerCount} owning module${ownerCount === 1 ? '' : 's'}` : ''}.`
      : 'No direct requirement justification has been validated for this API. Its purpose needs review.'
  }
  if (['architecture_component', 'service_module'].includes(node.type)) {
    return requirementCount > 0
      ? `This module provides "${node.description}" and is justified by ${requirementPhrase}.`
      : 'No direct requirement justification has been validated for this module. It should be reviewed as a possible orphan.'
  }
  if (node.type === 'architecture_decision') {
    return `This option is evaluated against ${requirementPhrase} and their explicit technical consequences. Passing a comparison score is evidence for selection, not proof of implementation.`
  }
  if (node.type === 'technical_characteristic') {
    const source = node.metadata.requirement_text
    return typeof source === 'string'
      ? `This technical need is derived from the requirement: "${source}"`
      : 'This technical need records an architecture consequence of the selected requirement path.'
  }
  if (['functional_requirement', 'non_functional_requirement', 'constraint', 'assumption'].includes(node.type)) {
    return `This ${causalTypeLabels[node.type].toLowerCase()} was extracted from the project brief. The connected path shows the technical and architecture elements that respond to it.`
  }
  return requirementCount > 0
    ? `This element is connected to ${requirementPhrase} through the validated relationships shown below.`
    : 'This element has no validated originating requirement in the current graph.'
}

function readStringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function readEndpointDetails(value: unknown) {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const endpoint = item as Record<string, unknown>
    if (
      typeof endpoint.method !== 'string' ||
      typeof endpoint.path !== 'string' ||
      typeof endpoint.purpose !== 'string'
    ) return []
    return [{
      method: endpoint.method,
      path: endpoint.path,
      purpose: endpoint.purpose,
      authRequired: endpoint.auth_required === true,
    }]
  })
}

function uniqueNodes(nodes: CausalGraphNode[]) {
  return [...new Map(nodes.map((node) => [node.id, node])).values()]
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5 border-t pt-4" style={{ borderColor: 'var(--card-border)' }}>
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted">{title}</h4>
      {children}
    </section>
  )
}
