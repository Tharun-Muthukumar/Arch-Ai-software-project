import type { Workspace, WorkspaceCreatePayload, ProjectDescriptionAnalyzePayload, ReweightRequest, ExportAdrsRequest, BlastRadiusRequest, CausalGraph, CausalGraphTrace, WorkspaceEditPreview, WorkspaceEditRequest, WorkspaceMutationResponse } from '../types/api'
import type { ArchitectureScorecard, BlastRadiusResult } from '../types/api'
import type { ResilienceRecommendationsRequest, ApplyMitigationsRequest, ResilienceRecommendation } from '../types/api'
import type { ConwayFitRequest, ConwayFitResult, TwinMatch, TwinMatchRequest } from '../types/api'
import type { ArchitectureChangeProposal, ArchitectureChatRequest, ArchitectureChatResponse, ArchitectureRiskAnalysis } from '../types/api'
import type { HealthStatus } from '../types/client'
import type { CounterfactualSimulationRequest, CounterfactualSimulationResult } from '../types/api'
import type {
  AuthResponse,
  AuthSessionResponse,
  ConversationDetail,
  ConversationShare,
  ConversationSummary,
  SignInPayload,
  SignUpPayload,
  UserLookup,
} from '../types/account'

const STORAGE_KEY = 'archai-api-base'

