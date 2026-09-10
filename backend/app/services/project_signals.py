"""Canonical, traceable project signals shared by every generator.

Raw answers used to be appended to unrelated strings.  This module turns each
answer into a typed, project-local fact exactly once.  It never holds mutable
module state, so a project's context cannot affect another project's output.
"""

from __future__ import annotations

import re

from app.schemas.domain import (
    Actor,
    BoundedContext,
    ConfidenceReport,
    IntegrationDetail,
    ProjectProfile,
    RequirementModel,
    SecurityModel,
    SourceEvidence,
    StructuredClarification,
    TechnicalCharacteristic,
)
from app.services.decision_config import CONFIDENCE_THRESHOLDS, SCALE_THRESHOLDS
from app.services.domain_inference import (
    cluster_entities,
    extract_actors,
    parse_availability_percent,
    parse_region_count,
    singularize,
    tokenize,
)

_UNKNOWN_VALUES = frozenset({
    "", "n/a", "unknown", "undecided", "not applicable", "not specified",
    "not specified yet", "needs discussion", "no preference",
})

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("integrations", ("legacy", "integration", "external system", "partner system")),
    ("technical-data", ("format", "protocol", "data", "event", "consistency", "database")),
    ("availability", ("availability", "sla", "failover", "recovery", "rto", "rpo")),
    ("security", ("security", "auth", "identity", "access", "mfa", "sso", "oauth", "oidc")),
    ("scale", ("traffic", "concurrent", "scale", "throughput", "volume", "load")),
    ("retention", ("retention", "archive", "audit period")),
    ("regional", ("region", "geography", "residency", "locality")),
)

_PROTOCOLS = ("REST", "GraphQL", "gRPC", "SOAP", "EDI", "Webhook", "AMQP", "MQTT", "SFTP")
_FORMATS = ("JSON", "XML", "ISO 20022", "CSV", "Avro", "Parquet", "HL7", "FHIR")
_SECURITY_MARKERS = {
    "SSO": ("sso", "saml"),
    "OAuth2/OIDC": ("oauth", "oidc"),
    "MFA": ("mfa", "multi-factor", "multifactor"),
    "RBAC": ("rbac", "role-based", "role based"),
    "Fine-grained authorization": ("fine-grained authorization", "fine grained authorization", "attribute-based", "abac"),
    "mTLS": ("mtls", "mutual tls"),
    "Service credentials": ("service credential", "client credential", "api credential", "api key"),
    "Encryption at rest and in transit": ("encryption", "encrypted at rest", "encrypted in transit"),
}

_HUMAN_ACTOR_MARKERS = frozenset({
    "admin", "administrator", "analyst", "auditor", "buyer", "cashier",
    "client", "clinician", "coordinator", "customer", "doctor", "driver",
    "employee", "engineer", "inspector", "manager", "member", "nurse",
    "operator", "patient", "pharmacist", "planner", "reviewer", "student",
    "officer", "support", "supervisor", "teacher", "technician", "user", "worker",
    "attendant", "crew", "passenger", "personnel", "staff", "traveler", "traveller",
})
_DEVICE_ACTOR_MARKERS = frozenset({
    "controller", "device", "drone", "gateway", "instrument", "kiosk",
    "meter", "robot", "sensor", "terminal",
})
_EVENT_SOURCE_MARKERS = frozenset({"event", "feed", "stream", "telemetry"})
_MACHINE_ACTOR_MARKERS = frozenset({
    "automation", "bot", "daemon", "job", "scheduler", "worker-process",
})
_EXTERNAL_SYSTEM_MARKERS = frozenset({
    "api", "crm", "erp", "gateway", "idp", "oauth", "processor", "sso",
    "service", "software", "system", "webhook",
})
_EXTERNAL_PARTNER_MARKERS = frozenset({
    "broker", "carrier", "distributor", "manufacturer", "partner", "provider",
    "retailer", "supplier", "vendor", "wholesaler",
})
_ORGANIZATIONAL_ACTOR_MARKERS = frozenset({
    "agency", "authority", "branch", "business", "company", "department",
    "division", "facility", "organization", "plant", "team", "warehouse",
})


def is_known(value: str | None) -> bool:
    return bool(value and " ".join(value.split()).casefold() not in _UNKNOWN_VALUES)


def clarification_category(key: str, question: str = "") -> str:
    haystack = f"{key} {question}".casefold().replace("_", " ")
    for category, markers in _CATEGORY_RULES:
        if any(marker in haystack for marker in markers):
            return category
    return "domain"


def split_semantic_items(value: str) -> list[str]:
    """Split explicit lists only; preserve prose and conjunctions in sentences."""
    value = value.replace("•", "\n")
    normalized = " ".join(value.split())
    if not normalized:
        return []
    if re.search(r"[;\n]", value):
        parts = re.split(r"\s*[;\n]+\s*", value)
    else:
        parts = [normalized]
    return [
        " ".join(re.sub(r"^[-*]\s*", "", part).split()).strip(" .")
        for part in parts
        if len(re.sub(r"^[-*]\s*", "", part).strip(" .")) >= 2
    ]


def _split_integration_items(value: str) -> list[str]:
    explicit = split_semantic_items(value)
    if len(explicit) != 1 or "," not in value:
        return explicit
    comma_parts = [" ".join(part.split()).strip(" .") for part in value.split(",")]
    # Commas represent a system list only when every item is name-like. Long
    # prose remains one complete integration description.
    if 1 < len(comma_parts) <= 12 and all(0 < len(part.split()) <= 7 for part in comma_parts):
        return comma_parts
    return explicit


