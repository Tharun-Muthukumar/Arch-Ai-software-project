import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getApiBaseUrl, getHealth, listWorkspaces } from '../lib/api'

export function useWorkspacesQuery() {
  const [searchParams] = useSearchParams()
  const activeWorkspaceId = searchParams.get('workspace')
  return useQuery({
    queryKey: ['workspaces', getApiBaseUrl(), activeWorkspaceId ?? 'latest'],
    queryFn: () => listWorkspaces(activeWorkspaceId),
  })
}

export function useHealthQuery() {
  return useQuery({
    queryKey: ['health', getApiBaseUrl()],
    queryFn: getHealth,
    retry: 1,
    staleTime: 15_000,
  })
}
