import { Download } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { MarkdownPanel } from '../components/docs/MarkdownPanel'
import { StatePanel } from '../components/workspace/StatePanel'
import { downloadMarkdown, downloadPdf } from '../lib/api'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { downloadBlob, getActiveWorkspace, getErrorMessage } from '../lib/utils'

export function DocsPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(
    workspaceQuery.data,
    searchParams.get('workspace'),
  )

  if (workspaceQuery.isLoading) {
    return <StatePanel badge="Loading" title="Loading report" description="Preparing the export." />
  }

  if (workspaceQuery.isError) {
    return (
      <StatePanel
        badge="Backend issue"
        title="Could not reach the backend"
        description={getErrorMessage(workspaceQuery.error)}
        tone="danger"
        actionLabel="Retry"
        onAction={() => void workspaceQuery.refetch()}
      />
    )
  }

  if (!workspace) {
    return (
      <StatePanel
        badge="No workspace"
        title="No report available"
        description="Create a project brief from the dashboard first."
        actionLabel="Open Dashboard"
        actionTo="/dashboard"
      />
    )
  }

  const workspaceId = workspace.id
  const workspaceTitle = workspace.title

  async function handleMarkdownDownload() {
    const markdown = await downloadMarkdown(workspaceId)
    downloadBlob(
      new Blob([markdown], { type: 'text/markdown;charset=utf-8' }),
      `${workspaceTitle}.md`,
    )
  }

  async function handlePdfDownload() {
    const pdf = await downloadPdf(workspaceId)
    downloadBlob(pdf, `${workspaceTitle}.pdf`)
  }

  return (
    <div className="space-y-4">
      <div className="panel flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <span className="pill">Report</span>
          <h2 className="mt-2 text-lg font-semibold">{workspace.title}</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void handleMarkdownDownload()}
            className="button-secondary flex items-center gap-1.5 text-sm"
          >
            <Download className="h-4 w-4" /> Markdown
          </button>
          <button
            type="button"
            onClick={() => void handlePdfDownload()}
            className="button-brand flex items-center gap-1.5 text-sm"
          >
            <Download className="h-4 w-4" /> PDF
          </button>
        </div>
      </div>

      <MarkdownPanel markdown={workspace.documentation_markdown} />
    </div>
  )
}