def _consumers(category: str) -> list[str]:
    return {
        "integrations": ["integrations", "APIs", "architecture", "deployment"],
        "technical-data": ["technical characteristics", "integrations", "APIs", "data model"],
        "availability": ["NFRs", "architecture scoring", "deployment", "rationale"],
        "security": ["security model", "APIs", "integrations", "deployment"],
        "scale": ["NFRs", "architecture scoring", "deployment"],
        "retention": ["technical characteristics", "data model", "compliance", "deployment"],
        "regional": ["project profile", "deployment", "data locality"],
    }.get(category, ["requirements"])


def _evidence(key: str, answer: str, *, status: str = "confirmed") -> SourceEvidence:
    return SourceEvidence(
        source_id=f"CL-{key.upper().replace('_', '-')}",
        source=f"clarification {key}",
        status=status,  # type: ignore[arg-type]
        excerpt=answer,
    )


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    lower = text.casefold()
    return any(marker in lower for marker in markers)


def _extract_protocols(value: str) -> list[str]:
    return [
        item for item in _PROTOCOLS
        if re.search(
            rf"(?<![a-z0-9]){re.escape(item)}{'s?' if item == 'Webhook' else ''}(?![a-z0-9])",
            value,
            re.I,
        )
    ]


def _extract_formats(value: str) -> list[str]:
    return [
        item for item in _FORMATS
        if re.search(rf"(?<![a-z0-9]){re.escape(item)}(?![a-z0-9])", value, re.I)
    ]


def _integration_name(item: str) -> str:
    cleaned = re.sub(
        r"^(?:user-specified\s+)?(?:external/legacy\s+integration:\s*)",
        "",
        item.strip(),
        flags=re.I,
    )
    cleaned = re.sub(r"^(?:and|or)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(?:the\s+)?(?:legacy|existing|external)\s+", "", cleaned, flags=re.I)
    # A technical clarification may use "System A uses REST/JSON". Keep the
    # boundary name, not the transport sentence, as the actor/integration id.
    cleaned = re.split(
        r"\s+(?:uses?|via|over|through|exchanges?|sends?|receives?)\s+",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0]
    cleaned = re.sub(r"\b(?:platform|software)\b$", "", cleaned, flags=re.I).strip()
    if len(cleaned.split()) > 8 or re.search(
        r"\b(?:owns?|allows?|requires?|supports?|integrates?|exchanges?)\b",
        cleaned,
        flags=re.I,
    ):
        return ""
    return cleaned or item.strip()


def _integration_key(name: str) -> str:
    return " ".join(
        singularize(token)
        for token in tokenize(name)
        if token not in {"external", "integration", "platform", "software", "system", "systems"}
    )


def _integration_mode(value: str) -> str:
    lower = value.casefold()
    if re.search(r"\b(?:webhooks?|events?|event-driven|streams?|async|asynchronous)\b", lower):
        return "asynchronous"
    if re.search(r"\b(?:batch|csv|edi|sftp|nightly)\b", lower):
        return "batch"
    if re.search(r"\b(?:rest|graphql|grpc|soap|request)\b", lower):
        return "synchronous"
    return "unknown"


def _security_model(text: str, evidence: list[SourceEvidence]) -> SecurityModel:
    found = [label for label, markers in _SECURITY_MARKERS.items() if _contains_marker(text, markers)]
    lower = text.casefold()
    human = [item for item in found if item in {"SSO", "OAuth2/OIDC", "MFA"}]
    service = [item for item in found if item in {"mTLS", "Service credentials", "OAuth2/OIDC"}]
    authorization = [item for item in found if item in {"RBAC", "Fine-grained authorization"}]
    partner = [item for item in found if item in {"mTLS", "Service credentials", "OAuth2/OIDC"}]
    data_protection = [item for item in found if item == "Encryption at rest and in transit"]
    return SecurityModel(
        human_authentication=human,
        service_authentication=service,
        partner_authentication=partner,
        authorization=authorization,
        data_protection=data_protection,
        source_evidence=evidence if found else [],
    )


def _semantic_entity_attributes(
    name: str,
    evidence_text: str,
    entity_names: list[str],
) -> list[str]:
    """Derive record attributes from project phrases, without domain templates."""
    entity_key = singularize(tokenize(name)[-1]) if tokenize(name) else ""
    if not entity_key:
        return []
    attributes: list[str] = []
    property_blocklist = {
        "and", "or", "across", "with", "while", "system", "platform",
        "manage", "support", "process", "processing", "coordinate", "operation",
        "through", "using", "use", "without", "must", "should", "can",
        "search", "make", "check", "receive", "track", "view", "book", "send",
        "create", "update", "approve", "assign", "schedule", "record",
    }
    for sentence in re.split(r"[.;]", evidence_text):
        if not re.search(rf"\b{re.escape(entity_key)}(?:s|es)?\b", sentence, re.I):
            continue
        for match in re.finditer(
            rf"\b{re.escape(entity_key)}(?:s|es)?\s+([a-z][a-z-]+)",
            sentence,
            re.I,
        ):
            prop = singularize(match.group(1))
            if (
                prop not in property_blocklist
                and prop not in {entity_key, "must", "can", "should"}
                and len(prop) > 2
            ):
                attributes.append(prop.replace("-", "_"))
        if re.search(r"\b(?:manage|create|update|track|process|approve|assign|schedule|book|record)\w*\b", sentence, re.I):
            attributes.extend(["status", "created_at", "updated_at"])

    # Compound evidence such as "passenger bookings" or "device readings"
    # creates an ownership reference on the record named by the head noun.
    for other_name in entity_names:
        other_tokens = tokenize(other_name)
        if not other_tokens or other_name.casefold() == name.casefold():
            continue
        other_key = singularize(other_tokens[-1])
        if re.search(
            rf"\b{re.escape(other_key)}(?:s|es)?\s+{re.escape(entity_key)}(?:s|es)?\b",
            evidence_text,
            re.I,
        ):
            attributes.append(f"{other_key}_id")
    return list(dict.fromkeys(attributes))[:10]


