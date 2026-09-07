import type { ProjectConstraints, Workspace } from '../types/api'

export function comparisonMatrix(workspace: Workspace): Record<string, Record<string, number>> {
  return Object.fromEntries(workspace.comparison.scorecards.map((scorecard) => [
    scorecard.architecture_id,
    Object.fromEntries(scorecard.metric_scores.map((metric) => [metric.metric, metric.score])),
  ]))
}

export function detectedEntities(workspace: Workspace, fallbackComponents: string[]): string[] {
  const entities = workspace.database_design.entities.map((entity) => entity.name)
  return entities.length > 0 ? entities : fallbackComponents
}

export function deploymentStack(workspace: Workspace): string[] {
  return Array.from(new Set([
    ...workspace.deployment_plan.target_stack,
    ...workspace.deployment_plan.docker_services,
    ...workspace.deployment_plan.kubernetes_modules,
  ]))
}

export function projectConstraints(workspace: Workspace): ProjectConstraints {
  const teamMatch = /\d+/.exec(workspace.answers.team_size ?? '')
  const teamSize = teamMatch ? Number.parseInt(teamMatch[0].trim(), 10) : Number.NaN
  const timeline = Number.parseInt(workspace.answers.timeline_weeks ?? '', 10)
  const budget = workspace.answers.budget?.toLowerCase()
  return {
    team_size: Number.isFinite(teamSize) && teamSize > 0 ? Math.min(teamSize, 1000) : 5,
    budget_level: budget === 'low' || budget === 'high' ? budget : 'medium',
    expected_scale: workspace.requirements.scale_profile,
    timeline_weeks: Number.isFinite(timeline) && timeline > 0 ? timeline : 12,
  }
}

export function teamSizeSource(workspace: Workspace): 'specified' | 'default' {
  const teamMatch = /\d+/.exec(workspace.answers.team_size ?? '')
  const teamSize = teamMatch ? Number.parseInt(teamMatch[0], 10) : Number.NaN
  return Number.isFinite(teamSize) && teamSize > 0 ? 'specified' : 'default'
}
