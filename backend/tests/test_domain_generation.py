"""Domain propagation tests: the same generator must produce meaningfully
different, domain-faithful artifacts for different business domains — and
must never leak the e-commerce template into unrelated projects.

Ollama is disabled by conftest, so these exercise the deterministic path.
"""

from app.services.conway_law_engine import suggest_roles
from app.services.domain_inference import (
    cluster_entities,
    normalize_constraint_statements,
    payment_evidence_level,
)
from app.services.requirement_analyzer import RequirementAnalyzer
from app.schemas.domain import ProjectConstraints


BEVERAGE_BRIEF = {
    "title": "Global Beverage Manufacturing and Distribution Platform",
    "description": (
        "Build an enterprise platform for a multinational non-alcoholic beverage "
        "company that manages product formulation, concentrate production, bottling "
        "partnerships, manufacturing, inventory, distribution, sales, and customer "
        "delivery across more than 200 international markets. Key capabilities include "
        "supply chain management, production planning, inventory tracking, partner "
        "management, order processing, distribution monitoring, sales analytics, "
        "consumer insights, and integration with retailers and wholesalers. The system "
        "must handle very high transaction volumes, support real-time operational data, "
        "and provide reliable access across multiple geographic regions."
    ),
    "business_context": (
        "The organization operates globally through a hybrid business model consisting "
        "of centralized product development and brand management combined with "
        "independently operated regional manufacturing and distribution partners. The "
        "business serves consumers in more than 200 countries and territories through "
        "approximately 200 regional production partners and hundreds of manufacturing "
        "facilities. Products move through a complex network involving ingredient "
        "suppliers, manufacturing facilities, bottling partners, warehouses, "
        "distributors, wholesalers, retailers, and food-service customers. The company "
        "requires global standardization of core business processes while allowing "
        "regional flexibility for local products, regulations, pricing, currencies, "
        "languages, and market strategies. The platform is business-critical because "
        "supply chain disruptions, production delays, inventory inaccuracies, or system "
        "outages can affect millions of daily transactions and product deliveries. The "
        "organization is also expanding its use of digital commerce, consumer analytics, "
        "artificial intelligence, and real-time supply chain monitoring."
    ),
    "constraints": [
        "Must support global operations across multiple geographic regions and time zones.",
        "Must maintain high availability with minimal downtime for business-critical manufacturing and distribution operations.",
        "Must support independent regional partners while maintaining centralized governance and standardized APIs.",
        "Must comply with regional data protection, privacy, financial, tax, and food-industry regulations.",
        "Must support multiple languages, currencies, tax rules, and regional product configurations.",
        "Must integrate with legacy ERP, manufacturing, warehouse management, retailer, distributor, and partner systems.",
        "Must handle high transaction volumes and large-scale analytics workloads.",
        "Must provide strong role-based access control, SSO, audit logging, encryption, and enterprise-grade cybersecurity.",
        "Regional failures must not cause a complete global system outage.",
        "The architecture must support gradual modernization of existing legacy systems without requiring a complete system replacement.",
    ],
}

ECOMMERCE_TERMS = {"buyer", "buyers", "merchant", "merchants", "cart", "carts", "checkout", "checkouts"}


def _blob(workspace: dict, *fields: str) -> str:
    parts: list[str] = []
    requirements = workspace["requirements"]
    parts.extend(requirements["functional_requirements"])
    parts.extend(requirements["non_functional_requirements"])
    parts.extend(requirements["constraints"])
    parts.extend(requirements["integrations"])
    parts.extend(actor["name"] for actor in requirements["actors"])
    parts.extend(entity["name"] for entity in requirements["domain_entities"])
    if "database" in fields:
        parts.extend(entity["name"] for entity in workspace["database_design"]["entities"])
    if "api" in fields:
        for group in workspace["api_design"]["groups"]:
            parts.append(group["name"])
            for endpoint in group["endpoints"]:
                parts.append(endpoint["path"])
    return "\n".join(parts).casefold()


def test_blueprint_matching_requires_meaningful_evidence():
    analyzer = RequirementAnalyzer()
    assert analyzer._pick_blueprint("our digital commerce strategy is evolving") is None
    assert analyzer._pick_blueprint("visit our shop") is None
    assert (
        analyzer._pick_blueprint(
            "Build an online pharmacy with prescription verification and secure checkout."
        ).domain
        == "Online Pharmacy"
    )
    assert (
        analyzer._pick_blueprint(
            "Build an EV charging station booking platform with charger availability."
        ).domain
        == "EV Charging Booking Platform"
    )


