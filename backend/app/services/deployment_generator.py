"""Deployment recommendations derived from project requirements.

Design rationale:
  Every deployment decision traces to an input: availability targets set
  replicas and failover posture, region counts and global-operation markers
  set the region plan, and the architecture plus data characteristics select
  the stack (each entry carries a workload reason). Nothing is listed
  because it is popular, and unknown inputs stay explicitly unknown instead
  of inventing values.
"""

from app.schemas.domain import DeploymentPlan, RecommendationResult, RequirementModel
from app.services.domain_inference import (
    audit_evidence,
    auth_evidence,
    has_global_markers,
    parse_availability_percent,
    parse_region_count,
)


def _downtime_budget(sla: float) -> str:
    minutes = (100.0 - sla) / 100.0 * 365 * 24 * 60
    if minutes < 90:
        return f"≈{minutes:.0f} minutes downtime/year"
    hours = minutes / 60
    if hours < 72:
        return f"≈{hours:.1f} hours downtime/year"
    return f"≈{hours / 24:.1f} days downtime/year"


class DeploymentGenerator:
    def generate(
        self,
        requirements: RequirementModel,
        recommendation: RecommendationResult,
        answers: dict[str, str] | None = None,
    ) -> DeploymentPlan:
        answers = answers or {}
        cloud = answers.get("preferred_cloud")
        if cloud and cloud.casefold() == "no preference":
            cloud = None
        arch_id = recommendation.recommended_architecture_id

        constraints = requirements.constraints
        non_functional = requirements.non_functional_requirements
        sla = parse_availability_percent(answers.get("sla"), *non_functional, *constraints)
        region_count = parse_region_count(
            answers.get("geographic_regions", ""), *non_functional, *constraints
        )
        multi_region = bool(region_count and region_count > 1) or has_global_markers(
            *non_functional, *constraints
        )
        high_scale = requirements.scale_profile == "high-scale"
        realtime = any(
            marker in " ".join(
                requirements.functional_requirements + non_functional
            ).lower()
            for marker in ("real-time", "realtime", "stream", "telemetry", "event")
        )
        data_text = " ".join(
            requirements.functional_requirements
            + non_functional
            + requirements.data_characteristics
        ).lower()
        needs_cache = high_scale or any(
            marker in data_text
            for marker in ("cach", "session", "queue", "rate limit", "leaderboard")
        )
        needs_files = any(
            marker in data_text
            for marker in ("file", "media", "image", "video", "document", "upload", "export")
        )

        serverless_arch = arch_id in {"serverless-platform", "hybrid-modular-serverless", "hybrid-event-serverless"}
        event_arch = arch_id in {
            "event-driven-microservices", "hybrid-event-serverless", "hybrid-modular-serverless",
        }
        container_arch = arch_id in {
            "modular-monolith", "service-based", "event-driven-microservices",
            "hybrid-modular-serverless", "hybrid-event-serverless",
        }

        # Replicas: 3 when the brief demands zone-level redundancy.
        if (sla is not None and sla >= 99.99) or high_scale or multi_region:
            replicas = 3
        else:
            replicas = 2

        # Regions as deployment roles (never invented place names).
        if region_count and region_count > 1:
            regions = ["Primary region", "Secondary region (failover)"]
            if region_count > 6:
                regions.append(f"Federated footprint across {region_count} markets")
            else:
                regions.extend(
                    f"Additional region {index}"
                    for index in range(3, min(region_count, 6) + 1)
                )
        elif multi_region:
            regions = ["Primary region", "Secondary region (failover)"]
        else:
            regions = ["Single primary region"]

        if sla is not None and sla >= 99.99:
            deployment_strategy = (
                "Blue-green deployments with automated rollback "
                f"(required by the {sla}% availability target)."
            )
        elif multi_region:
            deployment_strategy = (
                "Rolling deployments per region behind health gates "
                "(regional isolation requirement)."
            )
        else:
            deployment_strategy = "Rolling deployments with health checks and smoke tests."

        if sla is not None:
            availability_configuration = (
                f"{sla}% availability target ({_downtime_budget(sla)}): "
                "multi-AZ placement, automated failover, and tested disaster "
                "recovery with defined RTO/RPO."
            )
        else:
            availability_configuration = (
                "Availability target unconfirmed; design for zonal redundancy "
                "and confirm the SLA before committing to a failover topology."
            )

        # Stack: each technology names the workload that needs it.
        target_stack: list[str] = []
        stack_rationale: list[str] = []

        def _add_stack(name: str, reason: str) -> None:
            target_stack.append(name)
            stack_rationale.append(f"{name}: {reason}.")

        _add_stack("PostgreSQL", "relational system of record for transactional domain state")
        if container_arch:
            _add_stack("Docker", "reproducible packaging for the containerized services")
            _add_stack("Kubernetes-ready manifests", "orchestration, self-healing, and horizontal scaling")
            _add_stack("NGINX", "edge routing and TLS termination for containerized services")
        if event_arch or realtime:
            _add_stack(
                "Kafka or managed event bus",
                "durable events for the asynchronous/event-driven workloads in the brief",
            )
        if needs_cache:
            _add_stack("Redis", "caching and queue backing for hot paths and background work")
        if needs_files:
            _add_stack("Object storage", "durable storage for files, media, and exports")
        if serverless_arch:
            _add_stack("Managed functions", "elastic compute for the serverless handlers in the recommended hybrid")
            _add_stack("Managed API gateway", "metered HTTPS front door for function endpoints")

        docker_services = ["frontend", "postgres"]
        if container_arch:
            docker_services.append("backend")
        if event_arch or realtime:
            docker_services.append("kafka")
        if needs_cache:
            docker_services.append("redis (for queues and caching)")
        if serverless_arch:
            docker_services.append("managed function package")
        if needs_files:
            docker_services.append("object storage binding")

        if arch_id == "event-driven-microservices":
            kubernetes_modules = [
                "Ingress controller",
                "Backend deployment with HPA",
                "Worker deployment for long-running exports",
                "PostgreSQL or managed database binding",
                "Secrets and config maps",
                "Kafka or managed event bus",
            ]
        elif arch_id == "service-based":
            kubernetes_modules = [
                "Ingress controller",
                "Backend deployment with HPA",
                "Worker deployment for long-running exports",
                "PostgreSQL or managed database binding",
                "Secrets and config maps",
                "Service deployments with per-service scaling policies",
            ]
        elif arch_id == "hybrid-modular-serverless":
            kubernetes_modules = [
                "Containerized core deployment with HPA",
                "Managed function deployment package for edge handlers",
                "Queue or event-bus binding between core and edge",
                "Managed database and secret bindings",
            ]
        elif arch_id == "hybrid-event-serverless":
            kubernetes_modules = [
                "Coarse service deployments with HPA",
                "Managed function deployments for event consumers",
                "Event backbone (Kafka or managed bus) with replay",
                "Managed database and secret bindings",
            ]
        elif arch_id == "serverless-platform":
            kubernetes_modules = [
                "Managed API gateway mapping",
                "Function deployment package",
                "Workflow orchestration definitions",
                "Managed database and secret bindings",
            ]
        else:
            kubernetes_modules = [
                "Ingress controller",
                "Backend deployment with HPA",
                "Worker deployment for long-running exports",
                "PostgreSQL or managed database binding",
                "Secrets and config maps",
            ]

        scaling_strategy = [
            "Scale read-heavy APIs horizontally based on CPU and request concurrency.",
            "Offload long-running generation tasks to background workers or managed workflows.",
        ]
        if high_scale:
            scaling_strategy.append(
                "Use read replicas, async event processing, and CDN-backed asset delivery for burst absorption."
            )
        if multi_region:
            scaling_strategy.append(
                "Replicate serving capacity per region with locality-aware routing "
                f"({replicas} replicas per region baseline)."
            )
        else:
            scaling_strategy.append(
                f"Run {replicas} replicas for baseline redundancy within the primary region."
            )

        security_controls = [
            "Store secrets in a managed vault or Kubernetes secret manager.",
            "Enforce TLS termination, CORS policy, and content security controls.",
            "Apply database backups, retention, and audit-log protection policies.",
        ]
        if auth_evidence(
            *requirements.functional_requirements, *non_functional, *constraints
        ):
            security_controls.append(
                "Enforce the stated enterprise identity controls (SSO/MFA/RBAC) at every service boundary."
            )

        observability = [
            "Structured logs with correlation IDs",
            "Prometheus-compatible metrics",
            "Tracing for long-running artifact generation flows",
            "Error alerting for failed exports and regeneration tasks",
        ]
        if audit_evidence(*non_functional, *constraints):
            observability.append(
                "Tamper-evident audit event pipeline for the stated compliance obligations."
            )

        return DeploymentPlan(
            deployment_model=recommendation.recommended_architecture_name,
            replicas=replicas,
            regions=regions,
            deployment_strategy=deployment_strategy,
            availability_configuration=availability_configuration,
            target_stack=target_stack,
            docker_services=docker_services,
            kubernetes_modules=kubernetes_modules,
            cicd_pipeline=[
                "Run backend tests and frontend tests on pull requests.",
                "Build versioned Docker images and execute production frontend build.",
                "Promote artifacts through staging to production with health checks and smoke tests.",
            ],
            observability=observability,
            scaling_strategy=scaling_strategy,
            security_controls=security_controls,
            cloud_recommendation=(
                f"Evaluate {cloud} using the confirmed data, availability, and integration constraints."
                if cloud
                else "Hosting model is unknown; select it after residency, connectivity, availability, and operations constraints are clarified."
            ),
            stack_rationale=stack_rationale,
        )
