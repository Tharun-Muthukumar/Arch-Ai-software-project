"""Curated real-world architecture precedent matching.

Design rationale:
  This module matches the recommended architecture's score vector against a
  small curated set of well-known, publicly documented systems using weighted
  distance in criteria-space. It grounds an abstract recommendation in real
  industry precedent rather than a generic label such as "microservices".
  Case facts are intentionally broad and public; matching is deterministic.
  Similarity scores are algorithmic distances between score vectors, not
  measurements of any company's internal systems.
"""

from math import sqrt

from app.schemas.domain import ProjectProfile, TwinCaseStudy, TwinMatch, TwinSimilarMetric
from app.services.comparison_engine import BASE_PROFILES
from app.services.decision_config import (
    PRECEDENT_DOMAIN_COMPATIBILITY_THRESHOLD,
    PRECEDENT_INCOMPATIBLE_INDUSTRY_CAP,
    PRECEDENT_SIMILARITY_WEIGHTS,
    PRECEDENT_WEAK_DOMAIN_OVERALL_CAP,
    metric_raw_score,
    metric_utility,
)
from app.services.domain_inference import tokenize


def _profile(architecture_id: str, **adjustments: int) -> dict[str, int]:
    """Create a bounded public-case score vector from an existing baseline."""
    base_id = {
        "monolithic": "modular-monolith",
        "layered": "modular-monolith",
        "clean": "modular-monolith",
        "microservices": "event-driven-microservices",
        "event-driven": "event-driven-microservices",
        "event_driven": "event-driven-microservices",
        "serverless": "serverless-platform",
        "service-based": "service-based",
        "service_based": "service-based",
        "hybrid-modular-serverless": "hybrid-modular-serverless",
        "hybrid-event-serverless": "hybrid-event-serverless",
    }.get(architecture_id, architecture_id)
    if base_id not in BASE_PROFILES:
        base_id = "service-based"
    profile = BASE_PROFILES[base_id].copy()
    for metric, delta in adjustments.items():
        if metric in profile:
            profile[metric] = metric_raw_score(
                metric,
                metric_utility(metric, profile[metric]) + delta,
            )
    return profile


def _case(
    id: str,
    company: str,
    architecture_id: str,
    services: list[str],
    summary: str,
    lesson: str,
    source_note: str,
    **adjustments: int,
) -> TwinCaseStudy:
    return TwinCaseStudy(
        id=id,
        company=company,
        architecture_id=architecture_id,
        score_vector=_profile(architecture_id, **adjustments),
        notable_services=services,
        summary=summary,
        lesson=lesson,
        source_note=source_note,
    )


