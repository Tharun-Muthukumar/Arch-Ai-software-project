import {
  CheckCircle2,
  FileSliders,
  LoaderCircle,
  Sparkles,
  WandSparkles,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { sampleProject } from '../../lib/sampleProject'
import type { WorkspaceCreatePayload } from '../../types/api'

interface WorkspaceFormProps {
  isPending: boolean
  isAnalyzing: boolean
  analysisError?: string | null
  onAnalyze: (prompt: string) => Promise<WorkspaceCreatePayload>
  onSubmit: (payload: WorkspaceCreatePayload) => void
}

type InputMode = 'ai' | 'detailed'

const PROMPT_MIN_LENGTH = 40
const PROMPT_MIN_WORDS = 8
const PROMPT_MAX_LENGTH = 5000

const promptPlaceholder =
  'I want to build an EV charging station booking platform for India. Users should be able to find nearby charging stations, check real-time charger availability, reserve charging slots, pay online, and receive notifications. Charging station operators should have a dashboard to manage chargers, pricing, availability and bookings. Initially we expect around 100,000 users, but the system should scale nationally. Prefer AWS and PostgreSQL. Security and payment compliance are important.'

const initialValues = {
  title: '',
  description: '',
  business_context: '',
  preferred_cloud: '',
  constraints: '',
  team_size: '',
}

function valuesFromPayload(payload: WorkspaceCreatePayload) {
  return {
    title: payload.title,
    description: payload.description,
    business_context: payload.business_context ?? '',
    preferred_cloud: payload.preferred_cloud ?? '',
    constraints: payload.constraints.join(';\n'),
    team_size: payload.team_size ? String(payload.team_size) : '',
  }
}

export function WorkspaceForm({
  isPending,
  isAnalyzing,
  analysisError,
  onAnalyze,
  onSubmit,
}: WorkspaceFormProps) {
  const [mode, setMode] = useState<InputMode>('detailed')
  const [values, setValues] = useState(initialValues)
  const [aiPrompt, setAiPrompt] = useState('')
  const [localAnalysisError, setLocalAnalysisError] = useState<string | null>(null)
  const [showRemoteError, setShowRemoteError] = useState(false)
  const [analysisComplete, setAnalysisComplete] = useState(false)
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

  function selectMode(nextMode: InputMode) {
    setMode(nextMode)
    setLocalAnalysisError(null)
  }

  function handlePromptChange(value: string) {
    setAiPrompt(value)
    setLocalAnalysisError(null)
    setShowRemoteError(false)
  }

  async function handleAnalyze() {
    const prompt = aiPrompt.trim()
    const wordCount = prompt.split(/\s+/).filter(Boolean).length
    if (!prompt) {
      setLocalAnalysisError('Describe the project before asking ArchAI to analyze it.')
      return
    }
    if (prompt.length < PROMPT_MIN_LENGTH || wordCount < PROMPT_MIN_WORDS) {
      setLocalAnalysisError(
        `Add a little more detail: use at least ${PROMPT_MIN_LENGTH} characters and ${PROMPT_MIN_WORDS} words.`,
      )
      return
    }

    setLocalAnalysisError(null)
    setShowRemoteError(true)
    setAnalysisComplete(false)
    try {
      const analyzed = await onAnalyze(prompt)
      setValues(valuesFromPayload(analyzed))
      setAnalysisComplete(true)
      setShowRemoteError(false)
      setMode('detailed')
    } catch (error) {
      setLocalAnalysisError(
        error instanceof Error
          ? error.message
          : 'ArchAI could not analyze this project description. Please try again.',
      )
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const teamSize = Number.parseInt(values.team_size, 10)
    onSubmit({
      title: values.title.trim(),
      description: values.description.trim(),
      business_context: values.business_context.trim(),
      preferred_cloud: values.preferred_cloud || undefined,
      constraints: values.constraints
        .split(/[;\n]+/)
        .map((constraint) => constraint.trim())
        .filter(Boolean),
      team_size: Number.isFinite(teamSize) && teamSize > 0 ? Math.min(teamSize, 1000) : undefined,
    })
  }

  function loadSampleProject() {
    setValues(valuesFromPayload(sampleProject))
    setAnalysisComplete(false)
  }

  const displayedAnalysisError = localAnalysisError || (showRemoteError ? analysisError : null)

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <div className="mb-4">
        <span className="pill">Phase 1</span>
        <h3 className="section-title mt-2">Project brief</h3>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
          Describe the idea naturally or enter the structured brief yourself.
        </p>
      </div>

      <div className="segmented-control mb-5 w-full" role="tablist" aria-label="Project input method">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'ai'}
          className={mode === 'ai' ? 'is-active flex-1' : 'flex-1'}
          disabled={isPending || isAnalyzing}
          onClick={() => selectMode('ai')}
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          Describe with AI
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'detailed'}
          className={mode === 'detailed' ? 'is-active flex-1' : 'flex-1'}
          disabled={isPending || isAnalyzing}
          onClick={() => selectMode('detailed')}
        >
          <FileSliders className="h-4 w-4" aria-hidden="true" />
          Detailed Form
        </button>
      </div>

      {mode === 'ai' ? (
        <div>
          <div className="mb-4">
            <h4 className="text-lg font-semibold">Describe your project</h4>
            <p className="mt-1 text-sm leading-6" style={{ color: 'var(--text-muted)' }}>
              Tell ArchAI what you want to build. Describe your idea naturally and we'll extract the technical requirements for you.
            </p>
          </div>

          <label className="block space-y-2">
            <span className="text-sm font-medium">Project description</span>
            <textarea
              rows={12}
              maxLength={PROMPT_MAX_LENGTH}
              value={aiPrompt}
              disabled={isPending || isAnalyzing}
              onChange={(event) => handlePromptChange(event.target.value)}
              className="input-shell min-h-64 resize-y leading-6"
              placeholder={promptPlaceholder}
            />
          </label>

          <div className="mt-2 flex items-center justify-between gap-4 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span>Include users, workflows, scale, constraints, preferences, and security needs when known.</span>
            <span className="shrink-0 tabular-nums" aria-live="polite">
              {aiPrompt.length.toLocaleString()} / {PROMPT_MAX_LENGTH.toLocaleString()}
            </span>
          </div>

          {displayedAnalysisError ? (
            <div className="notice notice-danger mt-4" role="alert">
              <span>{displayedAnalysisError}</span>
            </div>
          ) : null}

          <div className="mt-5 flex justify-end">
            <button
              type="button"
              disabled={isPending || isAnalyzing}
              className="button-brand min-w-48 gap-2"
              onClick={() => void handleAnalyze()}
            >
              {isAnalyzing ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles className="h-4 w-4" aria-hidden="true" />
              )}
              {isAnalyzing ? 'Analyzing your project...' : 'Analyze Project'}
            </button>
          </div>
        </div>
      ) : (
        <div>
          {analysisComplete ? (
            <div className="notice notice-info mb-4" role="status">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span><strong>AI draft ready.</strong> Review and edit every field before generating the architecture.</span>
            </div>
          ) : null}

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

            <label className="block space-y-1">
              <span className="text-sm font-medium">Team size (engineers)</span>
              <input
                type="number"
                min={1}
                max={1000}
                step={1}
                required
                value={values.team_size}
                onChange={(event) => updateField('team_size', event.target.value)}
                className="input-shell"
                placeholder="e.g. 6"
              />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Used for Conway&apos;s Law team fit, ownership boundaries, and scoring.
              </span>
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium">Constraints</span>
              <textarea
                rows={3}
                value={values.constraints}
                onChange={(event) => updateField('constraints', event.target.value)}
                className="input-shell"
                placeholder="Must use PostgreSQL; SSO required; 99.99% availability..."
              />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Separate constraints with semicolons or new lines so multi-part statements stay complete.
              </span>
            </label>
          </div>

          {isPending ? (
            <div
              className="mt-5 flex items-start gap-3 rounded-lg border p-3"
              style={{ borderColor: 'var(--card-border)', background: 'var(--bg)' }}
              role="status"
            >
              <LoaderCircle className="mt-0.5 h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
              <div className="min-w-0 text-sm">
                <p className="font-medium">Analyzing the brief</p>
                <p className="mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  {elapsedSeconds}s elapsed. Completed sections are shown alongside this form as soon as they are ready.
                </p>
              </div>
            </div>
          ) : null}

          <div className="mt-5 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={loadSampleProject}
              className="button-secondary text-sm"
            >
              Load Sample
            </button>
            <button
              type="submit"
              disabled={isPending || isAnalyzing}
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
        </div>
      )}
    </form>
  )
}
