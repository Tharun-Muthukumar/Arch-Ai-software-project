import { useEffect, useState, type FormEvent } from 'react'
import { GitCompareArrows, Play, Route, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { simulateCounterfactual } from '../../lib/api'
import {
  buildCounterfactualChanges,
  formatCounterfactualVariable,
  type CounterfactualFormValues,
} from '../../lib/counterfactual'
import type { CounterfactualSimulationResult, Workspace } from '../../types/api'

const initialValues: CounterfactualFormValues = {
  expected_users: '',
  peak_traffic_multiplier: '',
  availability_percent: '',
  latency_ms: '',
  team_size: '',
  geographic_regions: '',
  realtime_required: false,
  compliance_level: '',
  data_volume_multiplier: '',
  growth_rate_percent: '',
}

const numberFields = [
  ['expected_users', 'Expected users', 'e.g. 2000000'],
  ['peak_traffic_multiplier', 'Peak traffic multiplier', 'e.g. 10'],
  ['availability_percent', 'Availability %', 'e.g. 99.99'],
  ['latency_ms', 'Latency target (ms)', 'e.g. 100'],
  ['team_size', 'Team size', 'e.g. 5'],
  ['geographic_regions', 'Geographic regions', 'e.g. 3'],
  ['data_volume_multiplier', 'Data volume multiplier', 'e.g. 5'],
  ['growth_rate_percent', 'Annual growth %', 'e.g. 80'],
] as const

function score(value?: number | null, suffix = '') {
  return value == null ? 'Unknown' : `${value.toFixed(1)}${suffix}`
}

export function CounterfactualSimulator({ workspace }: { workspace: Workspace }) {
  const [values, setValues] = useState<CounterfactualFormValues>(initialValues)
  const [scenario, setScenario] = useState('')
  const [result, setResult] = useState<CounterfactualSimulationResult | null>(null)
  const [error, setError] = useState('')
  const [isPending, setIsPending] = useState(false)

  const update = (key: keyof CounterfactualFormValues, value: string | boolean) => {
    setValues((current) => ({ ...current, [key]: value }))
  }

  // Simulations snapshot one workspace revision: discard the result when the
  // workspace changes so a stale before/after comparison is never shown.
  const workspaceStamp = `${workspace.id}:${workspace.updated_at}`
  useEffect(() => {
    setResult(null)
    setError('')
  }, [workspaceStamp])

  const run = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setIsPending(true)
    try {
      setResult(await simulateCounterfactual(workspace.id, {
        scenario: scenario.trim() || undefined,
        changes: buildCounterfactualChanges(values),
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Simulation failed.')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="counterfactual-title">
      <form className="panel" onSubmit={run}>
        <div className="flex items-center gap-2">
          <GitCompareArrows className="h-5 w-5" style={{ color: 'var(--brand)' }} />
          <div>
            <span className="pill">Counterfactual Simulator</span>
            <h3 id="counterfactual-title" className="mt-2 font-semibold">Temporary architecture scenario</h3>
          </div>
        </div>

        <label className="mt-4 block space-y-1">
          <span className="text-sm font-medium">Scenario</span>
          <textarea
            rows={2}
            className="input-shell"
            value={scenario}
            onChange={(event) => setScenario(event.target.value)}
            placeholder="What happens if users grow from 50K to 2 million and availability rises from 99.9% to 99.99%?"
          />
        </label>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {numberFields.map(([key, label, placeholder]) => (
            <label key={key} className="block space-y-1">
              <span className="text-xs font-medium">{label}</span>
              <input
                type="number"
                step="any"
                min={0}
                className="input-shell"
                value={values[key] as string}
                onChange={(event) => update(key, event.target.value)}
                placeholder={placeholder}
              />
            </label>
          ))}
          <label className="block space-y-1">
            <span className="text-xs font-medium">Compliance level</span>
            <select className="input-shell" value={values.compliance_level as string} onChange={(event) => update('compliance_level', event.target.value)}>
              <option value="">Unchanged</option><option value="standard">Standard</option><option value="high">High</option><option value="regulated">Regulated</option>
            </select>
          </label>
          <label className="flex items-center gap-2 self-end rounded-lg border px-3 py-2.5 text-sm" style={{ borderColor: 'var(--card-border)' }}>
            <input type="checkbox" checked={values.realtime_required as boolean} onChange={(event) => update('realtime_required', event.target.checked)} />
            Real-time processing required
          </label>
        </div>

        <div className="mt-4 flex justify-end">
          <button className="button-brand gap-2" type="submit" disabled={isPending}>
            <Play className="h-4 w-4" />{isPending ? 'Simulating...' : 'Run simulation'}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-red-500" role="alert">{error}</p>}
      </form>

      {result && <SimulationResult workspace={workspace} result={result} />}
    </section>
  )
}

function SimulationResult({ workspace, result }: { workspace: Workspace; result: CounterfactualSimulationResult }) {
  const rows = [
    ['Suitability', score(result.before.suitability_score), score(result.after.suitability_score)],
    ['Architecture rank', `#${result.before.rank}`, `#${result.after.rank}`],
    ['Resilience', score(result.before.resilience_score, '/10'), score(result.after.resilience_score, '/10')],
    ['Risk', `${result.before.risk_level} (${score(result.before.risk_score)})`, `${result.after.risk_level} (${score(result.after.risk_score)})`],
    ['Team fit', score(result.before.team_fit_score, '/10'), score(result.after.team_fit_score, '/10')],
    ['Operational complexity (lower is better)', score(result.before.operational_complexity_score, '/10'), score(result.after.operational_complexity_score, '/10')],
  ]
  return (
    <>
      <div className="panel overflow-x-auto">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><span className="pill">{result.confidence} confidence</span><h3 className="mt-2 font-semibold">{result.before.architecture_name}</h3></div>
          <strong className={result.current_architecture_still_suitable ? 'text-emerald-500' : 'text-amber-500'}>
            {result.current_architecture_still_suitable ? 'Current architecture remains suitable' : 'Evolution should be evaluated'}
          </strong>
        </div>
        <table className="mt-4 w-full min-w-[620px] text-sm">
          <thead><tr className="border-b text-left" style={{ borderColor: 'var(--card-border)' }}><th className="py-2">Measure</th><th>Before</th><th>After</th></tr></thead>
          <tbody>{rows.map(([label, before, after]) => <tr key={label} className="border-b" style={{ borderColor: 'var(--card-border)' }}><td className="py-2 font-medium">{label}</td><td>{before}</td><td>{after}</td></tr>)}</tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <h3 className="font-semibold">Changed variables</h3>
          <div className="mt-3 space-y-2 text-sm">{result.changed_variables.length ? result.changed_variables.map((change) => (
            <div key={change.variable} className="flex justify-between gap-3 border-b pb-2" style={{ borderColor: 'var(--card-border)' }}><span>{formatCounterfactualVariable(change.variable)}</span><span className="text-right tabular-nums">{String(change.original_value ?? 'Unknown')} to {String(change.hypothetical_value)}</span></div>
          )) : <p style={{ color: 'var(--text-muted)' }}>No supported variable changed.</p>}</div>
        </div>
        <div className="panel">
          <h3 className="font-semibold">Architecture ranking after change</h3>
          <ol className="mt-3 space-y-2 text-sm">{result.after_ranking.map((item) => <li key={item.architecture_id} className="flex justify-between gap-3"><span>{item.rank}. {item.architecture_name}</span><span className="tabular-nums">{item.suitability_score.toFixed(1)}</span></li>)}</ol>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <div className="flex items-center gap-2"><Route className="h-4 w-4" /><h3 className="font-semibold">Recommended Evolution Path</h3></div>
          <ol className="mt-3 space-y-2 text-sm">{result.recommended_evolution_path.map((step, index) => <li key={step}>{index + 1}. {step}</li>)}</ol>
        </div>
        <div className="panel">
          <h3 className="font-semibold">Why did this change?</h3>
          <ul className="mt-3 space-y-2 text-sm">{result.explanation.map((item) => <li key={item}>{item}</li>)}</ul>
          {result.affected_components.length > 0 && <p className="mt-3 text-sm"><strong>Affected:</strong> {result.affected_components.join(', ')}</p>}
          <Link className="button-secondary mt-4 gap-2" to={`/causal-graph?workspace=${workspace.id}`}><Route className="h-4 w-4" />Trace impacted nodes</Link>
        </div>
      </div>

      {result.conflicts.length > 0 && <div className="panel border-amber-600/50"><div className="flex items-center gap-2"><TriangleAlert className="h-4 w-4 text-amber-500" /><h3 className="font-semibold">Constraint conflicts</h3></div><ul className="mt-3 space-y-2 text-sm">{result.conflicts.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{result.estimate_notes.map((note) => <p key={note}>{note}</p>)}</div>
    </>
  )
}
