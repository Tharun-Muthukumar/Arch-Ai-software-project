import json


def build_structured_prompt(stage: str, payload: dict) -> str:
    if stage == "unknown-domain-requirement-extraction":
        return (
            "You are ArchAI's domain-neutral requirements analyst. Analyze the raw project "
            "brief directly using your pretrained knowledge. No domain blueprint or generic "
            "platform template has been applied.\n"
            "Return only JSON matching the enforced schema.\n"
            "Category definitions (never mix them):\n"
            "- Source boundary: description is the product behavior/scope source. business_context explains the current "
            "business, motivation, scale, and desired outcomes; do NOT restate its current operations or goals as "
            "functional requirements or actors unless a sentence explicitly directs the application/platform/system. "
            "Business-context quality targets, constraints, and named integrations still belong in their typed fields.\n"
            "- functional_requirements: user-visible capabilities, each naming WHO does WHAT to WHICH business object "
            "(actor + action + object). Every noun and verb must come from the brief. Paraphrase minimally; never add "
            "objects, actions, or qualifiers the brief does not state. Viewing an item does not imply creating it.\n"
            "- non_functional_requirements: measurable qualities or behaviors (latency, availability, integrity, "
            "provenance, offline, safety, privacy) ONLY when the brief states the quality word or a numeric target. "
            "If the brief states no quality, return an empty list — never invent generic qualities.\n"
            "- explicit_constraints: hard obligations ONLY (must, must not, never, only, cannot, required, shall, "
            "at least, no more than). Soft goals and feature descriptions are not constraints. If none, return [].\n"
            "- actors: people, organizational roles, or active machine participants EXPLICITLY named in the brief "
            "who operate the software. Every word of an actor name (pluralization aside) must appear in the brief. "
            "Passive storage, external software, and the application/system itself are never actors — put them in "
            "integrations. Never turn a person who is only viewed/selected into an operator.\n"
            "- domain_entities: business records the brief names. Every word must appear in the brief. Never add "
            "generic records (Financial, Encryption, Auditability, Residency) or debate topics.\n"
            "- domain_workflows: 2-6 end-to-end flows that restate functional requirements in order; no new concepts.\n"
            "- integrations: only named or necessarily implied external systems. Never claim compatibility or "
            "synchronization with systems the brief does not name.\n"
            "- data_characteristics: only brief-evidenced characteristics (realtime, offline, immutable, safety, "
            "geospatial, transactional, volume). Never infer from domain norms.\n"
            "- assumptions: cautious inferences only, each starting with 'Assumption:'. Confirmed brief facts are never assumptions.\n"
            "- open_questions: architecture-critical gaps only. Questions must not imply an answer.\n"
            "Rules:\n"
            "- Describe the actual software domain with a concise, specific name.\n"
            "- Ground every requirement in the raw brief. Preserve explicitly named concepts.\n"
            "- Do not add authentication, dashboards, search, notifications, payments, CRUD, "
            "or admin features unless the brief justifies them.\n"
            "- Do not invent users, traffic, latency, availability, budgets, retention, team "
            "size, regions, dates, quantities, or other numeric constraints.\n"
            "- Do not select products or technologies such as cloud providers, databases, "
            "queues, frameworks, or orchestration tools unless the user explicitly requires one.\n"
            "- Put only named or necessarily implied external systems in integrations.\n"
            "- Never claim compatibility or synchronization with systems the brief does not name.\n"
            "- Actors are people, organizational roles, or active machine participants. Put passive "
            "storage and external software dependencies in integrations instead. Never use the "
            "application or system itself as an actor. Do not turn a person who is only viewed or "
            "selected into an operator unless the brief says they use the software.\n"
            "- Return actors, domain_entities, and domain_workflows as concise names only; ArchAI "
            "derives their descriptions and relationships from validated requirements.\n"
            "- Capture explicit realtime, offline, immutability, safety, geospatial, transactional, "
            "and data-volume characteristics in the appropriate structured fields.\n"
            "- State cautious inferences in assumptions, not as confirmed requirements.\n"
            "- Provide at most five concise qualitative non-functional requirements that are "
            "directly justified by brief wording. Never invent "
            "numeric targets; ask a question when a target is unknown. Do not infer realtime, "
            "offline, immutable, streaming, geospatial, or multi-region behavior from domain norms. "
            "An empty list is correct when the brief states no quality.\n"
            "- Put architecture-critical missing information in open_questions. Questions must "
            "not imply an answer.\n"
            "- Use domain-specific actors, entities, workflows, and terminology. Keep every item "
            "under 24 words, correct obvious spelling mistakes, and avoid generic filler. Keep "
            "source nouns and actions exact; do not substitute or add merely related domain concepts. "
            "For example, viewing an item does not imply creating or generating it.\n"
            f"Raw input JSON:\n{json.dumps(payload, indent=2)}"
        )

    if stage == "architecture-selection":
        return (
            "You are ArchAI's architecture strategist. Choose the three most suitable "
            "architecture styles for the brief from the supplied candidate catalog, "
            "including a hybrid when the signals genuinely call for split treatment "
            "(for example a small team with bursty or event-heavy slices, or a cohesive "
            "core with isolated high-scale workloads).\n"
            "Return only JSON matching the enforced schema: "
            '{"selected_ids": ["<id>", "<id>", "<id>"], "rationale": "<one or two sentences>"}.\n'
            "Rules:\n"
            "- selected_ids must contain exactly three unique ids, each from the candidate id list.\n"
            "- Prefer the deterministic suitability scores unless the brief text clearly justifies an override.\n"
            "- Include a hybrid id when scale pressure, variable demand, or team constraints make a pure style weaker than a composed one.\n"
            "- Do not invent new ids, technologies, vendors, or numeric targets.\n"
            "- Keep rationale under 40 words and grounded in the supplied signals.\n"
            f"Selection input JSON:\n{json.dumps(payload, indent=2)}"
        )

    if stage == "workspace-semantic-edit":
        return (
            "You are ArchAI's careful requirements editor. Interpret the user's raw edit in "
            "the supplied project context and return only JSON matching the enforced schema.\n"
            "Rules:\n"
            "- Preserve every explicit actor, action, object, qualifier, and negation.\n"
            "- Improve clarity and testability without changing the user's meaning.\n"
            "- Do not invent features, users, integrations, technologies, vendors, numbers, "
            "traffic, latency, availability, retention, regions, budgets, or team sizes.\n"
            "- Inferred characteristics must be direct technical consequences of explicit wording.\n"
            "- Put uncertain interpretations in assumptions and missing architecture-critical "
            "information in clarification_questions. Questions must not imply an answer.\n"
            "- Keep suggested_text under 60 words and each list item concise.\n"
            f"Raw edit and context JSON:\n{json.dumps(payload, indent=2)}"
        )

    if stage == "actor-semantic-generation":
        return (
            "You are ArchAI's principal actor and role modeling specialist. Analyze the compact "
            "project context, functional requirements, and integrations to identify ONLY genuine "
            "actors that actively interact with or operate the software system.\n\n"
            "An actor must be one of:\n"
            "- 'human': end user, operator, or specialist (e.g. 'Customer', 'Station Operator', 'Dispatcher')\n"
            "- 'organizational': internal business unit or team with distinct operational responsibilities (e.g. 'Customer Support Team')\n"
            "- 'external-partner': external commercial entity or partner organization (e.g. 'Delivery Partner', 'Wholesale Supplier')\n"
            "- 'external-system': autonomous external software system, service, or API (e.g. 'Payment Gateway', 'Legacy ERP')\n"
            "- 'device' or 'machine': physical hardware, telemetry source, or machine participant (e.g. 'Charging Kiosk', 'IoT Sensor')\n\n"
            "STRICT REJECTION RULES (Violations will cause validation rejection):\n"
            "1. NEVER output actions, verbs, or workflow names as actors (e.g. 'Coordinate Maintenance', 'Place Order', 'Manage Inventory' are REJECTED).\n"
            "2. NEVER output data concepts, records, or entities as actors (e.g. 'Data From Sensor', 'Shipment', 'Invoice', 'Telemetry' are REJECTED).\n"
            "3. NEVER output technologies, protocols, or infrastructure as actors (e.g. 'PostgreSQL', 'Kafka', 'REST API', 'Docker' are REJECTED).\n"
            "4. NEVER output generic nouns, system names, or the software itself as actors (e.g. 'System', 'Platform', 'Application', 'Software', 'User', 'Users' are REJECTED).\n"
            "5. NEVER output full sentences, clauses, or requirement fragments as actor names (e.g. 'Operators Use Data From Control Systems', 'That Allows Customer', 'Provide Secure Customer' are STRICTLY FORBIDDEN).\n"
            "6. Actor names must be concise role titles (1-4 words, capitalized, e.g. 'Customer', 'Delivery Partner', 'Customer Support Team').\n"
            "7. Distinguish external systems and partner organizations from human users.\n"
            "8. Deduplicate: do not create redundant variants of the same role (e.g. choose either 'Customer' or 'Buyer', not both).\n"
            "9. For every actor, supply:\n"
            "   - 'name': concise canonical title\n"
            "   - 'actor_type': one of 'human', 'organizational', 'external-partner', 'external-system', 'device', 'machine'\n"
            "   - 'responsibilities': 1-3 specific active responsibilities in this domain\n"
            "   - 'permissions': 1-3 explicit authorized actions/workflows this actor can initiate\n"
            "   - 'source_evidence': 1-2 brief quotes or requirement keys justifying this actor\n\n"
            f"Project Context JSON:\n{json.dumps(payload, indent=2)}"
        )

    stage_instruction = {
        "requirement-analysis": "Rewrite the summary in at most 35 words.",
        "architecture-generation": (
            "Rewrite each architecture overview in at most 30 words. "
            "Preserve every id and name exactly."
        ),
    }.get(stage, "Improve specificity concisely.")

    return (
        f"You are ArchAI's {stage} assistant.\n"
        "Return valid JSON only.\n"
        "Keep exactly the same schema shape and keys as the input seed.\n"
        f"{stage_instruction}\n"
        f"Seed JSON:\n{json.dumps(payload, indent=2)}"
    )
