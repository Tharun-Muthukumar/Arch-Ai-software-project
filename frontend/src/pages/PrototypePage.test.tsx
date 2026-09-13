import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/ui/ToastProvider'
import type { Workspace } from '../types/api'
import { PrototypePage } from './PrototypePage'

const mocks = vi.hoisted(() => ({
  useWorkspacesQuery: vi.fn(),
  applyEdit: vi.fn(),
  applyProjectAction: vi.fn(),
}))

vi.mock('../hooks/useWorkspaces', () => ({
  useWorkspacesQuery: mocks.useWorkspacesQuery,
}))
vi.mock('../hooks/useWorkspaceEditing', () => ({
  useWorkspaceEditing: () => ({ apply: { mutate: mocks.applyEdit, isPending: false } }),
}))
vi.mock('../lib/api', () => ({
  applyProjectAction: mocks.applyProjectAction,
}))

const workspace = {
  id: 'workspace-1',
  title: 'EV charging booking',
  updated_at: '2026-09-13T10:00:00Z',
  requirements: {
    functional_requirements: [
      'Drivers can find nearby charging stations.',
      'Drivers can reserve an available charging slot.',
    ],
    non_functional_requirements: [],
  },
  prototype: {
    id: 'prototype-1',
    project_id: 'workspace-1',
    version: '1',
    title: 'EV charging prototype',
    domain: 'EV charging station booking',
    theme: {
      pattern: 'scheduling',
      accent: 'cyan',
      density: 'comfortable',
      accessible: true,
      realtime: true,
      offline: false,
    },
    roles: [{ actor_id: 'ACT-001', name: 'Driver', description: 'Books charging slots.' }],
    screens: [{
      id: 'PROTO-SCREEN-OVERVIEW',
      name: 'Overview',
      route: '/overview',
      purpose: 'Introduces the validated charging workflow.',
      layout: 'overview',
      actor_ids: ['ACT-001'],
      components: [{
        id: 'PROTO-COMP-OVERVIEW',
        component_type: 'hero',
        title: 'EV charging booking',
        description: 'Find and reserve charging slots.',
        fields: [],
        items: ['Nearby charging stations', 'Available charging slots'],
        actions: [{
          id: 'PROTO-ACTION-BOOKINGS',
          label: 'Open Bookings',
          action_type: 'navigate',
          target_screen_id: 'PROTO-SCREEN-BOOKING',
          source_requirement_ids: ['FR-002'],
        }],
        source_requirement_ids: ['FR-001', 'FR-002'],
        source_entity_ids: [],
      }],
      states: ['Loading', 'Empty', 'Error'],
      source_requirement_ids: ['FR-001', 'FR-002'],
      source_actor_ids: ['ACT-001'],
      source_entity_ids: [],
      visual_overrides: {},
    }, {
      id: 'PROTO-SCREEN-BOOKING',
      name: 'Bookings',
      route: '/bookings',
      purpose: 'Supports charging-slot reservations.',
      layout: 'workflow',
      actor_ids: ['ACT-001'],
      components: [{
        id: 'PROTO-COMP-BOOKING',
        component_type: 'form',
        title: 'Reserve a slot',
        description: 'Select an available charging slot.',
        fields: ['Station', 'Time slot'],
        items: [],
        actions: [{
          id: 'PROTO-ACTION-RESERVE',
          label: 'Reserve slot',
          action_type: 'submit',
          feedback: 'Reservation simulated.',
          source_requirement_ids: ['FR-002'],
        }],
        source_requirement_ids: ['FR-002'],
        source_entity_ids: [],
      }],
      states: ['Loading', 'Empty', 'Error'],
      source_requirement_ids: ['FR-002'],
      source_actor_ids: ['ACT-001'],
      source_entity_ids: [],
      visual_overrides: {},
    }],
    start_screen_id: 'PROTO-SCREEN-OVERVIEW',
    dismissed_screen_ids: [],
    warnings: [],
    generated_at: '2026-09-13T10:00:00Z',
  },
} as unknown as Workspace

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/prototype?workspace=workspace-1']}>
          <PrototypePage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('PrototypePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.useWorkspacesQuery.mockReturnValue({ data: [workspace], isLoading: false, isError: false })
  })

  it('navigates the deterministic prototype and simulates supported actions', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Prototype Studio' })).toBeInTheDocument()
    expect(screen.getByText('Drivers can find nearby charging stations.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open Bookings' }))
    expect(screen.getAllByRole('heading', { name: 'Bookings' }).length).toBeGreaterThan(0)
    expect(screen.getByText('Drivers can reserve an available charging slot.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reserve slot' }))
    expect(screen.getByText('Reservation simulated.')).toBeInTheDocument()
  })

  it('sends visual-only screen edits through the canonical workspace editor', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.click(screen.getByTitle('Rename screen'))
    fireEvent.change(screen.getByDisplayValue('Overview'), { target: { value: 'Charging home' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(mocks.applyEdit).toHaveBeenCalledWith(
      expect.objectContaining({
        target_type: 'prototype_screen',
        operation: 'update',
        target_id: 'PROTO-SCREEN-OVERVIEW',
        value: expect.objectContaining({
          name: 'Charging home',
          visual_overrides: { name: 'Charging home' },
        }),
      }),
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )
  })

  it('labels prototype-only and product-behavior additions clearly', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Add prototype screen' }))
    expect(screen.getByRole('button', { name: /prototype only/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /product behavior/i })).toBeInTheDocument()
    expect(screen.getByText(/requirements stay unchanged/i)).toBeInTheDocument()
    expect(screen.getByText(/reviewable fr plus prototype proposal/i)).toBeInTheDocument()
  })
})
