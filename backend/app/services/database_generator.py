import re

from app.schemas.domain import (
    DatabaseDesign,
    DatabaseEntity,
    DatabaseField,
    DatabaseRelationship,
    RequirementModel,
)
from app.services.domain_inference import (
    audit_evidence,
    auth_evidence,
    cluster_entities,
    singularize,
    to_display_name,
    to_identifier,
    tokenize,
)

_PARTY_TOKENS = frozenset(
    {"partner", "supplier", "distributor", "retailer", "wholesaler", "customer",
     "vendor", "facility", "warehouse", "store", "user", "member", "client",
     "carrier", "broker", "dealer", "manufacturer", "bottler", "plant", "outlet"}
)

_CATALOG_TOKENS = frozenset(
    {"product", "sku", "ingredient", "course", "lesson", "medicine", "drug",
     "catalog", "formulation", "concentrate", "recipe"}
)

_TRANSACTIONAL_TOKENS = frozenset(
    {"order", "shipment", "booking", "session", "forecast", "inspection",
     "delivery", "plan", "enrollment", "submission", "prescription", "payment",
     "invoice", "ticket", "reservation", "cycle", "procedure", "review",
     "sale", "sales", "checkout"}
)


class DatabaseGenerator:
    def generate(self, requirements: RequirementModel) -> DatabaseDesign:
        if requirements.analysis_source == "conservative-fallback":
            return DatabaseDesign(
                database_engine="Unknown; select after the domain model is clarified",
                entities=[],
                relationships=[],
                indexes=[],
                normalization_notes=[
                    "No domain entities are invented when structured extraction is unavailable."
                ],
                sql_schema="-- Database schema pending domain clarification.",
                sample_inserts="-- Sample records pending domain clarification.",
            )
        # Every populated canonical domain model uses the same hint-driven
        # path. A known-domain label is not permission to inject a complete
        # industry schema (payments, shipments, inventory, and similar
        # records still require evidence in the brief).
        if requirements.domain_entities:
            return self._generate_from_hints(requirements)

        lower_text = " ".join(requirements.functional_requirements).lower()
        is_curated_domain = (
            "charger" in lower_text
            or "station" in lower_text
            or requirements.domain == "EV Charging Booking Platform"
            or "prescription" in lower_text
            or requirements.domain == "Online Pharmacy"
        )
        # Platform tables exist only with evidence: curated domains reference
        # users throughout, otherwise identity/audit tables require explicit
        # auth and audit requirements (audit attribution implies users).
        entities: list[DatabaseEntity] = []
        if is_curated_domain or self._auth_evidence(requirements) or self._audit_evidence(requirements):
            entities.append(
                DatabaseEntity(
                    name="users",
                    description="Core platform users with role-based access.",
                    fields=[
                        DatabaseField(name="id", data_type="UUID", description="Primary key"),
                        DatabaseField(name="email", data_type="VARCHAR(255)", indexed=True, description="Unique login email"),
                        DatabaseField(name="full_name", data_type="VARCHAR(255)", description="Display name"),
                        DatabaseField(name="role", data_type="VARCHAR(50)", indexed=True, description="Business role"),
                        DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Creation time"),
                    ],
                )
            )
        relationships: list[DatabaseRelationship] = []
        if is_curated_domain or self._audit_evidence(requirements):
            entities.append(
                DatabaseEntity(
                    name="audit_logs",
                    description="Immutable audit trail for major business and administrative actions.",
                    fields=[
                        DatabaseField(name="id", data_type="UUID", description="Primary key"),
                        DatabaseField(name="actor_id", data_type="UUID", indexed=True, description="User who triggered the event"),
                        DatabaseField(name="event_type", data_type="VARCHAR(80)", indexed=True, description="Domain event type"),
                        DatabaseField(name="entity_name", data_type="VARCHAR(80)", description="Affected entity"),
                        DatabaseField(name="metadata", data_type="JSONB", description="Structured event details"),
                        DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Creation time"),
                    ],
                )
            )
            relationships.append(
                DatabaseRelationship(
                    source="audit_logs",
                    target="users",
                    relationship="many-to-one",
                    description="Every audit log entry is attributed to a user or system actor.",
                )
            )
        pattern_assumptions: list[str] = []

        if "charger" in lower_text or "station" in lower_text or requirements.domain == "EV Charging Booking Platform":
            entities.extend(
                [
                    DatabaseEntity(
                        name="stations",
                        description="Charging station locations with operator-visible availability and status metadata.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="name", data_type="VARCHAR(255)", indexed=True, description="Station display name"),
                            DatabaseField(name="city", data_type="VARCHAR(120)", indexed=True, description="Primary city or region"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Station status"),
                            DatabaseField(name="geo_hash", data_type="VARCHAR(24)", indexed=True, description="Geo search token"),
                        ],
                    ),
                    DatabaseEntity(
                        name="chargers",
                        description="Physical chargers published under each station.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="station_id", data_type="UUID", indexed=True, description="Parent station"),
                            DatabaseField(name="connector_type", data_type="VARCHAR(40)", indexed=True, description="Connector standard"),
                            DatabaseField(name="max_kw", data_type="INTEGER", description="Max charging power"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Operational state"),
                        ],
                    ),
                    DatabaseEntity(
                        name="bookings",
                        description="Reserved charging slots linked to drivers, stations, and chargers.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="user_id", data_type="UUID", indexed=True, description="Driver owner"),
                            DatabaseField(name="station_id", data_type="UUID", indexed=True, description="Booked station"),
                            DatabaseField(name="charger_id", data_type="UUID", indexed=True, description="Booked charger"),
                            DatabaseField(name="slot_start", data_type="TIMESTAMPTZ", indexed=True, description="Reservation start"),
                            DatabaseField(name="slot_end", data_type="TIMESTAMPTZ", indexed=True, description="Reservation end"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Booking lifecycle"),
                        ],
                    ),
                    DatabaseEntity(
                        name="charging_sessions",
                        description="Live or completed charging sessions spawned from bookings.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="booking_id", data_type="UUID", indexed=True, description="Linked booking"),
                            DatabaseField(name="started_at", data_type="TIMESTAMPTZ", nullable=True, description="Actual session start"),
                            DatabaseField(name="ended_at", data_type="TIMESTAMPTZ", nullable=True, description="Actual session end"),
                            DatabaseField(name="energy_kwh", data_type="NUMERIC(10,2)", nullable=True, description="Delivered energy"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Session state"),
                        ],
                    ),
                    DatabaseEntity(
                        name="payments",
                        description="Captured payments and refund states for booking transactions.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="booking_id", data_type="UUID", indexed=True, description="Linked booking"),
                            DatabaseField(name="user_id", data_type="UUID", indexed=True, description="Paying driver"),
                            DatabaseField(name="amount", data_type="NUMERIC(12,2)", description="Charged amount"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Payment status"),
                            DatabaseField(name="refund_status", data_type="VARCHAR(40)", nullable=True, description="Refund lifecycle"),
                        ],
                    ),
                ]
            )
            relationships.extend(
                [
                    DatabaseRelationship(
                        source="chargers",
                        target="stations",
                        relationship="many-to-one",
                        description="Each charger belongs to a station.",
                    ),
                    DatabaseRelationship(
                        source="bookings",
                        target="users",
                        relationship="many-to-one",
                        description="Each booking belongs to a driver.",
                    ),
                    DatabaseRelationship(
                        source="bookings",
                        target="stations",
                        relationship="many-to-one",
                        description="Each booking selects a station.",
                    ),
                    DatabaseRelationship(
                        source="bookings",
                        target="chargers",
                        relationship="many-to-one",
                        description="Each booking reserves a charger.",
                    ),
                    DatabaseRelationship(
                        source="charging_sessions",
                        target="bookings",
                        relationship="one-to-one",
                        description="Each charging session is created from a booking.",
                    ),
                    DatabaseRelationship(
                        source="payments",
                        target="bookings",
                        relationship="many-to-one",
                        description="Each payment settles a booking.",
                    ),
                    DatabaseRelationship(
                        source="payments",
                        target="users",
                        relationship="many-to-one",
                        description="Each payment is attributed to a driver.",
                    ),
                ]
            )
        elif "prescription" in lower_text or requirements.domain == "Online Pharmacy":
            entities.extend(
                [
                    DatabaseEntity(
                        name="products",
                        description="Sellable medicines and wellness items.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="sku", data_type="VARCHAR(80)", indexed=True, description="Stock keeping unit"),
                            DatabaseField(name="name", data_type="VARCHAR(255)", description="Display name"),
                            DatabaseField(name="requires_prescription", data_type="BOOLEAN", description="Prescription flag"),
                            DatabaseField(name="price", data_type="NUMERIC(12,2)", description="Current selling price"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Catalog availability"),
                        ],
                    ),
                    DatabaseEntity(
                        name="inventory",
                        description="Current stock position and reorder state for each medicine.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="product_id", data_type="UUID", indexed=True, description="Referenced medicine"),
                            DatabaseField(name="available_units", data_type="INTEGER", description="Sellable stock quantity"),
                            DatabaseField(name="reserved_units", data_type="INTEGER", description="Units held for open orders"),
                            DatabaseField(name="reorder_threshold", data_type="INTEGER", description="Low-stock trigger"),
                            DatabaseField(name="updated_at", data_type="TIMESTAMPTZ", description="Last stock refresh"),
                        ],
                    ),
                    DatabaseEntity(
                        name="prescriptions",
                        description="Uploaded prescriptions pending or completed pharmacist review.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="user_id", data_type="UUID", indexed=True, description="Customer owner"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Verification state"),
                            DatabaseField(name="file_url", data_type="TEXT", description="Prescription document location"),
                            DatabaseField(name="uploaded_at", data_type="TIMESTAMPTZ", description="Upload time"),
                            DatabaseField(name="reviewed_at", data_type="TIMESTAMPTZ", nullable=True, description="Review time"),
                        ],
                    ),
                    DatabaseEntity(
                        name="orders",
                        description="Checkout transaction and fulfillment state.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="user_id", data_type="UUID", indexed=True, description="Customer owner"),
                            DatabaseField(name="prescription_id", data_type="UUID", nullable=True, description="Linked prescription"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Lifecycle status"),
                            DatabaseField(name="total_amount", data_type="NUMERIC(12,2)", description="Order total"),
                            DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Order placement time"),
                        ],
                    ),
                    DatabaseEntity(
                        name="order_items",
                        description="Line items within each order.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="order_id", data_type="UUID", indexed=True, description="Parent order"),
                            DatabaseField(name="product_id", data_type="UUID", indexed=True, description="Referenced product"),
                            DatabaseField(name="quantity", data_type="INTEGER", description="Ordered units"),
                            DatabaseField(name="unit_price", data_type="NUMERIC(12,2)", description="Captured sale price"),
                            DatabaseField(name="substitution_allowed", data_type="BOOLEAN", description="Whether pharmacist substitutions are permitted"),
                        ],
                    ),
                    DatabaseEntity(
                        name="payments",
                        description="Captured payments for checkout and refund handling.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="order_id", data_type="UUID", indexed=True, description="Linked order"),
                            DatabaseField(name="user_id", data_type="UUID", indexed=True, description="Paying customer"),
                            DatabaseField(name="amount", data_type="NUMERIC(12,2)", description="Charged amount"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Payment state"),
                            DatabaseField(name="paid_at", data_type="TIMESTAMPTZ", nullable=True, description="Capture time"),
                        ],
                    ),
                    DatabaseEntity(
                        name="shipments",
                        description="Courier assignment, tracking, and delivery status for each fulfilled order.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="order_id", data_type="UUID", indexed=True, description="Fulfilled order"),
                            DatabaseField(name="courier_id", data_type="UUID", indexed=True, description="Delivery partner user"),
                            DatabaseField(name="tracking_number", data_type="VARCHAR(80)", indexed=True, description="Tracking reference"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Delivery lifecycle"),
                            DatabaseField(name="dispatched_at", data_type="TIMESTAMPTZ", nullable=True, description="Dispatch time"),
                        ],
                    ),
                ]
            )
            relationships.extend(
                [
                    DatabaseRelationship(
                        source="inventory",
                        target="products",
                        relationship="one-to-one",
                        description="Each product keeps one current stock summary record.",
                    ),
                    DatabaseRelationship(
                        source="prescriptions",
                        target="users",
                        relationship="many-to-one",
                        description="Each prescription belongs to a customer.",
                    ),
                    DatabaseRelationship(
                        source="orders",
                        target="users",
                        relationship="many-to-one",
                        description="Each order belongs to a customer.",
                    ),
                    DatabaseRelationship(
                        source="orders",
                        target="prescriptions",
                        relationship="many-to-one",
                        description="Prescription orders reference a validated prescription when required.",
                    ),
                    DatabaseRelationship(
                        source="order_items",
                        target="orders",
                        relationship="many-to-one",
                        description="Each order has multiple line items.",
                    ),
                    DatabaseRelationship(
                        source="order_items",
                        target="products",
                        relationship="many-to-one",
                        description="Each line item references a product.",
                    ),
                    DatabaseRelationship(
                        source="payments",
                        target="orders",
                        relationship="many-to-one",
                        description="Each payment settles an order.",
                    ),
                    DatabaseRelationship(
                        source="payments",
                        target="users",
                        relationship="many-to-one",
                        description="Each payment is attributed to a customer.",
                    ),
                    DatabaseRelationship(
                        source="shipments",
                        target="orders",
                        relationship="one-to-one",
                        description="Each fulfilled order has one shipment tracking record.",
                    ),
                    DatabaseRelationship(
                        source="shipments",
                        target="users",
                        relationship="many-to-one",
                        description="Each shipment is handled by a delivery partner user.",
                    ),
                ]
            )
        else:
            # Entity-driven model: every table comes from the brief's domain
            # entities (never generic platform placeholders), with platform
            # tables added only when identity/audit evidence requires them.
            domain_entities = self._generate_from_blueprint_entities(requirements)
            entities.extend(domain_entities)
            inferred_relationships, assumed_links = self._relationships_for_entities(
                requirements, domain_entities
            )
            relationships.extend(inferred_relationships)
            for assumed in assumed_links:
                pattern_assumptions.append(
                    f"Line-item link for {assumed} is a structural assumption; confirm the parent records."
                )

        entity_names = {entity.name for entity in entities}
        indexes = []
        if "users" in entity_names:
            indexes.append("CREATE INDEX idx_users_role ON users(role);")
        if "audit_logs" in entity_names:
            indexes.extend(
                [
                    "CREATE INDEX idx_audit_logs_event_type ON audit_logs(event_type);",
                    "CREATE INDEX idx_audit_logs_actor_id ON audit_logs(actor_id);",
                ]
            )
        for entity in entities:
            for field in entity.fields:
                if field.indexed and field.name not in {"role", "event_type", "actor_id"}:
                    indexes.append(
                        f"CREATE INDEX idx_{entity.name}_{field.name} ON {entity.name}({field.name});"
                    )
        normalization_notes = [
            "Core transactional tables are normalized to third normal form.",
            "JSONB is reserved for extensible metadata, not for high-cardinality relational joins.",
            "Indexing prioritizes role lookups, status filters, and audit/event retrieval paths.",
        ]
        normalization_notes.extend(pattern_assumptions)
        if any(entity.bounded_context for entity in entities):
            normalization_notes.append(
                "Tables carry their owning bounded context; relationships prefer "
                "aggregate-root ownership inferred from workflow and requirement co-mention."
            )
        if self._needs_ledger_model(requirements):
            existing = {entity.name for entity in entities}
            for ledger_entity in self._ledger_entities():
                if ledger_entity.name not in existing:
                    entities.append(ledger_entity)
                    existing.add(ledger_entity.name)
            existing_pairs = {(relation.source, relation.target) for relation in relationships}
            for relation in self._ledger_relationships():
                if (relation.source, relation.target) not in existing_pairs:
                    relationships.append(relation)
            indexes.extend([
                "CREATE UNIQUE INDEX uq_ledger_entries_idempotency ON ledger_entries(idempotency_key);",
                "CREATE INDEX idx_ledger_entries_transaction ON ledger_entries(transaction_id);",
            ])
            normalization_notes.append(
                "Ledger postings are immutable double-entry records: each transaction_id groups balanced debit/credit legs with idempotent writes."
            )

        sql_schema = self._render_sql(entities, relationships)
        sample_inserts = self._sample_inserts(entities)

        # Every table carries an owning bounded context, including curated
        # domains, so ownership and consistency checks work uniformly.
        fallback_contexts = cluster_entities([entity.name for entity in entities])
        for entity in entities:
            if not entity.bounded_context:
                entity.bounded_context = fallback_contexts.get(
                    entity.name, to_display_name(entity.name)
                )

        return DatabaseDesign(
            database_engine="PostgreSQL",
            entities=entities,
            relationships=relationships,
            indexes=indexes,
            normalization_notes=normalization_notes,
            sql_schema=sql_schema,
            sample_inserts=sample_inserts,
        )

    def _auth_evidence(self, requirements: RequirementModel) -> bool:
        return auth_evidence(
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
        )

    def _needs_ledger_model(self, requirements: RequirementModel) -> bool:
        """Whether the brief demands double-entry ledger semantics."""
        text = " ".join([
            requirements.domain,
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
            *[hint.name for hint in requirements.domain_entities],
        ]).lower()
        markers = ("ledger", "double-entry", "double entry", "journal", "posting", "settlement", "reconcile", "reconciliation", "chart of accounts", "debit", "credit")
        banking = ("banking" in text or "financial services" in text) and any(
            token in text for token in ("transfer", "transaction", "payment", "settlement", "ledger", "account")
        )
        return banking or any(marker in text for marker in markers)

    def _ledger_entities(self) -> list[DatabaseEntity]:
        return [
            DatabaseEntity(
                name="accounts",
                description="Ledger accounts forming the chart of accounts; authoritative balance owners.",
                fields=[
                    DatabaseField(name="id", data_type="UUID", description="Primary key"),
                    DatabaseField(name="code", data_type="VARCHAR(40)", indexed=True, description="Unique account code in the chart of accounts"),
                    DatabaseField(name="name", data_type="VARCHAR(255)", description="Account display name"),
                    DatabaseField(name="account_type", data_type="VARCHAR(40)", indexed=True, description="Asset, liability, equity, income, or expense classification"),
                    DatabaseField(name="currency", data_type="VARCHAR(8)", description="Default ISO currency code"),
                    DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Active, frozen, or closed lifecycle state"),
                    DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Account creation time"),
                ],
                bounded_context="Ledger",
            ),
            DatabaseEntity(
                name="ledger_entries",
                description="Immutable double-entry postings; debits must equal credits per transaction.",
                fields=[
                    DatabaseField(name="id", data_type="UUID", description="Primary key"),
                    DatabaseField(name="transaction_id", data_type="UUID", indexed=True, description="Grouping key for the balanced debit/credit set"),
                    DatabaseField(name="account_id", data_type="UUID", indexed=True, description="Owning ledger account"),
                    DatabaseField(name="debit_amount", data_type="NUMERIC(18,2)", nullable=True, description="Debit leg; exactly one leg non-zero"),
                    DatabaseField(name="credit_amount", data_type="NUMERIC(18,2)", nullable=True, description="Credit leg; exactly one leg non-zero"),
                    DatabaseField(name="currency", data_type="VARCHAR(8)", description="ISO currency code"),
                    DatabaseField(name="booking_order", data_type="INTEGER", indexed=True, description="Authoritative booking sequence within the account"),
                    DatabaseField(name="idempotency_key", data_type="VARCHAR(120)", indexed=True, description="Duplicate-posting guard"),
                    DatabaseField(name="occurred_at", data_type="TIMESTAMPTZ", indexed=True, description="Authoritative posting time"),
                    DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Record creation time"),
                ],
                bounded_context="Ledger",
            ),
        ]

    def _ledger_relationships(self) -> list[DatabaseRelationship]:
        return [
            DatabaseRelationship(
                source="ledger_entries",
                target="accounts",
                relationship="many-to-one",
                description="Each ledger entry posts to exactly one ledger account; balanced sets share a transaction_id.",
                cardinality="many-to-one",
                foreign_key="ledger_entries.account_id",
                ownership_implication="The Ledger boundary owns postings; Accounts remain the aggregate root for balances.",
            ),
        ]

    def _audit_evidence(self, requirements: RequirementModel) -> bool:
        return audit_evidence(
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
        )

    def _entity_kind(self, identifier: str) -> str:
        from app.services.domain_inference import singularize

        tokens = {singularize(part) for part in identifier.split("_")}
        if tokens & {"ledger", "account", "journal", "posting", "entry", "entries"}:
            return "ledger"
        if tokens & _PARTY_TOKENS:
            return "party"
        if tokens & _CATALOG_TOKENS:
            return "catalog"
        if tokens & _TRANSACTIONAL_TOKENS:
            return "transactional"
        return "general"

    def _mentioned_identifiers(self, text: str, identifiers: list[str]) -> list[str]:
        """Identifiers mentioned in the text, in order of first appearance.

        Matching is tolerant (singular/plural, partner/partnerships) so
        brief wording still grounds the model without inventing concepts.
        """
        tokens = tokenize(text)
        singular_tokens = [singularize(token) for token in tokens]
        positions: dict[str, int] = {}
        for identifier in identifiers:
            parts = [part for part in identifier.split("_") if len(part) > 2]
            if not parts:
                continue
            hits = [
                self._part_position(part, tokens, singular_tokens) for part in parts
            ]
            if all(position is not None for position in hits):
                positions[identifier] = min(position for position in hits if position is not None)
        return sorted(positions, key=lambda name: positions[name])

    @staticmethod
    def _part_position(part: str, tokens: list[str], singular_tokens: list[str]) -> int | None:
        for index, (token, singular) in enumerate(zip(tokens, singular_tokens)):
            if part == token or part == singular:
                return index
            if len(part) >= 5 and (
                singular.startswith(part) or part.startswith(singular)
            ):
                return index
        return None

    def _generate_from_blueprint_entities(
        self, requirements: RequirementModel
    ) -> list[DatabaseEntity]:
        """Build tables from the brief's domain entities with kind-based
        lifecycle fields. Every table traces to an extracted domain concept."""
        identifiers = [to_identifier(hint.name) for hint in requirements.domain_entities]
        identifiers = [item for item in identifiers if item]
        contexts = cluster_entities(identifiers)
        entities: list[DatabaseEntity] = []
        for hint, identifier in zip(requirements.domain_entities, identifiers, strict=False):
            if not identifier or any(entity.name == identifier for entity in entities):
                continue
            if identifier in {"users", "audit_logs", "notifications"}:
                # Platform tables are added once, with evidence, by the caller.
                continue
            display = to_display_name(identifier)
            context = contexts.get(identifier, display)
            kind = self._entity_kind(identifier)
            fields = [DatabaseField(name="id", data_type="UUID", description="Primary key")]
            if kind == "party":
                fields.extend(
                    [
                        DatabaseField(name="name", data_type="VARCHAR(255)", description=f"{display} display name"),
                        DatabaseField(name="code", data_type="VARCHAR(80)", indexed=True, description=f"{display} business code"),
                        DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Lifecycle status"),
                        DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Creation time"),
                    ]
                )
            elif kind == "catalog":
                fields.extend(
                    [
                        DatabaseField(name="name", data_type="VARCHAR(255)", description=f"{display} display name"),
                        DatabaseField(name="sku", data_type="VARCHAR(80)", indexed=True, description="Stock keeping unit or catalog code"),
                        DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Catalog availability"),
                    ]
                )
            elif kind == "transactional":
                fields.extend(
                    [
                        DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Lifecycle status"),
                        DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Creation time"),
                        DatabaseField(name="updated_at", data_type="TIMESTAMPTZ", nullable=True, description="Last change time"),
                    ]
                )
            else:
                fields.extend(
                    [
                        DatabaseField(name="name", data_type="VARCHAR(255)", description=f"{display} display name"),
                        DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Lifecycle status"),
                        DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Creation time"),
                    ]
                )
            entities.append(
                DatabaseEntity(
                    name=identifier,
                    description=(
                        f"{display} in the {context} bounded context "
                        f"({hint.description or 'domain record'})."
                    ),
                    fields=fields,
                    bounded_context=context,
                )
            )
        return entities

    def _relationships_for_entities(
        self, requirements: RequirementModel, entities: list[DatabaseEntity]
    ) -> tuple[list[DatabaseRelationship], list[str]]:
        """Infer ownership relationships from workflow structure, requirement
        co-mention, compound containment, line-item patterns, and enumeration
        flow. Every rule is structural (no domain hardcoding); pattern-based
        assumptions are returned for review notes."""
        identifiers = [entity.name for entity in entities]
        by_name = {entity.name: entity for entity in entities}
        canonical_lookup = {
            tuple(singularize(part) for part in name.split("_") if part): name
            for name in identifiers
        }
        relationships: list[DatabaseRelationship] = []
        seen: set[tuple[str, str]] = set()
        assumed: list[str] = []

        def _link(source: str, target: str, reason: str, *, fk: bool = True) -> None:
            if source == target or (source, target) in seen or (target, source) in seen:
                return
            if source not in by_name or target not in by_name:
                return
            seen.add((source, target))
            if fk:
                target_singular = target[:-1] if target.endswith("s") and not target.endswith("ss") else target
                fk_field = f"{target_singular}_id"
                if not any(field.name == fk_field for field in by_name[source].fields):
                    by_name[source].fields.insert(
                        1,
                        DatabaseField(
                            name=fk_field,
                            data_type="UUID",
                            indexed=True,
                            description=f"Owning {to_display_name(target)} reference",
                        ),
                    )
            relationships.append(
                DatabaseRelationship(
                    source=source,
                    target=target,
                    relationship="many-to-one",
                    description=reason,
                    cardinality="many-to-one",
                    foreign_key=f"{source}.{fk_field}" if fk else None,
                    ownership_implication=f"{target} is the aggregate owner of related {source} records.",
                )
            )

        # Workflow aggregate roots own their related entities.
        for workflow in requirements.domain_workflows:
            if not re.search(
                r"\b(?:manage|create|make|book|assign|register|record|submit|issue|schedule"
                r"|process|generate|execute|perform|configure|calibrate|monitor|track|analyze"
                r"|simulate|inspect|review|collect|aggregate|transform|produce|compose|deploy"
                r"|provision|stream|transmit|receive|upload|download|sync|coordinate|orchestrate"
                r"|validate|verify|approve|evaluate|compute|render|publish|allocate|dispatch"
                r"|route|measure|index|scan|update|delete|remove|modify|handle|initiate"
                r"|maintain|store|retrieve|send|notify|trigger|run|start|stop|complete"
                r"|fulfill|reserve|cancel|return|transfer|convert|import|export|enroll"
                r"|grade|assess|diagnose|prescribe|administer|install|test|build|release"
                r"|plan|design|map|connect|integrate|link)\w*\b",
                workflow.description,
                re.I,
            ):
                continue
            members = [
                canonical_lookup.get(
                    tuple(
                        singularize(part)
                        for part in to_identifier(name).split("_")
                        if part
                    )
                )
                for name in workflow.related_entities
            ]
            members = list(dict.fromkeys(name for name in members if name in by_name))
            if len(members) >= 2:
                root, others = members[0], members[1:]
                for other in others:
                    _link(other, root, f"{other} belongs to {root} via the {workflow.name} workflow.")
        # Transactional records reference co-mentioned parties and catalogs.
        for requirement in requirements.functional_requirements:
            mentioned = self._mentioned_identifiers(requirement, identifiers)
            parties = [name for name in mentioned if self._entity_kind(name) == "party"]
            catalogs = [name for name in mentioned if self._entity_kind(name) == "catalog"]
            transactions = [name for name in mentioned if self._entity_kind(name) == "transactional"]
            for transaction in transactions:
                for party in parties:
                    _link(
                        transaction,
                        party,
                        f"{transaction} references {party} (co-mentioned requirement).",
                    )
                for catalog in catalogs:
                    _link(
                        transaction,
                        catalog,
                        f"{transaction} references {catalog} (co-mentioned requirement).",
                    )
            # General co-mention fallback: when no party/catalog/transactional
            # classification matched, link any two co-mentioned entities.
            if not parties and not catalogs and not transactions and len(mentioned) >= 2:
                root = mentioned[0]
                for other in mentioned[1:]:
                    _link(
                        other,
                        root,
                        f"{other} associated with {root} (co-mentioned in requirement).",
                    )
        # Compound containment: order_items belongs to orders (compared on
        # singularized tokens so plural blueprint names resolve).
        from app.services.domain_inference import singularize as _singularize

        token_sets = {
            name: {_singularize(part) for part in name.split("_")}
            for name in identifiers
        }
        for source in identifiers:
            source_tokens = token_sets[source]
            for target in identifiers:
                if len(target) >= len(source):
                    continue
                if token_sets[target] < source_tokens:
                    _link(source, target, f"{source} belongs to {target} (compound containment).")
        # Line-item pattern: X_items lines reference their parent order and
        # the first catalog entity (assumption, flagged for review).
        catalog_entities = [name for name in identifiers if self._entity_kind(name) == "catalog"]
        for source in identifiers:
            if not (source.endswith("_items") or source.endswith("_lines") or source.endswith("_entries")):
                continue
            if catalog_entities:
                _link(
                    source,
                    catalog_entities[0],
                    f"{source} references catalog {catalog_entities[0]} (line-item pattern; confirm).",
                )
                assumed.append(source)
        # Enumeration flow: "suppliers, facilities, partners, warehouses..."
        # after a movement verb describes a handoff chain; consecutive pairs
        # get flows-to links. Plain capability enumerations (no movement or
        # path language) never create flow links. Identifiers appearing
        # before the movement verb (the thing being moved, e.g. "Products
        # move through...") are skipped.
        movement_verbs = ("move", "moves", "flow", "flows", "travel", "travels", "pass", "passes", "route", "routes")
        for sentence in self._enumeration_sentences(requirements):
            lowered = sentence.casefold()
            has_movement = (
                any(f" {verb} " in f" {lowered} " for verb in movement_verbs)
                or " through " in lowered
            )
            if not has_movement:
                continue
            chain = [
                name for name in self._mentioned_identifiers(sentence, identifiers)
                if name in by_name
            ]
            verb_at = min(
                (lowered.find(f" {verb} ") for verb in movement_verbs if f" {verb} " in lowered),
                default=-1,
            )
            if verb_at >= 0:
                lead_text = lowered[:verb_at]
                chain = [
                    name for name in chain
                    if not any(
                        part in lead_text
                        for part in name.split("_")
                    )
                ]
            for first, second in zip(chain, chain[1:]):
                if (first, second) in seen or (second, first) in seen:
                    continue
                seen.add((first, second))
                relationships.append(
                    DatabaseRelationship(
                        source=first,
                        target=second,
                        relationship="flows-to",
                        description=f"{first} hands off to {second} (enumeration flow; confirm cardinality).",
                    )
                )
        # Universal FK injection fallback: if all heuristics above produced
        # fewer relationships than max(1, len(entities) - 1), fill gaps using
        # co-occurrence counting from functional requirements, then a simple
        # chain as the final fallback.
        min_desired = max(1, len(entities) - 1)
        if len(relationships) < min_desired and len(entities) >= 2:
            # Build co-occurrence matrix from functional requirements.
            pair_counts: dict[tuple[str, str], int] = {}
            for requirement in requirements.functional_requirements:
                mentioned = self._mentioned_identifiers(requirement, identifiers)
                mentioned = [name for name in mentioned if name in by_name]
                for i, a in enumerate(mentioned):
                    for b in mentioned[i + 1:]:
                        pair = (a, b) if a < b else (b, a)
                        pair_counts[pair] = pair_counts.get(pair, 0) + 1
            # Add relationships by co-occurrence (highest count first).
            for (a, b), _count in sorted(pair_counts.items(), key=lambda x: -x[1]):
                if len(relationships) >= min_desired:
                    break
                if (a, b) in seen or (b, a) in seen:
                    continue
                _link(
                    a,
                    b,
                    f"{a} references {b} (requirement co-occurrence; confirm relationship).",
                )
            # Last resort: sequential chain linking entities to the first one.
            if len(relationships) < min_desired:
                root = identifiers[0] if identifiers else None
                if root and root in by_name:
                    for other in identifiers[1:]:
                        if len(relationships) >= min_desired:
                            break
                        if other not in by_name:
                            continue
                        if (other, root) in seen or (root, other) in seen:
                            continue
                        _link(
                            other,
                            root,
                            f"{other} associated with {root} (structural assumption; confirm relationship).",
                        )
                        assumed.append(other)
        if assumed:
            return relationships, sorted(set(assumed))
        return relationships, []

    def _enumeration_sentences(self, requirements: RequirementModel) -> list[str]:
        """Source sentences enumerating 3+ domain entities in sequence."""
        sentences: list[str] = []
        for requirement in requirements.functional_requirements:
            segments = re.split(r",\s*|\s+and\s+", requirement)
            if len(segments) >= 4:
                sentences.append(requirement)
        return sentences

    def _generate_from_hints(self, requirements: RequirementModel) -> DatabaseDesign:
        entities: list[DatabaseEntity] = []
        relationships: list[DatabaseRelationship] = []
        indexes: list[str] = []

        for hint in requirements.domain_entities:
            entity_name = self._identifier(hint.name)
            if not entity_name or any(entity.name == entity_name for entity in entities):
                continue
            fields = [DatabaseField(name="id", data_type="UUID", description="Primary key")]
            seen_fields = {"id"}
            for attribute in hint.attributes[:8]:
                field_name = self._identifier(attribute)
                if not field_name or field_name in seen_fields:
                    continue
                seen_fields.add(field_name)
                fields.append(
                    DatabaseField(
                        name=field_name,
                        data_type=self._field_type(field_name),
                        nullable=True,
                        indexed=field_name.endswith("_id")
                        or field_name in {"status", "state", "code"},
                        description=attribute,
                    )
                )
                if fields[-1].indexed:
                    indexes.append(
                        f"CREATE INDEX idx_{entity_name}_{field_name} ON {entity_name}({field_name});"
                    )
            if len(fields) == 1:
                # An opaque `details JSONB` field hides the domain rather
                # than modelling it.  Use conservative lifecycle/reference
                # fields derived from the entity role; dynamic metadata is
                # allowed only when the brief explicitly requires it.
                fields.extend(self._semantic_default_fields(entity_name, hint.description))
            entities.append(
                DatabaseEntity(
                    name=entity_name,
                    description=hint.description or f"Domain record for {hint.name}.",
                    fields=fields,
                    bounded_context=hint.bounded_context,
                    source_evidence=hint.source_evidence,
                )
            )

        entity_names = {entity.name for entity in entities}
        singular_lookup = {
            self._singular(entity_name): entity_name for entity_name in entity_names
        }
        for entity in entities:
            for field in entity.fields:
                if not field.name.endswith("_id"):
                    continue
                reference_name = field.name[:-3]
                target = singular_lookup.get(reference_name)
                if target is None:
                    reference_name = re.sub(
                        r"^(?:source|destination|payer|recipient|owner|parent)_",
                        "",
                        reference_name,
                    )
                    target = singular_lookup.get(reference_name)
                if target and target != entity.name:
                    relationships.append(
                        DatabaseRelationship(
                            source=entity.name,
                            target=target,
                            relationship="many-to-one",
                            description=f"{entity.name}.{field.name} references {target}.id.",
                            cardinality="many-to-one",
                            foreign_key=f"{entity.name}.{field.name}",
                            ownership_implication=(
                                f"The {entity.bounded_context or to_display_name(entity.name)} boundary owns "
                                f"the reference; {target} remains owned by its bounded context."
                            ),
                            source_evidence=list(entity.source_evidence),
                        )
                    )

        inferred_relationships, assumed_relationships = self._relationships_for_entities(
            requirements, entities
        )
        existing_pairs = {(relation.source, relation.target) for relation in relationships}
        relationships.extend(
            relation
            for relation in inferred_relationships
            if (relation.source, relation.target) not in existing_pairs
            and (relation.target, relation.source) not in existing_pairs
        )

        contexts = cluster_entities([entity.name for entity in entities])
        for entity in entities:
            entity.bounded_context = entity.bounded_context or contexts.get(entity.name, to_display_name(entity.name))

        # Platform tables only with evidence, same rule as the blueprint path.
        platform_entities: list[DatabaseEntity] = []
        if auth_evidence(
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
        ):
            platform_entities.append(
                DatabaseEntity(
                    name="users",
                    description="Core platform users with role-based access.",
                    fields=[
                        DatabaseField(name="id", data_type="UUID", description="Primary key"),
                        DatabaseField(name="email", data_type="VARCHAR(255)", indexed=True, description="Unique login email"),
                        DatabaseField(name="role", data_type="VARCHAR(50)", indexed=True, description="Business role"),
                    ],
                    bounded_context="Identity",
                )
            )
            indexes.append("CREATE INDEX idx_users_role ON users(role);")
        if audit_evidence(
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
            *requirements.constraints,
        ):
            if not any(entity.name == "users" for entity in platform_entities):
                platform_entities.append(
                    DatabaseEntity(
                        name="users",
                        description="Core platform users with role-based access.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="email", data_type="VARCHAR(255)", indexed=True, description="Unique login email"),
                            DatabaseField(name="role", data_type="VARCHAR(50)", indexed=True, description="Business role"),
                        ],
                        bounded_context="Identity",
                    )
                )
                indexes.append("CREATE INDEX idx_users_role ON users(role);")
            platform_entities.append(
                DatabaseEntity(
                    name="audit_logs",
                    description="Immutable audit trail for major business and administrative actions.",
                    fields=[
                        DatabaseField(name="id", data_type="UUID", description="Primary key"),
                        DatabaseField(name="actor_id", data_type="UUID", indexed=True, description="Attribution reference"),
                        DatabaseField(name="event_type", data_type="VARCHAR(80)", indexed=True, description="Domain event type"),
                    ],
                    bounded_context="Governance",
                )
            )
            relationships.append(
                DatabaseRelationship(
                    source="audit_logs",
                    target="users",
                    relationship="many-to-one",
                    description="Every audit log entry is attributed to a user or system actor.",
                )
            )
            indexes.append("CREATE INDEX idx_audit_logs_event_type ON audit_logs(event_type);")
        # Banking/ledger semantics: the API contract promises balanced,
        # idempotent postings, so the relational model must back it with
        # accounts + immutable double-entry ledger_entries.
        if self._needs_ledger_model(requirements):
            existing_by_name = {
                self._singular(entity.name): entity for entity in [*platform_entities, *entities]
            }
            for ledger_entity in self._ledger_entities():
                ledger_key = self._singular(ledger_entity.name)
                existing_entity = existing_by_name.get(ledger_key)
                if existing_entity is None:
                    entities.append(ledger_entity)
                    existing_by_name[ledger_key] = ledger_entity
                else:
                    known_fields = {field.name for field in existing_entity.fields}
                    existing_entity.fields.extend(
                        field for field in ledger_entity.fields
                        if field.name not in known_fields
                    )
            existing_pairs = {(relation.source, relation.target) for relation in relationships}
            for relation in self._ledger_relationships():
                if (relation.source, relation.target) not in existing_pairs:
                    relationships.append(relation)
                    existing_pairs.add((relation.source, relation.target))
            indexes.extend([
                "CREATE UNIQUE INDEX uq_ledger_entries_idempotency ON ledger_entries(idempotency_key);",
                "CREATE INDEX idx_ledger_entries_transaction ON ledger_entries(transaction_id);",
            ])
        entities = [*platform_entities, *entities]

        return DatabaseDesign(
            database_engine="PostgreSQL (architecture recommendation)",
            entities=entities,
            relationships=relationships,
            indexes=self._dedupe(indexes),
            normalization_notes=[
                "Entity names and candidate attributes come from the validated requirement extraction.",
                "Attribute types and relationships are provisional until the open data-model questions are answered.",
                "Use object storage alongside the relational model if binary or high-volume data requires it.",
                *(
                    ["Some relationship cardinalities are inferred from workflow structure and should be confirmed."]
                    if assumed_relationships else []
                ),
            ],
            sql_schema=self._render_sql(entities, relationships),
            sample_inserts="-- Sample records are intentionally omitted until domain values are confirmed.",
        )

    def _semantic_default_fields(self, entity_name: str, description: str) -> list[DatabaseField]:
        """Minimal useful attributes for an extracted domain concept.

        These are type/lifecycle semantics, not a hidden template for a named
        industry.  They ensure every canonical entity has a stable business
        reference and auditable state while leaving unsupported detail open.
        """
        kind = self._entity_kind(entity_name)
        tokens = set(entity_name.split("_")) | set(tokenize(description))
        fields = [
            DatabaseField(name="external_reference", data_type="VARCHAR(120)", nullable=True, indexed=True, description="Business or source-system reference when one exists."),
            DatabaseField(name="status", data_type="VARCHAR(40)", nullable=True, indexed=True, description="Lifecycle state where the domain defines one."),
            DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Record creation time."),
            DatabaseField(name="updated_at", data_type="TIMESTAMPTZ", nullable=True, description="Most recent state change time."),
        ]
        if kind in {"party", "catalog", "general"}:
            fields.insert(0, DatabaseField(name="name", data_type="VARCHAR(255)", nullable=True, description="Human-readable business name."))
        if "event" in tokens:
            fields.extend([
                DatabaseField(name="event_type", data_type="VARCHAR(80)", indexed=True, description="Domain event classification."),
                DatabaseField(name="occurred_at", data_type="TIMESTAMPTZ", indexed=True, description="Time at which the event occurred."),
                DatabaseField(name="correlation_id", data_type="UUID", nullable=True, indexed=True, description="Workflow correlation reference."),
            ])
        if kind == "transactional":
            fields.append(DatabaseField(name="version", data_type="INTEGER", nullable=True, description="Optimistic-concurrency version when the workflow changes state."))
            # Retry-safe commands need idempotency even when the brief does
            # not name the column: without it the API idempotency contract
            # has no backing uniqueness constraint.
            if any(token in tokens for token in ("payment", "transfer", "order", "booking", "transaction", "settlement")):
                fields.append(DatabaseField(name="idempotency_key", data_type="VARCHAR(120)", nullable=True, indexed=True, description="Client-supplied idempotency key for safe retries."))
        if kind == "ledger":
            fields.extend([
                DatabaseField(name="account_id", data_type="UUID", indexed=True, description="Owning ledger account reference."),
                DatabaseField(name="debit_amount", data_type="NUMERIC(18,2)", nullable=True, description="Debit leg amount; exactly one leg is non-zero per entry."),
                DatabaseField(name="credit_amount", data_type="NUMERIC(18,2)", nullable=True, description="Credit leg amount; exactly one leg is non-zero per entry."),
                DatabaseField(name="currency", data_type="VARCHAR(8)", description="ISO currency code for the posting."),
                DatabaseField(name="booking_order", data_type="INTEGER", indexed=True, description="Authoritative booking sequence within the account."),
                DatabaseField(name="idempotency_key", data_type="VARCHAR(120)", indexed=True, description="Duplicate-posting guard for retry-safe ledger writes."),
                DatabaseField(name="occurred_at", data_type="TIMESTAMPTZ", indexed=True, description="Authoritative posting time."),
            ])
        return fields

    def _identifier(self, value: str) -> str:
        identifier = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return identifier[:63]

    def _singular(self, value: str) -> str:
        if value.endswith("ies"):
            return value[:-3] + "y"
        if value.endswith("s") and not value.endswith("ss"):
            return value[:-1]
        return value

    def _field_type(self, field_name: str) -> str:
        if field_name.endswith("_id"):
            return "UUID"
        if field_name.endswith("_at") or "timestamp" in field_name or field_name.endswith("_time"):
            return "TIMESTAMPTZ"
        if field_name.endswith("_date"):
            return "DATE"
        if field_name.startswith(("is_", "has_")):
            return "BOOLEAN"
        if any(token in field_name for token in ("count", "quantity", "sequence", "version")):
            return "INTEGER"
        if any(token in field_name for token in ("measurement", "value", "amount")):
            return "NUMERIC"
        if any(token in field_name for token in ("metadata", "coordinates", "geometry", "data")):
            return "JSONB"
        if any(token in field_name for token in ("uri", "url", "path", "description", "notes")):
            return "TEXT"
        return "VARCHAR(255)"

    def _dedupe(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    def _render_sql(
        self, entities: list[DatabaseEntity], relationships: list[DatabaseRelationship]
    ) -> str:
        lines = ["CREATE EXTENSION IF NOT EXISTS pgcrypto;", ""]
        relationship_map = {
            ("audit_logs", "actor_id"): "users(id)",
            ("chargers", "station_id"): "stations(id)",
            ("bookings", "user_id"): "users(id)",
            ("bookings", "station_id"): "stations(id)",
            ("bookings", "charger_id"): "chargers(id)",
            ("charging_sessions", "booking_id"): "bookings(id)",
            ("payments", "booking_id"): "bookings(id)",
            ("payments", "user_id"): "users(id)",
            ("prescriptions", "user_id"): "users(id)",
            ("orders", "user_id"): "users(id)",
            ("orders", "prescription_id"): "prescriptions(id)",
            ("order_items", "order_id"): "orders(id)",
            ("order_items", "product_id"): "products(id)",
            ("inventory", "product_id"): "products(id)",
            ("payments", "order_id"): "orders(id)",
            ("payments", "user_id"): "users(id)",
            ("shipments", "order_id"): "orders(id)",
            ("shipments", "courier_id"): "users(id)",
            ("workflows", "owner_id"): "users(id)",
            ("notifications", "user_id"): "users(id)",
        }
        # Dynamic foreign keys from inferred ownership relationships.
        for relation in relationships:
            if relation.relationship != "many-to-one":
                continue
            singular = (
                relation.target[:-1]
                if relation.target.endswith("s") and not relation.target.endswith("ss")
                else relation.target
            )
            relationship_map.setdefault(
                (relation.source, f"{singular}_id"), f"{relation.target}(id)"
            )
            relationship_map.setdefault(
                (relation.source, f"{relation.target}_id"), f"{relation.target}(id)"
            )

        for entity in entities:
            lines.append(f"CREATE TABLE {entity.name} (")
            column_lines: list[str] = []
            for field in entity.fields:
                nullable = "" if not field.nullable else " NULL"
                not_null = " NOT NULL" if not field.nullable else nullable
                default = " DEFAULT gen_random_uuid()" if field.name == "id" else ""
                column = f"  {field.name} {field.data_type}{default}{not_null}"
                if field.name == "id":
                    column += " PRIMARY KEY"
                fk_key = (entity.name, field.name)
                if fk_key in relationship_map:
                    column += f" REFERENCES {relationship_map[fk_key]}"
                column_lines.append(column)
            if entity.name == "ledger_entries":
                column_lines.append("  CHECK ((debit_amount IS NULL) <> (credit_amount IS NULL))")
                column_lines.append("  CHECK (COALESCE(debit_amount, 0) >= 0 AND COALESCE(credit_amount, 0) >= 0)")
            lines.append(",\n".join(column_lines))
            lines.append(");")
            lines.append("")
            if entity.name == "ledger_entries":
                lines.append("CREATE UNIQUE INDEX uq_ledger_entries_idempotency ON ledger_entries(idempotency_key);")
                lines.append("CREATE INDEX idx_ledger_entries_transaction ON ledger_entries(transaction_id);")
                lines.append("")
        return "\n".join(lines)

    def _sample_inserts(self, entities: list[DatabaseEntity]) -> str:
        entity_names = {entity.name for entity in entities}
        lines = []
        if "users" in entity_names:
            lines.extend(
                [
                    "INSERT INTO users (id, email, full_name, role, created_at)",
                    "VALUES (gen_random_uuid(), 'admin@archai.dev', 'ArchAI Admin', 'admin', NOW());",
                ]
            )
        else:
            lines.append("-- No identity seed: add user records once the auth model is confirmed.")
        if "products" in entity_names:
            lines.extend(
                [
                    "",
                    "INSERT INTO products (id, sku, name, requires_prescription, price, status)",
                    "VALUES (gen_random_uuid(), 'MED-001', 'Sample Medication', TRUE, 19.99, 'active');",
                ]
            )
        if "stations" in entity_names:
            lines.extend(
                [
                    "",
                    "INSERT INTO stations (id, name, city, status, geo_hash)",
                    "VALUES (gen_random_uuid(), 'Central Business District Hub', 'Bengaluru', 'active', 'tdr1v9k');",
                ]
            )
        if "workflows" in entity_names:
            lines.extend(
                [
                    "",
                    "INSERT INTO workflows (id, owner_id, status, payload, created_at)",
                    "SELECT gen_random_uuid(), id, 'draft', '{\"source\":\"seed\"}'::jsonb, NOW() FROM users LIMIT 1;",
                ]
            )
        return "\n".join(lines)