function resolveDefaultApiBaseUrl() {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL
  }

  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8010/api/v1`
  }

  return 'http://127.0.0.1:8010/api/v1'
}

const DEFAULT_API_BASE_URL = resolveDefaultApiBaseUrl()

function normalizeApiBaseUrl(value: string) {
  return value.trim().replace(/\/+$/, '')
}

export function getApiBaseUrl() {
  if (typeof window === 'undefined') {
    return DEFAULT_API_BASE_URL
  }

  return normalizeApiBaseUrl(
    window.localStorage.getItem(STORAGE_KEY) || DEFAULT_API_BASE_URL,
  )
}

export function setApiBaseUrl(value: string) {
  if (typeof window !== 'undefined') {
    const normalizedValue = normalizeApiBaseUrl(value)
    if (normalizedValue) {
      window.localStorage.setItem(STORAGE_KEY, normalizedValue)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  }
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new Error(
      `Could not reach the ArchAI API at ${getApiBaseUrl()}. Start the backend and make sure this frontend origin is allowed.`,
    )
  }

  if (!response.ok) {
    const responseText = await response.text()
    let message = responseText || `Request failed with status ${response.status}`
    try {
      const parsed = JSON.parse(responseText) as { detail?: string | Array<{ msg?: string }> }
      if (typeof parsed.detail === 'string') {
        message = parsed.detail
      } else if (Array.isArray(parsed.detail)) {
        message = parsed.detail.map((item) => item.msg).filter(Boolean).join('. ')
      }
    } catch {
      // Keep the server response text when it is not JSON.
    }
    throw new ApiError(message, response.status)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

const riskSeverities = new Set(['critical', 'high', 'medium', 'low', 'informational'])
const riskCategories = new Set([
  'reliability',
  'scalability',
  'security',
  'performance',
  'data',
  'cost',
  'operations',
  'compliance',
  'architecture_complexity',
  'resilience',
])

function requireArchitectureChatResponse(value: unknown): ArchitectureChatResponse {
  if (!isRecord(value) ||
      (value.type !== 'question' && value.type !== 'architecture_change') ||
      typeof value.answer !== 'string' ||
      !isStringArray(value.affected_components) ||
      !isStringArray(value.recommendations)) {
    throw new Error('AI Assistant returned an invalid response.')
  }
  if (value.type === 'question' && value.proposal != null) {
    throw new Error('AI Assistant returned an invalid informational response.')
  }
  if (value.type === 'architecture_change') {
    const proposal = value.proposal
    if (!isRecord(proposal) ||
        typeof proposal.proposal_id !== 'string' ||
        typeof proposal.architecture_id !== 'string' ||
        typeof proposal.base_updated_at !== 'string' ||
        typeof proposal.request !== 'string' ||
        typeof proposal.summary !== 'string' ||
        typeof proposal.reasoning !== 'string' ||
        !['low', 'medium', 'high'].includes(String(proposal.risk_level)) ||
        typeof proposal.auto_apply_safe !== 'boolean' ||
        !Array.isArray(proposal.architecture_changes) ||
        !Array.isArray(proposal.requirement_additions) ||
        !isStringArray(proposal.affected_components) ||
        !isStringArray(proposal.tradeoffs)) {
      throw new Error('AI Assistant returned an invalid change proposal.')
    }
  }
  return value as unknown as ArchitectureChatResponse
}

function requireRiskAnalysis(value: unknown): ArchitectureRiskAnalysis {
  if (!isRecord(value) ||
      typeof value.workspace_id !== 'string' ||
      typeof value.architecture_id !== 'string' ||
      typeof value.analyzed_workspace_updated_at !== 'string' ||
      typeof value.overall_risk !== 'string' ||
      !riskSeverities.has(value.overall_risk) ||
      typeof value.overview !== 'string' ||
      !isRecord(value.summary) ||
      !Array.isArray(value.risks)) {
    throw new Error('Risk Detector returned an invalid response.')
  }
  const summary = value.summary
  const counts = ['critical', 'high', 'medium', 'low', 'informational']
  if (counts.some((severity) =>
    typeof summary[severity] !== 'number' ||
    !Number.isInteger(summary[severity]) ||
    Number(summary[severity]) < 0)) {
    throw new Error('Risk Detector returned an invalid summary.')
  }
  const validRisks = value.risks.every((risk) =>
    isRecord(risk) &&
    typeof risk.id === 'string' &&
    typeof risk.title === 'string' &&
    typeof risk.category === 'string' && riskCategories.has(risk.category) &&
    typeof risk.severity === 'string' && riskSeverities.has(risk.severity) &&
    typeof risk.description === 'string' &&
    typeof risk.evidence === 'string' &&
    typeof risk.impact === 'string' &&
    typeof risk.recommendation === 'string' &&
    typeof risk.confidence === 'number' && Number.isFinite(risk.confidence) &&
    risk.confidence >= 0 && risk.confidence <= 1 &&
    typeof risk.needs_verification === 'boolean' &&
    isStringArray(risk.affected_components) &&
    isStringArray(risk.related_node_ids),
  )
  if (!validRisks) throw new Error('Risk Detector returned an invalid finding.')
  return value as unknown as ArchitectureRiskAnalysis
}

export function listWorkspaces(activeWorkspaceId?: string | null) {
  const query = activeWorkspaceId
    ? `?active_workspace_id=${encodeURIComponent(activeWorkspaceId)}`
    : ''
  return request<Workspace[]>(`/workspaces${query}`)
}

export function getHealth() {
  return request<HealthStatus>('/health')
}

export function createWorkspace(payload: WorkspaceCreatePayload) {
  return request<Workspace>('/workspaces', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function analyzeProjectDescription(payload: ProjectDescriptionAnalyzePayload) {
  return request<WorkspaceCreatePayload>('/workspaces/analyze-description', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface GenerationProgress {
  section: string
  status: 'complete'
  item_count: number
  preview?: string[]
}

interface WorkspaceStreamComplete {
  workspace: Workspace
  metrics?: {
    generation_time_ms: number
    llm_calls: number
    cache_hits: number
  }
}

export async function createWorkspaceStreaming(
  payload: WorkspaceCreatePayload,
  onProgress: (progress: GenerationProgress) => void,
) {
  let response: Response
  try {
    response = await fetch(`${getApiBaseUrl()}/workspaces/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new Error(
      `Could not reach the ArchAI API at ${getApiBaseUrl()}. Start the backend and make sure this frontend origin is allowed.`,
    )
  }

  if (!response.ok) {
    const responseText = await response.text()
    throw new ApiError(responseText || `Request failed with status ${response.status}`, response.status)
  }
  if (!response.body) {
    throw new Error('The server did not provide a generation stream.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completedWorkspace: Workspace | null = null

  const processBlock = (block: string) => {
    const lines = block.split(/\r?\n/)
    const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
    const data = lines
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!eventName || !data) return
    const parsed = JSON.parse(data) as GenerationProgress | WorkspaceStreamComplete | { message: string }
    if (eventName === 'progress') {
      onProgress(parsed as GenerationProgress)
    } else if (eventName === 'complete') {
      completedWorkspace = (parsed as WorkspaceStreamComplete).workspace
    } else if (eventName === 'error') {
      throw new Error((parsed as { message: string }).message)
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    blocks.forEach(processBlock)
    if (done) break
  }
  if (buffer.trim()) processBlock(buffer)
  if (!completedWorkspace) {
    throw new Error('Generation ended before the workspace was completed.')
  }
  return completedWorkspace as Workspace
}

export function answerClarifications(
  workspaceId: string,
  answers: Record<string, string>,
) {
  return request<Workspace>(`/workspaces/${workspaceId}/clarifications`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  })
}