def test_ecommerce_domain_keeps_commerce_concepts(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "CornerShop",
            "description": (
                "Build an online shop and marketplace where merchants list products, "
                "buyers fill a cart, check out securely, and track delivery. "
                "Support catalog search, promotions, refunds, and seller payouts."
            ),
            "business_context": "Launch a consumer marketplace with fast checkout and trusted payments.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    workspace = response.json()
    assert workspace["requirements"]["domain"] == "E-Commerce Platform"
    blob = _blob(workspace, "database", "api")
    assert "merchant" in blob
    assert "checkout" in blob or "cart" in blob
    assert "products" in blob
    assert "payments" in blob


def test_manufacturing_domain_has_no_ecommerce_leakage(client):
    response = client.post("/api/v1/workspaces", json=BEVERAGE_BRIEF)
    assert response.status_code == 201, response.text
    workspace = response.json()
    requirements = workspace["requirements"]

    assert requirements["domain"] == "Manufacturing and Distribution Platform"
    assert requirements["analysis_source"] == "deterministic-extraction"

    actor_names = {actor["name"].casefold() for actor in requirements["actors"]}
    assert "buyer" not in actor_names
    assert "merchant" not in actor_names
    assert actor_names & {"retailer", "wholesaler", "distributor", "bottling partner"}

    blob = _blob(workspace, "database", "api")
    assert not ECOMMERCE_TERMS.intersection(set(blob.split()))
    assert "order_items" not in blob
    assert "payments" not in [entity["name"] for entity in workspace["database_design"]["entities"]]

    domain_terms = {
        "manufacturing", "production", "bottling", "facility", "facilities",
        "inventory", "warehouse", "warehouses", "distributor", "distributors",
        "retailer", "retailers", "supply", "shipment", "shipments", "forecast",
    }
    assert len(domain_terms.intersection(set(blob.split()))) >= 6

    # The multi-part regulatory constraint survives as one complete statement.
    assert any(
        "food-industry regulations" in constraint
        and "privacy" in constraint
        for constraint in requirements["constraints"]
    )
    assert not any(
        constraint.strip().casefold() in {"privacy", "financial", "tax"}
        for constraint in requirements["constraints"]
    )

    # Enterprise integrations are inferred; no payment provider is assumed.
    integrations_blob = "\n".join(requirements["integrations"]).casefold()
    assert "erp" in integrations_blob
    assert "payment" not in integrations_blob or "where required" in integrations_blob


def test_beverage_scenario_end_to_end_with_clarifications(client):
    create_response = client.post(
        "/api/v1/workspaces",
        json={**BEVERAGE_BRIEF, "preferred_cloud": "AWS", "team_size": 350},
    )
    assert create_response.status_code == 201, create_response.text
    workspace_id = create_response.json()["id"]

    answers = {
        "auth": "Enterprise SSO + MFA + OAuth/OIDC + RBAC",
        "sla": "99.99%",
        "scale": "100,000+ concurrent users",
        "retention": "7-10 years",
        "team_size": "350",
        "geographic_regions": "200+",
        "payments": "External system",
    }
    clarified = client.post(
        f"/api/v1/workspaces/{workspace_id}/clarifications", json={"answers": answers}
    )
    assert clarified.status_code == 200, clarified.text
    workspace = clarified.json()

    valid_ids = {
        "modular-monolith", "service-based", "event-driven-microservices",
        "serverless-platform", "hybrid-modular-serverless", "hybrid-event-serverless",
    }
    assert len(workspace["architectures"]) == 3
    assert {option["id"] for option in workspace["architectures"]} <= valid_ids
    recommended = workspace["recommendation"]["recommended_architecture_id"]
    assert recommended in valid_ids
    assert workspace["recommendation"]["confidence"] in {"Low", "Medium", "High"}
    assert any("Evidence:" in item for item in workspace["recommendation"]["why"])

    # Deployment is derived from the stated global, high-availability inputs.
    deployment = workspace["deployment_plan"]
    assert deployment["replicas"] == 3
    assert len(deployment["regions"]) >= 2
    assert deployment["deployment_strategy"]
    assert "99.99" in (deployment["availability_configuration"] or "")
    assert deployment["stack_rationale"]
    assert any("PostgreSQL" in item for item in deployment["target_stack"])

    # Data model and APIs represent the domain, with bounded contexts.
    tables = [entity["name"] for entity in workspace["database_design"]["entities"]]
    assert "users" in tables  # SSO evidence requires identity
    assert "audit_logs" in tables  # compliance evidence requires audit trail
    assert "payments" not in tables
    assert all(entity.get("bounded_context") for entity in workspace["database_design"]["entities"])
    assert "REFERENCES" in workspace["database_design"]["sql_schema"]
    groups = [group["name"] for group in workspace["api_design"]["groups"]]
    assert "Identity and Access" in groups
    assert "Core Workflows" not in groups
    assert any(
        endpoint.get("requirement_ids")
        for group in workspace["api_design"]["groups"]
        for endpoint in group["endpoints"]
    )

    # Consistency validation reports warnings, never phantom errors.
    assert not [
        issue for issue in workspace["consistency_issues"] if issue["severity"] == "error"
    ]
    codes = {issue["code"] for issue in workspace["consistency_issues"]}
    assert "unjustified-payment-surface" not in codes
    assert "single-region-for-global" not in codes
    assert "## Consistency Review" in workspace["documentation_markdown"]

    # Diagrams render domain language, not commerce language.
    use_case = workspace["diagrams"]["use_case"]["mermaid"].casefold()
    assert "cart" not in use_case and "checkout" not in use_case


def test_saas_domain_differs_from_manufacturing(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "TeamFlow Analytics",
            "description": (
                "Build a multi-tenant SaaS platform for team collaboration analytics. "
                "Customers create workspaces, invite members, connect data sources through "
                "webhooks and API integrations, build dashboards, and manage subscription "
                "tiers with usage-based billing. Provide tenant onboarding, role management, "
                "and audit trails for workspace activity."
            ),
            "business_context": (
                "Self-serve SaaS with monthly releases. Tenants expect data isolation, "
                "SSO login, and usage metering for billing."
            ),
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    workspace = response.json()
    requirements = workspace["requirements"]
    assert requirements["domain"] == "Software and SaaS Platform"
    blob = _blob(workspace, "database", "api")
    assert "subscription" in blob or "tenant" in blob or "workspace" in blob
    assert "bottling" not in blob
    assert "warehouse" not in blob
    assert not ECOMMERCE_TERMS.intersection(set(blob.split()))


def test_ambiguous_domain_stays_honest(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "Misc Tool",
            "description": "Build a system to manage things efficiently.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    workspace = response.json()
    requirements = workspace["requirements"]
    assert requirements["analysis_source"] == "conservative-fallback"
    assert requirements["domain"] == "Unknown domain"
    assert requirements["open_questions"]
    blob = _blob(workspace)
    assert not ECOMMERCE_TERMS.intersection(set(blob.split()))


def test_constraint_normalization_merges_fragments():
    items, merges = normalize_constraint_statements(
        [
            "Must comply with regional privacy",
            "financial",
            "tax",
            "and food-industry regulations.",
            "SSO",
            "Must use PostgreSQL",
            "Must use PostgreSQL",
        ]
    )
    assert merges >= 2
    assert "Must comply with regional privacy, financial, tax, and food-industry regulations." in items
    assert any(item == "SSO." for item in items)
    assert len([item for item in items if "PostgreSQL" in item]) == 1
    assert not any(item.strip().casefold() in {"privacy", "financial", "tax"} for item in items)


def test_payment_evidence_levels():
    assert payment_evidence_level("General platform modernization.") == 0
    assert payment_evidence_level("B2B transactions with external payment systems where required.") == 1
    assert payment_evidence_level("Buyers check out with a cart and pay by card.") == 2
    assert payment_evidence_level("Usage-based subscriptions and billing.") == 2


def test_bounded_context_clustering():
    contexts = cluster_entities(["production_line", "production_order", "retailer", "supply_chain"])
    assert contexts["production_line"] == contexts["production_order"] == "Production"
    assert contexts["supply_chain"] == "Supply Chain"


def test_conway_staffing_totals_match_team_size():
    from app.schemas.domain import ArchitectureOption

    option = ArchitectureOption(
        id="hybrid-event-serverless", name="Hybrid", style="hybrid",
        overview="overview", components=[], data_flow=[], technology_stack=[],
        database="db", api_style="api", deployment="deploy", advantages=[],
        disadvantages=[], suitable_scenarios=[], estimated_complexity="High",
        estimated_cost="High", maintenance="plan",
    )
    for size in (1, 5, 13, 350):
        plan = suggest_roles(
            option, ProjectConstraints(team_size=size, expected_scale="x")
        )
        assert plan.total_team_size == size
        assert sum(role.recommended_headcount for role in plan.roles) == size
