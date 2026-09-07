import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AuthPage } from './AuthPage'

vi.mock('../context/auth', () => ({
  useAuth: () => ({
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    setUser: vi.fn(),
    isLoading: false,
  }),
}))

describe('AuthPage', () => {
  it('renders every required sign-up field without exposing a password value', () => {
    render(
      <MemoryRouter>
        <AuthPage mode="sign-up" />
      </MemoryRouter>,
    )

    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Email address')).toBeInTheDocument()
    expect(screen.getByLabelText('Phone number')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('Re-enter password')).toHaveAttribute('type', 'password')
    expect(screen.getByRole('button', { name: 'Create account' })).toBeEnabled()
  })
})
