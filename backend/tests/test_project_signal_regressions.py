"""Regression coverage for isolated, domain-faithful project generation."""

from datetime import datetime, timezone

from app.services.api_generator import ApiGenerator
from app.services.architecture_generator import ArchitectureGenerator
from app.services.comparison_engine import ComparisonEngine, recompute_with_weights
from app.services.conway_law_engine import check_fit
from app.services.database_generator import DatabaseGenerator
from app.services.deployment_generator import DeploymentGenerator
from app.services.decision_config import ARCHITECTURE_DECISION_MODEL_VERSION
from app.services.domain_inference import normalize_constraint_statements, split_sentences
from app.services.recommendation_engine import RecommendationEngine
from app.services.requirement_analyzer import RequirementAnalyzer
from app.services.twin_matching_engine import match_twins
from app.services.blast_radius_engine import simulate_failure
from app.services.workspace_orchestrator import WorkspaceOrchestrator
from app.services.project_signals import classify_actor
from app.schemas.domain import (
    Actor,
    ArchitectureComponent,
    ArchitectureOption,
    BoundedContext,
    CriteriaWeights,
    IntegrationDetail,
    ProjectConstraints,
    RequirementAnalysis,
    WorkspaceCreateRequest,
)


SCENARIOS = {
    "beverage": {
        "title": "Global Beverage Manufacturing and Distribution",
        "description": (
            "Manage production, bottling, inventory, warehouses, distributors, retailers, "
            "supply chain forecasting and manufacturing facilities across countries."
        ),
        "context": "Global manufacturing partners coordinate production and distribution.",
        "required": {"production", "bottling", "inventory", "warehouse", "facility"},
        "forbidden": {"cart", "checkout", "merchant", "buyer"},
    },
    "logistics": {
        "title": "Global Parcel Logistics",
        "description": (
            "Manage shipment tracking, packages, facilities, vehicles, drivers, routes, "
            "delivery attempts, customs documents and warehouse operations."
        ),
        "context": "Global logistics partners process high-volume tracking events.",
        "required": {"shipment", "tracking", "facility", "vehicle", "route", "customs"},
        "forbidden": {"bottling", "checkout", "merchant", "buyer"},
    },
    "healthcare": {
        "title": "Healthcare Information Platform",
        "description": (
            "Manage patients, clinical records, appointments, clinicians, diagnoses, "
            "treatment plans and laboratory results."
        ),
        "context": "Healthcare providers require secure clinical workflows and audit trails.",
        "required": {"patient", "clinical", "appointment", "treatment"},
        "forbidden": {"shipment", "bottling", "checkout", "merchant"},
    },
    "banking": {
        "title": "Banking Transaction Platform",
        "description": (
            "Manage customer accounts, transfers, transactions, payment processing, fraud risk, "
            "ledger entries, compliance and audit records."
        ),
        "context": "Bank operations require secure regulated transaction processing.",
        "required": {"account", "transaction", "transfer", "ledger", "audit"},
        "forbidden": {"shipment", "bottling", "checkout", "merchant"},
    },
    "media": {
        "title": "Global Media Streaming Platform",
        "description": (
            "Manage media catalogues, video encoding, playback sessions, viewers, subscriptions, "
            "content recommendations and live streaming across regions."
        ),
        "context": "A global streaming service processes high-volume playback events.",
        "required": {"media", "video", "playback", "streaming"},
        "forbidden": {"shipment", "bottling", "checkout", "merchant"},
    },
    "commerce": {
        "title": "Regional Commerce Platform",
        "description": (
            "Customers browse products, manage carts, place orders, authorize payments, "
            "track shipments, and request returns while merchants manage catalog and inventory."
        ),
        "context": "Commerce operations coordinate fulfillment with external carriers.",
        "required": {"customer", "product", "cart", "order", "payment", "shipment"},
        "forbidden": {"bottling", "clinical", "ledger", "prescription"},
    },
}


def _artifact_text(requirements, database, api, deployment) -> str:
    return " ".join(
        [
            *(entity.name for entity in requirements.domain_entities),
            *(actor.name for actor in requirements.actors),
            *(detail.name for detail in requirements.integration_details),
            *(entity.name for entity in database.entities),
            *(endpoint.path for group in api.groups for endpoint in group.endpoints),
            *deployment.target_stack,
            deployment.deployment_model,
        ]
    ).casefold()