def _purpose_from_integration_text(raw: str) -> str:
    if ":" not in raw:
        return "Purpose not specified in the brief."
    purpose = raw.split(":", 1)[1]
    purpose = re.split(r"\b(?:Ownership|Protocol|Formats?|Sync):", purpose, maxsplit=1, flags=re.I)[0]
    purpose = purpose.strip(" .")
    return purpose.rstrip(".") + "." if purpose else "Purpose not specified in the brief."


def classify_actor(actor: Actor, integrations: list[IntegrationDetail]) -> str:
    """Classify an actor from its full evidence, never from its name alone.

    Specific machine/system evidence wins over generic human nouns. Ambiguous
    participants remain unknown instead of being silently labelled as people.
    """
    text = " ".join([actor.name, actor.description, *actor.responsibilities]).casefold()
    tokens = set(tokenize(text))
    name_tokens = set(tokenize(actor.name))
    named_integration = bool(_integration_key(actor.name)) and any(
        _integration_key(actor.name) == _integration_key(integration.name)
        for integration in integrations
    )

    # Name-level evidence establishes identity. Words in a responsibility
    # describe what the actor touches and must not change who it is (an
    # Operations Team that uses an ERP remains an organization, not a system).
    if actor.actor_type == "external-partner" or name_tokens & _EXTERNAL_PARTNER_MARKERS:
        return "external-partner"
    if named_integration:
        return "external-system"
    if name_tokens & _EVENT_SOURCE_MARKERS and not name_tokens & _HUMAN_ACTOR_MARKERS:
        return "event-source"
    if name_tokens & _HUMAN_ACTOR_MARKERS:
        return "human"
    if name_tokens & _DEVICE_ACTOR_MARKERS:
        # Gateways named as external integrations are software/system actors;
        # physical gateways, sensors, and instruments are devices.
        if "gateway" in name_tokens and name_tokens & _EXTERNAL_SYSTEM_MARKERS - {"gateway"}:
            return "external-system"
        return "device"
    if name_tokens & _MACHINE_ACTOR_MARKERS or "ai agent" in actor.name.casefold():
        return "machine"
    if name_tokens & _ORGANIZATIONAL_ACTOR_MARKERS:
        return "organizational"
    if (
        name_tokens & _EXTERNAL_SYSTEM_MARKERS
        or any(phrase in text for phrase in ("identity provider", "payment provider", "external platform"))
    ):
        return "external-system"
    if actor.actor_type != "unknown":
        return actor.actor_type
    return "unknown"


