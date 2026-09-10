"""Deterministic API contracts derived from domain resources and boundaries."""

from __future__ import annotations

from app.schemas.domain import (
    ApiDesign,
    ApiEndpoint,
    ApiGroup,
    DatabaseDesign,
    DatabaseEntity,
    IntegrationDetail,
    RequirementModel,
    SourceEvidence,
)
from app.services.domain_inference import (
    auth_evidence,
    singularize,
    to_display_name,
    to_identifier,
    tokenize,
)


class ApiGenerator:
    """Build contracts from entities, lifecycle operations, and integrations.

    Requirement prose is used only for traceability and lifecycle intent; it is
    never converted directly into a URL or API group name.
    """

    _TRANSITION_VERBS = frozenset({
        "approve", "review", "cancel", "submit", "plan", "forecast",
        "schedule", "dispatch", "fulfill", "inspect", "register",
        "coordinate", "synchronize", "settle", "reconcile", "close",
        "activate", "deactivate", "assign", "release", "initiate",
        "authorize", "freeze", "unfreeze", "block", "assess", "score",
        "post", "verify", "submit", "export", "check", "board", "notify",
    })

    def generate(self, requirements: RequirementModel, database_design: DatabaseDesign) -> ApiDesign:
        if requirements.analysis_source == "conservative-fallback":
            return ApiDesign(
                style="Unknown; clarify domain resources and external protocols first",
                authentication_strategy="Unknown; clarify actors and trust boundaries first.",
                groups=[],
                validation_rules=[
                    "Do not publish endpoint contracts until domain commands and invariants are known."
                ],
                openapi_summary=["API design is intentionally deferred pending clarification."],
            )

        security = self._security_mechanisms(requirements)
        groups: list[ApiGroup] = []
        if self._auth_evidence(requirements) or security:
            groups.append(self._identity_group(requirements, security))
        groups.extend(self._domain_groups(requirements, database_design, security))
        groups.extend(self._integration_groups(requirements, security))

        has_events = any(
            endpoint.operation_type == "event"
            for group in groups
            for endpoint in group.endpoints
        )
        return ApiDesign(
            style="REST and asynchronous event contracts" if has_events else "REST",
            authentication_strategy=(
                ", ".join(security)
                if security
                else "Unknown; clarify human, partner, and service trust boundaries."
            ),
            groups=groups,
            validation_rules=[
                "Validate identifiers, payload types, lifecycle transitions, and domain invariants at the owning boundary.",
                "Require idempotency keys for retryable commands and externally delivered events.",
                "Define duplicate, late, and out-of-order handling for asynchronous contracts.",
                "Return structured errors with stable machine-readable codes.",
            ],
            openapi_summary=[
                "Endpoints are grouped by bounded context and domain resource.",
                "Every contract names its owner, operation type, security, and source requirement.",
                "External event contracts require correlation IDs, retries, dead-letter handling, and reconciliation.",
            ],
        )

    def _identity_group(self, requirements: RequirementModel, security: list[str]) -> ApiGroup:
        return ApiGroup(
            name="Identity and Access",
            description="Human authentication, service identity, and authorization contracts.",
            endpoints=[ApiEndpoint(
                method="POST",
                path="/api/v1/identity/sessions",
                purpose="Establish a human session using the confirmed identity mechanisms.",
                auth_required=False,
                request_description="Identity-provider assertion or credential exchange.",
                response_description="Short-lived access context with subject and authorization claims.",
                group="Identity and Access",
                resource="Identity Session",
                operation_type="command",
                owner="Identity and Access",
                service="Identity and Access",
                security_mechanisms=security,
                source_evidence=list(requirements.security_model.source_evidence),
            )],
        )

    def _domain_groups(
        self,
        requirements: RequirementModel,
        database_design: DatabaseDesign,
        security: list[str],
    ) -> list[ApiGroup]:
        entities = [
            entity for entity in database_design.entities
            if entity.name not in {"users", "audit_logs", "notifications"}
        ]
        by_context: dict[str, list[DatabaseEntity]] = {}
        for entity in entities:
            context = entity.bounded_context or f"{to_display_name(entity.name)} Management"
            by_context.setdefault(context, []).append(entity)

        groups: list[ApiGroup] = []
        for context, members in sorted(by_context.items()):
            endpoints: list[ApiEndpoint] = []
            for entity in members:
                endpoints.extend(self._resource_endpoints(requirements, entity, context, security))
            endpoints.extend(self._transition_endpoints(requirements, members, context, security))
            endpoints.extend(self._semantic_endpoints(requirements, members, context, security))
            endpoints = self._dedupe_endpoints(endpoints)
            if endpoints:
                groups.append(ApiGroup(
                    name=context,
                    description=(
                        f"{context} bounded context owns "
                        + ", ".join(to_display_name(entity.name) for entity in members)
                        + ". Contracts are emitted only for evidenced business operations."
                    ),
                    endpoints=endpoints,
                ))
        return groups

    def _resource_endpoints(
        self,
        requirements: RequirementModel,
        entity: DatabaseEntity,
        context: str,
        security: list[str],
    ) -> list[ApiEndpoint]:
        slug = self._collection_slug(entity.name)
        singular = self._singular_identifier(entity.name)
        resource = to_display_name(entity.name)
        requirement_ids = self._requirement_ids(requirements, entity.name, entity.description)
        evidence = [
            *entity.source_evidence,
            *self._requirement_evidence(requirements, requirement_ids),
        ]
        common = dict(
            auth_required=True if security or self._auth_evidence(requirements) else None,
            group=context,
            resource=resource,
            owner=context,
            service=context,
            requirement_ids=requirement_ids,
            security_mechanisms=security,
            source_evidence=evidence,
        )
        entity_key = singularize(to_identifier(entity.name))

        def targets_entity(workflow) -> bool:
            workflow_key = to_identifier(workflow.name)
            candidates = [
                singularize(to_identifier(related))
                for related in workflow.related_entities
                if singularize(to_identifier(related)) in workflow_key
            ]
            if not candidates:
                return False
            # Workflow labels are verb + object. The last matching entity is
            # the operated aggregate; earlier names often identify the actor.
            target = max(candidates, key=lambda item: workflow_key.rfind(item))
            return target == entity_key

        workflow_text = " ".join(
            workflow.description
            for workflow in requirements.domain_workflows
            if targets_entity(workflow)
        ).casefold()
        endpoints: list[ApiEndpoint] = []
        read_evidence = any(
            marker in workflow_text
            for marker in ("search", "browse", "list", "filter", "view", "track", "receive", "history", "report")
        )
        detail_evidence = read_evidence or any(
            marker in workflow_text
            for marker in ("manage", "update", "change", "approve", "assign", "schedule", "cancel")
        )
        create_evidence = any(
            marker in workflow_text
            for marker in ("create", "make", "book", "register", "submit", "record", "initiate", "issue")
        )
        update_evidence = any(
            marker in workflow_text
            for marker in ("manage", "update", "change", "configure", "edit")
        )
        if read_evidence:
            endpoints.append(ApiEndpoint(
                method="GET", path=f"/api/v1/{slug}",
                purpose=f"Search or list {resource} for the evidenced {context} workflows.",
                request_description="Filter, sort, and pagination query parameters.",
                response_description=f"A paginated collection of {resource} representations.",
                operation_type="query", **common,
            ))
        if detail_evidence:
            endpoints.append(ApiEndpoint(
                method="GET", path=f"/api/v1/{slug}/{{{singular}Id}}",
                purpose=f"Read the current {resource} state needed by an evidenced workflow.",
                request_description=f"Path identifier for the {resource}.",
                response_description=f"The current {resource} representation and version.",
                operation_type="query", **common,
            ))
        tokens = set(tokenize(entity.name))
        immutable_or_derived = bool(tokens & {"ledger", "entry", "transaction", "audit", "history"})
        if create_evidence and not immutable_or_derived:
            creation_purpose = (
                f"Initiate a {resource} using an idempotent domain command."
                if tokens & {"transfer", "payment", "booking", "order", "shipment"}
                else f"Execute the evidenced create/initiate workflow for {resource}."
            )
            endpoints.append(ApiEndpoint(
                method="POST", path=f"/api/v1/{slug}",
                purpose=creation_purpose,
                request_description=f"Typed domain command for {resource}; excludes server-owned state and accepts an idempotency key when retryable.",
                response_description=f"Accepted {resource} identifier, lifecycle state, and version.",
                operation_type="command", **common,
            ))
        if update_evidence and not immutable_or_derived:
            endpoints.append(ApiEndpoint(
                method="PATCH", path=f"/api/v1/{slug}/{{{singular}Id}}",
                purpose=f"Apply the evidenced manage/update operation to mutable {resource} fields.",
                request_description="Typed change command with expected version for concurrency control.",
                response_description=f"Updated {resource} state and version.",
                operation_type="command", **common,
            ))
        return endpoints

    def _semantic_endpoints(
        self,
        requirements: RequirementModel,
        members: list[DatabaseEntity],
        context: str,
        security: list[str],
    ) -> list[ApiEndpoint]:
        """Add business operations that cannot be represented by CRUD alone."""
        endpoints: list[ApiEndpoint] = []
        member_tokens = {entity.name: set(tokenize(entity.name)) for entity in members}
        security_required = True if security or self._auth_evidence(requirements) else None

        def add(
            method: str,
            path: str,
            purpose: str,
            resource: str,
            *,
            operation_type: str = "command",
            focus: str = "",
        ) -> None:
            requirement_ids = self._requirement_ids(requirements, resource, focus, purpose)
            endpoints.append(ApiEndpoint(
                method=method,
                path=path,
                purpose=purpose,
                auth_required=security_required,
                request_description="Typed domain input with actor, correlation ID, expected version, and idempotency key when retryable.",
                response_description="Domain result with stable identifiers, state, version, and trace metadata.",
                group=context,
                resource=resource,
                operation_type=operation_type,  # type: ignore[arg-type]
                owner=context,
                service=context,
                requirement_ids=requirement_ids,
                security_mechanisms=security,
                source_evidence=self._requirement_evidence(requirements, requirement_ids),
            ))

        for entity in members:
            tokens = member_tokens[entity.name]
            resource = to_display_name(entity.name)
            slug = self._collection_slug(entity.name)
            singular = self._singular_identifier(entity.name)
            if "transfer" in tokens:
                add("POST", f"/api/v1/{slug}/{{{singular}Id}}/cancel", "Cancel a transfer only while its lifecycle and settlement invariants permit it.", resource, focus="transfer")
            if "card" in tokens:
                add("POST", f"/api/v1/{slug}/{{{singular}Id}}/controls", "Apply an allowed card control such as freeze, unfreeze, or channel restriction.", resource, focus="manage cards")
            if {"risk", "assessment"} <= tokens or "fraud" in tokens:
                add("POST", f"/api/v1/{slug}/assess", "Assess a transaction and record a reviewable risk decision.", resource, focus="fraud assess")
            if {"regulatory", "report"} <= tokens:
                add("POST", f"/api/v1/{slug}/{{{singular}Id}}/submit", "Submit a prepared regulatory report with an auditable acknowledgement.", resource, focus="compliance reporting")
            if {"ledger", "entry"} <= tokens:
                add("POST", "/api/v1/internal/ledger/postings", "Atomically post a balanced set of debit and credit ledger entries; reject unbalanced or duplicate commands.", resource, focus="authoritative ledger")
                add("GET", "/api/v1/accounts/{accountId}/ledger-entries", "Read an account's ordered ledger entries and authoritative balance trail.", resource, operation_type="query", focus="ledger balances")
            elif "transaction" in tokens:
                add("GET", "/api/v1/accounts/{accountId}/transactions", "Read account transaction history with stable pagination and booking order.", resource, operation_type="query", focus="transaction history")
        return endpoints

    def _transition_endpoints(
        self,
        requirements: RequirementModel,
        members: list[DatabaseEntity],
        context: str,
        security: list[str],
    ) -> list[ApiEndpoint]:
        member_names = {
            singularize(to_identifier(entity.name)): entity for entity in members
        }
        endpoints: list[ApiEndpoint] = []
        for workflow in requirements.domain_workflows:
            words = workflow.name.strip().split()
            action = next((
                token.casefold()
                for token in tokenize(workflow.name)
                if token.casefold() in self._TRANSITION_VERBS
            ), "")
            if action not in self._TRANSITION_VERBS:
                continue
            entity = next((
                member_names[singularize(to_identifier(name))]
                for name in reversed(workflow.related_entities)
                if singularize(to_identifier(name)) in member_names
            ), None)
            if entity is None:
                continue
            if singularize(to_identifier(entity.name)) in {
                singularize(to_identifier(workflow.primary_actor)),
            }:
                continue
            slug = self._collection_slug(entity.name)
            singular = self._singular_identifier(entity.name)
            requirement_ids = self._requirement_ids(requirements, workflow.description)
            endpoints.append(ApiEndpoint(
                method="POST",
                path=f"/api/v1/{slug}/{{{singular}Id}}/{to_identifier(action)}",
                purpose=f"Apply the {action} lifecycle transition. {workflow.description}",
                auth_required=True if security or self._auth_evidence(requirements) else None,
                request_description="Transition command, expected version, actor, and optional reason.",
                response_description=f"Updated {to_display_name(entity.name)} state and transition metadata.",
                group=context,
                resource=to_display_name(entity.name),
                operation_type="command",
                owner=context,
                service=context,
                requirement_ids=requirement_ids,
                security_mechanisms=security,
                source_evidence=self._requirement_evidence(requirements, requirement_ids),
            ))
        return endpoints

    def _integration_groups(
        self,
        requirements: RequirementModel,
        default_security: list[str],
    ) -> list[ApiGroup]:
        by_context: dict[str, list[IntegrationDetail]] = {}
        for integration in requirements.integration_details:
            by_context.setdefault(integration.bounded_context or "External Integration", []).append(integration)
        groups: list[ApiGroup] = []
        for context, integrations in sorted(by_context.items()):
            endpoints: list[ApiEndpoint] = []
            for integration in integrations:
                slug = to_identifier(integration.name).replace("_", "-")
                security = integration.security_mechanisms or default_security
                asynchronous = integration.interaction_mode == "asynchronous"
                # Producer/consumer semantics: the owning boundary publishes;
                # downstream consumers are named from the integration purpose
                # and bounded context so replay/ordering ownership is explicit.
                producer = context if asynchronous else None
                consumers = (
                    [f"{context} consumers", f"{integration.name} subscribers"]
                    if asynchronous else []
                )
                delivery = (
                    "at-least-once with idempotent consumers, versioned envelope, retries, and dead-letter routing"
                    if asynchronous else None
                )
                ordering = "correlation ID / partition key derived from the business aggregate" if asynchronous else None
                endpoints.append(ApiEndpoint(
                    method="PUBLISH" if asynchronous else "POST",
                    path=f"/events/{slug}" if asynchronous else f"/api/v1/integrations/{slug}",
                    purpose=integration.purpose,
                    auth_required=True if security else None,
                    request_description=(
                        "Versioned event envelope with event ID, correlation ID, occurred-at time, and typed payload. "
                        f"Producer: {producer}. Ordering key: {ordering}."
                        if asynchronous else
                        "Versioned partner request using the confirmed protocol and data format."
                    ),
                    response_description=(
                        "Acknowledgement; retries, dead-letter routing, and reconciliation are contractually defined."
                        if asynchronous else
                        "Typed response or acknowledgement with stable partner error mapping."
                    ),
                    group=context,
                    resource=integration.name,
                    operation_type="event" if asynchronous else "command",
                    owner=context,
                    service=context,
                    security_mechanisms=security,
                    source_evidence=integration.source_evidence,
                    producer=producer,
                    consumers=consumers,
                    delivery_semantics=delivery,
                    ordering_key=ordering,
                ))
            groups.append(ApiGroup(
                name=f"{context} Contracts",
                description="External contracts separated from internal domain resource APIs.",
                endpoints=endpoints,
            ))
        return groups

    @staticmethod
    def _collection_slug(name: str) -> str:
        identifier = to_identifier(name)
        slug = identifier.replace("_", "-")
        final_word = identifier.rsplit("_", 1)[-1]
        if singularize(final_word) != final_word:
            return slug
        if slug.endswith("y") and not slug.endswith(("ay", "ey", "iy", "oy", "uy")):
            return slug[:-1] + "ies"
        if slug.endswith(("s", "x", "z", "ch", "sh")):
            return slug + "es"
        return slug + "s"

    @staticmethod
    def _singular_identifier(name: str) -> str:
        parts = to_identifier(name).split("_")
        parts[-1] = singularize(parts[-1])
        return "_".join(parts)

    @staticmethod
    def _security_mechanisms(requirements: RequirementModel) -> list[str]:
        return list(dict.fromkeys([
            *requirements.security_model.human_authentication,
            *requirements.security_model.service_authentication,
            *requirements.security_model.partner_authentication,
            *requirements.security_model.authorization,
            *requirements.security_model.data_protection,
        ]))

    def _auth_evidence(self, requirements: RequirementModel) -> bool:
        return auth_evidence(
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
            *(actor.description for actor in requirements.actors),
        )

    @staticmethod
    def _requirement_ids(requirements: RequirementModel, *texts: str) -> list[str]:
        focus = {token for text in texts for token in tokenize(text) if len(token) > 3}
        matches: list[str] = []
        for index, requirement in enumerate(requirements.functional_requirements, start=1):
            requirement_tokens = {token for token in tokenize(requirement) if len(token) > 3}
            if focus & requirement_tokens:
                matches.append(f"FR-{index:03d}")
        return matches[:4]

    @staticmethod
    def _requirement_evidence(
        requirements: RequirementModel, requirement_ids: list[str]
    ) -> list[SourceEvidence]:
        evidence: list[SourceEvidence] = []
        for requirement_id in requirement_ids:
            index = int(requirement_id.split("-")[1]) - 1
            if 0 <= index < len(requirements.functional_requirements):
                evidence.append(SourceEvidence(
                    source_id=requirement_id,
                    source="functional requirement",
                    status="confirmed",
                    excerpt=requirements.functional_requirements[index],
                ))
        return evidence

    @staticmethod
    def _dedupe_endpoints(endpoints: list[ApiEndpoint]) -> list[ApiEndpoint]:
        result: dict[tuple[str, str], ApiEndpoint] = {}
        for endpoint in endpoints:
            result[(endpoint.method.upper(), endpoint.path.casefold())] = endpoint
        return list(result.values())