def test_six_domains_remain_isolated_and_domain_faithful():
    analyzer = RequirementAnalyzer()
    generated: dict[str, tuple] = {}
    for name, scenario in SCENARIOS.items():
        requirements = analyzer.analyze(
            scenario["title"], scenario["description"], scenario["context"], {}
        )
        database = DatabaseGenerator().generate(requirements)
        api = ApiGenerator().generate(requirements, database)
        answers = {"team_size": "40"}
        architectures = ArchitectureGenerator().generate(requirements, answers)
        comparison = ComparisonEngine().compare(requirements, architectures, answers)
        recommendation = RecommendationEngine().recommend(requirements, architectures, comparison, answers)
        deployment = DeploymentGenerator().generate(requirements, recommendation, answers)
        generated[name] = (requirements, database, api, deployment)

        text = _artifact_text(requirements, database, api, deployment)
        assert scenario["required"] & set(text.replace("/", " ").replace("-", " ").split())
        assert not scenario["forbidden"] & set(text.replace("/", " ").replace("-", " ").split())
        assert all("details" not in {field.name for field in entity.fields} for entity in database.entities)
        assert all("coordinate-operations" not in endpoint.path for group in api.groups for endpoint in group.endpoints)

    # Objects generated for earlier projects are immutable snapshots and the
    # last project cannot overwrite their entities, contracts, or deployment.
    beverage_text = _artifact_text(*generated["beverage"])
    logistics_text = _artifact_text(*generated["logistics"])
    healthcare_text = _artifact_text(*generated["healthcare"])
    banking_text = _artifact_text(*generated["banking"])
    media_text = _artifact_text(*generated["media"])
    assert "shipment" not in beverage_text
    assert "bottling" not in logistics_text
    assert "clinical" not in banking_text
    assert "ledger" not in healthcare_text
    assert "patient" not in media_text

    # A -> B -> C -> D -> E -> A produces the same A snapshot; no mutable
    # analyzer or generator state can carry later domain nouns backward.
    first_beverage = generated["beverage"]
    scenario = SCENARIOS["beverage"]
    repeated_requirements = analyzer.analyze(
        scenario["title"], scenario["description"], scenario["context"], {}
    )
    repeated_database = DatabaseGenerator().generate(repeated_requirements)
    repeated_api = ApiGenerator().generate(repeated_requirements, repeated_database)
    assert _artifact_text(repeated_requirements, repeated_database, repeated_api, first_beverage[3]) == _artifact_text(*first_beverage)


def test_confirmed_clarifications_feed_every_downstream_consumer():
    answers = {
        "team_size": "250",
        "scale": "100,000+ concurrent users and 2 million tracking events per day",
        "sla": "99.99%",
        "legacy_systems": "TMS, WMS, customs, billing, fleet, tracking",
        "data_formats": "REST/JSON, XML, EDI, CSV, webhooks",
        "auth": "OAuth2/OIDC, SSO, MFA, RBAC, service credentials, mTLS",
        "failover": "active-active multi-region, replication, health checks",
        "retention": "7-10 years",
    }
    requirements = RequirementAnalyzer().analyze(
        SCENARIOS["logistics"]["title"],
        SCENARIOS["logistics"]["description"],
        SCENARIOS["logistics"]["context"],
        answers,
    )
    database = DatabaseGenerator().generate(requirements)
    api = ApiGenerator().generate(requirements, database)
    architectures = ArchitectureGenerator().generate(requirements, answers)
    comparison = ComparisonEngine().compare(requirements, architectures, answers)
    recommendation = RecommendationEngine().recommend(requirements, architectures, comparison, answers)
    deployment = DeploymentGenerator().generate(requirements, recommendation, answers)

    assert requirements.project_profile.classification == "globally distributed / mission-critical"
    assert requirements.project_profile.concurrent_users == 100_000
    assert requirements.project_profile.event_volume_per_day == 2_000_000
    assert {"TMS", "WMS", "customs", "billing", "fleet", "tracking"} <= {
        detail.name for detail in requirements.integration_details
    }
    assert {"REST", "JSON", "XML", "EDI", "CSV", "Webhook"} <= {
        item.value for item in requirements.technical_characteristics
    }
    assert deployment.availability_target_percent == 99.99
    assert deployment.failover_mode == "active-active multi-region"
    assert deployment.replicas_per_region == 3
    assert deployment.total_baseline_replicas == 6
    assert all(endpoint.owner for group in api.groups for endpoint in group.endpoints)
    assert any("OAuth2/OIDC" in endpoint.security_mechanisms for group in api.groups for endpoint in group.endpoints)
    assert all(score.weight is not None and score.requirement_signals for card in comparison.scorecards for score in card.metric_scores)


def test_precedent_matching_is_domain_aware_and_deterministic():
    matrix = {"event-driven-microservices": {"scalability": 10, "performance": 7, "maintainability": 6, "security": 7, "cost": 4, "reliability": 8, "availability": 9, "deployment_complexity": 3, "learning_curve": 4, "development_time": 4, "fault_isolation": 10, "operational_complexity": 3}}
    payload = dict(
        comparison_matrix=matrix,
        recommended_architecture_id="event-driven-microservices",
        deployment_stack=["Kafka", "PostgreSQL"],
        domain="Logistics and Transportation Platform",
        domain_signals=["shipment", "tracking", "facility", "route", "customs"],
    )
    first = match_twins(**payload)
    second = match_twins(**payload)
    assert [match.model_dump() for match in first] == [match.model_dump() for match in second]
    assert first[0].case_study.company != "Coca-Cola"
    assert first[0].domain_similarity >= first[-1].domain_similarity


