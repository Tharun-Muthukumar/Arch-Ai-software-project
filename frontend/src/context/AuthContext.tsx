import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'
import { ApiError, getCurrentUser, signIn, signOut } from '../lib/api'
import type { SignInPayload, UserAccount } from '../types/account'

interface AuthContextValue {
  user: UserAccount | null
  isLoading: boolean
  login: (payload: SignInPayload) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: UserAccount) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const authQuery = useQuery({
    queryKey: ['auth-user'],
    queryFn: async () => {
      try {
        return (await getCurrentUser()).user
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return null
        }
        throw error
      }
    },
    retry: false,
    staleTime: 60_000,
  })

  async function login(payload: SignInPayload) {
    const response = await signIn(payload)
    queryClient.removeQueries({ queryKey: ['workspaces'] })
    queryClient.removeQueries({ queryKey: ['history'] })
    queryClient.setQueryData(['auth-user'], response.user)
  }

  async function logout() {
    await signOut()
    await queryClient.cancelQueries()
    queryClient.removeQueries({
      predicate: (query) => query.queryKey[0] !== 'auth-user',
    })
    queryClient.setQueryData(['auth-user'], null)
  }

  function setUser(user: UserAccount) {
    queryClient.setQueryData(['auth-user'], user)
  }

  return (
    <AuthContext.Provider
      value={{
        user: authQuery.data ?? null,
        isLoading: authQuery.isLoading,
        login,
        logout,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
