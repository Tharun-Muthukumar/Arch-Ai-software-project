import { Wrench } from 'lucide-react'
import { useWorkspaceEditing } from '../../hooks/useWorkspaceEditing'
import type { Workspace } from '../../types/api'

/** Offers to remove extraction artifacts a project has carried since creation.
 *
 * A requirement model is persisted when a project is created and is edited by
 * the user, so unlike the diagrams it is never re-derived on read. That means a
 * fix to requirement extraction cannot reach a project that already exists: the
 * user upgrades, reloads their project, and sees the same wrong diagram, with
 * nothing in the UI explaining why.
 *
 * So the backend reports what it can *prove* is an artifact — a functional
 * requirement that is verbatim the brief's own product-title sentence, an actor
 * whose name is an access-mechanism acronym ("Sso Admin") or is not a role at
 * all ("USER") — and this is the one-click, undoable way to act on it. It is
 * never applied automatically, because the requirement model is the user's own
 * data.
 */
export function RequirementRepairNotice({ workspace }: { workspace: Workspace }) {
  const { repairRequirementModel } = useWorkspaceEditing(workspace)
  const issue = workspace.consistency_issues.find(
    (candidate) => candidate.code === 'requirement-extraction-artifact',
  )
  if (!issue) return null

  return (
    <section className="notice notice-warning repair-notice">
      <Wrench className="h-4 w-4 shrink-0" />
      <div className="repair-notice-body">
        <strong>This project carries extraction artifacts</strong>
        <p className="mt-1">{issue.message}</p>
      </div>
      <button
        type="button"
        className="button-brand shrink-0 gap-2 px-3 py-2"
        disabled={repairRequirementModel.isPending}
        onClick={() => repairRequirementModel.mutate()}
      >
        {repairRequirementModel.isPending ? 'Repairing…' : 'Repair requirement model'}
      </button>
    </section>
  )
}