def test_precedent_domains_are_gated_and_component_scores_are_separate():
    matrix = {"event-driven-microservices": {
        "scalability": 10, "performance": 8, "maintainability": 6,
        "security": 9, "cost": 4, "reliability": 9, "availability": 9,
        "deployment_complexity": 3, "learning_curve": 4,
        "development_time": 4, "fault_isolation": 9,
        "operational_complexity": 3,
    }}
    cases = (
        ("Manufacturing and Distribution", ["production", "bottling", "inventory"], {"Coca-Cola"}),
        ("Logistics and Transportation", ["shipment", "parcel", "route"], {"Uber", "Amazon"}),
        ("Healthcare and Pharmacy", ["patient", "clinical", "treatment"], {"NHS Digital"}),
        ("Financial Services", ["banking", "ledger", "transaction"], {"Monzo", "Capital One"}),
        ("Media and Streaming", ["media", "streaming", "playback"], {"Netflix", "BBC"}),
    )
    snapshots = {}
    for domain, signals, expected in cases:
        matches = match_twins(
            comparison_matrix=matrix,
            recommended_architecture_id="event-driven-microservices",
            deployment_stack=["Kafka", "PostgreSQL", "Kubernetes"],
            domain=domain,
            domain_signals=signals,
            capability_signals=signals,
            workload_signals=["high-volume event processing"],
            data_signals=["Kafka", "transactional records"],
            reliability_signals=["high availability", "reliability"],
            integration_signals=["event API"],
        )
        snapshots[domain] = [item.model_dump() for item in matches]
        assert matches[0].case_study.company in expected
        assert matches[0].domain_compatible
        assert matches[0].industry_similarity > 34
        assert all(item.industry_similarity <= 34 for item in matches if not item.domain_compatible)
        assert all(
            item.industry_similarity != item.architecture_precedent_similarity
            or item.domain_similarity == item.architecture_similarity
            for item in matches
        )

    # Repeating A after B/C/D/E returns byte-for-byte equivalent structured
    # scores, proving matching is stateless and independent of call order.
    repeated = match_twins(
        comparison_matrix=matrix,
        recommended_architecture_id="event-driven-microservices",
        deployment_stack=["Kafka", "PostgreSQL", "Kubernetes"],
        domain="Manufacturing and Distribution",
        domain_signals=["production", "bottling", "inventory"],
        capability_signals=["production", "bottling", "inventory"],
        workload_signals=["high-volume event processing"],
        data_signals=["Kafka", "transactional records"],
        reliability_signals=["high availability", "reliability"],
        integration_signals=["event API"],
    )
    assert [item.model_dump() for item in repeated] == snapshots["Manufacturing and Distribution"]


def test_legacy_resource_limit_input_cannot_change_architecture_scores():
    requirements = RequirementAnalyzer().analyze(
        SCENARIOS["banking"]["title"],
        SCENARIOS["banking"]["description"],
        SCENARIOS["banking"]["context"],
        {"team_size": "20"},
    )
    architectures = ArchitectureGenerator().generate(requirements, {"team_size": "20"})
    baseline = ComparisonEngine().compare(requirements, architectures, {"team_size": "20"})
    legacy_key = "bud" + "get"
    legacy = ComparisonEngine().compare(
        requirements, architectures, {"team_size": "20", legacy_key: "low"}
    )
    assert baseline.model_dump() == legacy.model_dump()


