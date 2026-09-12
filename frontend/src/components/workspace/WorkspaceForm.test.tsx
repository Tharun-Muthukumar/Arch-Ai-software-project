import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sampleProject } from '../../lib/sampleProject'
import { WorkspaceForm } from './WorkspaceForm'

describe('WorkspaceForm', () => {
  function renderForm(overrides: Partial<Parameters<typeof WorkspaceForm>[0]> = {}) {
    const props = {
      isPending: false,
      isAnalyzing: false,
      analysisError: null,
      onAnalyze: vi.fn(),
      onSubmit: vi.fn(),
      ...overrides,
    }
    render(<WorkspaceForm {...props} />)
    return props
  }

  it('submits a parsed workspace payload', () => {
    const handleSubmit = vi.fn()

    renderForm({ onSubmit: handleSubmit })

    fireEvent.change(screen.getByLabelText(/project title/i), {
      target: { value: 'ArchAI Demo' },
    })
    fireEvent.change(screen.getByLabelText(/project brief/i), {
      target: { value: 'Build a learning platform for 50,000 users.' },
    })
    fireEvent.change(screen.getByLabelText(/constraints/i), {
      target: { value: 'SSO; PostgreSQL' },
    })
    fireEvent.change(screen.getByLabelText(/team size/i), {
      target: { value: '6' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: /^generate$/i }),
    )

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'ArchAI Demo',
        preferred_cloud: undefined,
        constraints: ['SSO', 'PostgreSQL'],
        team_size: 6,
      }),
    )
  })

  it('loads the sample project brief', () => {
    renderForm()

    fireEvent.click(screen.getByRole('button', { name: /load sample/i }))

    expect(screen.getByLabelText(/project title/i)).toHaveValue(
      sampleProject.title,
    )
    expect(screen.getByLabelText(/project brief/i)).toHaveValue(
      sampleProject.description,
    )
  })

  it('keeps detailed form data when switching input modes', () => {
    renderForm()

    fireEvent.change(screen.getByLabelText(/project title/i), {
      target: { value: 'Persistent Draft' },
    })
    fireEvent.click(screen.getByRole('tab', { name: /describe with ai/i }))
    fireEvent.change(screen.getByLabelText(/project description/i), {
      target: { value: 'A sufficiently detailed project description remains here too.' },
    })
    fireEvent.click(screen.getByRole('tab', { name: /detailed form/i }))

    expect(screen.getByLabelText(/project title/i)).toHaveValue('Persistent Draft')
    fireEvent.click(screen.getByRole('tab', { name: /describe with ai/i }))
    expect(screen.getByLabelText(/project description/i)).toHaveValue(
      'A sufficiently detailed project description remains here too.',
    )
  })

  it('validates an empty and underspecified AI description locally', () => {
    const { onAnalyze } = renderForm()
    fireEvent.click(screen.getByRole('tab', { name: /describe with ai/i }))

    fireEvent.click(screen.getByRole('button', { name: /analyze project/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/describe the project/i)

    fireEvent.change(screen.getByLabelText(/project description/i), {
      target: { value: 'Build a small app.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /analyze project/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/at least 40 characters and 8 words/i)
    expect(onAnalyze).not.toHaveBeenCalled()
  })

  it('populates the existing detailed form with the AI analysis result', async () => {
    const prompt = 'Build a national charging station reservation platform for drivers with live availability and online payments.'
    const onAnalyze = vi.fn().mockResolvedValue({
      title: 'Charging Station Reservations',
      description: prompt,
      business_context: 'national charging station reservation platform',
      preferred_cloud: 'AWS',
      constraints: ['Payments must be audited'],
      team_size: 8,
    })
    renderForm({ onAnalyze })

    fireEvent.click(screen.getByRole('tab', { name: /describe with ai/i }))
    fireEvent.change(screen.getByLabelText(/project description/i), {
      target: { value: prompt },
    })
    fireEvent.click(screen.getByRole('button', { name: /analyze project/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/project title/i)).toHaveValue('Charging Station Reservations')
    })
    expect(onAnalyze).toHaveBeenCalledWith(prompt)
    expect(screen.getByLabelText(/project brief/i)).toHaveValue(prompt)
    expect(screen.getByLabelText(/team size/i)).toHaveValue(8)
    expect(screen.getByRole('status')).toHaveTextContent(/ai draft ready/i)
  })
})
