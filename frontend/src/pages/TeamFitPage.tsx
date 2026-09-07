import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Users } from 'lucide-react'
import { StatePanel } from '../components/workspace/StatePanel'
import { useWorkspacesQuery } from '../hooks/useWorkspaces'
import { checkConwayFit } from '../lib/api'
import { detectedEntities, projectConstraints, teamSizeSource } from '../lib/insightInputs'
import { getActiveWorkspace, getErrorMessage } from '../lib/utils'
import type { ConwayFitResult } from '../types/api'

const severityClass: Record<string, string> = {
  low: 'border-green-700 bg-green-950/35',
  medium: 'border-amber-700 bg-amber-950/35',
  high: 'border-red-700 bg-red-950/35',
}

function fitColor(score: number) {
  if (score >= 7) return '#22c55e'
  if (score >= 4) return '#f59e0b'
  return '#ef4444'
}

export function TeamFitPage() {
  const [searchParams] = useSearchParams()
  const workspaceQuery = useWorkspacesQuery()
  const workspace = getActiveWorkspace(workspaceQuery.data, searchParams.get('workspace'))
  const [result, setResult] = useState<ConwayFitResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const recommended = useMemo(() => workspace && (
    workspace.architectures.find((architecture) => architecture.id === workspace.recommendation.recommended_architecture_id)
    ?? workspace.architectures[0]
  ), [workspace])
  const baseConstraints = useMemo(() => workspace ? projectConstraints(workspace) : null, [workspace])
  const source = useMemo(() => workspace ? teamSizeSource(workspace) : 'default', [workspace])
  const [teamSizeInput, setTeamSizeInput] = useState('')

  useEffect(() => {
    if (baseConstraints) setTeamSizeInput(String(baseConstraints.team_size))
  }, [baseConstraints?.team_size, workspace?.id])

  const activeTeamSize = useMemo(() => {
    const parsed = Number.parseInt(teamSizeInput, 10)
    return Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, 1000) : baseConstraints?.team_size ?? 5
  }, [teamSizeInput, baseConstraints])

  // Debounce keystrokes so typing a team size feels instant without spamming
  // the fit endpoint on every character.
  const [debouncedTeamSize, setDebouncedTeamSize] = useState(activeTeamSize)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedTeamSize(activeTeamSize), 400)
    return () => window.clearTimeout(timer)
  }, [activeTeamSize])

  const constraints = useMemo(() => (
    baseConstraints ? { ...baseConstraints, team_size: debouncedTeamSize } : null
  ), [baseConstraints, debouncedTeamSize])

  useEffect(() => {
    if (!workspace || !recommended || !constraints) return
    let active = true
    setIsLoading(true)
    setError('')
    checkConwayFit({
      architecture: recommended,
      entities: detectedEntities(workspace, recommended.components.map((component) => component.name)),
      constraints,
    }).then((response) => {
      if (active) setResult(response)
    }).catch((requestError) => {
      if (active) setError(getErrorMessage(requestError))
    }).finally(() => {
      if (active) setIsLoading(false)
    })
    return () => { active = false }
    // workspace identity covers every regeneration (edits, clarifications,
    // change requests), so the fit never shows a stale architecture's score.
  }, [workspace, recommended, constraints])

  if (workspaceQuery.isLoading) return <StatePanel badge="Loading" title="Loading team fit" description="Preparing the role recommendation." />
  if (workspaceQuery.isError) return <StatePanel badge="Backend issue" title="Could not reach the backend" description={getErrorMessage(workspaceQuery.error)} tone="danger" actionLabel="Retry" onAction={() => void workspaceQuery.refetch()} />
  if (!workspace || !recommended) return <StatePanel badge="No workspace" title="No architecture available" description="Create a project brief from the dashboard first." actionLabel="Open Dashboard" actionTo="/dashboard" />

  return <div className="space-y-5">
    <div className="panel">
      <div className="flex items-center gap-2"><Users className="h-5 w-5" style={{ color: 'var(--brand)' }} /><h2 className="text-lg font-semibold">Conway&apos;s Law Team Fit</h2></div>
      <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>A deterministic staffing plan for <strong>{recommended.name}</strong>, mapped to ownership boundaries using Conway&apos;s Law.</p>
      <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>Team size is your input; the role split is an architecture-fit recommendation that always totals that input — not an estimate of any real company&apos;s headcount.</p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="block max-w-56 space-y-1">
          <span className="text-sm font-medium">Team size (engineers)</span>
          <input
            type="number"
            min={1}
            max={1000}
            step={1}
            value={teamSizeInput}
            onChange={(event) => setTeamSizeInput(event.target.value)}
            className="input-shell"
            aria-label="Team size in engineers"
          />
        </label>
        <p className="pb-2 text-xs" style={{ color: 'var(--text-muted)' }}>
          {source === 'specified'
            ? `Using the ${baseConstraints?.team_size}-person team from the project overview. Adjust here to explore fit.`
            : 'No team size was given in the overview, so a 5-person planning baseline is used. Enter the real team size for an accurate fit.'}
        </p>
      </div>
    </div>
    {isLoading && <div className="panel text-sm" style={{ color: 'var(--text-muted)' }}>Building role recommendations...</div>}
    {error && <div className="panel text-sm text-red-300">{error}</div>}
    {result && <>
      <div className="panel flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="grid h-28 w-28 shrink-0 place-items-center rounded-full text-center" style={{ background: `conic-gradient(${fitColor(result.fit_score)} ${result.fit_score * 10}%, var(--card-border) 0)` }}><div className="grid h-20 w-20 place-items-center rounded-full" style={{ background: 'var(--surface)' }}><span className="text-lg font-bold">{result.fit_score}/10</span></div></div>
        <div><h3 className="font-semibold">Team fit score</h3><p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>{result.summary}</p></div>
      </div>
      {result.team_fit_plan.coverage_warning && <div className="flex gap-3 rounded-lg border border-amber-600 bg-amber-950/45 p-4 text-amber-100"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" /><div><h3 className="font-semibold">Coverage warning</h3><p className="mt-1 text-sm">{result.team_fit_plan.coverage_warning}</p></div></div>}
      <section><div className="mb-3 flex items-baseline justify-between"><h3 className="text-sm font-semibold">Recommended roles</h3><span className="text-xs" style={{ color: 'var(--text-muted)' }}>{result.team_fit_plan.total_team_size} total people</span></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{result.team_fit_plan.roles.map((role) => <article key={role.role_name} className="panel flex min-h-52 flex-col"><div className="flex items-start justify-between gap-3"><h4 className="font-semibold">{role.role_name}</h4><span className="grid h-12 min-w-12 place-items-center rounded-full bg-amber-500/15 px-2 text-xl font-bold text-amber-300">{role.recommended_headcount}</span></div><p className="mt-3 text-sm" style={{ color: 'var(--text-muted)' }}>{role.description}</p><p className="mt-auto pt-4 text-xs text-slate-300">{role.rationale}</p></article>)}</div></section>
      <section className="panel">
        <h3 className="text-sm font-semibold">Ownership mapping (Conway&apos;s Law)</h3>
        <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>Each ownership unit is assigned to the staffed role with the lowest current load per person.</p>
        <ul className="mt-3 space-y-2 text-sm">
          {result.ownership_mapping.map((item) => (
            <li key={`${item.component}-${item.suggested_team}`} className="flex flex-col gap-1 rounded-md border p-2.5 sm:flex-row sm:items-center sm:justify-between" style={{ borderColor: 'var(--card-border)' }}>
              <span className="font-medium">{item.component}</span>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{item.suggested_team} — {item.reason}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-3"><h3 className="text-sm font-semibold">Friction points</h3>{result.friction_points.map((point, index) => <div key={`${point.description}-${index}`} className={`rounded-lg border p-4 ${severityClass[point.severity]}`}><div className="flex items-center justify-between gap-3"><span className="font-medium">{point.description}</span><span className="rounded-full border border-current px-2 py-0.5 text-xs font-semibold capitalize">{point.severity}</span></div><p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>Components: {point.affected_components.join(', ') || 'None'} | Roles: {point.affected_teams.join(', ') || 'None'}</p></div>)}</section>
    </>}
  </div>
}
