import type { QueryClient } from '@tanstack/react-query'
import { getApiBaseUrl } from './api'
import type { Workspace } from '../types/api'

/** React Query key prefix marking mutations that change workspace content. */
export const WORKSPACE_WRITE_KEY = ['workspace-write'] as const

/**
 * Push a mutated workspace into every live view instantly.
 *
 * All pages derive from the `['workspaces', baseUrl]` cache entry, so writing
 * here re-renders them with no refresh or navigation. The causal-graph query
 * key is invalidated too for the few consumers that still read it directly.
 */
export function syncWorkspaceResult(queryClient: QueryClient, nextWorkspace: Workspace) {
  queryClient.setQueryData<Workspace[]>(
    ['workspaces', getApiBaseUrl()],
    (currentWorkspaces) => {
      const remainingWorkspaces = (currentWorkspaces ?? []).filter(
        (item) => item.id !== nextWorkspace.id,
      )
      return [nextWorkspace, ...remainingWorkspaces]
    },
  )
  void queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  void queryClient.invalidateQueries({ queryKey: ['causal-graph', nextWorkspace.id] })
}
