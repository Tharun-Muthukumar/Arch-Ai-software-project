def test_ev_workspace_generates_clear_diagram_artifacts(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "VoltReserve",
            "description": (
                "Build an EV charging station booking platform for metro cities with "
                "station discovery, charger availability, slot booking, payments, "
                "refunds, operator controls, and charging session tracking."
            ),
            "business_context": (
                "The first release should support rapid city pilots with clear operator "
                "tooling and auditable payment flows."
            ),
            "preferred_cloud": "AWS",
            "constraints": ["Must use PostgreSQL", "Audit logs required"],
        },
    )

    assert response.status_code == 201
    workspace = response.json()

    assert workspace["requirements"]["domain"] == "EV Charging Booking Platform"
    assert set(workspace["diagrams"].keys()) == {
        "use_case",
        "activity",
        "sequence",
        "class",
        "er",
        "component",
        "deployment",
    }

    use_case = workspace["diagrams"]["use_case"]["mermaid"]
    er_diagram = workspace["diagrams"]["er"]["mermaid"]
    class_diagram = workspace["diagrams"]["class"]["mermaid"]

    # The project brief is not an actor and is no longer drawn as one; the
    # system boundary is a subgraph, and the real notation lives in
    # `use_case_model` (see tests/test_use_case_diagram.py).
    assert "Confirmed project brief" not in use_case
    assert "subgraph" in use_case
    assert "FR-001" in use_case
    assert "Driver" in use_case
    assert "charging" in use_case.lower()
    assert "pharmac" not in use_case.lower()

    use_case_model = workspace["diagrams"]["use_case"]["use_case_model"]
    assert use_case_model is not None
    assert any(actor["name"] == "Driver" for actor in use_case_model["actors"])

    assert "STATION" in er_diagram
    assert "CHARGER" in er_diagram
    assert "BOOKING" in er_diagram
    assert "PAYMENT" in er_diagram
    assert "||--o{" in er_diagram or "||--||" in er_diagram
    # Mermaid ER key notation, not a `*id` prefix invented into the name.
    assert "UUID id PK" in er_diagram
    assert " FK" in er_diagram, "foreign keys must be marked in the key slot"
    assert "*id" not in er_diagram
    # A nullable column is a comment, not part of the type. `VARCHAR?` is not
    # a type Mermaid understands.
    assert "?" not in er_diagram.replace("\\?", "")

    assert "Station" in class_diagram
    assert "Booking" in class_diagram
    assert "Payment" in class_diagram
    # UML members, and crucially parenthesis-free: a member containing `()` is
    # rendered by Mermaid in the methods compartment, which is where every
    # VARCHAR(255) column used to end up.
    assert "+id : UUID" in class_diagram
    assert "VARCHAR" not in class_diagram
    assert "(" not in class_diagram


def test_pharmacy_workspace_generates_domain_specific_diagrams(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "MediBridge",
            "description": (
                "Build an online pharmacy with medicine search, prescription upload, "
                "pharmacist verification, secure checkout, order tracking, "
                "inventory controls, and delivery partner updates."
            ),
            "business_context": (
                "The first release needs safe prescription handling, clear stock "
                "visibility, and operational fulfillment tracking."
            ),
            "preferred_cloud": "AWS",
            "constraints": ["Must use PostgreSQL", "Audit logs required"],
        },
    )

    assert response.status_code == 201
    workspace = response.json()

    assert workspace["requirements"]["domain"] == "Online Pharmacy"

    use_case = workspace["diagrams"]["use_case"]["mermaid"]
    activity = workspace["diagrams"]["activity"]["mermaid"]
    sequence = workspace["diagrams"]["sequence"]["mermaid"]
    er_diagram = workspace["diagrams"]["er"]["mermaid"]
    class_diagram = workspace["diagrams"]["class"]["mermaid"]

    assert "FR-001" in use_case
    assert "Customer" in use_case
    assert "prescription" in use_case.lower()
    assert "charging" not in use_case.lower()

    # The activity diagram used to hang every activity off a single
    # "Confirmed requirement model" hub — a star graph, not activity notation.
    # It is now start -> fork -> per-actor partitions -> join -> final.
    assert "Confirmed requirement model" not in activity
    assert "START" in activity and "FINAL" in activity
    assert "FORK" in activity and "JOIN" in activity
    assert "subgraph LANE1" in activity
    assert "prescription" in activity.lower()

    assert "System interface" in sequence
    assert "actor UserParticipant as" in sequence
    assert "actor Actor as" not in sequence
    assert any(term in sequence.lower() for term in ("catalog", "medicine", "prescription"))

    assert "INVENTORY" in er_diagram
    assert "PRESCRIPTION" in er_diagram
    assert "ORDER_ITEM" in er_diagram
    assert "PAYMENT" in er_diagram
    assert "SHIPMENT" in er_diagram

    assert "Inventory" in class_diagram
    assert "Prescription" in class_diagram
    assert "Shipment" in class_diagram