# These systems and technology associations are broadly public and intentionally
# summarized without operational details or quotations from their source material.
REFERENCE_CASE_STUDIES: list[TwinCaseStudy] = [
    _case("basecamp", "Basecamp", "monolithic", ["MySQL", "Redis", "Ruby on Rails"], "Basecamp has publicly discussed keeping a cohesive Rails application for rapid product work.", "A well-bounded monolith can remain productive when ownership and deployment stay simple.", "Source note: Basecamp technical writing on its Rails monolith."),
    _case("github", "GitHub", "monolithic", ["MySQL", "Redis", "Ruby on Rails", "GitHub Actions"], "GitHub publicly described a long-lived Rails monolith supported by specialized surrounding systems.", "Start with cohesive domain boundaries and extract only the workloads that earn separation.", "Source note: GitHub Engineering posts on the GitHub monolith.", scalability=1, maintainability=1),
    _case("stackoverflow", "Stack Overflow", "layered", ["SQL Server", "Redis", "Elasticsearch", "ASP.NET"], "Stack Overflow has publicly shared a vertically scaled web application approach with SQL Server and caching.", "Operational simplicity and efficient vertical scale can serve a focused product for a long time.", "Source note: Stack Overflow Engineering posts and public architecture descriptions.", performance=1, cost=1),
    _case("shopify", "Shopify", "layered", ["MySQL", "Redis", "Ruby on Rails", "Kafka"], "Shopify is widely known for evolving a large Rails core alongside modular and event-oriented supporting systems.", "Modularity inside a cohesive core can postpone distributed-system costs without blocking growth.", "Source note: Shopify Engineering posts on Rails, modularity, and Kafka.", scalability=1, reliability=1),
    _case("atlassian", "Atlassian", "layered", ["PostgreSQL", "Kafka", "Java", "Kubernetes"], "Atlassian products have publicly evolved from layered applications toward more modular platform capabilities.", "Use clear module contracts so a cohesive application can be split deliberately if needed.", "Source note: Atlassian Engineering publications."),
    _case("bbc", "BBC", "clean", ["Node.js", "AWS", "Redis", "PostgreSQL"], "BBC teams have publicly described domain-focused services and clean interface boundaries for digital delivery.", "Explicit dependency boundaries make testing and future replacement easier even before services are extracted.", "Source note: BBC Engineering blogs.", maintainability=1, security=1),
    _case("nhs-digital", "NHS Digital", "service-based", ["REST", "FHIR", "OAuth2", "API Gateway"], "NHS public API catalogues document standards-based healthcare interfaces and nationally shared digital capabilities.", "Healthcare interoperability benefits from explicit contracts, identity boundaries, provenance, and domain ownership.", "Source note: Public NHS API catalogue and interoperability standards; no private implementation detail is asserted.", security=1, reliability=1),
    _case("canva", "Canva", "clean", ["Java", "PostgreSQL", "Redis", "Kubernetes"], "Canva has publicly discussed platform engineering and well-defined service boundaries while scaling product delivery.", "Keep domain logic independent from transport and storage concerns to make teams more autonomous.", "Source note: Canva Engineering publications.", scalability=1, maintainability=1),
    _case("monzo", "Monzo", "clean", ["Go", "Kafka", "PostgreSQL", "Kubernetes"], "Monzo has publicly discussed service-oriented domain boundaries and event-based financial workflows.", "Strong domain interfaces and observability are prerequisites for independently deployable systems.", "Source note: Monzo Engineering blog.", security=1, reliability=1),
    _case("netflix", "Netflix", "microservices", ["Kafka", "Cassandra", "Redis", "Zuul/API Gateway", "Kubernetes"], "Netflix is a well-known example of independently deployable services supported by resilient platform tooling.", "Service autonomy needs mature resilience, observability, and platform investment.", "Source note: Netflix TechBlog and public OSS documentation.", scalability=1, availability=1),
    _case("uber", "Uber", "microservices", ["Kafka", "Cassandra", "Redis", "Kubernetes"], "Uber has publicly described a large service estate connected through streaming and platform infrastructure.", "Distributed ownership works best when common tooling reduces coordination overhead.", "Source note: Uber Engineering posts.", scalability=1, fault_isolation=1),
    _case("airbnb", "Airbnb", "microservices", ["Kubernetes", "Kafka", "MySQL", "Redis"], "Airbnb has publicly shared its evolution from a Rails application toward service and platform capabilities.", "Extract services around clear operational and domain boundaries, not organizational fashion.", "Source note: Airbnb Engineering publications.", maintainability=1),
    _case("amazon", "Amazon", "microservices", ["AWS", "DynamoDB", "SQS", "API Gateway"], "Amazon is widely associated with service-oriented teams and independently operated interfaces at large scale.", "Autonomy requires strict APIs, operational ownership, and investment in internal platforms.", "Source note: Public Amazon architecture and engineering material.", reliability=1, availability=1),
    _case("slack", "Slack", "event-driven", ["Kafka", "MySQL", "Memcached"], "Slack has publicly discussed using Kafka and caching in event-heavy collaboration workflows.", "Events decouple fast-moving workflows when consumers can tolerate asynchronous state changes.", "Source note: Slack Engineering blog.", performance=1, reliability=1),
    _case("linkedin", "LinkedIn", "event-driven", ["Kafka", "Hadoop", "MySQL", "Apache Samza"], "LinkedIn created and publicly documented Kafka for high-volume event streams between many systems.", "Event streams are valuable when replay, fan-out, and independent consumers are real requirements.", "Source note: LinkedIn Engineering and Apache Kafka project material.", scalability=1, availability=1),
    _case("walmart", "Walmart", "event-driven", ["Kafka", "Kubernetes", "Redis", "Elasticsearch"], "Walmart has publicly described event-driven and cloud-native approaches for large retail workloads.", "Streaming platforms pay off when they serve many independently evolving workflows.", "Source note: Walmart Global Tech public engineering material.", scalability=1, fault_isolation=1),
    _case("capital-one", "Capital One", "event-driven", ["Kafka", "AWS Lambda", "DynamoDB", "API Gateway"], "Capital One has publicly presented event-driven cloud architectures built from managed services.", "Managed events can reduce infrastructure work but still need clear contracts and tracing.", "Source note: Capital One developer and cloud conference material."),
    _case("coca-cola", "Coca-Cola", "serverless", ["AWS Lambda", "API Gateway", "DynamoDB"], "Coca-Cola has publicly appeared in AWS material describing serverless API and data workloads.", "Managed functions are effective for variable demand when workload boundaries are small and observable.", "Source note: Public AWS customer-story material.", cost=1, deployment_complexity=1),
    _case("lego", "LEGO", "serverless", ["AWS Lambda", "API Gateway", "DynamoDB", "S3"], "LEGO has publicly discussed using AWS serverless services for selected digital experiences.", "Serverless can let lean teams focus on product work while usage remains variable.", "Source note: Public AWS customer-story and conference material.", scalability=1),
]

