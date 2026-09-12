import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ArchitectureRiskAnalysis, Workspace } from '../types/api'
import { RiskDetectorPage } from './RiskDetectorPage'

const mocks = vi.hoisted(() => ({
  useWorkspacesQuery: vi.fn(),
  analyzeArchitectureRisks: vi.fn(),
}))

vi.mock('../hooks/useWorkspaces', () => ({
  useWorkspacesQuery: mocks.useWorkspacesQuery,
}))
vi.mock('../lib/api', () => ({
  analyzeArchitectureRisks: mocks.analyzeArchitectureRisks,
}))

const workspace = {
  id: 'workspace-1',
  title: 'Charging Platform',
  updated_at: '2026-09-11T10:00:00Z',
  recommendation: {
    recommended_architecture_id: 'modular-monolith',
  },
  architectures: [{
    id: 'modular-monolith',
    name: 'Modular Monolith',
    components: [{ name: 'Booking Component' }],
  }],
} as Workspace

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/risk-detector?workspace=workspace-1']}>
        <RiskDetectorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RiskDetectorPage', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.clearAllMocks()
  })

  it('shows a safe empty state when no architecture exists', () => {
    mocks.useWorkspacesQuery.mockReturnValue({ data: [], isLoading: false, isError: false })
    renderPage()
    expect(screen.getByText(/no architecture available/i)).toBeInTheDocument()
  })

  it('renders validated findings and marks an older analysis stale', async () => {
    const result: ArchitectureRiskAnalysis = {
      workspace_id: workspace.id,
      architecture_id: 'modular-monolith',
      analyzed_workspace_updated_at: '2026-09-11T09:00:00Z',
      overall_risk: 'high',
      overview: 'One availability concern needs verification.',
      summary: { critical: 0, high: 1, medium: 0, low: 0, informational: 0 },
      risks: [{
        id: 'risk-001',
        title: 'Database failover is not explicitly represented',
        category: 'reliability',
        severity: 'high',
        description: 'Potential risk in the current persistence path.',
        evidence: 'No replica or failover strategy is represented.',
        affected_components: ['Booking Component'],
        impact: 'Booking may be interrupted during an outage.',
        recommendation: 'Confirm availability needs and define failover.',
        confidence: 0.86,
        needs_verification: true,
        related_node_ids: ['CMP-001'],
      }],
    }
    mocks.useWorkspacesQuery.mockReturnValue({ data: [workspace], isLoading: false, isError: false })
    mocks.analyzeArchitectureRisks.mockResolvedValue(result)
    renderPage()

    fireEvent.click(screen.getAllByRole('button', { name: /analyze architecture/i })[0])
    expect(await screen.findByText('Database failover is not explicitly represented')).toBeInTheDocument()
    expect(screen.getByText(/architecture changed since this analysis/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /view blast radius/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /view causal graph/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ask ai assistant/i })).toBeInTheDocument()
    await waitFor(() => {
      expect(mocks.analyzeArchitectureRisks).toHaveBeenCalledWith(
        workspace.id,
        'modular-monolith',
        false,
      )
      expect(mocks.analyzeArchitectureRisks).toHaveBeenCalledWith(
        workspace.id,
        'modular-monolith',
        true,
      )
    })
  })
})