export function applyChangeRequest(workspaceId: string, changeRequest: string) {
  return request<Workspace>(`/workspaces/${workspaceId}/changes`, {
    method: 'POST',
    body: JSON.stringify({ change_request: changeRequest }),
  })
}

export async function sendArchitectureChat(
  workspaceId: string,
  payload: ArchitectureChatRequest,
) {
  const response = await request<unknown>(`/workspaces/${workspaceId}/architecture-chat`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return requireArchitectureChatResponse(response)
}

export function applyArchitectureChatProposal(
  workspaceId: string,
  proposal: ArchitectureChangeProposal,
) {
  return request<WorkspaceMutationResponse>(
    `/workspaces/${workspaceId}/architecture-chat/apply`,
    { method: 'POST', body: JSON.stringify({ proposal }) },
  )
}

export async function analyzeArchitectureRisks(
  workspaceId: string,
  architectureId?: string | null,
  includeAi = false,
) {
  const response = await request<unknown>(`/workspaces/${workspaceId}/risk-analysis`, {
    method: 'POST',
    body: JSON.stringify({ architecture_id: architectureId ?? null, include_ai: includeAi }),
  })
  return requireRiskAnalysis(response)
}

export function previewWorkspaceEdit(workspaceId: string, edit: WorkspaceEditRequest) {
  return request<WorkspaceEditPreview>(`/workspaces/${workspaceId}/edits/preview`, {
    method: 'POST',
    body: JSON.stringify(edit),
  })
}

export function applyWorkspaceEdit(workspaceId: string, edit: WorkspaceEditRequest) {
  return request<WorkspaceMutationResponse>(`/workspaces/${workspaceId}/edits`, {
    method: 'POST',
    body: JSON.stringify(edit),
  })
}

export function undoWorkspaceEdit(workspaceId: string) {
  return request<WorkspaceMutationResponse>(`/workspaces/${workspaceId}/edits/undo`, {
    method: 'POST',
  })
}

export function redoWorkspaceEdit(workspaceId: string) {
  return request<WorkspaceMutationResponse>(`/workspaces/${workspaceId}/edits/redo`, {
    method: 'POST',
  })
}

export function signUp(payload: SignUpPayload) {
  return request<AuthResponse>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function signIn(payload: SignInPayload) {
  return request<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function signOut() {
  await request<void>('/auth/logout', { method: 'POST' })
}

export function getCurrentUser() {
  return request<AuthSessionResponse>('/auth/session')
}

export function updateProfile(phoneNumber: string) {
  return request<AuthResponse>('/auth/profile', {
    method: 'PATCH',
    body: JSON.stringify({ phone_number: phoneNumber }),
  })
}

export function listHistory() {
  return request<ConversationSummary[]>('/history')
}

export function getConversation(conversationId: string) {
  return request<ConversationDetail>(`/history/${conversationId}`)
}

export function updateConversationTitle(conversationId: string, title: string) {
  return request<ConversationSummary>(`/history/${conversationId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

export function deleteConversation(conversationId: string) {
  return request<void>(`/history/${conversationId}`, { method: 'DELETE' })
}

export function searchUsers(query: string) {
  return request<UserLookup[]>(`/users/search?q=${encodeURIComponent(query)}`)
}

export function shareConversation(conversationId: string, recipientId: string) {
  return request<ConversationShare>(`/history/${conversationId}/shares`, {
    method: 'POST',
    body: JSON.stringify({ recipient_id: recipientId, permission: 'VIEW' }),
  })
}

export function revokeConversationShare(conversationId: string, recipientId: string) {
  return request<void>(`/history/${conversationId}/shares/${recipientId}`, {
    method: 'DELETE',
  })
}

export function getCausalGraph(workspaceId: string) {
  return request<CausalGraph>(`/workspaces/${workspaceId}/causal-graph`)
}

export function explainCausalNode(workspaceId: string, nodeId: string) {
  return request<CausalGraphTrace>(
    `/workspaces/${workspaceId}/causal-graph/nodes/${encodeURIComponent(nodeId)}`,
  )
}

export function simulateCounterfactual(
  workspaceId: string,
  payload: CounterfactualSimulationRequest,
) {
  return request<CounterfactualSimulationResult>(
    `/workspaces/${workspaceId}/counterfactual/simulate`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export async function downloadMarkdown(workspaceId: string) {
  let response: Response

  try {
    response = await fetch(
      `${getApiBaseUrl()}/workspaces/${workspaceId}/documentation/markdown`,
      { credentials: 'include' },
    )
  } catch {
    throw new Error(
      `Could not reach the ArchAI API at ${getApiBaseUrl()} while downloading markdown.`,
    )
  }

  if (!response.ok) {
    throw new Error(await response.text())
  }
  return response.text()
}

export async function downloadPdf(workspaceId: string) {
  let response: Response

  try {
    response = await fetch(
      `${getApiBaseUrl()}/workspaces/${workspaceId}/documentation/pdf`,
      { credentials: 'include' },
    )
  } catch {
    throw new Error(
      `Could not reach the ArchAI API at ${getApiBaseUrl()} while downloading the PDF export.`,
    )
  }

  if (!response.ok) {
    throw new Error(await response.text())
  }
  return response.blob()
}

export function reweightArchitectures(payload: ReweightRequest) {
  return request<ArchitectureScorecard[]>('/analysis/reweight', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function exportAdrs(payload: ExportAdrsRequest) {
  let response: Response

  try {
    response = await fetch(`${getApiBaseUrl()}/analysis/export-adrs`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new Error(
      `Could not reach the ArchAI API at ${getApiBaseUrl()} while exporting ADRs.`,
    )
  }

  if (!response.ok) {
    throw new Error(await response.text())
  }
  return response.blob()
}

export function simulateBlastRadius(payload: BlastRadiusRequest) {
  return request<BlastRadiusResult>('/analysis/blast-radius', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchResilienceRecommendations(payload: ResilienceRecommendationsRequest) {
  return request<ResilienceRecommendation[]>('/analysis/resilience-recommendations', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function applyMitigations(payload: ApplyMitigationsRequest) {
  return request<BlastRadiusResult>('/analysis/blast-radius/apply-mitigations', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function checkConwayFit(payload: ConwayFitRequest) {
  return request<ConwayFitResult>('/conway-fit', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchTwinMatches(payload: TwinMatchRequest) {
  return request<TwinMatch[]>('/twin-match', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