# Tags intentionally describe only high-level public precedent context.  They
# are not claims about a company's undisclosed internal architecture.
_CASE_DOMAIN_TAGS: dict[str, list[str]] = {
    "basecamp": ["collaboration", "saas", "business software"],
    "github": ["developer platform", "collaboration", "saas"],
    "stackoverflow": ["community", "knowledge platform"],
    "shopify": ["commerce", "retail"],
    "atlassian": ["business software", "collaboration", "saas"],
    "bbc": ["media", "content delivery"],
    "nhs-digital": ["healthcare", "clinical", "patient", "medical"],
    "canva": ["creative platform", "saas"],
    "monzo": ["banking", "financial services", "payments"],
    "netflix": ["media", "streaming"],
    "uber": ["mobility", "logistics"],
    "airbnb": ["travel", "marketplace"],
    "amazon": ["commerce", "logistics", "retail"],
    "slack": ["collaboration"],
    "linkedin": ["professional network"],
    "walmart": ["retail", "commerce", "supply chain"],
    "capital-one": ["banking", "financial services", "payments"],
    "coca-cola": ["manufacturing", "distribution", "consumer goods"],
    "lego": ["consumer goods", "commerce"],
}

_DOMAIN_TAXONOMY = (
    {"logistic", "shipment", "parcel", "carrier", "route", "transport", "delivery", "mobility"},
    {"manufacturing", "production", "bottling", "distribution", "supply", "chain", "inventory", "industrial"},
    {"banking", "financial", "payment", "transaction", "ledger", "settlement"},
    {"healthcare", "clinical", "patient", "medical", "health", "treatment", "pharmacy"},
    {"commerce", "retail", "marketplace", "store", "order", "catalog"},
    {"media", "streaming", "content", "playback", "video", "broadcast"},
    {"collaboration", "saas", "business", "workspace", "developer"},
    {"travel", "hospitality", "booking", "accommodation"},
)


def _taxonomy_expansion(values: list[str]) -> list[str]:
    tokens = {
        token.rstrip("s")
        for value in values
        for token in tokenize(value)
        if len(token) > 2
    }
    return sorted({term for group in _DOMAIN_TAXONOMY if tokens & group for term in group})


