import re

from app.schemas.domain import ApiDesign, ApiEndpoint, ApiGroup, DatabaseDesign, RequirementModel
from app.services.domain_inference import (
    auth_evidence,
    cluster_entities,
    to_display_name,
    to_identifier,
    tokenize,
)


class ApiGenerator:
    def generate(self, requirements: RequirementModel, database_design: DatabaseDesign) -> ApiDesign:
        if requirements.analysis_source == "conservative-fallback":
            return ApiDesign(
                style="Unknown; select after workflows and integration protocols are clarified",
                authentication_strategy="Unknown; clarify actors and trust boundaries first.",
                groups=[],
                validation_rules=[
                    "Do not publish endpoint contracts until domain commands and invariants are known."
                ],
                openapi_summary=["API design is intentionally deferred pending clarification."],
            )
        if requirements.analysis_source == "ollama-pretrained" and requirements.domain_workflows:
            return self._generate_from_workflows(requirements)

        lower_domain = requirements.domain.lower()
        groups = [
            ApiGroup(
                name="Authentication",
                description="Identity, session, and role bootstrap flows.",
                endpoints=[
                    ApiEndpoint(
                        method="POST",
                        path="/api/v1/auth/login",
                        purpose="Authenticate a user and return access plus refresh tokens.",
                        auth_required=False,
                        request_example={"email": "user@example.com", "password": "strong-password"},
                        response_example={"access_token": "jwt-token", "refresh_token": "refresh-token"},
                    ),
                    ApiEndpoint(
                        method="POST",
                        path="/api/v1/auth/refresh",
                        purpose="Rotate access tokens using a refresh token.",
                        auth_required=False,
                        request_example={"refresh_token": "refresh-token"},
                        response_example={"access_token": "new-jwt-token"},
                    ),
                ],
            ),
            ApiGroup(
                name="Users",
                description="Profile, role, and preference management.",
                endpoints=[
                    ApiEndpoint(
                        method="GET",
                        path="/api/v1/users/me",
                        purpose="Return the authenticated user's profile and feature entitlements.",
                        auth_required=True,
                        request_example={},
                        response_example={"id": "uuid", "email": "user@example.com", "role": "customer"},
                    ),
                    ApiEndpoint(
                        method="PATCH",
                        path="/api/v1/users/me/preferences",
                        purpose="Update profile settings and notification preferences.",
                        auth_required=True,
                        request_example={"theme": "dark", "notifications": ["email"]},
                        response_example={"status": "updated"},
                    ),
                ],
            ),
        ]

        if "charging" in lower_domain or any(entity.name == "stations" for entity in database_design.entities):
            groups.extend(
                [
                    ApiGroup(
                        name="Stations",
                        description="Station discovery, details, and charger availability.",
                        endpoints=[
                            ApiEndpoint(
                                method="GET",
                                path="/api/v1/stations",
                                purpose="Search nearby stations with connector, power, and availability filters.",
                                auth_required=False,
                                request_example={"city": "Bengaluru", "connector": "CCS2"},
                                response_example={"items": [{"id": "uuid", "name": "Central Business District Hub"}]},
                            ),
                            ApiEndpoint(
                                method="GET",
                                path="/api/v1/stations/{stationId}",
                                purpose="Return station details, charger inventory, and live slot availability.",
                                auth_required=False,
                                request_example={},
                                response_example={"id": "uuid", "status": "active"},
                            ),
                        ],
                    ),
                    ApiGroup(
                        name="Bookings",
                        description="Reservation, cancellation, and history workflows for drivers.",
                        endpoints=[
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/bookings",
                                purpose="Reserve a charging slot and initiate payment authorization.",
                                auth_required=True,
                                request_example={"stationId": "uuid", "chargerId": "uuid", "slotStart": "2026-08-05T18:30:00Z"},
                                response_example={"id": "uuid", "status": "pending_payment"},
                            ),
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/bookings/{bookingId}/cancel",
                                purpose="Cancel a reservation and trigger refund evaluation when applicable.",
                                auth_required=True,
                                request_example={"reason": "Plans changed"},
                                response_example={"id": "uuid", "status": "cancelled"},
                            ),
                        ],
                    ),
                    ApiGroup(
                        name="Charging Sessions",
                        description="Operational control over live or completed charging sessions.",
                        endpoints=[
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/sessions/{bookingId}/start",
                                purpose="Start a charging session for an eligible booking.",
                                auth_required=True,
                                request_example={"bookingId": "uuid"},
                                response_example={"sessionId": "uuid", "status": "active"},
                            ),
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/sessions/{sessionId}/stop",
                                purpose="Stop a charging session and finalize billing data.",
                                auth_required=True,
                                request_example={"meterKwh": 24.6},
                                response_example={"sessionId": "uuid", "status": "completed"},
                            ),
                        ],
                    ),
                ]
            )
        elif "pharmacy" in lower_domain or any(
            entity.name == "prescriptions" for entity in database_design.entities
        ):
            groups.extend(
                [
                    ApiGroup(
                        name="Catalog",
                        description="Product browsing and inventory-aware item lookup.",
                        endpoints=[
                            ApiEndpoint(
                                method="GET",
                                path="/api/v1/products",
                                purpose="Search and filter products with pagination.",
                                auth_required=False,
                                request_example={"query": "pain relief", "page": 1},
                                response_example={"items": [{"id": "uuid", "name": "Sample Medication"}]},
                            ),
                            ApiEndpoint(
                                method="GET",
                                path="/api/v1/products/{productId}",
                                purpose="Return medicine details, prescription rules, and stock summary.",
                                auth_required=False,
                                request_example={},
                                response_example={"id": "uuid", "requiresPrescription": True, "status": "active"},
                            ),
                        ],
                    ),
                    ApiGroup(
                        name="Prescriptions",
                        description="Prescription upload and pharmacist review workflows.",
                        endpoints=[
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/prescriptions",
                                purpose="Upload a prescription and start pharmacist review.",
                                auth_required=True,
                                request_example={"fileUrl": "https://storage/prescription.pdf"},
                                response_example={"id": "uuid", "status": "pending_review"},
                            ),
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/prescriptions/{prescriptionId}/review",
                                purpose="Approve, reject, or request clarification on a prescription.",
                                auth_required=True,
                                request_example={"decision": "approved", "notes": "Verified by licensed pharmacist"},
                                response_example={"id": "uuid", "status": "approved"},
                            ),
                        ],
                    ),
                    ApiGroup(
                        name="Orders",
                        description="Checkout, payment, and order status workflows.",
                        endpoints=[
                            ApiEndpoint(
                                method="POST",
                                path="/api/v1/orders",
                                purpose="Create an order from a validated cart and linked prescription when needed.",
                                auth_required=True,
                                request_example={"items": [{"productId": "uuid", "quantity": 1}], "prescriptionId": "uuid"},
                                response_example={"id": "uuid", "status": "pending_payment"},
                            ),
                            ApiEndpoint(
                                method="GET",
                                path="/api/v1/orders/{orderId}",
                                purpose="Return detailed order state including payment, fulfillment, and substitution status.",
                                auth_required=True,
                                request_example={},
                                response_example={"id": "uuid", "status": "packed"},
                            ),
                        ],
                    ),
                    ApiGroup(
                        name="Fulfillment",
                        description="Inventory reservation, shipment tracking, and delivery updates.",
                        endpoints=[
                            ApiEndpoint(
                                method="GET",
                                path="/api/v1/orders/{orderId}/tracking",
                                purpose="Return shipment milestones and courier-visible tracking details.",
                                auth_required=True,
                                request_example={},
                                response_example={"orderId": "uuid", "shipmentStatus": "out_for_delivery"},
                            ),
                            ApiEndpoint(
                                method="PATCH",
                                path="/api/v1/shipments/{shipmentId}/status",
                                purpose="Update courier delivery status for a dispatched order.",
                                auth_required=True,
                                request_example={"status": "delivered"},
                                response_example={"id": "uuid", "status": "delivered"},
                            ),
                        ],
                    ),
                ]
            )
        else:
            # Domain-driven groups replace the generic template: the Auth
            # group appears only with identity evidence, and the Users group
            # only when the data model actually contains a users table.
            kept = [groups[0]] if self._auth_evidence(requirements) else []
            if any(entity.name == "users" for entity in database_design.entities):
                kept.append(groups[1])
            kept.extend(
                self._generate_domain_groups(requirements, database_design)
            )
            groups = kept

        validation_rules = [
            "Use request-level Pydantic validation with strict enum and UUID parsing.",
            "Enforce optimistic locking or version fields for operator-facing write flows.",
            "Return structured error objects with machine-readable codes and remediation hints.",
        ]

        openapi_summary = [
            "Document all endpoints with example requests and responses.",
            "Use bearer token security schemes plus refresh token flows.",
            "Tag endpoints by bounded context so generated SDKs remain modular.",
        ]

        return ApiDesign(
            style="REST",
            authentication_strategy=(
                "JWT access tokens, refresh token rotation, role-based authorization"
                if self._auth_evidence(requirements)
                or requirements.domain in ("EV Charging Booking Platform", "Online Pharmacy")
                else "Unknown; clarify actor identity, trust boundaries, and machine credentials."
            ),
            groups=groups,
            validation_rules=validation_rules,
            openapi_summary=openapi_summary,
        )

    def _generate_from_workflows(self, requirements: RequirementModel) -> ApiDesign:
        requirement_text = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.constraints
        ).lower()
        identity_is_explicit = any(
            token in requirement_text
            for token in ("authenticate", "authorization", "permission", "access control", "identity")
        )
        groups: list[ApiGroup] = []
        for workflow in requirements.domain_workflows:
            method = self._workflow_method(workflow.name)
            path = f"/api/v1/{self._slug(workflow.name)}"
            groups.append(
                ApiGroup(
                    name=workflow.name,
                    description=workflow.description,
                    endpoints=[
                        ApiEndpoint(
                            method=method,
                            path=path,
                            purpose=workflow.description,
                            auth_required=True if identity_is_explicit else None,
                            request_example={},
                            response_example={},
                        )
                    ],
                )
            )

        return ApiDesign(
            style="REST candidate; confirm command, query, streaming, and device protocols per workflow",
            authentication_strategy=(
                "Authorization is required by the brief; exact identity mechanism remains open."
                if identity_is_explicit
                else "Unknown; clarify actor identity, trust boundaries, and machine credentials."
            ),
            groups=groups,
            validation_rules=[
                "Validate identifiers, state transitions, and domain invariants at the boundary.",
                "Define idempotency and concurrency behavior for every state-changing workflow.",
                "Treat request and response examples as unknown until payload contracts are clarified.",
            ],
            openapi_summary=[
                "Operations are derived from validated domain workflows, not a generic CRUD template.",
                "Protocol-specific integrations require separate contracts when the brief justifies them.",
            ],
        )

    def _workflow_method(self, name: str) -> str:
        first_word = name.strip().split(maxsplit=1)[0].lower() if name.strip() else ""
        if first_word in {"find", "get", "inspect", "list", "monitor", "retrieve", "search", "view"}:
            return "GET"
        if first_word in {"amend", "edit", "update"}:
            return "PATCH"
        return "POST"

    # ------------------------------------------------------------------
    # Domain-driven groups: one group per bounded context derived from the
    # actual domain entities and workflows — never a generic template.
    # ------------------------------------------------------------------

    _TRANSITION_VERBS = frozenset(
        {"approve", "review", "cancel", "submit", "plan", "forecast", "schedule",
         "dispatch", "fulfill", "inspect", "register", "coordinate", "synchronize"}
    )

    def _auth_evidence(self, requirements: RequirementModel) -> bool:
        return auth_evidence(
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
            *(actor.description for actor in requirements.actors),
        )

    def _requirement_ids(self, requirements: RequirementModel, *texts: str) -> list[str]:
        """Map FR indices (FR-001…) sharing content tokens with the endpoint."""
        focus: set[str] = set()
        for text in texts:
            focus |= {token for token in tokenize(text) if len(token) > 3}
        matched: list[str] = []
        for index, requirement in enumerate(requirements.functional_requirements, start=1):
            req_tokens = {token for token in tokenize(requirement) if len(token) > 3}
            if len(focus & req_tokens) >= 2:
                matched.append(f"FR-{index:03d}")
            if len(matched) >= 3:
                break
        return matched

    def _generate_domain_groups(
        self, requirements: RequirementModel, database_design: DatabaseDesign
    ) -> list[ApiGroup]:
        auth_required: bool | None = True if self._auth_evidence(requirements) else None
        # Platform tables (identity/governance) are served by the Auth/Users
        # groups, never by domain CRUD groups.
        entity_names = [
            entity.name
            for entity in database_design.entities
            if entity.name not in {"users", "audit_logs", "notifications"}
        ]
        contexts = cluster_entities(entity_names)
        context_members: dict[str, list[str]] = {}
        for name in entity_names:
            context_members.setdefault(contexts.get(name, to_display_name(name)), []).append(name)

        workflow_verbs: dict[str, str] = {}
        for workflow in requirements.domain_workflows:
            first = workflow.name.strip().split(maxsplit=1)
            verb = first[0].lower() if first else ""
            workflow_verbs[workflow.name] = verb

        groups: list[ApiGroup] = []
        for context in sorted(context_members):
            members = context_members[context]
            endpoints: list[ApiEndpoint] = []
            for member in members:
                slug = to_identifier(member).replace("_", "-")
                member_id = f"{slug[:-1] if slug.endswith('s') else slug}Id"
                owning = next(
                    (
                        workflow.description
                        for workflow in requirements.domain_workflows
                        if any(
                            token in tokenize(workflow.description)
                            for token in to_identifier(member).split("_")
                        )
                    ),
                    f"Lifecycle operations for {to_display_name(member)} records.",
                )
                endpoints.append(
                    ApiEndpoint(
                        method="GET",
                        path=f"/api/v1/{slug}",
                        purpose=f"List and filter {to_display_name(member)} records in the {context} context.",
                        auth_required=auth_required,
                        request_example={},
                        response_example={},
                        requirement_ids=self._requirement_ids(requirements, owning, member),
                    )
                )
                endpoints.append(
                    ApiEndpoint(
                        method="POST",
                        path=f"/api/v1/{slug}",
                        purpose=f"Create a {to_display_name(member)} record owned by {context}.",
                        auth_required=auth_required,
                        request_example={},
                        response_example={},
                        requirement_ids=self._requirement_ids(requirements, owning, member),
                    )
                )
                endpoints.append(
                    ApiEndpoint(
                        method="PATCH",
                        path=f"/api/v1/{slug}/{{{member_id}}}",
                        purpose=f"Update {to_display_name(member)} state or attributes within {context}.",
                        auth_required=auth_required,
                        request_example={},
                        response_example={},
                        requirement_ids=self._requirement_ids(requirements, owning, member),
                    )
                )
            # Workflow transition endpoints (approvals, scheduling, dispatch…)
            # live in the context of their primary entity.
            for workflow in requirements.domain_workflows:
                verb = workflow_verbs.get(workflow.name, "")
                if verb not in self._TRANSITION_VERBS:
                    continue
                related = workflow.related_entities or members[:1]
                home = contexts.get(related[0], context) if related else context
                if home != context:
                    continue
                endpoints.append(
                    ApiEndpoint(
                        method="POST",
                        path=f"/api/v1/{self._slug(workflow.name)}",
                        purpose=f"{workflow.description} (owning context: {context}).",
                        auth_required=auth_required,
                        request_example={},
                        response_example={},
                        requirement_ids=self._requirement_ids(requirements, workflow.description),
                    )
                )
            groups.append(
                ApiGroup(
                    name=context,
                    description=f"{context} bounded context: {', '.join(to_display_name(m) for m in members)}.",
                    endpoints=endpoints,
                )
            )
        return groups

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug[:100] or "domain-operation"
