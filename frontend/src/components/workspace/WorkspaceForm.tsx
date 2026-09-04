import { LoaderCircle, WandSparkles } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { sampleProject } from '../../lib/sampleProject'
import type { WorkspaceCreatePayload } from '../../types/api'

interface WorkspaceFormProps {
  isPending: boolean
  onSubmit: (payload: WorkspaceCreatePayload) => void
}

const initialValues = {
  title: '',
  description: '',
  business_context: '',
  budget: '',
  preferred_cloud: '',
  constraints: '',
}

export function WorkspaceForm({ isPending, onSubmit }: WorkspaceFormProps) {
  const [values, setValues] = useState(initialValues)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  useEffect(() => {
    if (!isPending) {
      setElapsedSeconds(0)
      return
    }

    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [isPending])

  function updateField(field: keyof typeof initialValues, value: string) {
    setValues((currentValues) => ({ ...currentValues, [field]: value }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit({
      title: values.title.trim(),
      description: values.description.trim(),
      business_context: values.business_context.trim(),
      budget: values.budget || undefined,
      preferred_cloud: values.preferred_cloud || undefined,
      constraints: values.constraints
        .split(',')
        .map((constraint) => constraint.trim())
        .filter(Boolean),
    })
  }

  function loadSampleProject() {
    setValues({
      title: sampleProject.title,
      description: sampleProject.description,
      business_context: sampleProject.business_context ?? '',
      budget: sampleProject.budget ?? 'medium',
      preferred_cloud: sampleProject.preferred_cloud ?? 'AWS',
      constraints: sampleProject.constraints.join(', '),
    })
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <div className="mb-4">
        <span className="pill">Phase 1</span>
        <h3 className="section-title mt-2">Project brief</h3>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
          Enter the brief once and ArchAI will generate the workspace.
        </p>
      </div>

      <div className="space-y-4">
        <label className="block space-y-1">
          <span className="text-sm font-medium">Project title</span>
          <input
            required
            value={values.title}
            onChange={(event) => updateField('title', event.target.value)}
            className="input-shell"
            placeholder="VoltReserve, MediBridge, CampusFlow..."
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">Project brief</span>
          <textarea
            required
            rows={5}
            value={values.description}
            onChange={(event) => updateField('description', event.target.value)}
            className="input-shell"
            placeholder="Build an EV charging station booking platform with live availability..."
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">Business context</span>
          <textarea
            rows={3}
            value={values.business_context}
            onChange={(event) => updateField('business_context', event.target.value)}
            className="input-shell"
            placeholder="Launch urgency, regional rollout, compliance pressure..."
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Budget</span>
            <select
              value={values.budget}
              onChange={(event) => updateField('budget', event.target.value)}
              className="input-shell"
            >
              <option value="">Not specified</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-sm font-medium">Cloud</span>
            <select
              value={values.preferred_cloud}
              onChange={(event) => updateField('preferred_cloud', event.target.value)}
              className="input-shell"
            >
              <option value="">Not specified</option>
              <option value="AWS">AWS</option>
              <option value="Azure">Azure</option>
              <option value="GCP">GCP</option>
              <option value="On-premise">On-premise</option>
              <option value="No preference">No preference</option>
            </select>
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-sm font-medium">Constraints</span>
          <input
            value={values.constraints}
            onChange={(event) => updateField('constraints', event.target.value)}
            className="input-shell"
            placeholder="PCI-aware checkout, must use PostgreSQL, SSO required..."
          />
        </label>
      </div>

      {isPending && (
        <div
          className="mt-5 flex items-start gap-3 rounded-lg border p-3"
          style={{ borderColor: 'var(--card-border)', background: 'var(--bg)' }}
          role="status"
        >
          <LoaderCircle className="mt-0.5 h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
          <div className="min-w-0 text-sm">
            <p className="font-medium">Analyzing the brief</p>
            <p className="mt-0.5" style={{ color: 'var(--text-muted)' }}>
              {elapsedSeconds}s elapsed. Unseen domains use local Ollama/Qwen before the remaining designs are generated.
            </p>
          </div>
        </div>
      )}

      <div className="mt-5 flex items-center justify-between">
        <button
          type="button"
          onClick={loadSampleProject}
          className="button-secondary text-sm"
        >
          Load Sample
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="button-brand gap-2"
        >
          {isPending ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <WandSparkles className="h-4 w-4" aria-hidden="true" />
          )}
          {isPending ? 'Analyzing...' : 'Generate'}
        </button>
      </div>
    </form>
  )
}
