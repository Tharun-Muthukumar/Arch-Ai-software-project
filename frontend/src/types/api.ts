export interface Actor {
  name: string
  description: string
}

export interface DomainEntityHint {
  name: string
  description: string
  attributes: string[]
}

export interface DomainWorkflowHint {
  name: string
  description: string
  primary_actor: string
  related_entities: string[]
}

export interface RequirementModel {
  summary: string
  domain: string
  scale_profile: string
  functional_requirements: string[]
  non_functional_requirements: string[]
  actors: Actor[]
  constraints: string[]
  assumptions: string[]
  domain_entities: DomainEntityHint[]
  domain_workflows: DomainWorkflowHint[]
  integrations: string[]
  data_characteristics: string[]
  open_questions: string[]
  analysis_source: 'predefined-blueprint' | 'ollama-pretrained' | 'conservative-fallback' | 'legacy'
  analysis_warnings: string[]
}

export interface ClarificationQuestion {
  key: string
  category: string
  question: string
  rationale: string
  priority: string
  options: string[]
}

export interface ClarificationPlan {
  completeness_score: number
  missing_areas: string[]
  questions: ClarificationQuestion[]
}

export interface ArchitectureComponent {
  name: string
  responsibility: string
  technologies: string[]
  interactions: string[]
}

export interface ArchitectureOption {
  id: string
  name: string
  style: string
  overview: string
  components: ArchitectureComponent[]
  data_flow: string[]
  technology_stack: string[]
  database: string
  api_style: string
  deployment: string
  advantages: string[]
  disadvantages: string[]
  suitable_scenarios: string[]
  estimated_complexity: string
  estimated_cost: string
  maintenance: string
}

export interface MetricScore {
  metric: string
  score: number
  explanation: string
}

export interface ArchitectureScorecard {
  architecture_id: string
  architecture_name: string
  overall_score: number
  weighted_score: number
  metric_scores: MetricScore[]
  strengths: string[]
  risks: string[]
}

export interface ComparisonResult {
  weights: Record<string, number>
  scorecards: ArchitectureScorecard[]
  reasoning: string[]
}

export interface RecommendationResult {
  recommended_architecture_id: string
  recommended_architecture_name: string
  decision_summary: string
  why: string[]
  why_not: Record<string, string[]>
  rollout_plan: string[]
  confidence: string
}

export interface DiagramArtifact {
  title: string
  description: string
  mermaid: string
  plantuml: string
}

export interface DatabaseField {
  name: string
  data_type: string
  nullable: boolean
  indexed: boolean
  description: string
}

export interface DatabaseEntity {
  name: string
  description: string
  fields: DatabaseField[]
}

export interface DatabaseRelationship {
  source: string
  target: string
  relationship: string
  description: string
}

export interface DatabaseDesign {
  database_engine: string
  entities: DatabaseEntity[]
  relationships: DatabaseRelationship[]
  indexes: string[]
  normalization_notes: string[]
  sql_schema: string
  sample_inserts: string
}

export interface ApiEndpoint {
  method: string
  path: string
  purpose: string
  auth_required: boolean | null
  request_example: Record<string, unknown>
  response_example: Record<string, unknown>
}

export interface ApiGroup {
  name: string
  description: string
  endpoints: ApiEndpoint[]
}

export interface ApiDesign {
  style: string
  authentication_strategy: string
  groups: ApiGroup[]
  validation_rules: string[]
  openapi_summary: string[]
}

export interface DeploymentPlan {
  deployment_model: string
  target_stack: string[]
  docker_services: string[]
  kubernetes_modules: string[]
  cicd_pipeline: string[]
  observability: string[]
  scaling_strategy: string[]
  security_controls: string[]
  cloud_recommendation: string
}

export interface ImpactAssessment {
  change_request: string
  impacted_modules: string[]
  reasoning: string[]
  regenerated_sections: string[]
}

export interface ArchitectureDecisionRecord {
  id: string
  timestamp: string
  title: string
  context: string
  decision: string
  status: string
  consequences: string
  changed_modules: string[]
}

export interface CriteriaWeights {
  weights: Record<string, number>
}

export interface ReweightRequest {
  matrix: Record<string, Record<string, number>>
  weights: CriteriaWeights
}

