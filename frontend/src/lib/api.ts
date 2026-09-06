import type { Workspace, WorkspaceCreatePayload, ReweightRequest, ExportAdrsRequest, BlastRadiusRequest, CausalGraph, CausalGraphTrace } from '../types/api'
import type { ArchitectureScorecard, BlastRadiusResult } from '../types/api'
import type { ResilienceRecommendationsRequest, ApplyMitigationsRequest, ResilienceRecommendation } from '../types/api'
import type { BudgetCompareRequest, BudgetEstimate, BudgetEstimateRequest, ConwayFitRequest, ConwayFitResult, TwinMatch, TwinMatchRequest } from '../types/api'
import type { HealthStatus } from '../types/client'
import type { CounterfactualSimulationRequest, CounterfactualSimulationResult } from '../types/api'

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
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
    throw new Error(await response.text())
  }

  return response.json() as Promise<T>
}

export function listWorkspaces() {
  return request<Workspace[]>('/workspaces')
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

export function fetchBudgetEstimate(payload: BudgetEstimateRequest) {
  return request<BudgetEstimate>('/budget-estimate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchBudgetComparison(payload: BudgetCompareRequest) {
  return request<Record<string, BudgetEstimate>>('/budget-compare', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