for _case_study in REFERENCE_CASE_STUDIES:
    # Idempotent initialization: recomputing tags must never accumulate
    # state across projects or imports (no cross-project leakage).
    _case_study.domain_tags = list(_CASE_DOMAIN_TAGS.get(_case_study.id, []))
    _case_study.capability_tags = list(dict.fromkeys([
        *_case_study.domain_tags,
        *_taxonomy_expansion(_case_study.domain_tags),
        *tokenize(f"{_case_study.summary} {_case_study.lesson}"),
    ]))
    architecture_tokens = _case_study.architecture_id.replace("_", "-").split("-")
    _case_study.workload_tags = list(dict.fromkeys([
        *architecture_tokens,
        *(("event processing", "asynchronous") if "event" in architecture_tokens else ()),
        *(("request response",) if "event" not in architecture_tokens else ()),
    ]))
    _case_study.scale_tags = [
        "large scale" if _case_study.score_vector.get("scalability", 5) >= 8 else "moderate scale",
        "high availability" if _case_study.score_vector.get("availability", 5) >= 8 else "standard availability",
    ]
    _case_study.data_tags = list(_case_study.notable_services)
    _case_study.reliability_tags = [
        "availability", "reliability", "fault isolation",
        *(["resilience"] if _case_study.score_vector.get("reliability", 5) >= 8 else []),
    ]
    _case_study.integration_tags = [
        item for item in _case_study.notable_services
        if any(marker in item.casefold() for marker in ("api", "kafka", "sqs", "samza", "fhir"))
    ]


def _same_family(left: str, right: str) -> bool:
    families = {
        "modular-monolith": "cohesive",
        "monolithic": "cohesive",
        "layered": "cohesive",
        "clean": "cohesive",
        "service-based": "service",
        "service_based": "service",
        "event-driven-microservices": "distributed",
        "microservices": "distributed",
        "event-driven": "distributed",
        "event_driven": "distributed",
        "serverless-platform": "serverless",
        "serverless": "serverless",
        "hybrid-modular-serverless": "hybrid-cohesive-serverless",
        "hybrid-event-serverless": "hybrid-distributed-serverless",
    }
    left_family = families.get(left, left)
    right_family = families.get(right, right)
    if left_family == right_family:
        return True
    # Hybrids share precedent with either parent family.
    hybrid_parents = {
        "hybrid-cohesive-serverless": {"cohesive", "serverless", "service"},
        "hybrid-distributed-serverless": {"distributed", "serverless", "service"},
    }
    if left_family in hybrid_parents:
        return right_family in hybrid_parents[left_family]
    if right_family in hybrid_parents:
        return left_family in hybrid_parents[right_family]
    return False


def compute_similarity(
    user_matrix_row: dict[str, int],
    case: TwinCaseStudy,
    weights: dict[str, float] | None = None,
) -> float:
    """Return a weighted, normalized Euclidean similarity on a 0-100 scale."""
    criteria = sorted(set(user_matrix_row) | set(case.score_vector))
    if not criteria:
        return 0.0
    active_weights = weights or {}
    denominator = sum(max(0.0, active_weights.get(metric, 1.0)) for metric in criteria)
    if denominator == 0:
        denominator = float(len(criteria))
        active_weights = {metric: 1.0 for metric in criteria}
    distance_sq = sum(
        max(0.0, active_weights.get(metric, 1.0))
        * (user_matrix_row.get(metric, 5) - case.score_vector.get(metric, 5)) ** 2
        for metric in criteria
    )
    max_distance = sqrt(81 * denominator)
    return round(max(0.0, min(100.0, (1 - sqrt(distance_sq) / max_distance) * 100)), 1)


def _overlap_services(deployment_stack: list[str], services: list[str]) -> list[str]:
    overlaps: list[str] = []
    for service in services:
        service_lower = service.lower()
        if any(service_lower in item.lower() or item.lower() in service_lower for item in deployment_stack):
            overlaps.append(service)
    return overlaps


def _alignment_metrics(user_row: dict[str, int], case: TwinCaseStudy) -> str:
    aligned = sorted(
        set(user_row) & set(case.score_vector),
        key=lambda metric: abs(user_row[metric] - case.score_vector[metric]),
    )[:2]
    return " and ".join(metric.replace("_", " ") for metric in aligned) or "overall architecture trade-offs"


def _similar_metrics(
    user_row: dict[str, int], case: TwinCaseStudy, top_n: int = 3
) -> list[TwinSimilarMetric]:
    """Return the closest metrics with both scores so the UI can name them precisely."""
    shared = sorted(
        set(user_row) & set(case.score_vector),
        key=lambda metric: (
            abs(user_row[metric] - case.score_vector[metric]),
            metric,
        ),
    )[:max(1, top_n)]
    return [
        TwinSimilarMetric(
            metric=metric,
            user_score=int(user_row[metric]),
            case_score=int(case.score_vector[metric]),
            delta=int(abs(user_row[metric] - case.score_vector[metric])),
        )
        for metric in shared
    ]


