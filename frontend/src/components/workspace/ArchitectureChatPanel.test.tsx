import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui/ToastProvider'
import type { ArchitectureChatResponse, Workspace, WorkspaceMutationResponse } from '../../types/api'
import { applyArchitectureChatProposal, sendArchitectureChat } from '../../lib/api'
import { ArchitectureChatPanel } from './ArchitectureChatPanel'

vi.mock('../../lib/api', () => ({
  getApiBaseUrl: () => 'http://test/api/v1',
  sendArchitectureChat: vi.fn(),
  applyArchitectureChatProposal: vi.fn(),
}))

const workspace = {
  id: 'workspace-1',
  title: 'Charging Platform',
  updated_at: '2026-09-11T10:00:00Z',
} as Workspace

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <ArchitectureChatPanel
            workspace={workspace}
            architectureId="modular-monolith"
            open
            onClose={vi.fn()}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('ArchitectureChatPanel', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.clearAllMocks()
  })

  it('renders an informational answer without applying a change', async () => {
    vi.mocked(sendArchitectureChat).mockResolvedValue({
      type: 'question',
      answer: 'The booking component owns the synchronous request path.',
      affected_components: ['Booking Component'],
      recommendations: [],
      proposal: null,
    })
    renderPanel()

    fireEvent.change(screen.getByLabelText(/message ai assistant/i), {
      target: { value: 'Where is the main request path?' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send message/i }))

    expect(await screen.findByText(/booking component owns/i)).toBeInTheDocument()
    expect(applyArchitectureChatProposal).not.toHaveBeenCalled()
  })

  it('does not apply a proposed change until explicit confirmation', async () => {
    const response: ArchitectureChatResponse = {
      type: 'architecture_change',
      answer: 'I prepared a cache change for review.',
      affected_components: ['Booking Component'],
      recommendations: [],
      proposal: {
        proposal_id: 'proposal-1',
        architecture_id: 'modular-monolith',
        base_updated_at: workspace.updated_at,
        request: 'Add a cache.',
        summary: 'Add booking cache',
        reasoning: 'This limits repeated availability reads.',
        architecture_changes: [{
          operation: 'add_component',
          component: {
            name: 'Booking Cache',
            responsibility: 'Caches availability reads.',
            technologies: ['Redis'],
            interactions: ['Serves Booking Component'],
            dependencies: ['Booking Component'],
          },
        }],
        requirement_additions: [],
        affected_components: ['Booking Component'],
        tradeoffs: ['Invalidation must be defined.'],
        risk_level: 'medium',
        auto_apply_safe: false,
      },
    }
    vi.mocked(sendArchitectureChat).mockResolvedValue(response)
    vi.mocked(applyArchitectureChatProposal).mockResolvedValue({
      workspace: { ...workspace, updated_at: '2026-09-11T10:01:00Z' },
      impact: { items: [], directly_affected_node_ids: [], indirectly_affected_node_ids: [], affected_artifacts: [], requires_confirmation: false },
      consistency_issues: [],
      message: 'Applied',
    } as WorkspaceMutationResponse)
    renderPanel()

    fireEvent.change(screen.getByLabelText(/message ai assistant/i), {
      target: { value: 'Add a cache.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send message/i }))

    expect(await screen.findByText('Add booking cache')).toBeInTheDocument()
    expect(applyArchitectureChatProposal).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /apply changes/i }))
    await waitFor(() => expect(applyArchitectureChatProposal).toHaveBeenCalledTimes(1))
  })

  it('automatically applies a server-verified direct project edit', async () => {
    vi.mocked(sendArchitectureChat).mockResolvedValue({
      type: 'architecture_change',
      answer: 'Adding the requirement and refreshing dependent views.',
      affected_components: [],
      recommendations: [],
      proposal: {
        proposal_id: 'proposal-auto',
        architecture_id: 'modular-monolith',
        base_updated_at: workspace.updated_at,
        request: 'Add a functional requirement: Users can export reports',
        summary: 'Add functional requirement',
        reasoning: 'The request is explicit.',
        architecture_changes: [],
        requirement_additions: [{
          target_type: 'functional_requirement',
          text: 'Users can export reports',
        }],
        affected_components: [],
        tradeoffs: [],
        risk_level: 'low',
        auto_apply_safe: true,
      },
    })
    vi.mocked(applyArchitectureChatProposal).mockResolvedValue({
      workspace: { ...workspace, updated_at: '2026-09-11T10:01:00Z' },
      impact: { items: [], directly_affected_node_ids: [], indirectly_affected_node_ids: [], affected_artifacts: [], requires_confirmation: false },
      consistency_issues: [],
      message: 'Applied',
    } as WorkspaceMutationResponse)
    renderPanel()

    fireEvent.change(screen.getByLabelText(/message ai assistant/i), {
      target: { value: 'Add a functional requirement: Users can export reports' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send message/i }))

    await waitFor(() => expect(applyArchitectureChatProposal).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Applied')).toBeInTheDocument()
  })
})
