import re

from app.schemas.domain import ClarificationPlan, ClarificationQuestion, RequirementModel

_UNKNOWN_VALUES = {
    "", "n/a", "needs discussion", "no preference", "not applicable",
    "not specified", "not specified yet", "undecided", "unknown",
}


def _is_answered(value: object) -> bool:
    if value is None:
        return False
    text = " ".join(str(value).split()).strip().casefold()
    return bool(text) and text not in _UNKNOWN_VALUES


class ClarificationEngine:
    """Phase 2 follow-ups: few, plain, and only when they change the design.

    The panel used to fire up to 8 questions including jargon-heavy asks
    (RTO/RPO, protocols, regions) on every workspace. Now at most 5 are
    shown: 4 core questions that directly drive architecture choice, plus
    conditional ones asked only when the brief signals they matter. Anything
    unasked keeps a safe neutral default downstream, so skipping is harmless.
    """

    # Core questions: always asked (when unanswered). Each one directly moves
    # an architecture decision, so they earn their place every time.
    _CORE_PROMPTS: dict[str, tuple[str, str, str, list[str]]] = {
        "scale": (
            "scalability",
            "Roughly how many people will use the system at peak?",
            "Peak usage is the biggest signal for architecture style.",
            ["Just me / a few", "Hundreds", "Thousands or more", "Undecided"],
        ),
        "auth": (
            "security",
            "How should users log in?",
            "Login choice shapes API design and access control.",
            ["Email/password", "SSO/SAML", "Social login", "Passwordless"],
        ),
        "preferred_cloud": (
            "deployment",
            "Where should this run?",
            "Hosting preference changes deployment and managed-service choices.",
            ["Cloud", "On-premise", "Hybrid", "No preference"],
        ),
        "team_size": (
            "team",
            "How many engineers will build and run it?",
            "Team size sets how much operational complexity is safe to take on.",
            ["Just me", "2-6", "7-15", "15+"],
        ),
    }

    # Conditional questions: asked only when `condition` finds supporting
    # evidence in the requirements. Each entry is
    # (category, question, rationale, options, condition).
    _CONDITIONAL_PROMPTS: dict[str, tuple[str, str, str, list[str], str]] = {
        "sla": (
            "operations",
            "Does the system need to stay up around the clock?",
            "Only high-availability needs change redundancy design; business-hours systems keep the simple default.",
            ["Business hours is fine", "Always available", "Undecided"],
            "availability",
        ),
        "retention": (
            "data",
            "How long should records be kept?",
            "Asked only when audit, compliance, or retention language appears in the brief.",
            ["Short-lived", "Long-term", "Regulated", "Undecided"],
            "retention",
        ),
        "legacy_systems": (
            "integrations",
            "Which existing systems must it connect to, if any?",
            "Asked only when the brief mentions integrations or external data exchange.",
            [],
            "integrations",
        ),
        "data_formats": (
            "technical-data",
            "What data formats do those connections use?",
            "Asked only when there is something to connect to.",
            ["REST/JSON", "XML", "EDI", "CSV", "Webhooks"],
            "formats",
        ),
        "failover": (
            "availability",
            "If a data center or region went down, should the system keep running?",
            "Plain-language recovery need; asked only when scale, availability, or multi-region signals exist.",
            ["Keep running elsewhere", "Manual recovery is fine", "Single region", "Undecided"],
            "failover",
        ),
        "geographic_regions": (
            "deployment",
            "Does it need to run in more than one region?",
            "Asked only when global or multi-region operation appears in the brief.",
            ["Single region", "Two regions", "Three or more", "Undecided"],
            "regions",
        ),
    }

    # Hard cap on visible questions: brevity is the point of Phase 2.
    MAX_QUESTIONS = 5
    # At most this many brief-derived domain questions; the fixed core set
    # covers the generic decisions.
    MAX_DOMAIN_QUESTIONS = 2

    # Domain-question topics already covered by a fixed prompt below. A
    # brief-derived question on one of these topics would interrogate the
    # user twice (e.g. open "workload volume?" next to core "peak usage?").
    _DOMAIN_OVERLAP_MARKERS: dict[str, tuple[str, ...]] = {
        "scale": ("workload", "concurrency", "concurrent", "traffic", "users"),
        "auth": ("authentication", "log in", "login"),
        "preferred_cloud": ("hosting", "cloud provider", "cloud hosting"),
        "team_size": ("team size", "engineers", "staffing", "operational skills"),
        "sla": ("availability", "recovery", "downtime", "uptime", "sla"),
        "failover": ("failover", "rto", "rpo", "replication"),
        "retention": ("retention", "audit", "regulatory", "retain"),
        "legacy_systems": ("external systems", "exchange data", "legacy"),
        "geographic_regions": ("regions", "residency", "geography"),
    }

    @classmethod
    def _domain_duplicates_fixed(cls, domain_question: str, fixed_keys: set[str]) -> bool:
        lower = domain_question.casefold()
        return any(
            any(marker in lower for marker in cls._DOMAIN_OVERLAP_MARKERS[key])
            for key in fixed_keys
            if key in cls._DOMAIN_OVERLAP_MARKERS
        )

    def generate(
        self,
        requirements: RequirementModel,
        answers: dict[str, str] | None = None,
    ) -> ClarificationPlan:
        answers = answers or {}
        questions: list[ClarificationQuestion] = []
        fixed_keys = (
            set(self._CORE_PROMPTS)
            | set(self._CONDITIONAL_PROMPTS)
            | {"payments"}
        )

        for index, question in enumerate(requirements.open_questions):
            if sum(1 for item in questions if item.category == "domain") >= self.MAX_DOMAIN_QUESTIONS:
                break
            key = f"domain_open_{index + 1}"
            if _is_answered(answers.get(key)):
                continue
            if self._domain_duplicates_fixed(question, fixed_keys):
                continue
            questions.append(
                ClarificationQuestion(
                    key=key,
                    category="domain",
                    question=question,
                    rationale="The brief does not provide this project-specific detail.",
                    priority="high",
                    options=[],
                )
            )

        for key, (category, question, rationale, options) in self._CORE_PROMPTS.items():
            if not _is_answered(answers.get(key)):
                questions.append(
                    ClarificationQuestion(
                        key=key,
                        category=category,
                        question=question,
                        rationale=rationale,
                        priority="high",
                        options=options,
                    )
                )

        signals = self._brief_signals(requirements, answers)
        for key, (category, question, rationale, options, condition) in self._CONDITIONAL_PROMPTS.items():
            if _is_answered(answers.get(key)):
                continue
            if not signals.get(condition):
                continue
            questions.append(
                ClarificationQuestion(
                    key=key,
                    category=category,
                    question=question,
                    rationale=rationale,
                    priority="medium",
                    options=options,
                )
            )

        requirement_text = " ".join(requirements.functional_requirements).lower()
        if any(
            token in requirement_text
            for token in ("payment", "billing", "checkout", "refund", "invoice")
        ) and not _is_answered(answers.get("payments")):
            questions.append(
                ClarificationQuestion(
                    key="payments",
                    category="commerce",
                    question="Are payments handled inside this system?",
                    rationale="Only payment-bearing briefs are asked; the answer sets transaction ownership.",
                    priority="high",
                    options=["In scope", "External system", "Not in scope", "Undecided"],
                )
            )

        # High-priority first, stable order otherwise, hard-capped so Phase 2
        # stays a quick pass instead of an interrogation.
        questions.sort(key=lambda item: (0 if item.priority == "high" else 1))
        visible = questions[: self.MAX_QUESTIONS]
        presented_keys = [item.key for item in visible]
        answered_count = len([value for value in answers.values() if _is_answered(value)])
        unresolved_count = sum(
            1 for key in presented_keys if not _is_answered(answers.get(key))
        )
        completeness = int(100 * answered_count / max(answered_count + unresolved_count, 1))

        return ClarificationPlan(
            completeness_score=completeness,
            missing_areas=presented_keys,
            questions=visible,
        )

    @staticmethod
    def _brief_signals(
        requirements: RequirementModel, answers: dict[str, str]
    ) -> dict[str, bool]:
        """Decide which conditional questions the brief earns.

        Signals come from requirement text plus already-known answers, so a
        user who volunteers context gets sharper follow-ups instead of the
        full battery.
        """
        text = " ".join([
            requirements.domain,
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
            *requirements.data_characteristics,
            *requirements.integrations,
            *[detail.name for detail in requirements.integration_details],
        ]).casefold()
        from app.services.domain_inference import (
            parse_availability_percent,
            parse_region_count,
        )

        has_integrations = bool(
            requirements.integrations
            or requirements.integration_details
            or any(
                marker in text
                for marker in (
                    "integrat", "legacy", "external system", "import", "export",
                    "erp", "webhook", "api ",
                )
            )
        )
        confirmed_technical = {
            (item.category, item.value.casefold())
            for item in requirements.technical_characteristics
            if item.status == "confirmed"
        }
        has_confirmed_protocols = any(
            category in {"protocol", "data-format"}
            for category, _ in confirmed_technical
        )
        return {
            # Availability matters once scale, realtime, compliance, or an
            # explicit target shows up — unless the brief already states a
            # numeric target, in which case there is nothing to ask.
            "availability": (
                any(
                    marker in text
                    for marker in (
                        "availab", "sla", "uptime", "24/7", "always available",
                        "realtime", "real-time", "compliance", "regulated",
                        "99.", "four nines",
                    )
                )
                or _is_answered(answers.get("scale"))
                or requirements.scale_profile in {"growth-scale", "high-scale"}
            )
            and parse_availability_percent(
                *requirements.non_functional_requirements,
                *requirements.constraints,
            ) is None,
            "retention": any(
                marker in text
                for marker in (
                    "retention", "retain", "audit", "compliance", "regulat",
                    "provenance", "lineage",
                )
            )
            # A stated duration (e.g. "retention 10 years") already answers it.
            and not re.search(r"\d+\s*(?:years?|months?)", text),
            # Named integrations already answer "which systems".
            "integrations": has_integrations and not requirements.integration_details,
            # Formats only matter once a connection target is known — and are
            # already answered when confirmed protocols were extracted.
            "formats": has_integrations
            and not has_confirmed_protocols
            and (
                _is_answered(answers.get("legacy_systems"))
                or bool(requirements.integration_details)
                or any(
                    marker in text
                    for marker in ("protocol", "format", "json", "xml", "edi", "csv")
                )
            ),
            "failover": (
                any(
                    marker in text
                    for marker in (
                        "failover", "multi-region", "multi region", "global",
                        "region", "replica", "rto", "rpo", "disaster",
                    )
                )
                or requirements.scale_profile == "high-scale"
                or _is_answered(answers.get("sla"))
            )
            # A stated topology (active-active / active-passive / single
            # region) already answers it.
            and not any(
                marker in text
                for marker in ("active-active", "active-passive", "single region")
            ),
            "regions": any(
                marker in text
                for marker in (
                    "multi-region", "multi region", "global", "data residency",
                    "regions",
                )
            )
            # An explicit count already answers it; vague "multi-region"
            # alone keeps the question.
            and parse_region_count(
                *requirements.non_functional_requirements,
                *requirements.constraints,
            ) is None,
        }