def _similar_metrics_clause(similar: list[TwinSimilarMetric]) -> str:
    parts = [
        f"{item.metric.replace('_', ' ')} (you {item.user_score}/10 vs {item.case_score}/10)"
        for item in similar
    ]
    return "; ".join(parts) or "overall architecture trade-offs"


def _tokens(values: list[str]) -> set[str]:
    return {
        token.rstrip("s")
        for value in values
        for token in tokenize(value)
        if len(token) > 2 and token not in {"platform", "system", "service", "services", "management"}
    }


_NON_DOMAIN_TERMS = {
    "api", "application", "architecture", "asynchronous", "availability",
    "cloud", "component", "data", "database", "event", "global", "high",
    "integration", "message", "notification", "operation", "operational",
    "platform", "processing", "realtime", "real", "regional", "reliable",
    "scalable", "service", "software", "stream", "streaming", "synchronous",
    "system", "technology", "update", "workflow",
}


def _domain_tokens(values: list[str]) -> set[str]:
    """Keep business-domain evidence separate from workload and topology terms."""
    return _tokens(values) - _NON_DOMAIN_TERMS


def _domain_similarity(domain: str, domain_signals: list[str], case: TwinCaseStudy) -> float:
    project = _domain_tokens([domain, *domain_signals])
    precedent = _domain_tokens(case.domain_tags)
    if not project or not precedent:
        return 0.0
    overlap = project & precedent
    # Related public categories can be a weak match, but never a substitute
    # for direct domain evidence (manufacturing is not logistics).
    direct = len(overlap) / max(min(len(project), len(precedent)), 1)
    related = any(project & group and precedent & group for group in _DOMAIN_TAXONOMY)
    return round(min(100.0, direct * 100 + (20.0 if related and not overlap else 0.0)), 1)


def _signal_similarity(project_values: list[str], precedent_values: list[str]) -> float:
    project = _tokens(project_values)
    precedent = _tokens(precedent_values)
    if not project or not precedent:
        return 0.0
    return round(100 * len(project & precedent) / max(min(len(project), len(precedent)), 1), 1)


def _technology_similarity(deployment_stack: list[str], case: TwinCaseStudy) -> float:
    project = _tokens(deployment_stack)
    precedent = _tokens(case.notable_services)
    if not project or not precedent:
        return 0.0
    return round(100 * len(project & precedent) / max(len(project), len(precedent)), 1)


def _workload_similarity(user_row: dict[str, int], case: TwinCaseStudy) -> float:
    workload_metrics = ("scalability", "performance", "reliability", "fault_isolation", "operational_complexity")
    values = [abs(user_row.get(metric, 5) - case.score_vector.get(metric, 5)) for metric in workload_metrics]
    return round(max(0.0, 100 - (sum(values) / max(len(values), 1)) * 10), 1)


def _scale_similarity(user_row: dict[str, int], case: TwinCaseStudy) -> float:
    scale_metrics = ("scalability", "availability", "reliability")
    values = [abs(user_row.get(metric, 5) - case.score_vector.get(metric, 5)) for metric in scale_metrics]
    return round(max(0.0, 100 - (sum(values) / max(len(values), 1)) * 10), 1)


def _normalised_similarity_weights(overrides: dict[str, float] | None) -> dict[str, float]:
    active = {**PRECEDENT_SIMILARITY_WEIGHTS, **(overrides or {})}
    active = {key: max(0.0, value) for key, value in active.items() if key in PRECEDENT_SIMILARITY_WEIGHTS}
    total = sum(active.values()) or 1.0
    return {key: value / total for key, value in active.items()}


