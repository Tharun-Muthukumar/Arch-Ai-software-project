"""Deterministic, order-of-magnitude architecture budget estimates.

Design rationale:
  This module derives rough monthly infrastructure, team, and tooling costs
  from a deployment stack and project constraints. Every number is an
  illustrative constant rather than a vendor quote; outputs are intended for
  early architecture trade-offs, not procurement or financial approval.
"""

from app.schemas.domain import (
    ArchitectureOption,
    BudgetEstimate,
    BudgetLineItem,
    ProjectConstraints,
    ScaleBudget,
)

# Illustrative monthly USD bases for a small deployment, deliberately rounded.
_COMPONENT_COSTS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "docker": ("Docker/Compose host", (60, 130, 350)),
    "kubernetes": ("Managed Kubernetes cluster and nodes", (240, 720, 2_200)),
    "nginx": ("Ingress/load balancer", (25, 55, 140)),
    "ingress": ("Ingress/load balancer", (25, 55, 140)),
    "postgres": ("Managed PostgreSQL", (80, 260, 900)),
    "mysql": ("Managed relational database", (80, 260, 900)),
    "kafka": ("Managed Kafka/event cluster", (220, 420, 1_100)),
    "redis": ("Managed Redis cache", (35, 90, 260)),
    "lambda": ("Serverless functions", (35, 180, 700)),
    "serverless": ("Serverless functions", (35, 180, 700)),
    "managed function": ("Serverless functions", (35, 180, 700)),
    "function package": ("Serverless functions", (35, 180, 700)),
    "function deployment": ("Serverless functions", (35, 180, 700)),
    "api gateway": ("API Gateway", (15, 45, 130)),
    "dynamodb": ("Managed DynamoDB", (30, 160, 600)),
    "queue": ("Managed queue/event bus", (15, 55, 180)),
    "event bus": ("Managed queue/event bus", (15, 55, 180)),
    "object storage": ("Object storage", (15, 60, 220)),
    "cdn": ("CDN/static delivery", (10, 45, 160)),
}
_SCALE_TIERS = ("small (~1K users)", "medium (~100K users)", "large (~1M+ users)")
_TEAM_COSTS = {"low": 3_000.0, "medium": 6_000.0, "high": 10_000.0}
_TOOLING_COSTS = {
    "modular-monolith": 180.0,
    "monolithic": 180.0,
    "layered": 200.0,
    "clean": 200.0,
    "service-based": 280.0,
    "service_based": 280.0,
    "event-driven-microservices": 480.0,
    "microservices": 480.0,
    "event-driven": 480.0,
    "event_driven": 480.0,
    "serverless-platform": 300.0,
    "serverless": 300.0,
    "hybrid-modular-serverless": 260.0,
    "hybrid-event-serverless": 380.0,
}


def _component_cost(stack_item: str, tier_index: int) -> tuple[str, float]:
    """Match a stack item to its first known illustrative cost profile."""
    lowered = stack_item.lower()
    for keyword, (label, tier_costs) in _COMPONENT_COSTS.items():
        if keyword in lowered:
            return label, tier_costs[tier_index]
    return stack_item, (30.0, 70.0, 180.0)[tier_index]


def estimate_infra_cost(architecture_id: str, deployment_stack: list[str]) -> list[ScaleBudget]:
    """Estimate infrastructure-only cost by stack item for each scale tier."""
    stack = deployment_stack or ["Application host", "PostgreSQL", "NGINX"]
    budgets: list[ScaleBudget] = []
    for tier_index, tier in enumerate(_SCALE_TIERS):
        items: list[BudgetLineItem] = []
        seen_labels: set[str] = set()
        for stack_item in stack:
            label, cost = _component_cost(stack_item, tier_index)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            items.append(BudgetLineItem(label=label, monthly_cost_usd=cost, category="infrastructure"))
        # A monolith commonly needs an additional horizontal scaling step at large scale.
        if tier_index == 2 and architecture_id in {"modular-monolith", "monolithic", "layered", "clean"}:
            items.append(BudgetLineItem(
                label="Horizontal application scaling transition",
                monthly_cost_usd=450.0,
                category="infrastructure",
            ))
        budgets.append(ScaleBudget(
            scale_tier=tier,
            total_monthly_usd=round(sum(item.monthly_cost_usd for item in items), 2),
            line_items=items,
        ))
    return budgets


def estimate_team_cost(team_size: int, budget_level: str) -> float:
    """Estimate blended monthly engineering cost; this is illustrative only."""
    return _TEAM_COSTS.get(budget_level.lower(), _TEAM_COSTS["medium"]) * max(team_size, 1)


def estimate_tooling_cost(architecture_id: str) -> float:
    """Estimate CI/CD, monitoring, tracing, and error tracking costs."""
    return _TOOLING_COSTS.get(architecture_id, 250.0)


def generate_budget(
    architecture: ArchitectureOption,
    deployment_stack: list[str],
    constraints: ProjectConstraints,
) -> BudgetEstimate:
    """Combine infrastructure, team, and tooling estimates into scale budgets."""
    infra_budgets = estimate_infra_cost(architecture.id, deployment_stack)
    team_cost = estimate_team_cost(constraints.team_size, constraints.budget_level)
    tooling_cost = estimate_tooling_cost(architecture.id)
    budgets: list[ScaleBudget] = []
    for infra_budget in infra_budgets:
        items = list(infra_budget.line_items)
        items.extend([
            BudgetLineItem(label=f"{constraints.team_size}-person engineering team", monthly_cost_usd=team_cost, category="team"),
            BudgetLineItem(label="CI/CD, observability, and error tracking", monthly_cost_usd=tooling_cost, category="tooling"),
        ])
        budgets.append(ScaleBudget(
            scale_tier=infra_budget.scale_tier,
            total_monthly_usd=round(sum(item.monthly_cost_usd for item in items), 2),
            line_items=items,
        ))
    return BudgetEstimate(
        architecture_id=architecture.id,
        budgets_by_scale=budgets,
        assumptions=[
            "Illustrative estimate only, not a vendor quote or procurement budget.",
            "Order-of-magnitude planning figures: useful for comparing architectures, not for financial approval.",
            "Docker/Compose hosts are modeled at about $60, $130, and $350 per month by scale.",
            "Managed Kubernetes is modeled at about $240, $720, and $2,200 per month including nodes.",
            "Managed relational databases are modeled at about $80, $260, and $900 per month by scale.",
            "Kafka is modeled at about $220, $420, and $1,100 per month; Redis at $35, $90, and $260.",
            "Serverless functions scale more smoothly at about $35, $180, and $700 per month; API Gateway stays comparatively low.",
            f"Each engineer uses an illustrative {constraints.budget_level} blended monthly cost of ${_TEAM_COSTS.get(constraints.budget_level, 6_000):,.0f}.",
            f"Team cost is {constraints.team_size} people x blended rate; update team size in the overview for an accurate figure.",
            "Tooling covers rough CI/CD, monitoring, tracing, and error tracking allowances.",
            "Excluded: data transfer/egress, third-party licenses, support contracts, regional price differences, and volume discounts.",
        ],
    )
