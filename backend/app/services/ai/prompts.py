import json


def build_structured_prompt(stage: str, payload: dict) -> str:
    if stage == "project-description-extraction":
        return (
            "You convert one natural-language project description into ArchAI's existing "
            "project-creation fields. Return only JSON matching the enforced schema.\n"
            "The raw requirement is the sole source of facts.\n"
            "Rules:\n"
            "- title: a concise 2-8 word project name grounded in nouns from the prompt.\n"
            "- business_context_excerpts: copy only exact prompt excerpts about motivation, "
            "rollout, scale, organization, market, timeline, or business outcomes. Do not "
            "copy product capabilities into this field. Return [] when absent.\n"
            "- explicit_constraint_excerpts: copy exact prompt excerpts only when they state "
            "a hard obligation such as must, required, only, cannot, shall, at least, or at "
            "most. Preferences and ordinary feature statements are not constraints.\n"
            "- preferred_cloud: set only when AWS, Azure, GCP, on-premise, or no cloud "
            "preference is explicit. Otherwise return null.\n"
            "- team_size: set only when the prompt explicitly gives the number of engineers "
            "or developers. User/customer counts are not team size. Otherwise return null.\n"
            "- Never invent requirements, actors, integrations, technologies, vendors, "
            "numbers, regions, compliance rules, or quality targets.\n"
            "- Do not summarize or rewrite excerpts: copy them from the prompt so their "
            "source can be verified.\n"
            f"Raw input JSON:\n{json.dumps(payload, indent=2)}"
        )

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

    if stage == "architecture-image-chat":
        return (
            "You are ArchAI's image-grounded project assistant. Inspect the attached image, then return "
            "one compact JSON object with exactly these fields: answer (string), suggested_item "
            "(string or null), affected_components (array of strings). Answer the latest raw_requirement "
            "using only visible evidence. If text is unreadable, say so. Never infer hidden screens, "
            "actors, requirements, numbers, technologies, or relationships. affected_components may "
            "contain only exact names from component_names. When requested_item_type is null, set "
            "suggested_item to null. Otherwise provide one concise item of exactly that type only when "
            "the image supports it; use null if uncertain. Never claim a change was applied.\n"
            f"Input:{json.dumps(payload, separators=(',', ':'))}"
        )

    if stage == "architecture-chat":
        return (
            "You are ArchAI's grounded project and architecture assistant. Return schema-valid JSON only. "
            "Use only the supplied project, current architecture, deployment, conversation, and "
            "latest raw_requirement. Classify it as question or architecture_change.\n"
            "Question: explain represented facts, mark uncertainty, return no changes, and never "
            "claim state changed. Treat direct imperative requests such as add, remove, replace, "
            "switch, migrate, or use as architecture_change, even when the user gives no rationale. "
            "Change: propose the smallest patch and say it is only proposed; never claim it was applied. "
            "Use exact component names; replace_text.from_value must exist; component updates must "
            "preserve supplied fields and valid dependencies. You may add a functional requirement, "
            "non-functional requirement, constraint, or assumption only when the user explicitly asks "
            "for it; preserve the user's meaning and invent no numbers. If images are attached, inspect "
            "only visible evidence and clearly mark uncertainty. Never "
            "invent requirements, components, vendors, regions, compliance, or guarantees. "
            "Recommendations must be labeled as advice. Preserve unrelated design.\n"
            f"Input:{json.dumps(payload, separators=(',', ':'))}"
        )

    if stage == "architecture-risk-analysis":
        return (
            "You are ArchAI's evidence-grounded architecture risk reviewer. Return only JSON "
            "matching the enforced schema. Analyze the supplied current architecture against its "
            "actual project requirements and deployment data. Deterministic findings are already "
            "provided; add only distinct risks that those checks missed.\n"
            "Every finding needs concrete evidence from supplied structured fields. Do not infer a "
            "definite vulnerability from an omitted implementation detail. For absence-based or "
            "uncertain findings, use wording such as `Potential risk`, `Not explicitly represented`, "
            "or `Needs verification`, set needs_verification=true, and lower confidence.\n"
            "Affected components must be exact names from current_architecture.components. Use [] "
            "for a cross-cutting or unrepresented concern. Never invent components, traffic, "
            "availability, latency, regions, budgets, compliance rules, or incidents. Do not repeat "
            "a deterministic finding. Return at most three distinct risks. Keep each description, "
            "evidence, impact, and recommendation under 30 words. Recommendations are architecture "
            "advice, not user requirements.\n"
            f"Input:{json.dumps(payload, separators=(',', ':'))}"
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