def match_twins(
    comparison_matrix: dict[str, dict[str, int]],
    recommended_architecture_id: str,
    deployment_stack: list[str],
    weights: dict[str, float] | None = None,
    domain: str = "",
    domain_signals: list[str] | None = None,
    capability_signals: list[str] | None = None,
    workload_signals: list[str] | None = None,
    data_signals: list[str] | None = None,
    reliability_signals: list[str] | None = None,
    integration_signals: list[str] | None = None,
    project_profile: ProjectProfile | None = None,
    similarity_weights: dict[str, float] | None = None,
    top_n: int = 3,
) -> list[TwinMatch]:
    """Rank public precedents using project-local, explainable dimensions."""
    user_row = comparison_matrix.get(recommended_architecture_id, {})
    domain_signals = domain_signals or []
    capability_signals = capability_signals or []
    workload_signals = workload_signals or []
    data_signals = data_signals or []
    reliability_signals = reliability_signals or []
    integration_signals = integration_signals or []
    profile_signals = [] if project_profile is None else [
        project_profile.classification,
        project_profile.geographic_scope,
        project_profile.criticality,
        project_profile.workload_variability,
    ]
    blend = _normalised_similarity_weights(similarity_weights)
    matches: list[TwinMatch] = []
    for case in REFERENCE_CASE_STUDIES:
        dimension_evidence = {
            "domain": bool((domain.strip() or domain_signals) and case.domain_tags),
            "capability": bool(capability_signals and case.capability_tags),
            "architecture": bool(user_row and case.score_vector),
            # Workload/scale similarity from score vectors alone is
            # architecture resemblance, not workload evidence. Only claim
            # workload/scale evidence when explicit workload signals or a
            # project profile exist.
            "workload": bool(workload_signals and (case.score_vector or case.workload_tags)),
            "scale": bool(project_profile and (case.score_vector or case.scale_tags)),
            "technology": bool(deployment_stack and case.notable_services),
            "data": bool(data_signals and case.data_tags),
            "reliability": bool(reliability_signals and case.reliability_tags),
            "integration": bool(integration_signals and case.integration_tags),
        }
        dimension_evidence["industry"] = dimension_evidence["domain"] or dimension_evidence["capability"]
        architecture_similarity = compute_similarity(user_row, case, weights)
        if _same_family(recommended_architecture_id, case.architecture_id):
            architecture_similarity = min(100.0, round(architecture_similarity + 2.0, 1))
        domain_similarity = _domain_similarity(domain, domain_signals, case)
        capability_similarity = _signal_similarity(capability_signals, case.capability_tags)
        workload_similarity = _workload_similarity(user_row, case)
        workload_evidence_similarity = _signal_similarity(workload_signals, case.workload_tags)
        if workload_evidence_similarity:
            workload_similarity = round((workload_similarity + workload_evidence_similarity) / 2, 1)
        scale_similarity = _scale_similarity(user_row, case)
        scale_evidence_similarity = _signal_similarity(profile_signals, case.scale_tags)
        if scale_evidence_similarity:
            scale_similarity = round((scale_similarity + scale_evidence_similarity) / 2, 1)
        technology_similarity = _technology_similarity(deployment_stack, case)
        data_similarity = _signal_similarity(data_signals, case.data_tags)
        reliability_similarity = _signal_similarity(reliability_signals, case.reliability_tags)
        integration_similarity = _signal_similarity(integration_signals, case.integration_tags)
        domain_compatible = bool(
            dimension_evidence["domain"]
            and domain_similarity >= PRECEDENT_DOMAIN_COMPATIBILITY_THRESHOLD
        )
        industry_parts = [
            (domain_similarity, 0.65, dimension_evidence["domain"]),
            (capability_similarity, 0.35, dimension_evidence["capability"]),
        ]
        industry_weight = sum(weight for _, weight, available in industry_parts if available)
        industry_similarity = (
            round(
                sum(value * weight for value, weight, available in industry_parts if available)
                / industry_weight,
                1,
            )
            if industry_weight
            else None
        )
        if not domain_compatible and industry_similarity is not None:
            industry_similarity = min(industry_similarity, PRECEDENT_INCOMPATIBLE_INDUSTRY_CAP)
        raw_dimensions = {
            "domain": domain_similarity,
            "capability": capability_similarity,
            "architecture": architecture_similarity,
            "workload": workload_similarity,
            "scale": scale_similarity,
            "technology": technology_similarity,
            "data": data_similarity,
            "reliability": reliability_similarity,
            "integration": integration_similarity,
        }
        available_weight = sum(
            blend.get(name, 0)
            for name in raw_dimensions
            if dimension_evidence.get(name)
        ) or 1.0
        similarity = round(
            sum(
                value * blend.get(name, 0)
                for name, value in raw_dimensions.items()
                if dimension_evidence.get(name)
            ) / available_weight,
            1,
        )
        if not domain_compatible:
            similarity = min(similarity, PRECEDENT_WEAK_DOMAIN_OVERALL_CAP)
        overlaps = _overlap_services(deployment_stack, case.notable_services)
        shared = f"Shares {', '.join(overlaps)} with {case.company}'s approach" if overlaps else f"No direct stack overlap is modeled with {case.company}'s public stack"
        similar = _similar_metrics(user_row, case)
        dimension_values = {
            "industry": industry_similarity,
            "domain": domain_similarity,
            "capability": capability_similarity,
            "architecture": architecture_similarity,
            "workload": workload_similarity,
            "scale": scale_similarity,
            "technology": technology_similarity,
            "data": data_similarity,
            "reliability": reliability_similarity,
            "integration": integration_similarity,
        }
        evidence_summary = ", ".join(
            f"{name} {round(value):.0f}/100" if dimension_evidence.get(name) and value is not None else f"{name} evidence unavailable"
            for name, value in dimension_values.items()
        )
        # Explicitly separate industry (domain/capability) resemblance from
        # architecture/technology resemblance so a similar topology is never
        # misread as operating in the same industry.
        domain_clause = (
            f"Industry similarity {industry_similarity:.0f}/100 reflects domain/capability overlap; "
            f"architecture similarity {architecture_similarity:.0f}/100 reflects topology overlap."
            if industry_similarity is not None
            else (
                "Industry similarity is unavailable because no domain or capability evidence overlaps the public case metadata; "
                f"architecture similarity {architecture_similarity:.0f}/100 reflects topology only and is not industry resemblance."
            )
        )
        matches.append(TwinMatch(
            case_study=case,
            similarity_score=similarity,
            overlap_services=overlaps,
            rationale=(
                f"{shared}; {evidence_summary}. {domain_clause} "
                f"Most similar metrics: {_similar_metrics_clause(similar)}."
            ),
            similar_metrics=similar,
            domain_similarity=domain_similarity if dimension_evidence["domain"] else None,
            capability_similarity=capability_similarity if dimension_evidence["capability"] else None,
            architecture_similarity=architecture_similarity if dimension_evidence["architecture"] else None,
            workload_similarity=workload_similarity if dimension_evidence["workload"] else None,
            scale_similarity=scale_similarity if dimension_evidence["scale"] else None,
            technology_similarity=technology_similarity if dimension_evidence["technology"] else None,
            data_similarity=data_similarity if dimension_evidence["data"] else None,
            reliability_similarity=reliability_similarity if dimension_evidence["reliability"] else None,
            integration_similarity=integration_similarity if dimension_evidence["integration"] else None,
            industry_similarity=industry_similarity,
            architecture_precedent_similarity=architecture_similarity if dimension_evidence["architecture"] else None,
            technology_precedent_similarity=technology_similarity if dimension_evidence["technology"] else None,
            domain_compatible=domain_compatible,
            dimension_evidence=dimension_evidence,
            evidence_notice=(
                "Algorithmic similarity from public, high-level evidence; unavailable dimensions are excluded from factual interpretation."
            ),
        ))
    matches.sort(
        key=lambda match: (
            match.domain_compatible,
            match.domain_similarity if match.domain_similarity is not None else -1,
            match.industry_similarity is not None,
            match.industry_similarity if match.industry_similarity is not None else -1,
            match.capability_similarity if match.capability_similarity is not None else -1,
            match.similarity_score,
        ),
        reverse=True,
    )
    selected = matches[:max(1, top_n)]
    for index, match in enumerate(selected):
        if match.domain_compatible and (match.industry_similarity or 0) >= 70:
            match.match_strength = "strong"
        elif match.domain_compatible:
            match.match_strength = "domain-relevant"
        elif index == 0:
            match.match_strength = "best-available"
        else:
            match.match_strength = "architecture-only"
    return selected
