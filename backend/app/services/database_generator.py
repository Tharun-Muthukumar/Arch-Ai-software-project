import re

from app.schemas.domain import (
    DatabaseDesign,
    DatabaseEntity,
    DatabaseField,
    DatabaseRelationship,
    RequirementModel,
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
        if requirements.analysis_source == "ollama-pretrained" and requirements.domain_entities:
            return self._generate_from_hints(requirements)

        lower_text = " ".join(requirements.functional_requirements).lower()
        entities = [
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
            ),
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
            ),
        ]
        relationships = [
            DatabaseRelationship(
                source="audit_logs",
                target="users",
                relationship="many-to-one",
                description="Every audit log entry is attributed to a user or system actor.",
            )
        ]

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
            entities.extend(
                [
                    DatabaseEntity(
                        name="workflows",
                        description="Primary business workflow records for the generated platform.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="owner_id", data_type="UUID", indexed=True, description="Owning user"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Workflow status"),
                            DatabaseField(name="payload", data_type="JSONB", description="Domain-specific data"),
                            DatabaseField(name="created_at", data_type="TIMESTAMPTZ", description="Creation time"),
                        ],
                    ),
                    DatabaseEntity(
                        name="notifications",
                        description="Outbound user and system notification requests.",
                        fields=[
                            DatabaseField(name="id", data_type="UUID", description="Primary key"),
                            DatabaseField(name="user_id", data_type="UUID", indexed=True, description="Recipient"),
                            DatabaseField(name="channel", data_type="VARCHAR(40)", description="Delivery channel"),
                            DatabaseField(name="status", data_type="VARCHAR(40)", indexed=True, description="Delivery status"),
                            DatabaseField(name="payload", data_type="JSONB", description="Message content"),
                        ],
                    ),
                ]
            )
            relationships.extend(
                [
                    DatabaseRelationship(
                        source="workflows",
                        target="users",
                        relationship="many-to-one",
                        description="Each workflow belongs to a user or account.",
                    ),
                    DatabaseRelationship(
                        source="notifications",
                        target="users",
                        relationship="many-to-one",
                        description="Notification recipients map to platform users.",
                    ),
                ]
            )

        indexes = [
            "CREATE INDEX idx_users_role ON users(role);",
            "CREATE INDEX idx_audit_logs_event_type ON audit_logs(event_type);",
            "CREATE INDEX idx_audit_logs_actor_id ON audit_logs(actor_id);",
        ]
        normalization_notes = [
            "Core transactional tables are normalized to third normal form.",
            "JSONB is reserved for extensible metadata, not for high-cardinality relational joins.",
            "Indexing prioritizes role lookups, status filters, and audit/event retrieval paths.",
        ]

        sql_schema = self._render_sql(entities, relationships)
        sample_inserts = self._sample_inserts(entities)

        return DatabaseDesign(
            database_engine="PostgreSQL",
            entities=entities,
            relationships=relationships,
            indexes=indexes,
            normalization_notes=normalization_notes,
            sql_schema=sql_schema,
            sample_inserts=sample_inserts,
        )

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
                fields.append(
                    DatabaseField(
                        name="details",
                        data_type="JSONB",
                        nullable=True,
                        description="Attributes to finalize after domain clarification.",
                    )
                )
            entities.append(
                DatabaseEntity(
                    name=entity_name,
                    description=hint.description or f"Domain record for {hint.name}.",
                    fields=fields,
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
                target = singular_lookup.get(field.name[:-3])
                if target and target != entity.name:
                    relationships.append(
                        DatabaseRelationship(
                            source=entity.name,
                            target=target,
                            relationship="many-to-one",
                            description=f"{entity.name} references {target}.",
                        )
                    )

        return DatabaseDesign(
            database_engine="PostgreSQL (architecture recommendation)",
            entities=entities,
            relationships=relationships,
            indexes=self._dedupe(indexes),
            normalization_notes=[
                "Entity names and candidate attributes come from the validated requirement extraction.",
                "Attribute types and relationships are provisional until the open data-model questions are answered.",
                "Use object storage alongside the relational model if binary or high-volume data requires it.",
            ],
            sql_schema=self._render_dynamic_sql(entities),
            sample_inserts="-- Sample records are intentionally omitted until domain values are confirmed.",
        )

    def _render_dynamic_sql(self, entities: list[DatabaseEntity]) -> str:
        statements: list[str] = []
        for entity in entities:
            columns: list[str] = []
            for field in entity.fields:
                suffix = " PRIMARY KEY DEFAULT gen_random_uuid()" if field.name == "id" else ""
                nullable = "" if field.nullable else " NOT NULL"
                columns.append(f"  {field.name} {field.data_type}{suffix}{nullable}")
            statements.extend(
                [f"CREATE TABLE {entity.name} (", ",\n".join(columns), ");", ""]
            )
        return "\n".join(statements).rstrip()

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
            lines.append(",\n".join(column_lines))
            lines.append(");")
            lines.append("")
        return "\n".join(lines)

    def _sample_inserts(self, entities: list[DatabaseEntity]) -> str:
        entity_names = {entity.name for entity in entities}
        lines = [
            "INSERT INTO users (id, email, full_name, role, created_at)",
            "VALUES (gen_random_uuid(), 'admin@archai.dev', 'ArchAI Admin', 'admin', NOW());",
        ]
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