export interface ExportAdrsRequest {
  adrs: ArchitectureDecisionRecord[]
}

export interface ComponentStatus {
  component: string
  role: string
  status: 'down' | 'degraded' | 'healthy'
  reason?: string | null
}

export interface BlastRadiusResult {
  failed_component: string
  architecture_id: string
  statuses: ComponentStatus[]
  impact_summary: string
  severity_score: number
}

export interface BlastRadiusRequest {
  architecture: ArchitectureOption
  failed_component: string
  comparison_matrix: Record<string, Record<string, number>>
}

export interface ResilienceRecommendation {
  id: string
  name: string
  category: string
  description: string
  severity_reduction: number
}

export interface ResilienceRecommendationsRequest {
  blast_result: BlastRadiusResult
  architecture: ArchitectureOption
}

export interface ApplyMitigationsRequest {
  blast_result: BlastRadiusResult
  selected_mitigation_ids: string[]
  architecture: ArchitectureOption
}

export interface OwnershipSuggestion {
  component: string
  suggested_team: string
  reason: string
}

export interface FrictionPoint {
  description: string
  severity: 'low' | 'medium' | 'high'
  affected_components: string[]
  affected_teams: string[]
}

export interface ConwayFitResult {
  fit_score: number
  team_fit_plan: TeamFitPlan
  ownership_mapping: OwnershipSuggestion[]
  friction_points: FrictionPoint[]
  summary: string
}

export interface ConwayFitRequest {
  architecture: ArchitectureOption
  entities: string[]
  constraints: ProjectConstraints
}

export interface RoleDefinition {
  role_name: string
  description: string
  suggested_percentage: number
  min_headcount: number
  essential: boolean
}

export interface RoleRecommendation {
  role_name: string
  description: string
  recommended_headcount: number
  rationale: string
}

export interface TeamFitPlan {
  architecture_id: string
  total_team_size: number
  roles: RoleRecommendation[]
  coverage_warning?: string | null
}

export interface TwinCaseStudy {
  id: string
  company: string
  architecture_id: string
  score_vector: Record<string, number>
  notable_services: string[]
  summary: string
  lesson: string
  source_note: string
}

export interface TwinMatch {
  case_study: TwinCaseStudy
  similarity_score: number
  overlap_services: string[]
  rationale: string
}

export interface TwinMatchRequest {
  comparison_matrix: Record<string, Record<string, number>>
  recommended_architecture_id: string
  deployment_stack: string[]
  weights?: Record<string, number>
}

export interface ProjectConstraints {
  team_size: number
  budget_level: 'low' | 'medium' | 'high'
  expected_scale: string
  timeline_weeks: number
}

export interface BudgetLineItem {
  label: string
  monthly_cost_usd: number
  category: 'infrastructure' | 'team' | 'tooling'
}

export interface ScaleBudget {
  scale_tier: string
  total_monthly_usd: number
  line_items: BudgetLineItem[]
}

export interface BudgetEstimate {
  architecture_id: string
  budgets_by_scale: ScaleBudget[]
  assumptions: string[]
}

export interface BudgetEstimateRequest {
  architecture: ArchitectureOption
  deployment_stack: string[]
  constraints: ProjectConstraints
}

export interface BudgetCompareRequest {
  architectures: ArchitectureOption[]
  deployment_stacks: Record<string, string[]>
  constraints: ProjectConstraints
}

export interface Workspace {
  id: string
  title: string
  original_prompt: string
  business_context?: string | null
  answers: Record<string, string>
  requirements: RequirementModel
  clarification_plan: ClarificationPlan
  architectures: ArchitectureOption[]
  comparison: ComparisonResult
  recommendation: RecommendationResult
  diagrams: Record<string, DiagramArtifact>
  database_design: DatabaseDesign
  api_design: ApiDesign
  deployment_plan: DeploymentPlan
  documentation_markdown: string
  impact_history: ImpactAssessment[]
  adr?: ArchitectureDecisionRecord | null
  created_at: string
  updated_at: string
}

export interface WorkspaceCreatePayload {
  title: string
  description: string
  business_context?: string
  budget?: string
  preferred_cloud?: string
  constraints: string[]
}
