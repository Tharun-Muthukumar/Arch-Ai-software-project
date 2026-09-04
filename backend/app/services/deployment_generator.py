from app.schemas.domain import DeploymentPlan, RecommendationResult, RequirementModel


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

        docker_services = [
            "frontend",
            "backend",
            "postgres",
            "redis (optional for queues and caching)",
            "ollama bridge or local model host",
        ]

        kubernetes_modules = [
            "Ingress controller",
            "Backend deployment with HPA",
            "Worker deployment for long-running exports",
            "PostgreSQL or managed database binding",
            "Secrets and config maps",
        ]

        if arch_id == "event-driven-microservices":
            docker_services.append("kafka")
            kubernetes_modules.append("Kafka or managed event bus")
        elif arch_id == "serverless-platform":
            kubernetes_modules = [
                "Managed API gateway mapping",
                "Function deployment package",
                "Workflow orchestration definitions",
                "Managed database and secret bindings",
            ]

        scaling_strategy = [
            "Scale read-heavy APIs horizontally based on CPU and request concurrency.",
            "Offload long-running generation tasks to background workers or managed workflows.",
            "Cache dashboard summaries and generated markdown exports for repeat access.",
        ]
        if requirements.scale_profile == "high-scale":
            scaling_strategy.append(
                "Use read replicas, async event processing, and CDN-backed asset delivery for burst absorption."
            )

        return DeploymentPlan(
            deployment_model=recommendation.recommended_architecture_name,
            target_stack=["Docker", "Docker Compose", "Kubernetes-ready manifests", "NGINX"],
            docker_services=docker_services,
            kubernetes_modules=kubernetes_modules,
            cicd_pipeline=[
                "Run backend tests and frontend tests on pull requests.",
                "Build versioned Docker images and execute production frontend build.",
                "Promote artifacts through staging to production with health checks and smoke tests.",
            ],
            observability=[
                "Structured logs with correlation IDs",
                "Prometheus-compatible metrics",
                "Tracing for long-running artifact generation flows",
                "Error alerting for failed exports and regeneration tasks",
            ],
            scaling_strategy=scaling_strategy,
            security_controls=[
                "Store secrets in a managed vault or Kubernetes secret manager.",
                "Enforce TLS termination, CORS policy, and content security controls.",
                "Apply database backups, retention, and audit-log protection policies.",
            ],
            cloud_recommendation=(
                f"Evaluate {cloud} using the confirmed data, availability, and integration constraints."
                if cloud
                else "Hosting model is unknown; select it after residency, connectivity, availability, and operations constraints are clarified."
            ),
        )