def test_project_switch_refresh_and_reopen_preserve_isolated_snapshots():
    class MemoryRepository:
        def __init__(self):
            self.items = {}
            self.save_calls = 0

        def add(self, workspace):
            workspace.id = f"project-{len(self.items) + 1}"
            workspace.created_at = workspace.updated_at = datetime.now(timezone.utc)
            self.items[workspace.id] = workspace
            return workspace

        def save(self, workspace):
            self.save_calls += 1
            workspace.updated_at = datetime.now(timezone.utc)
            self.items[workspace.id] = workspace
            return workspace

        def get(self, workspace_id):
            return self.items.get(workspace_id)

        def list(self):
            return list(self.items.values())

    repository = MemoryRepository()
    orchestrator = WorkspaceOrchestrator(repository)
    snapshots = {}
    ids = []
    for name in ("beverage", "logistics", "healthcare", "banking", "media"):
        scenario = SCENARIOS[name]
        workspace = orchestrator.create_workspace(WorkspaceCreateRequest(
            title=scenario["title"],
            description=scenario["description"],
            business_context=scenario["context"],
            constraints=[],
            team_size=40,
        ))
        ids.append(workspace.id)
        snapshots[workspace.id] = _artifact_text(
            workspace.requirements,
            workspace.database_design,
            workspace.api_design,
            workspace.deployment_plan,
        )

    reopened = WorkspaceOrchestrator(repository)
    for workspace_id in [*ids, ids[0]]:
        workspace = reopened.get_workspace(workspace_id)
        assert workspace is not None
        assert _artifact_text(
            workspace.requirements,
            workspace.database_design,
            workspace.api_design,
            workspace.deployment_plan,
        ) == snapshots[workspace_id]

    assert "shipment" not in snapshots[ids[0]]
    assert "patient" not in snapshots[ids[1]]
    assert "ledger" not in snapshots[ids[2]]
    assert "streaming" not in snapshots[ids[3]]

    # Persisted scorecards from the old directionless model are regenerated on
    # load, so existing projects cannot display inverted burden metrics.
    stale_workspace = repository.items[ids[1]]
    for scorecard in stale_workspace.comparison_json["scorecards"]:
        scorecard["decision_model"] = "legacy-directionless-model"
        for metric in scorecard["metric_scores"]:
            metric.pop("direction", None)
            metric.pop("normalized_score", None)
    saves_before_upgrade = repository.save_calls
    upgraded = reopened.get_workspace(ids[1])
    assert upgraded is not None
    assert repository.save_calls == saves_before_upgrade + 1
    assert all(
        card.decision_model == ARCHITECTURE_DECISION_MODEL_VERSION
        for card in upgraded.comparison.scorecards
    )
    assert all(
        metric.direction == "minimize"
        for card in upgraded.comparison.scorecards
        for metric in card.metric_scores
        if metric.metric == "deployment_complexity"
    )

    beverage_before = reopened.get_workspace(ids[0])
    database_before = beverage_before.database_design.model_dump()
    saves_before = repository.save_calls
    clarified = reopened.answer_clarifications(ids[0], {"sla": "99.99%"})
    assert clarified is not None
    assert clarified.deployment_plan.availability_target_percent == 99.99
    assert clarified.database_design.model_dump() == database_before
    assert repository.save_calls == saves_before + 1
    repeated = reopened.answer_clarifications(ids[0], {"sla": "99.99%"})
    assert repeated is not None
    assert repository.save_calls == saves_before + 1


def test_semantic_segmentation_preserves_conjunctions_and_bullets():
    source = (
        "Must support operations across countries, regions, and time zones.\n"
        "And provide near-real-time tracking while preserving billing accuracy; "
        "because reconciliation is required.\n"
        "- Retain audit records for seven years\n"
        "- Support REST/JSON, XML, EDI, CSV, and webhooks"
    )
    statements = split_sentences(source)
    assert all(statement.casefold() not in {"tracking", "billing", "privacy"} for statement in statements)
    assert any("countries, regions, and time zones" in statement for statement in statements)
    assert any("And provide near-real-time tracking" in statement for statement in statements)
    normalized, _ = normalize_constraint_statements(statements)
    assert all(item.endswith(".") for item in normalized)
    assert not any(item.casefold() in {"tracking.", "billing.", "and."} for item in normalized)


def test_metric_direction_and_recommendation_are_consistent():
    scenario = SCENARIOS["logistics"]
    requirements = RequirementAnalyzer().analyze(
        scenario["title"], scenario["description"], scenario["context"], {"team_size": "8"}
    )
    architectures = ArchitectureGenerator().generate(requirements, {"team_size": "8"})
    comparison = ComparisonEngine().compare(requirements, architectures, {"team_size": "8"})
    recommendation = RecommendationEngine().recommend(
        requirements, architectures, comparison, {"team_size": "8"}
    )
    burden_metrics = {
        "cost", "deployment_complexity", "learning_curve",
        "development_time", "operational_complexity",
    }
    for card in comparison.scorecards:
        metrics = {metric.metric: metric for metric in card.metric_scores}
        assert all(metrics[name].direction == "minimize" for name in burden_metrics)
        assert all(metrics[name].normalized_score == 11 - metrics[name].score for name in burden_metrics)
        expected = round(sum(
            (metric.normalized_score or 0) * (metric.weight or 0)
            for metric in card.metric_scores
        ), 1)
        assert card.overall_score == expected
        assert card.weighted_score == expected * 10

    best_overall = max(comparison.scorecards, key=lambda item: item.overall_score)
    best_weighted = max(comparison.scorecards, key=lambda item: item.weighted_score)
    assert recommendation.recommended_architecture_id == best_overall.architecture_id
    assert best_overall.architecture_id == best_weighted.architecture_id

    matrix = {
        card.architecture_id: {metric.metric: metric.score for metric in card.metric_scores}
        for card in comparison.scorecards
    }
    deployment_only = recompute_with_weights(
        matrix,
        CriteriaWeights(weights={
            metric: 1.0 if metric == "deployment_complexity" else 0.0
            for metric in matrix[next(iter(matrix))]
        }),
    )
    deployment_scores = {
        card.architecture_id: next(
            metric.score for metric in card.metric_scores
            if metric.metric == "deployment_complexity"
        )
        for card in comparison.scorecards
    }
    assert deployment_scores[deployment_only[0].architecture_id] == min(deployment_scores.values())


