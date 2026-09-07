from app.schemas.domain import ClarificationPlan, ClarificationQuestion, RequirementModel


class ClarificationEngine:
    def generate(
        self,
        requirements: RequirementModel,
        answers: dict[str, str] | None = None,
    ) -> ClarificationPlan:
        answers = answers or {}
        questions: list[ClarificationQuestion] = []

        for index, question in enumerate(requirements.open_questions):
            key = f"domain_open_{index + 1}"
            if answers.get(key):
                continue
            questions.append(
                ClarificationQuestion(
                    key=key,
                    category="domain",
                    question=question,
                    rationale="The raw brief does not provide this architecture-critical detail.",
                    priority="high",
                    options=[],
                )
            )

        prompts = {
            "auth": (
                "security",
                "What authentication model is required for end users and internal operators?",
                "Authentication influences API design, authorization, and deployment hardening.",
                ["Email/password", "SSO/SAML", "Social login", "Passwordless"],
            ),
            "team_size": (
                "team",
                "How many engineers are available to build and operate the system?",
                "Team size drives Conway's Law fit, ownership boundaries, and how much operational complexity the team can carry.",
                [],
            ),
            "preferred_cloud": (
                "deployment",
                "Do you have a preferred cloud provider or hosting model?",
                "Cloud preference changes deployment architecture and managed service choices.",
                ["Cloud", "On-premise", "Hybrid", "No preference"],
            ),
            "sla": (
                "operations",
                "What availability target or SLA should the platform meet?",
                "Availability expectations drive redundancy, monitoring, and failover design.",
                ["Business hours", "Always available", "Undecided"],
            ),
            "scale": (
                "scalability",
                "What peak concurrent traffic should the system be designed for?",
                "Peak traffic is a major signal for architecture style and data strategy.",
                ["Known workload", "Pilot workload", "Undecided"],
            ),
            "retention": (
                "data",
                "How long should business and audit data be retained?",
                "Retention affects storage cost, indexing, and compliance reporting.",
                ["Short-lived", "Long-term", "Regulated", "Undecided"],
            ),
        }

        missing_areas: list[str] = []
        for key, (category, question, rationale, options) in prompts.items():
            if not answers.get(key):
                missing_areas.append(key)
                questions.append(
                    ClarificationQuestion(
                        key=key,
                        category=category,
                        question=question,
                        rationale=rationale,
                        priority="high" if key in {"auth", "preferred_cloud", "scale"} else "medium",
                        options=options,
                    )
                )

        requirement_text = " ".join(requirements.functional_requirements).lower()
        if any(
            token in requirement_text
            for token in ("payment", "billing", "checkout", "refund", "invoice")
        ) and not answers.get("payments"):
            missing_areas.append("payments")
            questions.append(
                ClarificationQuestion(
                    key="payments",
                    category="commerce",
                    question="Which payment or transaction boundaries are in scope?",
                    rationale="Transaction ownership affects consistency, security, and recovery design.",
                    priority="high",
                    options=["In scope", "External system", "Not in scope", "Undecided"],
                )
            )

        unresolved_domain = [
            f"domain_open_{index + 1}"
            for index in range(len(requirements.open_questions))
            if not answers.get(f"domain_open_{index + 1}")
        ]
        unresolved_count = len(unresolved_domain) + len(missing_areas)
        answered_count = len([value for value in answers.values() if value])
        completeness = int(100 * answered_count / max(answered_count + unresolved_count, 1))

        return ClarificationPlan(
            completeness_score=completeness,
            missing_areas=[
                *unresolved_domain,
                *missing_areas,
            ],
            questions=questions[:8],
        )