def _parse_number(value: str, pattern: str) -> int | None:
    match = re.search(pattern, value, flags=re.I)
    if not match:
        return None
    base = int(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").casefold()
    return base * (1_000_000 if suffix in {"m", "million", "millions"} else 1_000 if suffix in {"k", "thousand"} else 1)


def _profile(requirements: RequirementModel, answers: dict[str, str]) -> ProjectProfile:
    source = " ".join([
        *requirements.functional_requirements,
        *requirements.non_functional_requirements,
        *requirements.constraints,
        *requirements.data_characteristics,
        *answers.values(),
    ])
    team_match = re.search(r"\d+", answers.get("team_size", ""))
    team_size = int(team_match.group()) if team_match else None
    concurrency = _parse_number(source, r"(\d[\d,]*)\s*(k|m|thousand|million|millions)?\s*\+?\s*(?:concurrent\s+)?(?:users|sessions|connections)")
    events = _parse_number(source, r"(\d[\d,]*)\s*(k|m|thousand|million|millions)?\s*(?:\+?\s*)?(?:[a-z-]+\s+){0,2}(?:events?|transactions?|messages?)\s*(?:/|per\s*)(?:day|daily)")
    availability = parse_availability_percent(answers.get("sla"), source)
    region_count = parse_region_count(answers.get("geographic_regions", ""), source)
    global_scope = bool(region_count and region_count > 1) or bool(re.search(r"\bglobal|multi-region|multiple countries|international", source, re.I))
    integration_count = len(requirements.integration_details) or len(requirements.integrations)
    regulated = bool(re.search(r"\bhipaa|pci|gdpr|kyc|aml|regulated|compliance\b", source, re.I))
    critical = bool(availability and availability >= SCALE_THRESHOLDS["mission_critical_availability"]) or bool(re.search(r"mission[ -]critical|life[ -]critical", source, re.I))
    event_heavy = bool(events and events >= SCALE_THRESHOLDS["high_event_volume_per_day"]) or bool(re.search(r"event[- ]driven|streaming|real[- ]time", source, re.I))

    if global_scope and (critical or concurrency and concurrency >= SCALE_THRESHOLDS["enterprise_concurrent_users"] or events):
        classification = "globally distributed / mission-critical"
    elif (team_size or 0) >= SCALE_THRESHOLDS["large_team"] or (concurrency or 0) >= SCALE_THRESHOLDS["enterprise_concurrent_users"] or integration_count >= SCALE_THRESHOLDS["large_integration_count"]:
        classification = "large-scale enterprise"
    elif global_scope or (concurrency or 0) >= SCALE_THRESHOLDS["growth_concurrent_users"] or (team_size or 0) >= SCALE_THRESHOLDS["enterprise_team"]:
        classification = "enterprise"
    elif team_size or concurrency or integration_count:
        classification = "departmental"
    else:
        classification = "small/local"

    evidence = [
        _evidence(key, value)
        for key, value in answers.items()
        if is_known(value) and clarification_category(key) in {"scale", "availability", "regional", "integrations", "security"}
    ]
    return ProjectProfile(
        classification=classification,
        team_size=team_size,
        concurrent_users=concurrency,
        event_volume_per_day=events,
        geographic_scope="global/multi-region" if global_scope else "local or unspecified",
        criticality="mission-critical" if critical else "standard",
        integration_complexity="high" if integration_count >= SCALE_THRESHOLDS["large_integration_count"] else "moderate" if integration_count >= 2 else "low",
        availability_target_percent=availability,
        workload_variability="event-heavy" if event_heavy else "unknown",
        data_complexity="high" if event_heavy or regulated else "moderate" if requirements.data_characteristics else "unknown",
        regulatory_sensitivity="high" if regulated else "unknown",
        source_evidence=evidence,
    )


def _confidence(requirements: RequirementModel, answers: dict[str, str], profile: ProjectProfile) -> ConfidenceReport:
    known = [key for key, value in answers.items() if is_known(value)]
    explicit = len(known)
    unresolved = len(requirements.open_questions)
    represented_areas = sum((
        requirements.domain.casefold() not in {"unknown", "unknown domain"},
        len(requirements.functional_requirements) >= 3,
        len(requirements.actors) >= 2,
        len(requirements.domain_entities) >= 3,
        len(requirements.domain_workflows) >= 2,
        bool(requirements.non_functional_requirements),
        bool(requirements.constraints),
        bool(requirements.integrations or requirements.integration_details),
        bool(requirements.data_characteristics or requirements.technical_characteristics),
        any((profile.concurrent_users, profile.event_volume_per_day, profile.availability_target_percent)),
    ))
    input_score = min(
        100,
        CONFIDENCE_THRESHOLDS["input_base"]
        + represented_areas * CONFIDENCE_THRESHOLDS["input_area_points"]
        + min(
            CONFIDENCE_THRESHOLDS["explicit_input_cap"],
            explicit * CONFIDENCE_THRESHOLDS["explicit_input_points"],
        ),
    )
    inference = (
        CONFIDENCE_THRESHOLDS["blueprint_inference_base"]
        if requirements.analysis_source == "predefined-blueprint"
        else CONFIDENCE_THRESHOLDS["model_inference_base"]
        if requirements.analysis_source == "ollama-pretrained"
        else CONFIDENCE_THRESHOLDS["deterministic_inference_base"]
    )
    inference -= min(30, unresolved * CONFIDENCE_THRESHOLDS["unresolved_inference_penalty"])
    if requirements.domain.casefold() in {"unknown", "unknown domain"}:
        inference -= CONFIDENCE_THRESHOLDS["unknown_domain_penalty"]
    source_text = " ".join([
        *requirements.non_functional_requirements,
        *requirements.constraints,
        *answers.values(),
    ])
    availability_values = {
        match.group(1)
        for match in re.finditer(r"(9\d(?:\.\d+)?)\s*%", source_text)
    }
    contradictions = 1 if len(availability_values) > 1 else 0
    inference -= contradictions * CONFIDENCE_THRESHOLDS["contradiction_inference_penalty"]
    architecture = (
        CONFIDENCE_THRESHOLDS["architecture_base"]
        + round(input_score * CONFIDENCE_THRESHOLDS["architecture_input_factor"])
        + (
            CONFIDENCE_THRESHOLDS["known_scale_bonus"]
            if profile.classification not in {"unknown", "small/local"}
            else 0
        )
    )
    architecture -= min(20, unresolved * CONFIDENCE_THRESHOLDS["unresolved_architecture_penalty"])
    architecture -= contradictions * CONFIDENCE_THRESHOLDS["contradiction_architecture_penalty"]
    rationale = [
        f"{represented_areas} decision-relevant area(s) are represented; optional empty fields do not count as defects.",
        f"{explicit} clarification or project input area(s) are explicitly confirmed.",
        f"{unresolved} unresolved clarification(s) reduce inference certainty without discarding confirmed facts.",
    ]
    if contradictions:
        rationale.append("Conflicting availability values reduce inference and architecture confidence until resolved.")
    return ConfidenceReport(
        input_completeness=max(0, min(100, input_score)),
        inference_confidence=max(0, min(100, inference)),
        architecture_confidence=max(0, min(100, architecture)),
        rationale=rationale,
    )


def hydrate_project_signals(
    requirements: RequirementModel,
    answers: dict[str, str] | None,
    questions: dict[str, str] | None = None,
) -> RequirementModel:
    """Return a deep-copied requirement model with canonical typed signals.

    The stable clarification key is the identity.  Re-running this function
    replaces derived values for that key, which prevents stale artifacts while
    retaining facts from prior answers in the same project.
    """
    updated = requirements.model_copy(deep=True)
    answers = answers or {}
    questions = questions or {}
    confirmed = [
        StructuredClarification(
            question_id=key,
            category=clarification_category(key, questions.get(key, "")),
            answer=" ".join(value.split()),
            source_evidence=[_evidence(key, " ".join(value.split()))],
            downstream_consumers=_consumers(clarification_category(key, questions.get(key, ""))),
        )
        for key, value in sorted(answers.items())
        if is_known(value)
    ]
    updated.clarification_answers = confirmed

    requirement_text = " ".join([
        *updated.functional_requirements,
        *updated.non_functional_requirements,
        *updated.constraints,
        *updated.data_characteristics,
        *updated.integrations,
    ])
    all_security_text = " ".join([
        requirement_text,
        *(answer.answer for answer in confirmed if answer.category == "security"),
    ])
    security_evidence = [
        evidence for answer in confirmed if answer.category == "security" for evidence in answer.source_evidence
    ]
    if any(_contains_marker(requirement_text, markers) for markers in _SECURITY_MARKERS.values()):
        security_evidence.append(SourceEvidence(
            source_id="REQ-SECURITY",
            source="confirmed project requirement",
            status="confirmed",
        ))
    updated.security_model = _security_model(all_security_text, security_evidence)

    formats = [
        answer for answer in confirmed if answer.category == "technical-data"
    ]
    integration_answers = [
        answer for answer in confirmed if answer.category == "integrations"
    ]
    security = [*updated.security_model.service_authentication, *updated.security_model.partner_authentication]
    reliability = [
        answer.answer
        for answer in confirmed
        if answer.category == "availability"
    ]
    details_by_name: dict[str, IntegrationDetail] = {}
    for raw in updated.integrations:
        if raw.casefold().startswith("user-specified external/legacy integration:"):
            continue
        name = _integration_name(raw.split(":", 1)[0])
        identity = _integration_key(name)
        if name and identity:
            existing = details_by_name.get(identity)
            if existing is None:
                details_by_name[identity] = IntegrationDetail(
                    id=f"INT-{len(details_by_name) + 1:03d}", name=name,
                    purpose=_purpose_from_integration_text(raw),
                    protocol=_extract_protocols(raw), data_formats=_extract_formats(raw),
                    interaction_mode=_integration_mode(raw), security_mechanisms=list(dict.fromkeys(security)),
                    reliability_requirements=list(dict.fromkeys(reliability)),
                    source_evidence=[SourceEvidence(source_id="REQ-INTEGRATIONS", source="requirement extraction")],
                )
            else:
                existing.protocol = list(dict.fromkeys([*existing.protocol, *_extract_protocols(raw)]))
                existing.data_formats = list(dict.fromkeys([*existing.data_formats, *_extract_formats(raw)]))
                mode = _integration_mode(raw)
                if existing.interaction_mode == "unknown" and mode != "unknown":
                    existing.interaction_mode = mode  # type: ignore[assignment]
                if existing.purpose.startswith("Purpose not specified"):
                    existing.purpose = _purpose_from_integration_text(raw)
    for answer in integration_answers:
        for item in _split_integration_items(answer.answer):
            name = _integration_name(item)
            if not name:
                continue
            key = _integration_key(name)
            if not key:
                continue
            existing = details_by_name.get(key)
            if existing is None:
                existing = IntegrationDetail(
                    id=f"INT-{len(details_by_name) + 1:03d}", name=name,
                    purpose=_purpose_from_integration_text(item),
                    protocol=_extract_protocols(item), data_formats=_extract_formats(item),
                    interaction_mode=_integration_mode(item), security_mechanisms=list(dict.fromkeys(security)),
                    reliability_requirements=list(dict.fromkeys(reliability)),
                    source_evidence=list(answer.source_evidence),
                )
                details_by_name[key] = existing
            else:
                existing.source_evidence = [*existing.source_evidence, *answer.source_evidence]
                existing.security_mechanisms = list(dict.fromkeys([*existing.security_mechanisms, *security]))
                existing.reliability_requirements = list(dict.fromkeys([*existing.reliability_requirements, *reliability]))

    # Technical clarification details belong on IntegrationDetail, with
    # source evidence. If an answer names a boundary, apply only its segment
    # to that boundary; otherwise the answer is a global contract default.
    all_details = list(details_by_name.values())
    for answer in formats:
        segments = split_semantic_items(answer.answer) or [answer.answer]
        for segment in segments:
            named_targets = [
                detail for detail in all_details
                if detail.name.casefold() in segment.casefold()
            ]
            answer_names_a_boundary = any(
                detail.name.casefold() in answer.answer.casefold()
                for detail in all_details
            )
            targets = named_targets or ([] if answer_names_a_boundary else all_details)
            segment_protocols = _extract_protocols(segment)
            segment_formats = _extract_formats(segment)
            segment_mode = _integration_mode(segment)
            for detail in targets:
                detail.protocol = list(dict.fromkeys([*detail.protocol, *segment_protocols]))
                detail.data_formats = list(dict.fromkeys([*detail.data_formats, *segment_formats]))
                if segment_mode != "unknown":
                    detail.interaction_mode = segment_mode  # type: ignore[assignment]
                detail.source_evidence = list({
                    evidence.source_id: evidence
                    for evidence in [*detail.source_evidence, *answer.source_evidence]
                }.values())

    updated.integration_details = list(details_by_name.values())
    # Avoid bare/short duplicates: if a structured entry already covers the
    # same boundary (e.g. "ERP: system-of-record ... Ownership: ..."), do not
    # append the short "ERP" alongside it.
    def _integration_covered(short: str, existing: list[str]) -> bool:
        short_tokens = {t for t in tokenize(short) if len(t) > 2}
        for item in existing:
            item_tokens = {t for t in tokenize(item) if len(t) > 2}
            if short_tokens and short_tokens <= item_tokens:
                return True
            if short.casefold() in item.casefold():
                return True
        return False

    merged_integrations: list[str] = []
    seen_integration_keys: set[str] = set()
    for item in updated.integrations:
        if item.casefold().startswith("user-specified external/legacy integration:"):
            continue
        key = _integration_key(_integration_name(item.split(":", 1)[0]))
        if key and key in seen_integration_keys:
            continue
        merged_integrations.append(item)
        if key:
            seen_integration_keys.add(key)
    for detail in updated.integration_details:
        if detail.name not in merged_integrations and not _integration_covered(detail.name, merged_integrations):
            merged_integrations.append(detail.name)
        # If the short name already exists but a richer structured entry
        # exists in details, replace the short form with the structured one.
        elif detail.name in merged_integrations:
            structured = next(
                (d for d in updated.integrations if detail.name.casefold() in d.casefold() and len(d) > len(detail.name)),
                None,
            )
            if structured is None:
                # Keep short name only when no richer entry exists.
                pass
    updated.integrations = list(dict.fromkeys(merged_integrations))

    technical: list[TechnicalCharacteristic] = []
    for answer in confirmed:
        if answer.category == "technical-data":
            for protocol in _extract_protocols(answer.answer):
                technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="protocol", value=protocol, status="confirmed", source_evidence=answer.source_evidence))
            for format_name in _extract_formats(answer.answer):
                technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="data-format", value=format_name, status="confirmed", source_evidence=answer.source_evidence))
            recognized_detail = False
            for category, pattern in (
                ("interaction-mode", r"\b(?:webhooks?|events?|event-driven|synchronous|asynchronous|sync|async)\b"),
                ("consistency", r"\b(?:strong|eventual) consistency\b"),
                ("data-locality", r"\b(?:data residency|data locality|in-country storage)\b"),
                ("delivery-semantics", r"\b(?:idempotent|safe retr(?:y|ies)|duplicate prevention|exactly-once|at-least-once)\b"),
            ):
                for match in re.finditer(pattern, answer.answer, flags=re.I):
                    recognized_detail = True
                    technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category=category, value=match.group(0), status="confirmed", source_evidence=answer.source_evidence))
            if not _extract_protocols(answer.answer) and not _extract_formats(answer.answer) and not recognized_detail:
                technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="technical-data", value=answer.answer, status="confirmed", source_evidence=answer.source_evidence))
        elif answer.category == "retention":
            technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="retention", value=answer.answer, status="confirmed", source_evidence=answer.source_evidence))
        elif answer.category == "scale":
            technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="scale", value=answer.answer, status="confirmed", source_evidence=answer.source_evidence))
    requirement_evidence = [SourceEvidence(
        source_id="REQ-TECHNICAL",
        source="confirmed project requirement",
        status="confirmed",
    )]
    for protocol in _extract_protocols(requirement_text):
        technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="protocol", value=protocol, status="confirmed", source_evidence=requirement_evidence))
    for format_name in _extract_formats(requirement_text):
        technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="data-format", value=format_name, status="confirmed", source_evidence=requirement_evidence))
    for category, pattern in (
        ("interaction-mode", r"\b(?:webhooks?|events?|event-driven|synchronous|asynchronous|sync|async)\b"),
        ("retention", r"\b\d+\s*(?:-|to)?\s*\d*\s*(?:years?|months?)\s+(?:retention|archive|history)\b"),
        ("consistency", r"\b(?:strong|eventual) consistency\b"),
        ("data-locality", r"\b(?:data residency|data locality|in-country storage)\b"),
    ):
        for match in re.finditer(pattern, requirement_text, flags=re.I):
            value = match.group(0)
            if category == "interaction-mode" and value.casefold() in {"event", "events", "event-driven", "webhook", "webhooks", "async"}:
                value = "asynchronous events"
            elif category == "interaction-mode" and value.casefold() == "sync":
                value = "synchronous"
            technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category=category, value=value, status="confirmed", source_evidence=requirement_evidence))
    for value in updated.data_characteristics:
        technical.append(TechnicalCharacteristic(id=f"DATA-{len(technical)+1:03d}", category="inferred", value=value, status="inferred", source_evidence=[SourceEvidence(source_id="REQ-DATA", source="requirement extraction")]))
    unique_technical: dict[tuple[str, str], TechnicalCharacteristic] = {}
    for item in technical:
        unique_technical[(item.category.casefold(), item.value.casefold())] = item
    updated.technical_characteristics = list(unique_technical.values())
    updated.data_characteristics = list(dict.fromkeys([
        *[value for value in updated.data_characteristics if not value.casefold().startswith("confirmed ")],
        *(f"Confirmed {item.category}: {item.value}." for item in updated.technical_characteristics if item.status == "confirmed"),
    ]))

    # External software belongs in Integrations, not in the people/roles actor
    # list. Also clean old generated snapshots that promoted every boundary to
    # an actor before this invariant existed.
    integration_keys = {_integration_key(item.name) for item in updated.integration_details}
    updated.actors = [
        actor for actor in updated.actors
        if actor.actor_type != "external-system"
        and _integration_key(actor.name) not in integration_keys
    ]

    # Domain clarifications can explicitly name missing participants and their
    # actions. They are trusted actor evidence, but never become entities or
    # integrations merely because they contain technical words.
    existing_actor_names = {actor.name.casefold() for actor in updated.actors}
    for answer in confirmed:
        if answer.category != "domain":
            continue
        for name, kind in extract_actors(answer.answer, limit=12):
            if kind == "external-system":
                continue
            name_tokens = {singularize(token) for token in tokenize(name)}
            evidence_clause = next((
                part.strip()
                for part in split_semantic_items(answer.answer)
                if name_tokens <= {singularize(token) for token in tokenize(part)}
            ), answer.answer)
            existing_actor = next((
                actor for actor in updated.actors
                if actor.name.casefold() == name.casefold()
            ), None)
            if existing_actor is not None:
                existing_actor.description = evidence_clause.rstrip(".") + "."
                existing_actor.responsibilities = list(dict.fromkeys([
                    *existing_actor.responsibilities,
                    evidence_clause.rstrip(".") + ".",
                ]))
                existing_actor.source_evidence = list({
                    item.source_id: item
                    for item in [*existing_actor.source_evidence, *answer.source_evidence]
                }.values())
                continue
            updated.actors.append(Actor(
                name=name,
                description=evidence_clause.rstrip(".") + ".",
                actor_type=kind if kind in {
                    "human", "organizational", "external-partner", "device",
                    "event-source", "machine", "unknown",
                } else "unknown",  # type: ignore[arg-type]
                responsibilities=[evidence_clause.rstrip(".") + "."],
                source_evidence=list(answer.source_evidence),
            ))
            existing_actor_names.add(name.casefold())

    # Add source and useful role/entity metadata without overwriting manual detail.
    for index, actor in enumerate(updated.actors, start=1):
        actor.id = actor.id or f"ACT-{index:03d}"
        actor_tokens = {token for token in tokenize(actor.name) if len(token) > 2}
        workflow_responsibilities = list(dict.fromkeys([
            workflow.description
            for workflow in updated.domain_workflows
            if actor_tokens & set(tokenize(f"{workflow.primary_actor} {workflow.description}"))
        ]))
        if workflow_responsibilities and (
            not actor.responsibilities or actor.responsibilities == [actor.description]
        ):
            actor.responsibilities = workflow_responsibilities
        elif not actor.responsibilities:
            actor.responsibilities = [actor.description]
        actor.source_evidence = actor.source_evidence or [SourceEvidence(
            source_id=f"ACT-{index:03d}",
            source="actor inferred during requirement extraction",
            status="inferred",
        )]
        actor.actor_type = classify_actor(actor, updated.integration_details)  # type: ignore[assignment]
    for index, entity in enumerate(updated.domain_entities, start=1):
        entity.id = entity.id or f"ENT-{index:03d}"
        entity.source_evidence = entity.source_evidence or [SourceEvidence(source_id=f"ENT-{index:03d}", source="requirement extraction")]
        evidence_text = " ".join([
            requirement_text,
            *(workflow.description for workflow in updated.domain_workflows),
        ])
        entity.attributes = list(dict.fromkeys([
            *entity.attributes,
            *_semantic_entity_attributes(
                entity.name,
                evidence_text,
                [item.name for item in updated.domain_entities],
            ),
        ]))
        if not entity.lifecycle_fields and re.search(r"track|manage|process|approve|deliver|ship|transfer|record", entity.description, re.I):
            entity.lifecycle_fields = ["status", "created_at", "updated_at"]

    contexts: dict[str, BoundedContext] = {}
    entity_lookup = {entity.name.casefold(): entity for entity in updated.domain_entities}
    context_assignments = cluster_entities([entity.name for entity in updated.domain_entities])

    # Explicit reference fields reveal aggregate ownership more reliably than
    # vocabulary families. Merge only entities connected by those fields and
    # derive the context label from the actual business nouns.
    parents = {entity.name: entity.name for entity in updated.domain_entities}

    def find(name: str) -> str:
        while parents[name] != name:
            parents[name] = parents[parents[name]]
            name = parents[name]
        return name

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    singular_names = {
        singularize(tokenize(entity.name)[-1]): entity.name
        for entity in updated.domain_entities
        if tokenize(entity.name)
    }
    for entity in updated.domain_entities:
        for attribute in entity.attributes:
            if not attribute.endswith("_id"):
                continue
            target = singular_names.get(singularize(attribute[:-3].split("_")[-1]))
            if target and target != entity.name:
                union(entity.name, target)
    ownership_groups: dict[str, list[str]] = {}
    for entity in updated.domain_entities:
        ownership_groups.setdefault(find(entity.name), []).append(entity.name)
    for group in ownership_groups.values():
        if 1 < len(group) <= 4:
            label = " and ".join(group)
            for name in group:
                context_assignments[name] = label

    for entity in updated.domain_entities:
        context_name = context_assignments.get(entity.name, entity.name) or "Core Operations"
        entity.bounded_context = context_name
        if "identified from" in entity.description.casefold():
            attribute_summary = ", ".join(entity.attributes[:5]) or "attributes requiring clarification"
            entity.description = (
                f"{entity.name} is owned by the {context_name} bounded context; "
                f"evidence-derived fields include {attribute_summary}."
            )
        if not entity.lifecycle_fields and "status" in entity.attributes:
            entity.lifecycle_fields = [
                field for field in ("status", "created_at", "updated_at")
                if field in entity.attributes
            ]
        key = context_name.casefold()
        context = contexts.setdefault(key, BoundedContext(
            id=f"CTX-{len(contexts) + 1:03d}",
            name=context_name,
            source_evidence=[SourceEvidence(
                source_id=entity.id or "REQ-ENTITY",
                source="domain entity ownership",
                status="inferred",
            )],
        ))
        context.owned_entities = list(dict.fromkeys([*context.owned_entities, entity.name]))
        context.responsibilities = list(dict.fromkeys([*context.responsibilities, entity.description]))

    for index, workflow in enumerate(updated.domain_workflows, start=1):
        workflow_tokens = set(tokenize(f"{workflow.name} {workflow.description}"))
        if workflow_tokens & {"fraud", "assess", "assessment", "score", "scoring"}:
            assessment = next((
                entity.name for entity in updated.domain_entities
                if set(tokenize(entity.name)) & {"risk", "fraud", "assessment"}
            ), None)
            if assessment:
                workflow.related_entities = list(dict.fromkeys([assessment, *workflow.related_entities]))
        related_contexts = list(dict.fromkeys(
            entity_lookup[entity_name.casefold()].bounded_context
            for entity_name in workflow.related_entities
            if entity_name.casefold() in entity_lookup
            and entity_lookup[entity_name.casefold()].bounded_context
        ))
        if related_contexts:
            context_name = max(
                related_contexts,
                key=lambda name: len(
                    workflow_tokens
                    & set(tokenize(" ".join([
                        name,
                        *contexts[name.casefold()].owned_entities,
                        *contexts[name.casefold()].responsibilities,
                    ])))
                ),
            )
        else:
            context_name = "Core Operations"
        key = context_name.casefold()
        context = contexts.setdefault(key, BoundedContext(
            id=f"CTX-{len(contexts) + 1:03d}",
            name=context_name,
            source_evidence=[SourceEvidence(source_id=f"WF-{index:03d}", source="business workflow", status="inferred")],
        ))
        context.responsibilities = list(dict.fromkeys([*context.responsibilities, workflow.description]))
        if not any(item.source_id == f"WF-{index:03d}" for item in context.source_evidence):
            context.source_evidence.append(SourceEvidence(source_id=f"WF-{index:03d}", source="business workflow", status="inferred"))
        primary_tokens = {token for token in tokenize(workflow.primary_actor) if len(token) > 2}
        for actor in updated.actors:
            actor_tokens = {token for token in tokenize(actor.name) if len(token) > 2}
            if actor.name.casefold() == workflow.primary_actor.casefold() or (primary_tokens and primary_tokens == actor_tokens):
                actor.owning_boundary = actor.owning_boundary or context_name
                actor.permissions = list(dict.fromkeys([*actor.permissions, f"Perform {workflow.name}"]))
    for integration in updated.integration_details:
        context_noise = {
            "system", "systems", "support", "purpose", "specified", "brief",
            "information", "data", "external", "integration", "unknown",
        }
        integration_tokens = set(tokenize(f"{integration.name} {integration.purpose}")) - context_noise
        matched = next((
            context for context in contexts.values()
            if integration_tokens & (
                set(tokenize(" ".join([context.name, *context.responsibilities, *context.owned_entities])))
                - context_noise
            )
        ), None)
        if matched:
            integration.bounded_context = matched.name
            matched.integrations = list(dict.fromkeys([*matched.integrations, integration.name]))
        else:
            integration.bounded_context = integration.bounded_context or "External Integration"

    # Actors mentioned in longer multi-role sentences may not be the primary
    # actor of one of the display-limited workflow hints. Assign those roles
    # to the context whose evidenced responsibilities overlap most strongly.
    for actor in updated.actors:
        actor_tokens = {
            singularize(token) for token in tokenize(
                " ".join([actor.name, actor.description, *actor.responsibilities])
            )
            if len(token) > 3
        }
        scored = [
            (
                len(actor_tokens & {
                    singularize(token) for token in tokenize(
                        " ".join([context.name, *context.responsibilities, *context.owned_entities])
                    )
                    if len(token) > 3
                }),
                context,
            )
            for context in contexts.values()
        ]
        if scored:
            score, context = max(scored, key=lambda item: (item[0], item[1].name))
            if score > 0:
                actor.owning_boundary = context.name
                actor.permissions = list(dict.fromkeys([
                    *actor.permissions,
                    f"Participate in {context.name} workflows",
                ]))
    if updated.integration_details and "external integration" not in contexts:
        external = [item.name for item in updated.integration_details if item.bounded_context == "External Integration"]
        if external:
            contexts["external integration"] = BoundedContext(
                id=f"CTX-{len(contexts) + 1:03d}",
                name="External Integration",
                responsibilities=["Own external contracts, adapters, retries, and reconciliation."],
                integrations=external,
                source_evidence=[SourceEvidence(source_id="REQ-INTEGRATIONS", source="integration requirements")],
            )
    updated.bounded_contexts = list(contexts.values())

    updated.project_profile = _profile(updated, answers)
    if updated.project_profile.classification in {"large-scale enterprise", "globally distributed / mission-critical"}:
        updated.scale_profile = "high-scale"
    elif updated.project_profile.classification == "enterprise":
        updated.scale_profile = "growth-scale"
    elif updated.project_profile.classification == "departmental" and updated.scale_profile == "unknown":
        # Departmental is based on an explicit team, integration, or traffic
        # signal.  A sparse/ambiguous brief remains honestly unknown.
        updated.scale_profile = "small-scale"
    updated.confidence = _confidence(updated, answers, updated.project_profile)
    return RequirementModel.model_validate(updated.model_dump())
