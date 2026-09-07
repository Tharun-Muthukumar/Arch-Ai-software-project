import { createContext, useContext } from 'react'
import type { SignInPayload, UserAccount } from '../types/account'

export interface AuthContextValue {
  user: UserAccount | null
  isLoading: boolean
  login: (payload: SignInPayload) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: UserAccount) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