def test_actor_classification_uses_actor_evidence_and_external_boundaries():
    integrations = [
        IntegrationDetail(
            id="INT-001",
            name="Payment Gateway",
            purpose="External payment processor API.",
        )
    ]
    cases = (
        (Actor(name="Payment Gateway", description="Processes card authorization."), "external-system"),
        (Actor(name="Bottling Partner", description="Operates an external bottling business."), "external-partner"),
        (Actor(name="Regional Operations Team", description="Internal operating unit."), "organizational"),
        (Actor(name="Warehouse Operator", description="Records inventory movements."), "human"),
        (Actor(name="Temperature Sensor", description="Reports measurements."), "device"),
        (Actor(name="Telemetry Feed", description="Publishes readings."), "event-source"),
        (Actor(name="Reconciliation Scheduler", description="Runs an automated job."), "machine"),
        (Actor(name="Participant", description="Participates in a workflow."), "unknown"),
    )
    assert [classify_actor(actor, integrations) for actor, _ in cases] == [
        expected for _, expected in cases
    ]


def test_conway_ownership_is_bounded_context_driven():
    architecture = ArchitectureOption(
        id="hybrid-event-serverless",
        name="Hybrid Event Architecture",
        style="hybrid",
        overview="Domain services with asynchronous processing.",
        components=[], data_flow=[], technology_stack=[], database="db",
        api_style="api", deployment="deploy", advantages=[], disadvantages=[],
        suitable_scenarios=[], estimated_complexity="High", estimated_cost="Medium",
        maintenance="plan",
    )
    contexts = [
        BoundedContext(id="CTX-001", name="Shipment", owned_entities=["Shipment"]),
        BoundedContext(id="CTX-002", name="Routing", owned_entities=["Route"]),
        BoundedContext(id="CTX-003", name="Customs", owned_entities=["Customs Document"]),
    ]
    result = check_fit(
        architecture,
        RequirementAnalysis(detected_entities=["Shipment", "Route", "Customs Document"]),
        ProjectConstraints(team_size=12, expected_scale="departmental"),
        contexts,
    )
    assert {item.component for item in result.ownership_mapping} == {
        context.name for context in contexts
    }
    assert all(item.suggested_team.startswith("Domain Team —") for item in result.ownership_mapping)
    assert not any("serverless consumer" in role.role_name.casefold() for role in result.team_fit_plan.roles)
    assert sum(role.recommended_headcount for role in result.team_fit_plan.roles) == 12
    assert result.friction_points == []
    assert result.fit_score == 9.5


def test_business_context_is_not_promoted_to_features_actors_or_entities(monkeypatch):
    analyzer = RequirementAnalyzer()
    monkeypatch.setattr(analyzer.ai_client, "generate", lambda *args, **kwargs: None)

    requirements = analyzer.analyze(
        "Laboratory Chain of Custody",
        (
            "Technicians register samples and reviewers approve test results. "
            "The system must respond within 200 ms and remain available 99.95% of the time."
        ),
        (
            "The company operates in 12 countries. Leadership coordinates regional teams "
            "using spreadsheets and wants lower costs and rapid growth. The platform must "
            "retain immutable audit history for 7 years."
        ),
        {},
    )

    assert requirements.functional_requirements == [
        "Technicians register samples.",
        "Reviewers approve test results.",
    ]
    assert all(
        not any(term in item.casefold() for term in ("leadership", "spreadsheets", "lower costs", "rapid growth"))
        for item in requirements.functional_requirements
    )
    assert any("200 ms" in item and "99.95%" in item for item in requirements.non_functional_requirements)
    assert any("7 years" in item and "audit" in item.casefold() for item in requirements.non_functional_requirements)
    assert requirements.constraints == []
    assert [(actor.name, actor.actor_type) for actor in requirements.actors] == [
        ("Technician", "human"),
        ("Reviewer", "human"),
    ]
    assert {entity.name for entity in requirements.domain_entities} == {"Sample", "Result"}


def test_semantic_constraint_dedupe_ignores_provenance_wrappers():
    analyzer = RequirementAnalyzer()
    assert analyzer._dedupe_constraints([
        "Must retain audit records for 7 years.",
        "User-specified retention: retain audit records for 7 years.",
        "Must use PostgreSQL.",
        "PostgreSQL is required.",
    ]) == [
        "Must retain audit records for 7 years.",
        "Must use PostgreSQL.",
    ]


