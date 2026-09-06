import type { Workspace } from './api'

export interface UserAccount {
  id: string
  username: string
  email: string
  phone_number: string
  created_at: string
}

export interface UserLookup {
  id: string
  username: string
  email: string
}

export interface AuthResponse {
  user: UserAccount
}

export interface SignUpPayload {
  username: string
  email: string
  phone_number: string
  password: string
  password_confirmation: string
}

export interface SignInPayload {
  identifier: string
  password: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  result_reference?: string | null
  created_at: string
}

export interface ConversationShare {
  recipient: UserLookup
  permission: 'VIEW'
  created_at: string
}

export interface ConversationSummary {
  id: string
  workspace_id: string
  title: string
  preview: string
  owner: UserLookup
  permission: 'OWNER' | 'VIEW'
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[]
  shares: ConversationShare[]
  workspace: Workspace
}
