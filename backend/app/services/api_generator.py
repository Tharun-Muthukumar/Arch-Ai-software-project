import re

from app.schemas.domain import ApiDesign, ApiEndpoint, ApiGroup, DatabaseDesign, RequirementModel


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
            groups.append(
                ApiGroup(
                    name="Core Workflows",
                    description="Primary domain CRUD and lifecycle transitions.",
                    endpoints=[
                        ApiEndpoint(
                            method="POST",
                            path="/api/v1/workflows",
                            purpose="Create a new domain workflow instance.",
                            auth_required=True,
                            request_example={"payload": {"name": "New workflow"}},
                            response_example={"id": "uuid", "status": "draft"},
                        ),
                        ApiEndpoint(
                            method="PATCH",
                            path="/api/v1/workflows/{workflowId}",
                            purpose="Update a workflow's state or payload.",
                            auth_required=True,
                            request_example={"status": "submitted"},
                            response_example={"id": "uuid", "status": "submitted"},
                        ),
                    ],
                )
            )

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
            authentication_strategy="JWT access tokens, refresh token rotation, role-based authorization",
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

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug[:100] or "domain-operation"