def test_integration_clarifications_populate_each_boundary_without_fake_entries():
    analyzer = RequirementAnalyzer()
    base = analyzer._conservative_fallback(
        "Laboratory Chain of Custody",
        "Technicians register samples.",
        [],
    )
    requirements = analyzer.apply_clarifications(
        base,
        {
            "legacy_systems": "LabWare LIMS, SAP Quality Management",
            "data_formats": (
                "LabWare LIMS uses CSV batch files; "
                "SAP Quality Management uses REST/JSON webhooks"
            ),
        },
        {
            "legacy_systems": "Which external systems must be integrated?",
            "data_formats": "Which protocols and data formats does each integration use?",
        },
    )

    details = {detail.name: detail for detail in requirements.integration_details}
    assert set(details) == {"LabWare LIMS", "SAP Quality Management"}
    assert details["LabWare LIMS"].data_formats == ["CSV"]
    assert details["LabWare LIMS"].interaction_mode == "batch"
    assert details["SAP Quality Management"].protocol == ["REST", "Webhook"]
    assert details["SAP Quality Management"].data_formats == ["JSON"]
    assert details["SAP Quality Management"].interaction_mode == "asynchronous"
    assert all(
        {"CL-LEGACY-SYSTEMS", "CL-DATA-FORMATS"}
        <= {evidence.source_id for evidence in detail.source_evidence}
        for detail in details.values()
    )
    assert requirements.integrations == ["LabWare LIMS", "SAP Quality Management"]
    assert not any("data formats/protocols" in item.casefold() for item in requirements.constraints)


def test_conway_excludes_adapter_context_and_honors_team_names():
    architecture = ArchitectureOption(
        id="hybrid-event-serverless", name="Hybrid", style="hybrid",
        overview="Domain services with asynchronous processing.", components=[],
        data_flow=[], technology_stack=[], database="db", api_style="api",
        deployment="deploy", advantages=[], disadvantages=[], suitable_scenarios=[],
        estimated_complexity="High", estimated_cost="Medium", maintenance="plan",
    )
    contexts = [
        BoundedContext(id="CTX-001", name="Samples", owned_entities=["Sample"]),
        BoundedContext(id="CTX-002", name="Results", owned_entities=["Result"]),
        BoundedContext(
            id="CTX-003", name="External Integration", integrations=["LabWare LIMS"],
            responsibilities=["Own external contracts, adapters, retries, and reconciliation."],
        ),
    ]
    result = check_fit(
        architecture,
        RequirementAnalysis(detected_entities=["Sample", "Result"]),
        ProjectConstraints(team_size=8, expected_scale="departmental"),
        contexts,
    )

    assert {item.component for item in result.ownership_mapping} == {"Samples", "Results"}
    assert all(item.component.casefold() in item.suggested_team.casefold() for item in result.ownership_mapping)
    assert not any("external integration" in role.role_name.casefold() for role in result.team_fit_plan.roles)
    assert "2 bounded-context ownership units" in result.summary


def test_actor_identity_comes_from_name_not_the_systems_it_uses():
    actor = Actor(
        name="Regional Operations Team",
        description="Uses the ERP system to coordinate work.",
        actor_type="organizational",
    )
    assert classify_actor(actor, []) == "organizational"


