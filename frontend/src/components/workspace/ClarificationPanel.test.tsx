import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Workspace } from '../../types/api'
import { ClarificationPanel } from './ClarificationPanel'

const workspace = {
  id: 'workspace-1',
  clarification_plan: {
    completeness_score: 25,
    missing_areas: ['domain_open_1', 'auth'],
    questions: [
      {
        key: 'domain_open_1',
        category: 'domain',
        question: 'Which state transitions are valid?',
        rationale: 'The brief does not define them.',
        priority: 'high',
        options: [],
      },
      {
        key: 'auth',
        category: 'security',
        question: 'Which authentication model is required?',
        rationale: 'Authentication affects authorization.',
        priority: 'high',
        options: ['SSO/SAML', 'Passwordless'],
      },
    ],
  },
} as Workspace

describe('ClarificationPanel', () => {
  it('uses a text field for open questions and a populated select for choices', () => {
    const handleSubmit = vi.fn()
    render(
      <ClarificationPanel
        workspace={workspace}
        isPending={false}
        onSubmit={handleSubmit}
      />,
    )

    const applyButton = screen.getByRole('button', { name: /apply answers/i })
    expect(applyButton).toBeDisabled()
    expect(
      screen.getByRole('textbox', { name: /which state transitions/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'SSO/SAML' })).toBeInTheDocument()

    fireEvent.change(
      screen.getByRole('textbox', { name: /which state transitions/i }),
      { target: { value: 'A reviewer can approve or reject.' } },
    )
    fireEvent.change(
      screen.getByRole('combobox', { name: /which authentication model/i }),
      { target: { value: 'SSO/SAML' } },
    )
    fireEvent.click(applyButton)

    expect(handleSubmit).toHaveBeenCalledWith({
      domain_open_1: 'A reviewer can approve or reject.',
      auth: 'SSO/SAML',
    })
  })
})
