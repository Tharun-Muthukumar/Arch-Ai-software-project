import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { getCurrentUser, signIn, signOut } from '../lib/api'
import type { SignInPayload, UserAccount } from '../types/account'
import { AuthContext } from './auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const authQuery = useQuery({
    queryKey: ['auth-user'],
    queryFn: async () => (await getCurrentUser()).user,
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