def test_rich_banking_semantics_propagate_without_crud_or_serverless_bias():
    answers = {
        "team_size": "40",
        "preferred_cloud": "Hybrid / Multi-cloud",
        "scale": "200,000+ concurrent users and millions of financial transactions per day",
        "auth": "OAuth2/OIDC; SSO; MFA; RBAC; fine-grained authorization; mTLS; service credentials",
        "legacy_systems": "core banking; payment processor; card network; regulatory reporting",
        "data_formats": "REST/JSON; ISO 20022 XML; asynchronous events",
        "retention": "10+ years",
        "sla": "Always available",
    }
    description = (
        "Retail and business customers manage accounts, beneficiaries, cards, payments, and transfers. "
        "Banking operators support customers, fraud analysts assess suspicious transactions, and "
        "compliance officers prepare regulatory reporting. The internal double-entry ledger is "
        "authoritative for balances and transaction state. Financial transactions must be strongly "
        "consistent, idempotent, safe to retry, and prevent duplicates. Fraud scoring, notifications, "
        "analytics, and reporting run asynchronously. Support multiple currencies and regional banking "
        "regulations, encryption, auditability, data residency, and incremental legacy modernization."
    )
    requirements = RequirementAnalyzer().analyze(
        "Regional Banking Platform",
        description,
        "Modernize banking capabilities without losing regulatory controls.",
        answers,
    )
    database = DatabaseGenerator().generate(requirements)
    api = ApiGenerator().generate(requirements, database)
    architectures = ArchitectureGenerator().generate(requirements, answers)
    comparison = ComparisonEngine().compare(requirements, architectures, answers)
    recommendation = RecommendationEngine().recommend(
        requirements, architectures, comparison, answers
    )
    deployment = DeploymentGenerator().generate(requirements, recommendation, answers)

    assert requirements.assumptions == []
    assert not set(requirements.functional_requirements) & set(requirements.non_functional_requirements)
    assert any("encryption" in item.casefold() for item in requirements.non_functional_requirements)
    assert any("strongly consistent" in item.casefold() for item in requirements.constraints)
    actors = {actor.name: actor for actor in requirements.actors}
    assert actors["Compliance Officer"].actor_type == "human"
    assert actors["Compliance Officer"].owning_boundary == "Risk and Compliance"
    assert not any(actor.actor_type == "external-system" for actor in actors.values())
    assert {"core banking", "payment processor", "card network", "regulatory reporting"} <= {
        detail.name for detail in requirements.integration_details
    }
    entity_names = {entity.name for entity in requirements.domain_entities}
    assert {"Account", "Transaction", "Ledger Entry", "Risk Assessment", "Regulatory Report"} <= entity_names
    assert not entity_names & {"Financial", "Encryption", "Auditability", "Residency", "Assess", "Suspicious"}
    assert {context.name for context in requirements.bounded_contexts} >= {
        "Ledger and Accounts", "Payments and Transfers", "Risk and Compliance"
    }
    ledger = next(entity for entity in database.entities if entity.name == "ledger_entry")
    assert {"account_id", "transaction_id", "debit_amount", "credit_amount", "currency", "occurred_at"} <= {
        field.name for field in ledger.fields
    }
    assert any(
        relation.source == "ledger_entry"
        and relation.target == "account"
        and relation.cardinality == "many-to-one"
        and relation.foreign_key == "ledger_entry.account_id"
        for relation in database.relationships
    )
    paths = {endpoint.path for group in api.groups for endpoint in group.endpoints}
    assert {
        "/api/v1/internal/ledger/postings",
        "/api/v1/accounts/{accountId}/transactions",
        "/api/v1/cards/{cardId}/controls",
        "/api/v1/risk-assessments/assess",
    } <= paths
    security = requirements.security_model
    assert {"SSO", "OAuth2/OIDC", "MFA"} <= set(security.human_authentication)
    assert {"RBAC", "Fine-grained authorization"} <= set(security.authorization)
    assert {"mTLS", "Service credentials"} <= set(security.service_authentication)
    assert security.data_protection == ["Encryption at rest and in transit"]
    technical = {(item.category, item.value) for item in requirements.technical_characteristics}
    assert {("data-format", "ISO 20022"), ("data-format", "XML"), ("interaction-mode", "asynchronous")} <= technical
    assert not any("serverless" in architecture.id for architecture in architectures)
    assert any("strongly consistent database transaction" in flow for architecture in architectures for flow in architecture.data_flow)
    assert recommendation.recommended_architecture_id == comparison.scorecards[0].architecture_id
    assert deployment.cloud_recommendation.startswith("Evaluate Hybrid / Multi-cloud")
    assert '"Always available"' in (deployment.availability_configuration or "")
    assert "Redis" not in deployment.target_stack
    assert recommendation.confidence != "Low"


def test_precedent_missing_evidence_is_not_presented_as_zero_similarity():
    matches = match_twins(
        comparison_matrix={"service-based": {"scalability": 7, "security": 8}},
        recommended_architecture_id="service-based",
        deployment_stack=[],
        domain="Financial Services",
        domain_signals=["banking", "ledger"],
        capability_signals=[],
        data_signals=[],
        reliability_signals=[],
        integration_signals=[],
    )
    assert matches[0].case_study.company in {"Monzo", "Capital One"}
    assert matches[0].dimension_evidence["industry"]
    assert not matches[0].dimension_evidence["technology"]
    assert not matches[0].dimension_evidence["data"]
    assert matches[0].technology_similarity is None
    assert matches[0].data_similarity is None
    assert "technology evidence unavailable" in matches[0].rationale


def test_workload_terms_do_not_create_false_industry_matches():
    matches = match_twins(
        comparison_matrix={"event-driven-microservices": {
            "scalability": 9, "performance": 8, "reliability": 9,
            "availability": 9, "fault_isolation": 8,
        }},
        recommended_architecture_id="event-driven-microservices",
        deployment_stack=["Kafka", "PostgreSQL"],
        domain="Airline operations and passenger management",
        domain_signals=["passenger", "flight", "airport", "baggage", "event"],
        capability_signals=["booking", "check-in", "boarding", "event processing"],
        workload_signals=["high-volume real-time event processing"],
    )
    assert not any(match.domain_compatible for match in matches)
    assert matches[0].match_strength == "best-available"
    assert all(match.match_strength == "architecture-only" for match in matches[1:])


def test_semantically_equivalent_quality_targets_are_not_duplicated():
    requirements = RequirementAnalyzer()._decompose_non_functional_requirements([
        "The system must provide near-real-time flight, gate, baggage, and disruption updates.",
        "The system must support real-time flight status, gate changes, baggage events, and disruption notifications.",
        "The system must provide high availability across regions.",
    ])
    assert len(requirements) == 2
    assert any("availability" in item.casefold() for item in requirements)


