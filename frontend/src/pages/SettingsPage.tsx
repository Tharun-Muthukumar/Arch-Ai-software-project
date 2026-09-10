import { useState, type FormEvent } from 'react'
import { StatePanel } from '../components/workspace/StatePanel'
import { useHealthQuery } from '../hooks/useWorkspaces'
import { getApiBaseUrl, setApiBaseUrl } from '../lib/api'
import { getErrorMessage } from '../lib/utils'

export function SettingsPage() {
  const [apiBaseUrl, setApiBaseUrlState] = useState(getApiBaseUrl)
  const [saved, setSaved] = useState(false)
  const healthQuery = useHealthQuery()

  const ollamaStatus = !healthQuery.data?.ollama_enabled
    ? 'disabled'
    : !healthQuery.data.ollama_reachable
      ? 'unreachable'
      : healthQuery.data.ollama_model_available
        ? `${healthQuery.data.ollama_model} ready`
        : `${healthQuery.data.ollama_model} not installed`

  function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setApiBaseUrl(apiBaseUrl)
    setSaved(true)
    window.setTimeout(() => setSaved(false), 1800)
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <header className="page-heading">
        <div>
          <span className="eyebrow">System Configuration</span>
          <h2>Settings & Health</h2>
          <p>Configure backend API endpoints and monitor Ollama runtime status.</p>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <form className="panel" onSubmit={saveSettings}>
        <h2 className="text-lg font-semibold">API Settings</h2>
        <label className="mt-4 block space-y-1">
          <span className="text-sm font-medium">Backend API base URL</span>
          <input
            value={apiBaseUrl}
            onChange={(event) => setApiBaseUrlState(event.target.value)}
            className="input-shell"
          />
        </label>
        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="button-brand text-sm">
            Save
          </button>
          {saved ? (
            <span className="text-sm" style={{ color: 'var(--success)' }}>
              Saved.
            </span>
          ) : null}
        </div>
      </form>

      <div className="space-y-4">
        {healthQuery.isError ? (
          <StatePanel
            badge="Backend issue"
            title="Cannot reach the API"
            description={getErrorMessage(healthQuery.error)}
            tone="danger"
            actionLabel="Retry"
            onAction={() => void healthQuery.refetch()}
          />
        ) : (
          <div className="panel">
            <h2 className="text-lg font-semibold">Backend Health</h2>
            {healthQuery.isLoading ? (
              <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>Checking connection...</p>
            ) : (
              <div className="mt-2 space-y-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                <p>Service: <strong>{healthQuery.data?.service}</strong> ({healthQuery.data?.environment})</p>
                <p>Ollama: {ollamaStatus}</p>
                <p>URL: <code>{getApiBaseUrl()}</code></p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  </div>
  )
}
