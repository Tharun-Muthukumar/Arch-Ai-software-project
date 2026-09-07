import { useMutation, useQueryClient } from '@tanstack/react-query'
import { applyWorkspaceEdit, getApiBaseUrl, previewWorkspaceEdit, redoWorkspaceEdit, undoWorkspaceEdit } from '../lib/api'
import { getErrorMessage } from '../lib/utils'
import type { Workspace, WorkspaceEditRequest, WorkspaceMutationResponse } from '../types/api'
import { useToast } from '../components/ui/ToastProvider'

function replaceWorkspace(
  current: Workspace[] | undefined,
  nextWorkspace: Workspace,
) {
  const remaining = (current ?? []).filter((item) => item.id !== nextWorkspace.id)
  return [nextWorkspace, ...remaining]
}

export function useWorkspaceEditing(workspace: Workspace) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  function acceptResult(result: WorkspaceMutationResponse) {
    queryClient.setQueryData<Workspace[]>(
      ['workspaces', getApiBaseUrl()],
      (current) => replaceWorkspace(current, result.workspace),
    )
    void queryClient.invalidateQueries({ queryKey: ['causal-graph', workspace.id] })
    showToast({
      title: result.message,
      description: result.impact.items
        .filter((item) => item.level !== 'none')
        .slice(0, 3)
        .map((item) => `${item.area}: ${item.level}`)
        .join(' · '),
    })
  }

  const preview = useMutation({
    mutationFn: (edit: WorkspaceEditRequest) => previewWorkspaceEdit(workspace.id, {
      ...edit,
      expected_updated_at: workspace.updated_at,
    }),
  })
  const apply = useMutation({
    mutationFn: (edit: WorkspaceEditRequest) => applyWorkspaceEdit(workspace.id, {
      ...edit,
      expected_updated_at: workspace.updated_at,
    }),
    onSuccess: acceptResult,
    onError: (error) => showToast({
      title: 'Change was not saved',
      description: getErrorMessage(error),
      tone: 'danger',
    }),
  })
  const undo = useMutation({
    mutationFn: () => undoWorkspaceEdit(workspace.id),
    onSuccess: acceptResult,
    onError: (error) => showToast({ title: 'Undo failed', description: getErrorMessage(error), tone: 'danger' }),
  })
  const redo = useMutation({
    mutationFn: () => redoWorkspaceEdit(workspace.id),
    onSuccess: acceptResult,
    onError: (error) => showToast({ title: 'Redo failed', description: getErrorMessage(error), tone: 'danger' }),
  })

  return { preview, apply, undo, redo }
}
