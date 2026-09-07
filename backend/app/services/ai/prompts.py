import json


def build_structured_prompt(stage: str, payload: dict) -> str:
    if stage == "unknown-domain-requirement-extraction":
        return (
            "You are ArchAI's domain-neutral requirements analyst. Analyze the raw project "
            "brief directly using your pretrained knowledge. No domain blueprint or generic "
            "platform template has been applied.\n"
            "Return only JSON matching the enforced schema.\n"
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
            "- Provide two to five concise qualitative non-functional requirements that are "
            "technically justified by the extracted actors, data, or workflows. Never invent "
            "numeric targets; ask a question when a target is unknown. Do not infer realtime, "
            "offline, immutable, streaming, geospatial, or multi-region behavior from domain norms.\n"
            "- Put architecture-critical missing information in open_questions. Questions must "
            "not imply an answer.\n"
            "- Use domain-specific actors, entities, workflows, and terminology. Keep every item "
            "under 24 words, correct obvious spelling mistakes, and avoid generic filler. Keep "
            "source nouns and actions exact; do not substitute or add merely related domain concepts. "
            "For example, viewing an item does not imply creating or generating it.\n"
            f"Raw input JSON:\n{json.dumps(payload, indent=2)}"
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

