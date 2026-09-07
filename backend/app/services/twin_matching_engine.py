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

from app.schemas.domain import TwinCaseStudy, TwinMatch, TwinSimilarMetric
from app.services.comparison_engine import BASE_PROFILES


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
            profile[metric] = max(1, min(10, profile[metric] + delta))
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


def match_twins(
    comparison_matrix: dict[str, dict[str, int]],
    recommended_architecture_id: str,
    deployment_stack: list[str],
    weights: dict[str, float] | None = None,
    top_n: int = 3,
) -> list[TwinMatch]:
    """Rank public case studies by score-vector similarity and stack overlap."""
    user_row = comparison_matrix.get(recommended_architecture_id, {})
    matches: list[TwinMatch] = []
    for case in REFERENCE_CASE_STUDIES:
        similarity = compute_similarity(user_row, case, weights)
        if _same_family(recommended_architecture_id, case.architecture_id):
            similarity = min(100.0, round(similarity + 2.0, 1))
        overlaps = _overlap_services(deployment_stack, case.notable_services)
        shared = f"Shares {', '.join(overlaps)} with {case.company}'s approach" if overlaps else f"No direct stack overlap is modeled with {case.company}'s public stack"
        similar = _similar_metrics(user_row, case)
        matches.append(TwinMatch(
            case_study=case,
            similarity_score=similarity,
            overlap_services=overlaps,
            rationale=f"{shared}; most similar metrics: {_similar_metrics_clause(similar)}.",
            similar_metrics=similar,
        ))
    matches.sort(key=lambda match: match.similarity_score, reverse=True)
    return matches[:max(1, top_n)]