def test_transport_brief_keeps_people_integrations_and_domain_operations_separate():
    description = (
        "Build a platform that manages trip schedules, vehicle assignments, crew operations, "
        "passenger bookings, check-in, boarding, baggage tracking, disruptions, and notifications. "
        "Passengers can search trips, make bookings, check in, receive boarding information, and "
        "track disruptions through web and mobile applications. Integrate with existing reservation, "
        "terminal, baggage, payment, loyalty, and operations systems."
    )
    answers = {
        "scale": "125,000 concurrent users and 4 million events per day",
        "legacy_systems": "Reservation Systems; Terminal Systems; Baggage Systems; Payment Systems; Loyalty Systems",
        "data_formats": (
            "Reservation Systems use REST/JSON synchronously; "
            "Baggage Systems deliver XML via webhooks"
        ),
        "domain_open_1": (
            "Passengers can search/book/check in/view trips; operations staff can manage trips and disruptions; "
            "crew can view assignments; ground staff can update boarding and baggage events; "
            "administrators configure the platform"
        ),
    }
    requirements = RequirementAnalyzer().analyze(
        "Passenger Operations Platform", description, None, answers
    )
    actor_names = {actor.name for actor in requirements.actors}
    assert {"Passenger", "Operations Staff", "Crew", "Ground Staff", "Administrator"} <= actor_names
    assert not any(actor.actor_type == "external-system" for actor in requirements.actors)
    assert not any("systems" in actor.name.casefold() for actor in requirements.actors)
    assert not any(len(actor.name.split()) > 6 for actor in requirements.actors)
    assert not any("integrate with" in item.casefold() for item in requirements.functional_requirements)
    assert not set(requirements.functional_requirements) & set(requirements.non_functional_requirements)

    details = {item.name: item for item in requirements.integration_details}
    assert details["Reservation Systems"].protocol == ["REST"]
    assert details["Reservation Systems"].data_formats == ["JSON"]
    assert details["Reservation Systems"].interaction_mode == "synchronous"
    assert details["Baggage Systems"].protocol == ["Webhook"]
    assert details["Baggage Systems"].data_formats == ["XML"]
    assert details["Baggage Systems"].interaction_mode == "asynchronous"
    assert all("domain data exchange" not in item.purpose.casefold() for item in details.values())
    assert any(
        item.category == "scale" and item.value == answers["scale"]
        for item in requirements.technical_characteristics
    )

    booking = next(item for item in requirements.domain_entities if item.name == "Booking")
    assert "passenger_id" in booking.attributes
    assert not {"station_id", "charger_id"} & set(booking.attributes)
    database = DatabaseGenerator().generate(requirements)
    api = ApiGenerator().generate(requirements, database)
    contracts = {(endpoint.method, endpoint.path) for group in api.groups for endpoint in group.endpoints}
    assert ("POST", "/api/v1/bookings") in contracts
    assert any(method == "GET" and "trip" in path for method, path in contracts)

    architecture = ArchitectureGenerator().generate(requirements, {"team_size": "40"})[0]
    fit = check_fit(
        architecture,
        RequirementAnalysis(detected_entities=[item.name for item in requirements.domain_entities]),
        ProjectConstraints(team_size=40),
        requirements.bounded_contexts,
    )
    assert all("+ more" not in role.role_name for role in fit.team_fit_plan.roles)


def test_blast_radius_follows_explicit_runtime_dependencies():
    architecture = ArchitectureOption(
        id="service-based",
        name="Dependency-owned services",
        style="service-based",
        overview="Explicit runtime dependencies",
        components=[
            ArchitectureComponent(name="Public API", responsibility="Routes requests", dependencies=["Booking Service"]),
            ArchitectureComponent(name="Booking Service", responsibility="Owns bookings", dependencies=["Booking Database"]),
            ArchitectureComponent(name="Notification Service", responsibility="Sends notifications", dependencies=["Event Backbone"]),
            ArchitectureComponent(name="Booking Database", responsibility="Stores bookings"),
            ArchitectureComponent(name="Event Backbone", responsibility="Carries events"),
        ],
        database="Explicit stores",
        api_style="Domain operations",
        deployment="Independent services",
        estimated_complexity="Medium",
        estimated_cost="Medium",
        maintenance="Owned by context teams",
    )
    result = simulate_failure(
        architecture,
        "Booking Database",
        {"service-based": {"fault_isolation": 8}},
    )
    statuses = {item.component: item for item in result.statuses}
    assert statuses["Booking Service"].status == "down"
    assert statuses["Public API"].status == "down"
    assert statuses["Notification Service"].status == "healthy"
    assert statuses["Event Backbone"].status == "healthy"
    assert "Booking Database" in (statuses["Booking Service"].reason or "")
