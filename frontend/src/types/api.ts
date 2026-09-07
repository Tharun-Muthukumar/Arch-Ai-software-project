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
  request_description: string
  response_description: string
  service?: string | null
  requirement_ids: string[]
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
  replicas?: number | null
  regions: string[]
  deployment_strategy?: string | null
  availability_configuration?: string | null
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
  directly_affected_node_ids: string[]
  indirectly_affected_node_ids: string[]
  affected_artifacts: string[]
}

export type WorkspaceEditTarget =
  | 'functional_requirement'
  | 'non_functional_requirement'
  | 'actor'
  | 'constraint'
  | 'assumption'
  | 'integration'
  | 'data_characteristic'
  | 'domain_entity'
  | 'architecture_component'
  | 'api_endpoint'
  | 'database_entity'
  | 'deployment'
  | 'diagram_layout'

export type WorkspaceEditOperation = 'add' | 'update' | 'delete' | 'reorder'
export type ImpactLevel = 'none' | 'minor' | 'moderate' | 'major' | 'visual'

export interface WorkspaceEditRequest {
  target_type: WorkspaceEditTarget
  operation: WorkspaceEditOperation
  target_id?: string
  parent_id?: string
  value?: string | Record<string, unknown>
  destination_index?: number
  use_ai?: boolean
  expected_updated_at?: string
}

export interface WorkspaceImpactItem {
  area: string
  level: ImpactLevel
  summary: string
}

export interface WorkspaceEditImpact {
  items: WorkspaceImpactItem[]
  directly_affected_node_ids: string[]
  indirectly_affected_node_ids: string[]
  affected_artifacts: string[]
  requires_confirmation: boolean
}

export interface SemanticEditSuggestion {
  suggested_text: string
  rationale: string
  inferred_characteristics: string[]
  assumptions: string[]
  clarification_questions: string[]
  source: 'ollama' | 'deterministic-fallback'
}

export interface WorkspaceEditPreview {
  edit: WorkspaceEditRequest
  normalized_value?: string | Record<string, unknown> | null
  impact: WorkspaceEditImpact
  suggestion?: SemanticEditSuggestion | null
  warnings: string[]
}

export interface ConsistencyIssue {
  code: string
  severity: 'info' | 'warning' | 'error'
  message: string
  related_ids: string[]
}

export type CausalNodeType =
  | 'user_requirement'
  | 'functional_requirement'
  | 'non_functional_requirement'
  | 'constraint'
  | 'assumption'
  | 'technical_characteristic'
  | 'architecture_decision'
  | 'architecture_component'
  | 'service_module'
  | 'api'
  | 'database_entity'
  | 'integration'
  | 'infrastructure'
  | 'risk'
  | 'cost'
  | 'adr'
  | 'diagram'

export type CausalRelationshipType =
  | 'requires'
  | 'satisfies'
  | 'caused_by'
  | 'implemented_by'
  | 'depends_on'
  | 'stores_in'
  | 'exposed_by'
  | 'deployed_on'
  | 'mitigates'
  | 'constrained_by'
  | 'affects'

export interface CausalGraphNode {
  id: string
  type: CausalNodeType
  name: string
  description: string
  source: string
  version: string
  confidence?: number | null
  metadata: Record<string, unknown>
}

export interface CausalGraphEdge {
  id: string
  source_node_id: string
  target_node_id: string
  relationship: CausalRelationshipType
  reason: string
  confidence?: number | null
}

export interface CausalGraph {
  version: string
  nodes: CausalGraphNode[]
  edges: CausalGraphEdge[]
  orphan_node_ids: string[]
}

export interface CausalGraphTrace {
  selected_node: CausalGraphNode
  why_it_exists: string[]
  requirements: CausalGraphNode[]
  upstream: CausalGraphNode[]
  downstream: CausalGraphNode[]
  related_adrs: CausalGraphNode[]
  affected_artifacts: string[]
}

export type CounterfactualVariable =
  | 'expected_users'
  | 'peak_traffic_multiplier'
  | 'availability_percent'
  | 'latency_ms'
  | 'budget_level'
  | 'monthly_budget_change_percent'
  | 'team_size'
  | 'geographic_regions'
  | 'realtime_required'
  | 'compliance_level'
  | 'data_volume_multiplier'
  | 'growth_rate_percent'

export interface CounterfactualChange {
  variable: CounterfactualVariable
  original_value?: string | number | boolean | null
  hypothetical_value: string | number | boolean
  source?: 'structured' | 'scenario'
}

export interface CounterfactualSimulationRequest {
  scenario?: string
  changes: CounterfactualChange[]
}

export interface CounterfactualArchitectureRank {
  architecture_id: string
  architecture_name: string
  rank: number
  suitability_score: number
  team_fit_score?: number | null
}

export interface CounterfactualSnapshot {
  architecture_id: string
  architecture_name: string
  suitability_score: number
  rank: number
  monthly_cost_estimate_usd?: number | null
  resilience_score: number
  risk_score: number
  risk_level: 'Low' | 'Medium' | 'High'
  team_fit_score?: number | null
  operational_complexity_score: number
}

export interface CounterfactualSimulationResult {
  simulation_id: string
  workspace_id: string
  current_architecture_version: string
  scenario?: string | null
  changed_variables: CounterfactualChange[]
  directly_affected_node_ids: string[]
  indirectly_affected_node_ids: string[]
  affected_components: string[]
  before: CounterfactualSnapshot
  after: CounterfactualSnapshot
  before_ranking: CounterfactualArchitectureRank[]
  after_ranking: CounterfactualArchitectureRank[]
  current_architecture_still_suitable: boolean
  recommended_architecture_id: string
  recommended_architecture_name: string
  recommended_evolution_path: string[]
  conflicts: string[]
  explanation: string[]
  confidence: 'Low' | 'Medium' | 'High'
  estimate_notes: string[]
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
  adrs: ArchitectureDecisionRecord[]
  causal_graph?: CausalGraph | null
  diagram_layouts: Record<string, Record<string, unknown>>
  consistency_issues: ConsistencyIssue[]
  can_undo: boolean
  can_redo: boolean
  created_at: string
  updated_at: string
}

export interface WorkspaceMutationResponse {
  workspace: Workspace
  impact: WorkspaceEditImpact
  consistency_issues: ConsistencyIssue[]
  message: string
}

export interface WorkspaceCreatePayload {
  title: string
  description: string
  business_context?: string
  budget?: string
  preferred_cloud?: string
  constraints: string[]
}
