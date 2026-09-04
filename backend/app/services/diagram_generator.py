import re
from textwrap import wrap

from app.schemas.domain import (
    ArchitectureOption,
    DatabaseDesign,
    DatabaseEntity,
    DatabaseRelationship,
    DeploymentPlan,
    DiagramArtifact,
    RecommendationResult,
    RequirementModel,
)


class DiagramGenerator:
    def generate(
        self,
        requirements: RequirementModel,
        architectures: list[ArchitectureOption],
        recommendation: RecommendationResult,
        database_design: DatabaseDesign,
        deployment_plan: DeploymentPlan,
    ) -> dict[str, DiagramArtifact]:
        architecture_lookup = {item.id: item for item in architectures}
        recommended = architecture_lookup[recommendation.recommended_architecture_id]

        return {
            "use_case": self._use_case(requirements),
            "activity": self._activity(requirements),
            "sequence": self._sequence(requirements),
            "class": self._class_diagram(database_design),
            "er": self._er_diagram(database_design),
            "component": self._component(recommended),
            "deployment": self._deployment(deployment_plan),
        }

    def _use_case(self, requirements: RequirementModel) -> DiagramArtifact:
        if requirements.domain == "EV Charging Booking Platform":
            mermaid = "\n".join(
                [
                    "---",
                    "title: EV CHARGING STATION BOOKING SYSTEM",
                    "---",
                    "flowchart TD",
                    "    classDef actor fill:transparent,stroke:transparent,color:#7a5a3e,font-weight:bold;",
                    "    classDef usecase fill:#fff7ef,stroke:#af7743,color:#2d1d11,stroke-width:1.4px;",
                    "    classDef support fill:#f8e9d8,stroke:#c59764,color:#3f2a17,stroke-dasharray: 5 3;",
                    "    classDef external fill:#13263a,stroke:#4b6d8d,color:#f7f0e7;",
                    "",
                    '    Driver["Driver"]:::actor',
                    '    Operator["Station Operator"]:::actor',
                    '    Admin["Platform Admin"]:::actor',
                    '    Gateway["Payment Gateway"]:::external',
                    "",
                    '    Login([Register<br/>and sign in]):::usecase',
                    '    Dashboard([View booking<br/>dashboard]):::usecase',
                    '    Browse([Browse charging<br/>stations]):::usecase',
                    '    Availability([Check charger<br/>availability]):::usecase',
                    '    Reserve([Reserve charging<br/>slot]):::usecase',
                    '    Cancel([Cancel<br/>booking]):::usecase',
                    '    History([View payment<br/>history]):::usecase',
                    '    Session([Start and stop<br/>charging]):::usecase',
                    '    ManageStations([Manage<br/>stations]):::usecase',
                    '    ManageSlots([Manage charging<br/>slots]):::usecase',
                    '    Reports([Review reports<br/>and analytics]):::usecase',
                    '    Upcoming([Upcoming<br/>bookings]):::support',
                    '    Recent([Recent<br/>bookings]):::support',
                    '    Details([View station<br/>details]):::support',
                    '    SelectSlot([Select station<br/>and slot]):::support',
                    '    Payment([Make<br/>payment]):::support',
                    '    Refund([Request<br/>refund]):::support',
                    '    StationOps([Add, update, or<br/>deactivate station]):::support',
                    '    SlotOps([Add, update, or<br/>deactivate slots]):::support',
                    "",
                    "    Driver --> Login",
                    "    Driver --> Dashboard",
                    "    Driver --> Browse",
                    "    Driver --> Availability",
                    "    Driver --> Reserve",
                    "    Driver --> Cancel",
                    "    Driver --> History",
                    "    Driver --> Session",
                    "    Operator --> ManageStations",
                    "    Operator --> ManageSlots",
                    "    Admin --> ManageStations",
                    "    Admin --> ManageSlots",
                    "    Admin --> Reports",
                    "    Dashboard -. includes .-> Upcoming",
                    "    Dashboard -. includes .-> Recent",
                    "    Browse -. includes .-> Details",
                    "    Availability -. includes .-> Details",
                    "    Reserve -. includes .-> SelectSlot",
                    "    Reserve -. includes .-> Payment",
                    "    Cancel -. extends .-> Refund",
                    "    ManageStations -. includes .-> StationOps",
                    "    ManageSlots -. includes .-> SlotOps",
                    "    Gateway --> Payment",
                    "    Gateway --> Refund",
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "left to right direction",
                    "actor Driver",
                    "actor \"Station Operator\" as Operator",
                    "actor \"Platform Admin\" as Admin",
                    "actor \"Payment Gateway\" as Gateway",
                    'rectangle "EV CHARGING STATION BOOKING SYSTEM" {',
                    '  usecase "Register / sign in" as UC_Login',
                    '  usecase "View booking dashboard" as UC_Dashboard',
                    '  usecase "Browse charging stations" as UC_Browse',
                    '  usecase "Check charger availability" as UC_Availability',
                    '  usecase "Reserve charging slot" as UC_Reserve',
                    '  usecase "Cancel booking" as UC_Cancel',
                    '  usecase "View payment history" as UC_History',
                    '  usecase "Start / stop charging" as UC_Session',
                    '  usecase "Manage stations" as UC_ManageStations',
                    '  usecase "Manage charging slots" as UC_ManageSlots',
                    '  usecase "Review reports & analytics" as UC_Reports',
                    '  usecase "Upcoming bookings" as UC_Upcoming',
                    '  usecase "Recent bookings" as UC_Recent',
                    '  usecase "View station details" as UC_Details',
                    '  usecase "Select station & slot" as UC_Select',
                    '  usecase "Make payment" as UC_Payment',
                    '  usecase "Request refund" as UC_Refund',
                    '  usecase "Add / update / deactivate station" as UC_StationOps',
                    '  usecase "Add / update / deactivate slots" as UC_SlotOps',
                    "}",
                    "Driver --> UC_Login",
                    "Driver --> UC_Dashboard",
                    "Driver --> UC_Browse",
                    "Driver --> UC_Availability",
                    "Driver --> UC_Reserve",
                    "Driver --> UC_Cancel",
                    "Driver --> UC_History",
                    "Driver --> UC_Session",
                    "Operator --> UC_ManageStations",
                    "Operator --> UC_ManageSlots",
                    "Admin --> UC_ManageStations",
                    "Admin --> UC_ManageSlots",
                    "Admin --> UC_Reports",
                    "UC_Dashboard .> UC_Upcoming : <<include>>",
                    "UC_Dashboard .> UC_Recent : <<include>>",
                    "UC_Browse .> UC_Details : <<include>>",
                    "UC_Availability .> UC_Details : <<include>>",
                    "UC_Reserve .> UC_Select : <<include>>",
                    "UC_Reserve .> UC_Payment : <<include>>",
                    "UC_Cancel .> UC_Refund : <<extend>>",
                    "UC_ManageStations .> UC_StationOps : <<include>>",
                    "UC_ManageSlots .> UC_SlotOps : <<include>>",
                    "Gateway --> UC_Payment",
                    "Gateway --> UC_Refund",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Use Case Diagram",
                description="Shows the driver, operator, admin, and payment workflows for EV reservation, cancellation, charging, and station management within one clear system boundary.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        if requirements.domain == "Online Pharmacy":
            mermaid = "\n".join(
                [
                    "---",
                    "title: ONLINE PHARMACY SYSTEM",
                    "---",
                    "flowchart TD",
                    "    classDef actor fill:transparent,stroke:transparent,color:#7a5a3e,font-weight:bold;",
                    "    classDef usecase fill:#fff7ef,stroke:#af7743,color:#2d1d11,stroke-width:1.4px;",
                    "    classDef support fill:#f8e9d8,stroke:#c59764,color:#3f2a17,stroke-dasharray: 5 3;",
                    "    classDef external fill:#13263a,stroke:#4b6d8d,color:#f7f0e7;",
                    "",
                    '    Customer["Customer"]:::actor',
                    '    Pharmacist["Pharmacist"]:::actor',
                    '    Courier["Delivery Partner"]:::actor',
                    '    Admin["Operations Admin"]:::actor',
                    '    Gateway["Payment Gateway"]:::external',
                    "",
                    '    Login([Register<br/>and sign in]):::usecase',
                    '    Browse([Search medicine<br/>catalog]):::usecase',
                    '    PlaceOrder([Place<br/>order]):::usecase',
                    '    RxOrder([Place prescription<br/>order]):::usecase',
                    '    Track([Track order<br/>status]):::usecase',
                    '    History([Review order<br/>history]):::usecase',
                    '    Inventory([Manage inventory<br/>levels]):::usecase',
                    '    Catalog([Manage catalog<br/>and pricing]):::usecase',
                    '    Substitute([Approve substitutions<br/>when needed]):::usecase',
                    '    Dispatch([Prepare and dispatch<br/>order]):::usecase',
                    '    Reports([Review operational<br/>dashboards]):::usecase',
                    '    ViewDetails([View medicine<br/>details]):::support',
                    '    UploadRx([Upload<br/>prescription]):::support',
                    '    VerifyRx([Verify<br/>prescription]):::support',
                    '    Payment([Process<br/>payment]):::support',
                    '    DeliveryUpdate([Update delivery<br/>status]):::support',
                    "",
                    "    Customer --> Login",
                    "    Customer --> Browse",
                    "    Customer --> PlaceOrder",
                    "    Customer --> RxOrder",
                    "    Customer --> Track",
                    "    Customer --> History",
                    "    Pharmacist --> VerifyRx",
                    "    Pharmacist --> Inventory",
                    "    Pharmacist --> Substitute",
                    "    Pharmacist --> Dispatch",
                    "    Courier --> DeliveryUpdate",
                    "    Admin --> Catalog",
                    "    Admin --> Inventory",
                    "    Admin --> Reports",
                    "    Browse -. includes .-> ViewDetails",
                    "    PlaceOrder -. includes .-> Payment",
                    "    RxOrder -. extends .-> PlaceOrder",
                    "    RxOrder -. includes .-> UploadRx",
                    "    RxOrder -. includes .-> VerifyRx",
                    "    Gateway --> Payment",
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "left to right direction",
                    "actor Customer",
                    "actor Pharmacist",
                    "actor \"Delivery Partner\" as Courier",
                    "actor \"Operations Admin\" as Admin",
                    "actor \"Payment Gateway\" as Gateway",
                    'rectangle "ONLINE PHARMACY SYSTEM" {',
                    '  usecase "Register / sign in" as UC_Login',
                    '  usecase "Search medicine catalog" as UC_Browse',
                    '  usecase "Place order" as UC_PlaceOrder',
                    '  usecase "Place prescription order" as UC_RxOrder',
                    '  usecase "Track order status" as UC_Track',
                    '  usecase "Review order history" as UC_History',
                    '  usecase "Manage inventory levels" as UC_Inventory',
                    '  usecase "Manage catalog and pricing" as UC_Catalog',
                    '  usecase "Approve substitutions when needed" as UC_Substitute',
                    '  usecase "Prepare and dispatch order" as UC_Dispatch',
                    '  usecase "Review operational dashboards" as UC_Reports',
                    '  usecase "View medicine details" as UC_ViewDetails',
                    '  usecase "Upload prescription" as UC_UploadRx',
                    '  usecase "Verify prescription" as UC_VerifyRx',
                    '  usecase "Process payment" as UC_Payment',
                    '  usecase "Update delivery status" as UC_DeliveryUpdate',
                    "}",
                    "Customer --> UC_Login",
                    "Customer --> UC_Browse",
                    "Customer --> UC_PlaceOrder",
                    "Customer --> UC_RxOrder",
                    "Customer --> UC_Track",
                    "Customer --> UC_History",
                    "Pharmacist --> UC_VerifyRx",
                    "Pharmacist --> UC_Inventory",
                    "Pharmacist --> UC_Substitute",
                    "Pharmacist --> UC_Dispatch",
                    "Courier --> UC_DeliveryUpdate",
                    "Admin --> UC_Catalog",
                    "Admin --> UC_Inventory",
                    "Admin --> UC_Reports",
                    "UC_Browse .> UC_ViewDetails : <<include>>",
                    "UC_PlaceOrder .> UC_Payment : <<include>>",
                    "UC_RxOrder .> UC_PlaceOrder : <<extend>>",
                    "UC_RxOrder .> UC_UploadRx : <<include>>",
                    "UC_RxOrder .> UC_VerifyRx : <<include>>",
                    "Gateway --> UC_Payment",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Use Case Diagram",
                description="Shows the core customer, pharmacist, courier, admin, and payment interactions for catalog search, prescription handling, checkout, and fulfillment.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        actors = requirements.actors or []
        primary_actor = actors[0].name if len(actors) > 0 else "Primary User"
        secondary_actor = actors[1].name if len(actors) > 1 else "Secondary User"
        tertiary_actor = actors[2].name if len(actors) > 2 else "External Service"

        raw_requirements = requirements.functional_requirements[:6]
        primary_labels = [self._clean_use_case_label(r) for r in raw_requirements]
        primary_labels = [l for l in primary_labels if l]

        if len(primary_labels) < 3:
            primary_labels = primary_labels + ["View dashboard", "Manage settings", "Generate report"][
                : 3 - len(primary_labels)
            ]

        support_labels = self._derive_support_labels(primary_labels)

        num_primary = min(len(primary_labels), 6)
        num_support = min(len(support_labels), 3)

        mermaid_lines = [
            "flowchart TD",
            "    classDef actor fill:transparent,stroke:transparent,color:#7a5a3e,font-weight:bold;",
            "    classDef usecase fill:#fff7ef,stroke:#af7743,color:#2d1d11,stroke-width:1.4px;",
            "    classDef support fill:#f8e9d8,stroke:#c59764,color:#3f2a17,stroke-dasharray: 5 3;",
            "",
            f'    Primary["{primary_actor}"]:::actor',
        ]
        if num_primary > 3:
            mermaid_lines.append(f'    Secondary["{secondary_actor}"]:::actor')
        if num_support > 0:
            mermaid_lines.append(f'    External["{tertiary_actor}"]:::actor')

        mermaid_lines.append("")

        for i, label in enumerate(primary_labels[:num_primary], start=1):
            mermaid_lines.append(
                f'    UC{i}([{self._wrap_label(label, 18, html=True)}]):::usecase'
            )
        for i, label in enumerate(support_labels[:num_support], start=1):
            mermaid_lines.append(
                f'    SC{i}([{self._wrap_label(label, 14, html=True)}]):::support'
            )

        mermaid_lines.append("")

        for i in range(1, num_primary + 1):
            mermaid_lines.append(f"    Primary --> UC{i}")
        if num_primary > 3:
            mermaid_lines.append(f"    Secondary --> UC{num_primary}")
            mermaid_lines.append(f"    Secondary --> UC{max(1, num_primary - 1)}")
        for i in range(1, num_support + 1):
            mermaid_lines.append(f"    External --> SC{i}")
        for i in range(1, min(num_primary, num_support) + 1):
            mermaid_lines.append(f"    UC{i} -. includes .-> SC{i}")

        plantuml_lines = [
            "@startuml",
            "left to right direction",
            f'actor "{primary_actor}" as Primary',
        ]
        if num_primary > 3:
            plantuml_lines.append(f'actor "{secondary_actor}" as Secondary')
        if num_support > 0:
            plantuml_lines.append(f'actor "{tertiary_actor}" as External')
        plantuml_lines.append(f'rectangle "{requirements.domain.upper()}" {{')
        for i, label in enumerate(primary_labels[:num_primary], start=1):
            plantuml_lines.append(f'  usecase "{self._wrap_label(label, 18)}" as UC{i}')
        for i, label in enumerate(support_labels[:num_support], start=1):
            plantuml_lines.append(f'  usecase "{self._wrap_label(label, 14)}" as SC{i}')
        plantuml_lines.append("}")
        for i in range(1, num_primary + 1):
            plantuml_lines.append(f"Primary --> UC{i}")
        if num_primary > 3:
            plantuml_lines.append(f"Secondary --> UC{num_primary}")
            plantuml_lines.append(f"Secondary --> UC{max(1, num_primary - 1)}")
        for i in range(1, num_support + 1):
            plantuml_lines.append(f"External --> SC{i}")
        for i in range(1, min(num_primary, num_support) + 1):
            plantuml_lines.append(f"UC{i} .> SC{i} : <<include>>")
        plantuml_lines.append("@enduml")

        return DiagramArtifact(
            title="Use Case Diagram",
            description=f"Shows the primary actors and use cases for the {requirements.domain} system.",
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _activity(self, requirements: RequirementModel) -> DiagramArtifact:
        if requirements.domain == "EV Charging Booking Platform":
            mermaid = "\n".join(
                [
                    "flowchart TD",
                    '    Start([Driver opens platform]) --> Search["Search stations and filter connectors"]',
                    '    Search --> Details["Review station details and live availability"]',
                    '    Details --> Slot{"Slot available?"}',
                    '    Slot -- Yes --> Reserve["Reserve slot and confirm booking"]',
                    '    Slot -- No --> Search',
                    '    Reserve --> Pay["Authorize payment"]',
                    '    Pay --> Session["Start and monitor charging session"]',
                    '    Session --> Stop["Stop charging and capture usage"]',
                    '    Stop --> Summary["Send receipt, history, and analytics updates"]',
                    '    Summary --> End([Journey completed])',
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "start",
                    ":Search stations;",
                    ":Review details and availability;",
                    "if (Slot available?) then (yes)",
                    "  :Reserve slot;",
                    "  :Authorize payment;",
                    "  :Start charging session;",
                    "  :Stop charging and finalize usage;",
                    "  :Send receipt and history update;",
                    "else (no)",
                    "  :Try another station or slot;",
                    "endif",
                    "stop",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Activity Diagram",
                description="Shows the EV booking journey from station discovery through payment and charging completion.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        if requirements.domain == "Online Pharmacy":
            mermaid = "\n".join(
                [
                    "flowchart TD",
                    '    Start([Customer opens pharmacy]) --> Search["Search catalog and select medicines"]',
                    '    Search --> RxRequired{"Prescription required?"}',
                    '    RxRequired -- Yes --> Upload["Upload prescription"]',
                    '    Upload --> Review["Pharmacist verifies prescription"]',
                    '    Review --> Approved{"Prescription approved?"}',
                    '    Approved -- No --> Rework["Request correction or remove Rx items"]',
                    '    Rework --> Search',
                    '    Approved -- Yes --> Checkout["Confirm cart, address, and order"]',
                    '    RxRequired -- No --> Checkout',
                    '    Checkout --> Pay["Authorize payment"]',
                    '    Pay --> Reserve["Reserve inventory and create order"]',
                    '    Reserve --> Dispatch["Pick, pack, and dispatch shipment"]',
                    '    Dispatch --> Track["Send tracking updates and delivery status"]',
                    '    Track --> End([Order completed])',
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "start",
                    ":Search catalog and select medicines;",
                    "if (Prescription required?) then (yes)",
                    "  :Upload prescription;",
                    "  :Pharmacist verifies prescription;",
                    "  if (Prescription approved?) then (yes)",
                    "    :Confirm order;",
                    "  else (no)",
                    "    :Request correction or remove Rx items;",
                    "    :Return to product selection;",
                    "  endif",
                    "else (no)",
                    "  :Confirm order;",
                    "endif",
                    ":Authorize payment;",
                    ":Reserve inventory and create order;",
                    ":Pick, pack, and dispatch shipment;",
                    ":Send tracking updates and delivery status;",
                    "stop",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Activity Diagram",
                description="Shows the pharmacy order flow from product selection through prescription verification, payment, inventory reservation, and delivery updates.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        mermaid = "\n".join(
            [
                "flowchart TD",
                '    Brief([Brief submitted]) --> Analyze["Requirement analyzer extracts actors, constraints, and scale"]',
                '    Analyze --> Clarify{"Clarifications needed?"}',
                '    Clarify -- Yes --> Questions["Collect targeted follow-up answers"]',
                '    Questions --> Options["Generate architecture options"]',
                '    Clarify -- No --> Options["Generate architecture options"]',
                '    Options --> Compare["Score alternatives and recommend a direction"]',
                '    Compare --> Artifacts["Render diagrams, schema, APIs, and exports"]',
                '    Artifacts --> Finish([Workspace ready])',
            ]
        )
        plantuml = "\n".join(
            [
                "@startuml",
                "start",
                ":Collect project brief;",
                ":Extract requirements;",
                "if (Clarifications needed?) then (yes)",
                "  :Collect follow-up answers;",
                "endif",
                ":Generate architecture alternatives;",
                ":Compare, recommend, and render artifacts;",
                "stop",
                "@enduml",
            ]
        )
        return DiagramArtifact(
            title="Activity Diagram",
            description="Shows how the platform transforms a brief into a structured architecture workspace.",
            mermaid=mermaid,
            plantuml=plantuml,
        )

    def _sequence(self, requirements: RequirementModel) -> DiagramArtifact:
        if requirements.domain == "EV Charging Booking Platform":
            mermaid = "\n".join(
                [
                    "sequenceDiagram",
                    "    participant Driver",
                    "    participant Web as Web App",
                    "    participant API as Booking API",
                    "    participant Availability as Availability Service",
                    "    participant Payments as Payment Gateway",
                    "    participant Sessions as Session Service",
                    "    participant DB as PostgreSQL",
                    "    Driver->>Web: Search stations and pick a slot",
                    "    Web->>API: Request availability snapshot",
                    "    API->>Availability: Fetch live station and charger status",
                    "    Availability-->>API: Return open slots",
                    "    Driver->>Web: Confirm reservation",
                    "    Web->>Payments: Authorize payment",
                    "    Payments-->>Web: Payment approved",
                    "    Web->>API: Create booking",
                    "    API->>DB: Persist booking and payment state",
                    "    Driver->>Web: Start session",
                    "    Web->>Sessions: Start charging session",
                    "    Sessions->>DB: Save session telemetry",
                    "    Sessions-->>Web: Live session status",
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "actor Driver",
                    "participant \"Web App\" as Web",
                    "participant \"Booking API\" as API",
                    "participant \"Availability Service\" as Availability",
                    "participant \"Payment Gateway\" as Payments",
                    "participant \"Session Service\" as Sessions",
                    "database PostgreSQL",
                    "Driver -> Web : Search stations and pick a slot",
                    "Web -> API : Request availability snapshot",
                    "API -> Availability : Fetch live station and charger status",
                    "Availability --> API : Open slots",
                    "Driver -> Web : Confirm reservation",
                    "Web -> Payments : Authorize payment",
                    "Payments --> Web : Payment approved",
                    "Web -> API : Create booking",
                    "API -> PostgreSQL : Persist booking and payment state",
                    "Driver -> Web : Start session",
                    "Web -> Sessions : Start charging session",
                    "Sessions -> PostgreSQL : Save session telemetry",
                    "Sessions --> Web : Live session status",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Sequence Diagram",
                description="Illustrates the EV reservation flow across availability, payment, booking, and live session services.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        if requirements.domain == "Online Pharmacy":
            mermaid = "\n".join(
                [
                    "sequenceDiagram",
                    "    participant Customer",
                    "    participant Web as Web App",
                    "    participant Catalog as Catalog Service",
                    "    participant Prescription as Prescription Service",
                    "    participant Pharmacist as Pharmacist Console",
                    "    participant Orders as Order Service",
                    "    participant Payments as Payment Gateway",
                    "    participant Inventory as Inventory Service",
                    "    participant Delivery as Delivery Service",
                    "    participant DB as PostgreSQL",
                    "    Customer->>Web: Search medicine catalog",
                    "    Web->>Catalog: Query products and stock summary",
                    "    Catalog->>DB: Read catalog and inventory state",
                    "    Catalog-->>Web: Matching medicines",
                    "    Customer->>Web: Upload prescription for Rx items",
                    "    Web->>Prescription: Create prescription review",
                    "    Prescription->>DB: Persist prescription metadata",
                    "    Prescription-->>Pharmacist: Review request",
                    "    Pharmacist-->>Prescription: Approve prescription",
                    "    Customer->>Web: Confirm order",
                    "    Web->>Payments: Authorize payment",
                    "    Payments-->>Web: Payment approved",
                    "    Web->>Orders: Create order",
                    "    Orders->>Inventory: Reserve stock",
                    "    Inventory->>DB: Update inventory and order lines",
                    "    Orders->>Delivery: Create shipment and tracking",
                    "    Delivery->>DB: Persist shipment status",
                    "    Orders-->>Web: Confirmed order and tracking",
                    "    Web-->>Customer: Show order status",
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "actor Customer",
                    "participant \"Web App\" as Web",
                    "participant \"Catalog Service\" as Catalog",
                    "participant \"Prescription Service\" as Prescription",
                    "participant \"Pharmacist Console\" as Pharmacist",
                    "participant \"Order Service\" as Orders",
                    "participant \"Payment Gateway\" as Payments",
                    "participant \"Inventory Service\" as Inventory",
                    "participant \"Delivery Service\" as Delivery",
                    "database PostgreSQL",
                    "Customer -> Web : Search medicine catalog",
                    "Web -> Catalog : Query products and stock summary",
                    "Catalog -> PostgreSQL : Read catalog and inventory state",
                    "Catalog --> Web : Matching medicines",
                    "Customer -> Web : Upload prescription for Rx items",
                    "Web -> Prescription : Create prescription review",
                    "Prescription -> PostgreSQL : Persist prescription metadata",
                    "Prescription --> Pharmacist : Review request",
                    "Pharmacist --> Prescription : Approve prescription",
                    "Customer -> Web : Confirm order",
                    "Web -> Payments : Authorize payment",
                    "Payments --> Web : Payment approved",
                    "Web -> Orders : Create order",
                    "Orders -> Inventory : Reserve stock",
                    "Inventory -> PostgreSQL : Update inventory and order lines",
                    "Orders -> Delivery : Create shipment and tracking",
                    "Delivery -> PostgreSQL : Persist shipment status",
                    "Orders --> Web : Confirmed order and tracking",
                    "Web --> Customer : Show order status",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Sequence Diagram",
                description="Illustrates the pharmacy flow across catalog lookup, prescription approval, payment, inventory reservation, and shipment tracking.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        mermaid = "\n".join(
            [
                "sequenceDiagram",
                "    participant User",
                "    participant UI as Frontend",
                "    participant API as FastAPI",
                "    participant Engine as Decision Engine",
                "    participant DB as PostgreSQL",
                "    User->>UI: Submit project brief",
                "    UI->>API: POST /workspaces",
                "    API->>Engine: Run analysis pipeline",
                "    Engine->>DB: Persist generated artifacts",
                "    API-->>UI: Return workspace snapshot",
                "    UI-->>User: Present diagrams, comparison, and docs",
            ]
        )
        plantuml = "\n".join(
            [
                "@startuml",
                "actor User",
                "participant Frontend",
                "participant FastAPI",
                "participant Engine",
                "database PostgreSQL",
                "User -> Frontend : Submit project brief",
                "Frontend -> FastAPI : POST /workspaces",
                "FastAPI -> Engine : Run analysis pipeline",
                "Engine -> PostgreSQL : Save workspace",
                "FastAPI --> Frontend : Workspace response",
                "Frontend --> User : Present generated outputs",
                "@enduml",
            ]
        )
        return DiagramArtifact(
            title="Sequence Diagram",
            description="Illustrates the request-response flow from brief submission to rendered workspace output.",
            mermaid=mermaid,
            plantuml=plantuml,
        )

    def _class_diagram(self, database_design: DatabaseDesign) -> DiagramArtifact:
        selected_entities = self._diagram_entities(database_design)
        selected_names = {entity.name for entity in selected_entities}

        mermaid_lines = ["classDiagram"]
        plantuml_lines = ["@startuml", "hide empty members"]

        for entity in selected_entities:
            alias = self._entity_alias(entity.name)
            mermaid_lines.append(f"class {alias} {{")
            plantuml_lines.append(f"class {alias} {{")
            for field in entity.fields[:6]:
                field_type = f"{field.data_type}{'?' if field.nullable else ''}"
                mermaid_lines.append(f"  {field.name}: {field_type}")
                plantuml_lines.append(f"  {field.name} : {field_type}")
            mermaid_lines.append("}")
            plantuml_lines.append("}")

        for relation in database_design.relationships:
            if relation.source not in selected_names or relation.target not in selected_names:
                continue
            parent = self._entity_alias(relation.target)
            child = self._entity_alias(relation.source)
            parent_cardinality, child_cardinality = self._class_cardinality(
                relation.relationship
            )
            label = self._relationship_label(relation)
            mermaid_lines.append(
                f'{parent} "{parent_cardinality}" --> "{child_cardinality}" {child} : {label}'
            )
            plantuml_lines.append(
                f'{parent} "{parent_cardinality}" --> "{child_cardinality}" {child} : {label}'
            )

        plantuml_lines.append("@enduml")
        return DiagramArtifact(
            title="Class Diagram",
            description="Highlights the core platform entities, key fields, and relationship multiplicities.",
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _er_diagram(self, database_design: DatabaseDesign) -> DiagramArtifact:
        selected_entities = self._diagram_entities(database_design)
        selected_names = {entity.name for entity in selected_entities}
        diagram_names = {
            entity.name: self._entity_diagram_name(entity.name) for entity in selected_entities
        }

        entity_blocks: list[str] = []
        for entity in selected_entities:
            entity_blocks.append(f"    {diagram_names[entity.name]} {{")
            for field in entity.fields[:6]:
                field_type = re.sub(r"\(.*?\)", "", field.data_type)
                nullable = "?" if field.nullable else ""
                prefix = "*" if field.name == "id" else ""
                entity_blocks.append(f"        {field_type}{nullable} {prefix}{field.name}")
            entity_blocks.append("    }")

        relations = []
        for relation in database_design.relationships:
            if relation.source not in selected_names or relation.target not in selected_names:
                continue
            parent_left, child_right = self._er_cardinality(relation.relationship)
            label = self._relationship_label(relation)
            relations.append(
                f'    {diagram_names[relation.target]} {parent_left}--{child_right} {diagram_names[relation.source]} : "{label}"'
            )

        plantuml_lines = ["@startuml", "!theme plain", "hide circle"]
        for entity in selected_entities:
            plantuml_lines.append(f"entity {diagram_names[entity.name]} {{")
            for field in entity.fields[:6]:
                field_type = f"{field.data_type}{'?' if field.nullable else ''}"
                prefix = "*" if field.name == "id" else ""
                plantuml_lines.append(f"  {prefix}{field.name} : {field_type}")
            plantuml_lines.append("}")
        for relation in database_design.relationships:
            if relation.source not in selected_names or relation.target not in selected_names:
                continue
            parent_left, child_right = self._er_cardinality(relation.relationship)
            plantuml_lines.append(
                f"{diagram_names[relation.target]} {parent_left}--{child_right} {diagram_names[relation.source]} : {self._relationship_label(relation)}"
            )
        plantuml_lines.append("@enduml")

        return DiagramArtifact(
            title="ER Diagram",
            description="Displays a clearer relational view with primary keys, optional fields, and explicit relationship cardinalities.",
            mermaid="\n".join(["erDiagram", *entity_blocks, *relations]),
            plantuml="\n".join(plantuml_lines),
        )

    def _component(self, architecture: ArchitectureOption) -> DiagramArtifact:
        grouped_components = {
            "Experience Layer": [],
            "Application Services": [],
            "Data & State": [],
            "Async & Operations": [],
        }

        for component in architecture.components:
            tier = self._component_tier(component.name)
            grouped_components[tier].append(component)

        mermaid_lines = ["flowchart LR"]
        for group_name, components in grouped_components.items():
            if not components:
                continue
            group_id = self._to_identifier(group_name).upper()
            mermaid_lines.append(f'    subgraph {group_id}["{group_name}"]')
            mermaid_lines.append("        direction TB")
            for component in components:
                component_id = self._component_id(component.name)
                label = self._wrap_label(
                    f"{component.name}\n{', '.join(component.technologies[:2])}", 18, html=True
                )
                mermaid_lines.append(f'        {component_id}["{label}"]')
            mermaid_lines.append("    end")

        for left, right in zip(architecture.components, architecture.components[1:]):
            mermaid_lines.append(
                f"    {self._component_id(left.name)} --> {self._component_id(right.name)}"
            )

        plantuml_lines = ["@startuml", "skinparam componentStyle rectangle"]
        for group_name, components in grouped_components.items():
            if not components:
                continue
            plantuml_lines.append(f'package "{group_name}" {{')
            for component in components:
                plantuml_lines.append(
                    f'component "{component.name}\\n{", ".join(component.technologies[:2])}" as {self._component_id(component.name)}'
                )
            plantuml_lines.append("}")
        for left, right in zip(architecture.components, architecture.components[1:]):
            plantuml_lines.append(
                f"{self._component_id(left.name)} --> {self._component_id(right.name)}"
            )
        plantuml_lines.append("@enduml")

        return DiagramArtifact(
            title="Component Diagram",
            description="Groups the recommended runtime building blocks into clearer architectural tiers.",
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _deployment(self, deployment_plan: DeploymentPlan) -> DiagramArtifact:
        mermaid = "\n".join(
            [
                "flowchart TB",
                '    Browser["Client Browser"] --> Edge["Edge Delivery<br/>CDN / NGINX"]',
                '    subgraph APP["Application Runtime"]',
                "        direction LR",
                '        API["FastAPI API"]',
                '        Worker["Background Jobs"]',
                "    end",
                '    subgraph DATA["Data & Persistence"]',
                "        direction LR",
                '        DB["PostgreSQL"]',
                '        Cache["Redis / Queue"]',
                '        Artifact["Export Storage"]',
                "    end",
                "    Edge --> API",
                "    API --> DB",
                "    API --> Cache",
                "    API --> Worker",
                "    Worker --> Artifact",
                "    Worker --> DB",
            ]
        )
        plantuml = "\n".join(
            [
                "@startuml",
                "node \"Client Browser\" as Browser",
                "node \"Edge Delivery\\nCDN / NGINX\" as Edge",
                "node \"Application Runtime\" {",
                "  node \"FastAPI API\" as API",
                "  node \"Background Jobs\" as Worker",
                "}",
                "node \"Data & Persistence\" {",
                "  database PostgreSQL as DB",
                "  queue \"Redis / Queue\" as Cache",
                "  artifact \"Export Storage\" as Artifact",
                "}",
                "Browser --> Edge",
                "Edge --> API",
                "API --> DB",
                "API --> Cache",
                "API --> Worker",
                "Worker --> Artifact",
                "Worker --> DB",
                "@enduml",
            ]
        )
        return DiagramArtifact(
            title="Deployment Diagram",
            description="Shows the runtime footprint with clearer separation between edge delivery, application services, and persistence.",
            mermaid=mermaid,
            plantuml=plantuml,
        )

    def _clean_use_case_label(self, requirement: str) -> str:
        cleaned = requirement.strip().rstrip(".")
        cleaned = re.sub(
            r"^(the system (shall|must|should|will)|we (shall|must|should|will)|it (shall|must|should|will))\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(support|allow|enable|provide|expose|deliver|keep|implement|handle|process|ensure|maintain|manage|offer|give|make)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.split(r"\s+(with|using|via|through|including|that|which)\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
        cleaned = cleaned.replace(" and ", " & ").replace("/", " / ")
        if not cleaned:
            return ""
        return cleaned[0].upper() + cleaned[1:]

    def _derive_support_labels(self, primary_labels: list[str]) -> list[str]:
        supports: list[str] = []
        seen: set[str] = set()
        for label in primary_labels:
            lower = label.lower()
            candidates: list[str] = []
            if any(kw in lower for kw in ("search", "browse", "find", "catalog", "list")):
                candidates.append("View details")
            if any(kw in lower for kw in ("create", "add", "register", "sign up", "new")):
                candidates.append("Confirm entry")
            if any(kw in lower for kw in ("pay", "checkout", "purchase", "billing", "invoice")):
                candidates.append("Process payment")
            if any(kw in lower for kw in ("cancel", "refund", "withdraw")):
                candidates.append("Process refund")
            if any(kw in lower for kw in ("report", "analytics", "dashboard", "stats")):
                candidates.append("Export data")
            if any(kw in lower for kw in ("upload", "import", "attach")):
                candidates.append("Validate file")
            if any(kw in lower for kw in ("track", "monitor", "status")):
                candidates.append("View progress")
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    supports.append(c)
        return supports[:3]

    def _entity_alias(self, entity_name: str) -> str:
        singular = entity_name
        if singular.endswith("ies"):
            singular = singular[:-3] + "y"
        elif singular.endswith("s") and not singular.endswith("ss"):
            singular = singular[:-1]
        return "".join(part.capitalize() for part in singular.split("_"))

    def _entity_diagram_name(self, entity_name: str) -> str:
        singular = entity_name
        if singular.endswith("ies"):
            singular = singular[:-3] + "y"
        elif singular.endswith("s") and not singular.endswith("ss"):
            singular = singular[:-1]
        return "_".join(part.upper() for part in singular.split("_"))

    def _relationship_label(self, relation: DatabaseRelationship) -> str:
        source = relation.source
        target = relation.target
        if source == "chargers" and target == "stations":
            return "belongs to"
        if source == "bookings" and target == "users":
            return "made by"
        if source == "bookings" and target == "stations":
            return "at"
        if source == "bookings" and target == "chargers":
            return "uses"
        if source == "charging_sessions" and target == "bookings":
            return "linked to"
        if source == "payments" and target == "bookings":
            return "for"
        if source == "payments" and target == "users":
            return "made by"
        if source == "inventory" and target == "products":
            return "tracks"
        if source == "prescriptions" and target == "users":
            return "uploaded by"
        if source == "orders" and target == "users":
            return "placed by"
        if source == "orders" and target == "prescriptions":
            return "linked to"
        if source == "payments" and target == "orders":
            return "for"
        if source == "shipments" and target == "orders":
            return "fulfills"
        if source == "shipments" and target == "users":
            return "delivered to"
        if source == "audit_logs":
            return "tracks"
        if source == "prescriptions":
            return "references"
        if source == "order_items" and target == "orders":
            return "in"
        if source == "order_items" and target == "products":
            return "contains"
        if source == "notifications":
            return "sends to"
        source_clean = source.replace("_", " ").rstrip("s")
        target_clean = target.replace("_", " ").rstrip("s")
        return f"of {target_clean}"

    def _class_cardinality(self, relationship: str) -> tuple[str, str]:
        if relationship == "one-to-one":
            return ("1", "0..1")
        if relationship == "one-to-many":
            return ("0..*", "1")
        return ("1", "0..*")

    def _er_cardinality(self, relationship: str) -> tuple[str, str]:
        if relationship == "one-to-one":
            return ("||", "||")
        if relationship == "one-to-many":
            return ("o{", "||")
        return ("||", "o{")

    def _component_tier(self, component_name: str) -> str:
        lower_name = component_name.lower()
        if any(keyword in lower_name for keyword in ("client", "frontend", "web", "gateway")):
            return "Experience Layer"
        if any(keyword in lower_name for keyword in ("postgres", "database", "persistence", "redis")):
            return "Data & State"
        if any(keyword in lower_name for keyword in ("background", "workflow", "event", "queue")):
            return "Async & Operations"
        return "Application Services"

    def _component_id(self, component_name: str) -> str:
        return self._to_identifier(component_name).upper()

    def _diagram_entities(self, database_design: DatabaseDesign) -> list[DatabaseEntity]:
        entity_names = {entity.name for entity in database_design.entities}
        if {"stations", "chargers", "bookings"}.issubset(entity_names):
            priority_order = [
                "users",
                "stations",
                "chargers",
                "bookings",
                "charging_sessions",
                "payments",
                "audit_logs",
            ]
            limit = 6
        elif {"products", "prescriptions", "orders"}.issubset(entity_names):
            priority_order = [
                "users",
                "products",
                "inventory",
                "prescriptions",
                "orders",
                "order_items",
                "payments",
                "shipments",
            ]
            limit = 8
        elif {"products", "orders"}.issubset(entity_names):
            priority_order = [
                "users",
                "products",
                "orders",
                "order_items",
                "payments",
                "shipments",
                "audit_logs",
            ]
            limit = 7
        else:
            priority_order = []
            limit = 6
        lookup = {entity.name: entity for entity in database_design.entities}
        selected: list[DatabaseEntity] = []

        for entity_name in priority_order:
            entity = lookup.get(entity_name)
            if entity and entity not in selected:
                selected.append(entity)
            if len(selected) == limit:
                return selected

        for entity in database_design.entities:
            if entity not in selected:
                selected.append(entity)
            if len(selected) == limit:
                break

        return selected

    def _to_identifier(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")

    def _wrap_label(self, value: str, width: int, html: bool = False) -> str:
        pieces = wrap(value, width=width) or [value]
        separator = "<br/>" if html else "\\n"
        return separator.join(pieces)
