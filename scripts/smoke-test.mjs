const apiBase = (process.env.ARCHAI_API_BASE ?? 'http://127.0.0.1:8010/api/v1').replace(
  /\/$/,
  '',
)

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

async function fetchWithRetry(url, init = {}, attempts = 4) {
  let lastError

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetch(url, init)
    } catch (error) {
      lastError = error
      if (attempt === attempts) {
        throw error
      }
      await new Promise((resolve) => setTimeout(resolve, attempt * 1000))
    }
  }

  throw lastError
}

async function request(path, init = {}) {
  const response = await fetchWithRetry(`${apiBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  })

  const contentType = response.headers.get('content-type') ?? ''
  const rawBody = await response.text()
  const body =
    contentType.includes('application/json') && rawBody
      ? JSON.parse(rawBody)
      : rawBody

  if (!response.ok) {
    const detail =
      typeof body === 'string' ? body : JSON.stringify(body, null, 2)
    throw new Error(
      `${init.method ?? 'GET'} ${path} failed with ${response.status}: ${detail}`,
    )
  }

  return body
}

function log(step, detail) {
  console.log(`[smoke] ${step}${detail ? `: ${detail}` : ''}`)
}

async function main() {
  log('API base', apiBase)

  const health = await request('/health', {
    headers: {
      'Content-Type': 'application/json',
    },
  })
  assert(health.status === 'ok', 'Health check did not return status=ok')
  log('Health check', `${health.service} (${health.environment})`)

  const titleSuffix = new Date().toISOString().replace(/[:.]/g, '-')
  const payload = {
    title: `VoltReserve Smoke ${titleSuffix}`,
    description:
      'Build an EV charging station booking platform for metro cities with station discovery, live charger availability, slot booking, payments, refunds, operator controls, and charging session tracking.',
    business_context:
      'The first release should support rapid city pilots with auditable payments, operator tooling, and clear charging workflows.',
    budget: 'medium',
    preferred_cloud: 'AWS',
    constraints: [
      'Must use PostgreSQL',
      'Audit logs required',
      '99.9% availability target',
    ],
  }

  const workspace = await request('/workspaces', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  assert(workspace.id, 'Workspace creation did not return an id')
  assert(
    Array.isArray(workspace.architectures) && workspace.architectures.length > 0,
    'Workspace creation did not generate architecture options',
  )
  assert(
    workspace.recommendation?.recommended_architecture_name,
    'Workspace creation did not generate a recommendation',
  )
  assert(
    workspace.requirements?.domain === 'EV Charging Booking Platform',
    'Workspace creation did not detect the EV charging domain',
  )
  assert(
    ['use_case', 'activity', 'sequence', 'class', 'er', 'component', 'deployment'].every(
      (key) => workspace.diagrams?.[key]?.mermaid && workspace.diagrams?.[key]?.plantuml,
    ),
    'Workspace creation did not generate the full diagram pack',
  )
  assert(
    workspace.documentation_markdown?.includes(payload.title),
    'Workspace documentation markdown was not generated',
  )
  assert(
    workspace.causal_graph?.nodes?.length > 0 &&
      workspace.causal_graph?.edges?.length > 0,
    'Workspace creation did not generate a causal graph',
  )
  assert(
    workspace.adrs?.length === 1,
    'Workspace creation did not persist its initial ADR',
  )
  log('Workspace created', workspace.id)

  const causalGraph = await request(`/workspaces/${workspace.id}/causal-graph`)
  const causalComponent = causalGraph.nodes.find((node) =>
    ['architecture_component', 'service_module'].includes(node.type),
  )
  assert(causalComponent, 'Causal graph did not contain an architecture component')
  const causalTrace = await request(
    `/workspaces/${workspace.id}/causal-graph/nodes/${encodeURIComponent(causalComponent.id)}`,
  )
  assert(
    causalTrace.requirements?.length > 0 && causalTrace.why_it_exists?.length > 0,
    'Architecture component did not trace back to a requirement',
  )
  log('Causal trace', `${causalComponent.id} -> ${causalTrace.requirements.length} requirements`)

  const counterfactual = await request(
    `/workspaces/${workspace.id}/counterfactual/simulate`,
    {
      method: 'POST',
      body: JSON.stringify({
        scenario:
          'What happens if users grow from 100K to 2 million, traffic increases 10x, realtime becomes required, and team size falls from 12 to 5?',
        changes: [],
      }),
    },
  )
  assert(
    counterfactual.changed_variables?.length >= 4 &&
      counterfactual.directly_affected_node_ids?.length > 0 &&
      counterfactual.after_ranking?.length === workspace.architectures.length,
    'Counterfactual simulation did not parse, trace, and re-rank the scenario',
  )
  const workspaceAfterSimulation = await request(`/workspaces/${workspace.id}`)
  assert(
    JSON.stringify(workspaceAfterSimulation.requirements) === JSON.stringify(workspace.requirements) &&
      JSON.stringify(workspaceAfterSimulation.causal_graph) === JSON.stringify(workspace.causal_graph),
    'Counterfactual simulation mutated the persisted workspace',
  )
  log('Counterfactual simulation', `${counterfactual.changed_variables.length} changes, isolated`)

  const comparisonMatrix = Object.fromEntries(
    workspace.comparison.scorecards.map((scorecard) => [
      scorecard.architecture_id,
      Object.fromEntries(
        scorecard.metric_scores.map((metric) => [metric.metric, metric.score]),
      ),
    ]),
  )
  const recommended = workspace.architectures.find(
    (architecture) =>
      architecture.id === workspace.recommendation.recommended_architecture_id,
  )
  assert(recommended, 'Recommended architecture was not present in the shortlist')

  const reweighted = await request('/analysis/reweight', {
    method: 'POST',
    body: JSON.stringify({
      matrix: comparisonMatrix,
      weights: { weights: workspace.comparison.weights },
    }),
  })
  assert(
    reweighted.length === workspace.architectures.length,
    'Architecture reweighting returned an incomplete shortlist',
  )
  log('Architecture reweighting', `${reweighted.length} scorecards`)

  const failedComponent = recommended.components[0]?.name
  assert(failedComponent, 'Recommended architecture did not contain components')
  const blastResult = await request('/analysis/blast-radius', {
    method: 'POST',
    body: JSON.stringify({
      architecture: recommended,
      failed_component: failedComponent,
      comparison_matrix: comparisonMatrix,
    }),
  })
  assert(
    blastResult.failed_component === failedComponent &&
      blastResult.statuses.length === recommended.components.length,
    'Blast-radius simulation returned an invalid result',
  )

  const mitigations = await request('/analysis/resilience-recommendations', {
    method: 'POST',
    body: JSON.stringify({ blast_result: blastResult, architecture: recommended }),
  })
  assert(mitigations.length > 0, 'No resilience recommendations were returned')

  const mitigatedResult = await request('/analysis/blast-radius/apply-mitigations', {
    method: 'POST',
    body: JSON.stringify({
      blast_result: blastResult,
      selected_mitigation_ids: [mitigations[0].id],
      architecture: recommended,
    }),
  })
  assert(
    mitigatedResult.severity_score <= blastResult.severity_score,
    'Applying a mitigation increased blast-radius severity',
  )
  log('Blast radius and mitigations', `${blastResult.severity_score} -> ${mitigatedResult.severity_score}`)

  const projectConstraints = {
    team_size: 6,
    budget_level: 'medium',
    expected_scale: workspace.requirements.scale_profile,
    timeline_weeks: 12,
  }
  const deploymentStack = workspace.deployment_plan.target_stack

  const teamFit = await request('/conway-fit', {
    method: 'POST',
    body: JSON.stringify({
      architecture: recommended,
      entities: workspace.database_design.entities.map((entity) => entity.name),
      constraints: projectConstraints,
    }),
  })
  assert(teamFit.fit_score >= 0, 'Team-fit analysis did not return a score')

  const twins = await request('/twin-match', {
    method: 'POST',
    body: JSON.stringify({
      comparison_matrix: comparisonMatrix,
      recommended_architecture_id: recommended.id,
      deployment_stack: deploymentStack,
      weights: workspace.comparison.weights,
    }),
  })
  assert(twins.length > 0, 'Industry-twin matching returned no results')

  const budgetRequest = {
    architecture: recommended,
    deployment_stack: deploymentStack,
    constraints: projectConstraints,
  }
  const budget = await request('/budget-estimate', {
    method: 'POST',
    body: JSON.stringify(budgetRequest),
  })
  assert(budget.budgets_by_scale.length > 0, 'Budget estimate returned no scale tiers')

  const budgetComparison = await request('/budget-compare', {
    method: 'POST',
    body: JSON.stringify({
      architectures: workspace.architectures,
      deployment_stacks: Object.fromEntries(
        workspace.architectures.map((architecture) => [architecture.id, deploymentStack]),
      ),
      constraints: projectConstraints,
    }),
  })
  assert(
    Object.keys(budgetComparison).length === workspace.architectures.length,
    'Budget comparison returned an incomplete architecture set',
  )
  log('Team, twin, and budget insights', 'ok')

  const clarificationAnswers = Object.fromEntries(
    (workspace.clarification_plan?.questions ?? [])
      .filter((question) => question.options?.length)
      .map((question) => [question.key, question.options[0]]),
  )

  if (Object.keys(clarificationAnswers).length > 0) {
    const clarifiedWorkspace = await request(
      `/workspaces/${workspace.id}/clarifications`,
      {
        method: 'POST',
        body: JSON.stringify({ answers: clarificationAnswers }),
      },
    )
    assert(
      clarifiedWorkspace.id === workspace.id,
      'Clarification update returned the wrong workspace id',
    )
    log(
      'Clarifications applied',
      `${Object.keys(clarificationAnswers).length} answers submitted`,
    )
  } else {
    log('Clarifications skipped', 'No follow-up questions were generated')
  }

  const changedWorkspace = await request(`/workspaces/${workspace.id}/changes`, {
    method: 'POST',
    body: JSON.stringify({
      change_request:
        'Add mobile apps to the first release and introduce CDN-backed media delivery.',
    }),
  })
  assert(
    Array.isArray(changedWorkspace.impact_history) &&
      changedWorkspace.impact_history.length > 0,
    'Change request did not record impact history',
  )
  assert(
    changedWorkspace.impact_history.at(-1)?.directly_affected_node_ids?.length > 0,
    'Change impact did not include direct causal graph nodes',
  )
  assert(
    changedWorkspace.adrs?.length >= 2,
    'Change request did not persist its ADR history',
  )
  log('Change request applied', `${changedWorkspace.impact_history.length} impact entry`)

  assert(changedWorkspace.adr, 'Change request did not generate an ADR')
  const adrResponse = await fetchWithRetry(`${apiBase}/analysis/export-adrs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ adrs: [changedWorkspace.adr] }),
  })
  assert(adrResponse.ok, `ADR export failed with ${adrResponse.status}`)
  const adrBytes = Buffer.from(await adrResponse.arrayBuffer())
  assert(
    adrBytes.subarray(0, 2).toString('utf8') === 'PK',
    'ADR export did not return a ZIP file signature',
  )
  log('ADR export', `${adrBytes.length} bytes`)

  const workspaceDetails = await request(`/workspaces/${workspace.id}`)
  assert(workspaceDetails.id === workspace.id, 'Workspace lookup failed after update')
  log('Workspace lookup', 'ok')

  const markdown = await request(
    `/workspaces/${workspace.id}/documentation/markdown`,
    {
      headers: {
        Accept: 'text/plain',
        'Content-Type': 'application/json',
      },
    },
  )
  assert(
    typeof markdown === 'string' && markdown.includes(payload.title),
    'Markdown export did not include the workspace title',
  )
  log('Markdown export', `${markdown.length} characters`)

  const pdfResponse = await fetchWithRetry(
    `${apiBase}/workspaces/${workspace.id}/documentation/pdf`,
  )
  assert(pdfResponse.ok, `PDF export failed with ${pdfResponse.status}`)
  const pdfBytes = Buffer.from(await pdfResponse.arrayBuffer())
  assert(pdfBytes.length > 0, 'PDF export was empty')
  assert(
    pdfBytes.subarray(0, 4).toString('utf8') === '%PDF',
    'PDF export did not return a PDF file signature',
  )
  log('PDF export', `${pdfBytes.length} bytes`)

  log('Smoke test passed', workspace.id)
}

main().catch((error) => {
  console.error(`[smoke] FAILED: ${error instanceof Error ? error.message : String(error)}`)
  process.exitCode = 1
})
