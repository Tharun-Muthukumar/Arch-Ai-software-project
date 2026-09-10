"""Deployment recommendations derived from project requirements.

Design rationale:
  Every deployment decision traces to an input: availability targets set
  replicas and failover posture, region counts and global-operation markers
  set the region plan, and the architecture plus data characteristics select
  the stack (each entry carries a workload reason). Nothing is listed
  because it is popular, and unknown inputs stay explicitly unknown instead
  of inventing values.
"""

import re

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
        sla = requirements.project_profile.availability_target_percent or parse_availability_percent(
            answers.get("sla"), *non_functional, *constraints
        )
        region_count = parse_region_count(
            answers.get("geographic_regions", ""), *non_functional, *constraints
        )
        multi_region = requirements.project_profile.geographic_scope == "global/multi-region" or bool(region_count and region_count > 1) or has_global_markers(
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
        needs_cache = any(
            marker in data_text
            for marker in ("cach", "read-heavy", "hot key", "rate limit", "leaderboard")
        )
        needs_files = any(
            marker in data_text
            for marker in ("file", "media", "image", "video", "document", "upload", "export")
        )
        retention_requirements = [
            item.value for item in requirements.technical_characteristics
            if item.category == "retention" and item.status == "confirmed"
        ]

        serverless_arch = arch_id in {"serverless-platform", "hybrid-modular-serverless", "hybrid-event-serverless"}
        event_arch = arch_id in {
            "event-driven-microservices", "hybrid-event-serverless", "hybrid-modular-serverless",
        }
        container_arch = arch_id in {
            "modular-monolith", "service-based", "event-driven-microservices",
            "hybrid-modular-serverless", "hybrid-event-serverless",
        }
        orchestrated_containers = container_arch and (
            high_scale
            or multi_region
            or arch_id in {"event-driven-microservices", "hybrid-event-serverless"}
        )

        # Replicas: 3 when the brief demands zone-level redundancy.
        if (sla is not None and sla >= 99.99) or high_scale or multi_region:
            replicas = 3
        else:
            replicas = 2

        # Regions as deployment roles (never invented place names).
        if region_count and region_count > 1:
            regions = ["Primary region", "Secondary region (failover)"]
            regions.extend(
                f"Additional region {index}"
                for index in range(3, region_count + 1)
            )
            effective_region_count = region_count
        elif multi_region:
            regions = ["Primary region", "Secondary region (failover)"]
            effective_region_count = 2
        else:
            regions = ["Single primary region"]
            effective_region_count = 1

        failover_answer = " ".join([
            answers.get("failover", ""),
            *requirements.non_functional_requirements,
            *requirements.constraints,
        ])
        lower_failover = failover_answer.casefold()
        if "active-active" in lower_failover:
            failover_mode = "active-active multi-region"
        elif multi_region:
            failover_mode = "active-passive regional failover"
        else:
            failover_mode = "zonal redundancy"

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

        rto = self._extract_recovery_target(failover_answer, "rto")
        rpo = self._extract_recovery_target(failover_answer, "rpo")
        qualitative_availability = " ".join((answers.get("sla") or "").split()).strip()
        if sla is not None:
            availability_configuration = (
                f"{sla}% availability target ({_downtime_budget(sla)}): "
                f"{failover_mode}, automated failover, and tested disaster "
                f"recovery{f' (RTO {rto}, RPO {rpo})' if rto or rpo else ''}."
            )
        elif qualitative_availability and qualitative_availability.casefold() not in {"unknown", "not specified", "no preference"}:
            availability_configuration = (
                f'User-stated availability expectation: "{qualitative_availability}". '
                "Use zonal redundancy and tested recovery, but confirm a measurable SLA/RTO/RPO "
                "before adding regions or claiming an uptime percentage."
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
        if orchestrated_containers:
            _add_stack("Kubernetes-ready manifests", "orchestration, self-healing, and horizontal scaling")
            _add_stack("Managed load balancer or ingress", "health-checked routing and TLS termination across replicas")
        if event_arch or realtime:
            _add_stack(
                "Kafka or managed event bus",
                "durable events for the asynchronous/event-driven workloads in the brief",
            )
        if needs_cache:
            _add_stack("Redis", "caching and queue backing for hot paths and background work")
        if needs_files:
            _add_stack("Object storage", "durable storage for files, media, and exports")
        if retention_requirements:
            _add_stack(
                "Archive storage tier",
                "confirmed retention policy requires lifecycle-managed immutable archives",
            )
        if serverless_arch:
            _add_stack("Managed functions", "elastic compute for the serverless handlers in the recommended hybrid")
            _add_stack("Managed API gateway", "metered HTTPS front door for function endpoints")

        docker_services = ["postgres"]
        if container_arch:
            docker_services.append("backend")
        # Only include a client/frontend container when the brief evidences a
        # user-facing web or mobile surface; never assume one by default.
        client_markers = ("web ", "web app", "frontend", " ui", "user interface", "mobile", "portal", "dashboard")
        if any(marker in data_text for marker in client_markers):
            docker_services.insert(0, "frontend")
        if event_arch or realtime:
            docker_services.append("kafka")
        if needs_cache:
            docker_services.append("redis (for queues and caching)")
        if serverless_arch:
            docker_services.append("managed function package")
        if needs_files:
            docker_services.append("object storage binding")

        if not orchestrated_containers and not serverless_arch:
            kubernetes_modules = []
        elif arch_id == "event-driven-microservices":
            kubernetes_modules = [
                "Ingress controller",
                "Backend deployment with HPA",
                "Background worker deployment for async domain jobs",
                "PostgreSQL or managed database binding",
                "Secrets and config maps",
                "Kafka or managed event bus",
            ]
        elif arch_id == "service-based":
            kubernetes_modules = [
                "Ingress controller",
                "Backend deployment with HPA",
                "Background worker deployment for async domain jobs",
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
                "Background worker deployment for async domain jobs",
                "PostgreSQL or managed database binding",
                "Secrets and config maps",
            ]

        scaling_strategy = [
            "Scale read-heavy APIs horizontally based on CPU and request concurrency.",
            "Offload asynchronous domain work to background workers or managed workflows.",
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
        if retention_requirements:
            security_controls.append(
                "Apply the confirmed retention policy to backups, audit records, and lifecycle-managed archives: "
                + "; ".join(retention_requirements) + "."
            )
        if requirements.security_model.human_authentication or requirements.security_model.authorization or auth_evidence(
            *requirements.functional_requirements, *non_functional, *constraints
        ):
            security_controls.append(
                "Enforce human identity and authorization controls at every service boundary: "
                + ", ".join(dict.fromkeys([
                    *requirements.security_model.human_authentication,
                    *requirements.security_model.authorization,
                ])) + "."
            )
        if requirements.security_model.service_authentication:
            security_controls.append(
                "Require service-to-service controls: "
                + ", ".join(requirements.security_model.service_authentication) + "."
            )
        if requirements.security_model.partner_authentication:
            security_controls.append(
                "Require partner integration controls: "
                + ", ".join(requirements.security_model.partner_authentication) + "."
            )
        if requirements.security_model.data_protection:
            security_controls.append(
                "Enforce data-protection controls: "
                + ", ".join(requirements.security_model.data_protection) + "."
            )

        observability = [
            "Structured logs with correlation IDs",
            "Prometheus-compatible metrics",
            "Distributed tracing for request and event flows",
            "Error alerting for failed jobs and degraded dependencies",
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
                "Run automated tests and static checks on pull requests.",
                "Build versioned container images with pinned dependencies.",
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
            replicas_per_region=replicas,
            total_baseline_replicas=replicas * effective_region_count,
            availability_target_percent=sla,
            failover_mode=failover_mode,
            rto=rto,
            rpo=rpo,
            source_evidence=requirements.project_profile.source_evidence,
        )

    @staticmethod
    def _extract_recovery_target(value: str, key: str) -> str | None:
        match = re.search(rf"\b{key}\s*[:=]?\s*([^,;.!]+)", value or "", re.I)
        return match.group(1).strip() if match else None
