import { useMutation, useQueryClient } from '@tanstack/react-query'
import { applyProjectAction, applyWorkspaceEdit, previewWorkspaceEdit, redoWorkspaceEdit, undoWorkspaceEdit } from '../lib/api'
import { WORKSPACE_WRITE_KEY, syncWorkspaceResult } from '../lib/workspaceSync'
import { getErrorMessage } from '../lib/utils'
import type { Workspace, WorkspaceEditRequest, WorkspaceMutationResponse } from '../types/api'
import { useToast } from '../components/ui/ToastProvider'

export function useWorkspaceEditing(workspace: Workspace) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  function acceptResult(result: WorkspaceMutationResponse) {
    syncWorkspaceResult(queryClient, result.workspace)
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
    mutationKey: [...WORKSPACE_WRITE_KEY, 'apply'],
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
    mutationKey: [...WORKSPACE_WRITE_KEY, 'undo'],
    mutationFn: () => undoWorkspaceEdit(workspace.id),
    onSuccess: acceptResult,
    onError: (error) => showToast({ title: 'Undo failed', description: getErrorMessage(error), tone: 'danger' }),
  })
  const redo = useMutation({
    mutationKey: [...WORKSPACE_WRITE_KEY, 'redo'],
    mutationFn: () => redoWorkspaceEdit(workspace.id),
    onSuccess: acceptResult,
    onError: (error) => showToast({ title: 'Redo failed', description: getErrorMessage(error), tone: 'danger' }),
  })

  // Removes extraction artifacts a project has carried since it was created.
  // A requirement model is persisted and user-edited, so it is never
  // re-derived on read and a fix to extraction cannot reach an existing
  // project on its own; this is the explicit, undoable path for that.
  const repairRequirementModel = useMutation({
    mutationKey: [...WORKSPACE_WRITE_KEY, 'repair'],
    mutationFn: () => applyProjectAction(
      workspace.id,
      { action: 'repair_requirement_model', rationale: 'Remove requirement extraction artifacts.' },
      workspace.updated_at,
    ),
    onSuccess: acceptResult,
    onError: (error) => showToast({
      title: 'Repair failed',
      description: getErrorMessage(error),
      tone: 'danger',
    }),
  })

  return { preview, apply, undo, redo, repairRequirementModel }
}
