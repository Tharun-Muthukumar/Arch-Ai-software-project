import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProtectedRoute } from '../auth/ProtectedRoute'
import { AuthProvider } from '../../context/AuthContext'
import { AppShell } from './AppShell'

const user = {
  id: 'user-1',
  username: 'architect',
  email: 'architect@example.com',
  phone_number: '+1 202 555 0100',
  created_at: '2026-09-06T12:00:00Z',
}

function renderAuthenticatedApp(logoutStatus = 204) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/auth/session')) {
      return new Response(JSON.stringify({ authenticated: true, user }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    if (url.endsWith('/auth/logout') && init?.method === 'POST') {
      if (logoutStatus === 204) return new Response(null, { status: 204 })
      return new Response(JSON.stringify({ detail: 'Unable to revoke session' }), {
        status: logoutStatus,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/dashboard']}>
          <Routes>
            <Route path="/sign-in" element={<div>Signed out</div>} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/dashboard" element={<div>Dashboard content</div>} />
              </Route>
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AppShell logout', () => {
  it('revokes the session, clears authenticated state, and opens sign in', async () => {
    const fetchMock = renderAuthenticatedApp()
    expect(await screen.findByText('Dashboard content')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))

    expect(await screen.findByText('Signed out')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/auth/logout'),
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
  })

  it('keeps the session visible and reports a server logout failure', async () => {
    renderAuthenticatedApp(500)
    expect(await screen.findByText('Dashboard content')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to revoke session')
    expect(screen.getByText('Dashboard content')).toBeInTheDocument()
  })
})
