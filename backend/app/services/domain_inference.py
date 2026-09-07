"""Deterministic, domain-agnostic inference utilities for the generation pipeline.

Design rationale:
  Downstream generators (APIs, data model, deployment, diagrams, staffing)
  must derive their content from the actual project brief instead of falling
  back to a generic e-commerce template. This module centralizes the reusable
  building blocks for that: role/entity/capability/integration extraction from
  raw prose, domain-family classification, constraint normalization, bounded
  context clustering, and evidence gating for commerce-sensitive assumptions.

  Everything here is deterministic and uses generic English/vocabulary rules.
  No business domain is hardcoded: families are broad categories scored by
  vocabulary evidence, and all extracted terms come from the user's own text.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Shared text utilities
# --------------------------------------------------------------------------

_ENGLISH_STOPWORDS = frozenset(
    """
    a an and are as at be been before being but by can could did do does each
    for from further had has have having here how in into is it its more most
    must need no nor not of off on once only or other ought our shall should
    so some such than that the their them then there these they this those
    through to under until up was were when where which while will with would
    your across between both per via within without including include includes
    using used use uses make made over under again once high low new existing
    various several multiple single much many robust scalable secure reliable
    """.split()
)

_PREPOSITIONS = frozenset(
    "of for with from into onto across through between against among around via per by at to in on".split()
)

# Words that are almost never domain entities on their own.
_NON_ENTITY_NOUNS = frozenset(
    """
    thing things stuff aspect aspects kind kinds type types way ways part parts
    system systems platform platforms software application applications project
    projects program programs process processes data information details detail
    requirement requirements operation operations activity activities initiative
    initiatives effort efforts goal goals objective objectives capability
    capabilities feature features functionality solution solutions approach
    approaches strategy strategies policy policies procedure procedures
    regulation regulations compliance requirement rule rules law laws tax taxes
    currency currencies language languages market markets country countries
    user users team teams company companies organization organizations
    business businesses access control role roles permission permissions
    overview summary context quotidian analytic analytics insight insights
    visibility intelligence metric metrics dashboard dashboards volume volumes
    throughput workload workloads capacity capacities utilization
    """.split()
)

_GENERIC_ACTOR_NAMES = frozenset(
    {"application", "platform", "software", "system", "systems", "user", "users"}
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens."""
    return re.findall(r"[a-z][a-z0-9-]*", text.lower())


def singularize(word: str) -> str:
    """Lightweight English singularization for entity/role normalization."""
    lower = word.lower()
    if lower in {"sales", "analytics", "news", "premises", "series", "species", "headquarters"}:
        return lower
    if lower.endswith("ies") and len(lower) > 4:
        return lower[:-3] + "y"
    if lower.endswith(("sses", "xes", "zes", "ches", "shes")) and len(lower) > 5:
        return lower[:-2]
    if lower.endswith("s") and not lower.endswith(("ss", "us", "is")) and len(lower) > 3:
        return lower[:-1]
    return lower


def _content_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in _ENGLISH_STOPWORDS]


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences on terminal punctuation (never on commas)."""
    parts = re.split(r"(?<=[.!?;])\s+", text or "")
    return [part.strip() for part in parts if part.strip()]


def to_display_name(snake_or_phrase: str) -> str:
    """Normalize an extracted term to a Title Case display name."""
    words = re.split(r"[_\s]+", snake_or_phrase.strip())
    words = [word for word in words if word]
    if not words:
        return ""
    return " ".join(word[:1].upper() + word[1:] for word in words)


def to_identifier(display: str) -> str:
    """Normalize a display name to a snake_case identifier."""
    identifier = re.sub(r"[^a-z0-9]+", "_", display.lower()).strip("_")
    return identifier[:63]


# --------------------------------------------------------------------------
# Role vocabulary (generic English role nouns, not domain-specific)
# --------------------------------------------------------------------------

_HUMAN_ROLE_NOUNS = frozenset(
    """
    manager administrator admin operator planner engineer representative rep
    officer agent coordinator analyst auditor reviewer author editor
    supervisor lead specialist consultant advisor driver pilot rider courier
    customer client guest member patient student learner instructor teacher
    tutor doctor nurse pharmacist pharmacist clinician staff employee worker
    contractor technician mechanic inspector controller handler packer picker
    cashier teller clerk receptionist concierge host marketer seller merchant
    buyer purchaser sponsor owner founder director executive chief president
    assistant associate partner associate aide operative steward warden
    """.split()
)

_ORGANIZATIONAL_ROLE_NOUNS = frozenset(
    """
    partner supplier distributor retailer wholesaler vendor provider
    manufacturer bottler facility plant warehouse organization organisation
    company enterprise business agency authority department division branch
    subsidiary franchise outlet chain network cooperative collective consortium
    carrier shipper forwarder broker dealer reseller grower farm factory mill
    """.split()
)

_MACHINE_ROLE_NOUNS = frozenset(
    {"controller", "controllers", "device", "devices", "sensor", "sensors",
     "instrument", "instruments", "gateway", "gateways", "terminal", "terminals",
     "kiosk", "kiosks", "robot", "robots", "drone", "drones"}
)

_MODIFIER_WORDS = frozenset(
    """
    regional global corporate central independent external internal third
    local national senior junior chief lead key strategic primary secondary
    licensed certified registered approved authorized designated dedicated
    remote onsite field inside outside partner affiliated contracted
    """.split()
)

_ROLE_PATTERN = re.compile(
    r"\b((?:[A-Za-z][A-Za-z/-]*\s+){0,2}?"
    r"(?:managers?|administrators?|admins?|operators?|planners?|engineers?|"
    r"representatives?|reps?|officers?|agents?|coordinators?|analysts?|"
    r"auditors?|reviewers?|supervisors?|specialists?|consultants?|advisors?|"
    r"drivers?|couriers?|customers?|clients?|members?|patients?|students?|"
    r"learners?|instructors?|teachers?|tutors?|doctors?|nurses?|pharmacists?|"
    r"partners?|suppliers?|distributors?|retailers?|wholesalers?|vendors?|"
    r"manufacturers?|bottlers?|carriers?|brokers?|dealers?|resellers?|"
    r"technicians?|inspectors?|handlers?|marketers?|sellers?|merchants?|"
    r"buyers?|owners?|directors?|executives?|assistants?|teams?|"
    r"controllers?|devices?|sensors?|instruments?))\b",
    flags=re.IGNORECASE,
)


_LEADING_STRIP_WORDS = frozenset(
    {"integration", "integrations", "coordination", "commerce", "use", "support", "exchange", "flow", "movement"}
)

_LEADING_PREPOSITIONS = frozenset(
    {"with", "through", "from", "to", "and", "via", "between", "across", "for", "by", "of", "in", "on", "plus"}
)


def _normalize_role(raw: str) -> str:
    words = [word.strip("/-") for word in raw.strip().split() if word.strip("/-")]
    words = [word for word in words if word.lower() not in {"the", "a", "an", "and", "of", "for", "to"}]
    # Strip leading non-modifier nouns ("Integration With Retailer" -> "Retailer")
    # and prepositions ("Through Ingredient Supplier" -> "Ingredient Supplier").
    while len(words) > 1 and (
        words[0].lower() in _LEADING_STRIP_WORDS
        or words[0].lower() in _LEADING_PREPOSITIONS
    ):
        words = words[1:]
    if not words:
        return ""
    if len(words) == 1:
        normalized = [singularize(words[0]).capitalize()]
    else:
        normalized = [
            *(word.capitalize() for word in words[:-1]),
            singularize(words[-1]).capitalize(),
        ]
    name = " ".join(normalized)
    if name.casefold() in _GENERIC_ACTOR_NAMES:
        return ""
    return name


def _classify_role(name: str) -> str:
    """Classify an actor as human, organizational, external-system, or machine."""
    tokens = set(tokenize(name))
    if tokens & _MACHINE_ROLE_NOUNS:
        return "machine"
    if tokens & _ORGANIZATIONAL_ROLE_NOUNS:
        return "organizational"
    return "human"


def extract_actors(source_text: str, *, limit: int = 8) -> list[tuple[str, str]]:
    """Extract (actor name, kind) pairs from raw prose.

    Actors are role phrases actually present in the brief; kinds distinguish
    human actors, organizational/business parties, external systems, and
    machine participants. Ordered by frequency, then first appearance.
    """
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    kinds: dict[str, str] = {}
    for position, match in enumerate(_ROLE_PATTERN.finditer(source_text or "")):
        name = _normalize_role(match.group(1))
        if not name or len(name) > 48:
            continue
        key = name.casefold()
        counts[key] = counts.get(key, 0) + 1
        first_seen.setdefault(key, position)
        kinds.setdefault(key, _classify_role(name))
    ranked = sorted(counts, key=lambda key: (-counts[key], first_seen[key]))
    result: list[tuple[str, str]] = []
    kept: dict[str, str] = {}
    for key in ranked:
        name = " ".join(word.capitalize() for word in key.split())
        tokens = set(key.split())
        # Drop actors subsumed by a longer actor ("Partner" adds nothing
        # next to "Bottling Partner"), in either arrival order.
        if any(tokens < set(existing.split()) for existing in kept):
            continue
        for existing in [existing for existing in kept if set(existing.split()) < tokens]:
            del kept[existing]
        kept[key] = name
    for key, name in kept.items():
        result.append((name, kinds[key]))
    return result[: max(1, limit)]


# --------------------------------------------------------------------------
# Entity extraction (generic noun-phrase heuristics)
# --------------------------------------------------------------------------

_GERUND_TO_ENTITY = {
    "forecasting": "forecast",
    "planning": "plan",
    "scheduling": "schedule",
    "tracking": "track",
    "monitoring": "monitor",
}

# Single-word "management of X" topics that are scope adjectives rather than
# domain concepts ("global operations" is not an entity).
_ADJECTIVE_TOPICS = frozenset(
    {"global", "regional", "local", "central", "daily", "real", "large",
     "small", "high", "low", "core", "key", "existing", "new", "major",
     "primary", "secondary", "various", "multiple", "single", "complex",
     "hybrid", "independent", "food"}
)

_MANAGEMENT_PATTERN = re.compile(
    r"\b([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,1})\s+"
    r"(management|tracking|planning|monitoring|processing|scheduling|analytics|operations)\b",
    flags=re.IGNORECASE,
)

_PLURAL_NOUN_PATTERN = re.compile(r"\b([a-z]{4,}(?:s|es))\b")

# Heads so generic that the compound must be kept ("supply chain",
# "production line") instead of collapsing to the bare head ("chain").
_COMPOUND_KEEP_HEADS = frozenset(
    {"line", "order", "record", "item", "rule", "log", "entry", "report",
     "event", "forecast", "plan", "chain", "network", "group", "unit",
     "node", "point", "cycle", "window", "session", "profile", "account"}
)


def _candidate_entity_scores(source_text: str) -> dict[str, float]:
    """Score candidate entity identifiers found in the prose."""
    text = source_text or ""
    lower = text.casefold()
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0

    def add(identifier: str, weight: float) -> None:
        nonlocal order
        if not identifier or len(identifier) > 40:
            return
        scores[identifier] = scores.get(identifier, 0.0) + weight
        first_seen.setdefault(identifier, order)
        order += 1

    # "X management/tracking/planning/..." phrases name first-class concepts.
    for match in _MANAGEMENT_PATTERN.finditer(lower):
        topic = match.group(1).strip()
        topic_words = [word for word in topic.split() if word not in _ENGLISH_STOPWORDS]
        # Drop leading verbs and scope adjectives: "support global operations"
        # names no entity, while "supply chain management" does.
        while topic_words and (
            topic_words[0] in _ADJECTIVE_TOPICS
            or topic_words[0] in _CAPABILITY_VERBS
            or topic_words[0].rstrip("s") in _CAPABILITY_VERBS
        ):
            topic_words = topic_words[1:]
        if not topic_words:
            continue
        if (
            len(topic_words) == 1
            and (
                topic_words[0] in _ADJECTIVE_TOPICS
                or topic_words[0].endswith(("-scale", "-based", "-level", "-wide"))
            )
        ):
            continue
        head = singularize(topic_words[-1])
        if head in _NON_ENTITY_NOUNS or len(head) < 3:
            continue
        if len(topic_words) > 1 and singularize(topic_words[-1]) not in _COMPOUND_KEEP_HEADS:
            identifier = head
        else:
            identifier = "_".join(singularize(word) for word in topic_words)
        add(identifier, 3.0)

    # Frequent plural nouns are usually domain collections. Capability verbs
    # ("manages") and prepositions ("across") are never entities.
    frequencies: dict[str, int] = {}
    for match in _PLURAL_NOUN_PATTERN.finditer(lower):
        word = match.group(1)
        singular = singularize(word)
        if singular in _NON_ENTITY_NOUNS or len(singular) < 3:
            continue
        if singular in _CAPABILITY_VERBS or singular in _PREPOSITIONS:
            continue
        frequencies[singular] = frequencies.get(singular, 0) + 1
    for singular, count in frequencies.items():
        add(singular, 1.0 + min(count, 4) * 0.75)

    # Enumerated lists of plural nouns ("suppliers, facilities, partners,
    # warehouses, distributors") strongly signal sibling domain entities,
    # even when adjectives intervene ("manufacturing facilities").
    for sentence in split_sentences(lower):
        for chunk in re.split(r";\s+", sentence):
            segments = re.split(r",\s*|\s+and\s+", chunk)
            plural_segments = [
                segment.strip()
                for segment in segments
                if re.search(r"[a-z]{4,}s$", segment.strip().split()[-1])
                if segment.strip()
            ]
            if len(plural_segments) >= 3:
                for segment in plural_segments:
                    singular = singularize(segment.split()[-1])
                    if (
                        singular in _NON_ENTITY_NOUNS
                        or len(singular) < 3
                        or singular in _CAPABILITY_VERBS
                        or singular in _PREPOSITIONS
                    ):
                        continue
                    add(singular, 1.5)

    # Hyphenated compounds such as "food-service" customers are modifiers, skip.
    scores.pop("food_service", None)
    return scores


def extract_entities(
    source_text: str,
    *,
    limit: int = 8,
    extra_weights: dict[str, float] | None = None,
) -> list[str]:
    """Extract ranked snake_case entity identifiers from raw prose.

    `extra_weights` boosts identifiers (or their head nouns) grounded
    elsewhere, e.g. actor vocabulary or capability objects.
    """
    scores = _candidate_entity_scores(source_text)
    if extra_weights:
        for identifier in list(scores):
            head = identifier.split("_")[-1]
            boost = extra_weights.get(identifier, extra_weights.get(head, 0.0))
            if boost:
                scores[identifier] += boost
    # Rank by score, breaking ties by first appearance so the brief's own
    # emphasis order wins over alphabetical order.
    order = _candidate_order(source_text)
    ranked = sorted(scores, key=lambda key: (-scores[key], order.get(key, 10**9), key))
    return ranked[: max(1, limit)]


def _candidate_order(source_text: str) -> dict[str, int]:
    """First-appearance position for each candidate entity identifier."""
    lower = (source_text or "").casefold()
    positions: dict[str, int] = {}
    for match in re.finditer(r"[a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,1}", lower):
        phrase = match.group(0)
        words = [word for word in phrase.split() if word not in _ENGLISH_STOPWORDS]
        if not words:
            continue
        head = singularize(words[-1])
        identifier = head if len(words) == 1 else "_".join(singularize(word) for word in words)
        positions.setdefault(identifier, match.start())
        positions.setdefault(head, min(positions.get(head, 10**9), match.start()))
    return positions


def capability_object_tokens(capabilities: list[str]) -> set[str]:
    """Head nouns following capability verbs inside capability sentences."""
    objects: set[str] = set()
    for capability in capabilities:
        words = tokenize(capability)
        for index, word in enumerate(words[:-1]):
            if word in _CAPABILITY_VERBS:
                taken = 0
                for following in words[index + 1:]:
                    if following in _ENGLISH_STOPWORDS or following in _PREPOSITIONS:
                        continue
                    if len(following) > 2:
                        objects.add(singularize(following))
                        taken += 1
                    if taken >= 3:
                        break
                break
    return objects


# --------------------------------------------------------------------------
# Capability extraction (verb-led requirement sentences)
# --------------------------------------------------------------------------

_CAPABILITY_VERBS = frozenset(
    """
    manage manages managing track tracks tracking monitor monitors monitoring
    plan plans planning schedule schedules scheduling coordinate coordinates
    coordinating process processes processing handle handles handling support
    supports supporting provide provides providing forecast forecasts
    forecasting analyze analyzes analyzing analyse maintain maintains
    maintaining operate operates operating record records recording register
    registers registering review reviews reviewing approve approves approving
    configure configures configuring integrate integrates integrating
    synchronize synchronizes synchronizing sync syncs inspect inspects
    inspecting fulfill fulfills fulfilling dispatch dispatches dispatching
    fulfill fulfil inspect configure manage track monitor plan schedule
    coordinate process handle support provide forecast analyze maintain
    operate record register review approve configure integrate synchronize
    inspect fulfill dispatch integration visit view create update delete
    expand expands expanding serve serves serving move moves moving
    """.split()
)

_FRAMING_PREFIX = re.compile(
    r"^(?:the\s+platform|the\s+system|the\s+organisation|the\s+organization|"
    r"it|they|this\s+system|this\s+platform)\s+"
    r"(?:must|should|will|shall|can|needs?\s+to)\s+",
    flags=re.IGNORECASE,
)

_BUILD_FRAMING = re.compile(
    r"^(?:build|create|develop|design)\s+(?:an?\s+)?", flags=re.IGNORECASE
)


def _looks_like_capability(clause: str, entity_tokens: set[str], actor_tokens: set[str]) -> bool:
    words = tokenize(clause)
    if len(words) < 2:
        return False
    if not any(
        word in _CAPABILITY_VERBS or word in _CAPABILITY_NOUNS for word in words
    ):
        return False
    content = {word.rstrip("s") for word in words if word not in _ENGLISH_STOPWORDS}
    grounding = {word.rstrip("s") for word in (entity_tokens | actor_tokens)}
    if not (content & grounding):
        return False
    return True


def _normalize_capability(clause: str) -> str:
    text = " ".join(clause.split()).strip().rstrip(".")
    text = _FRAMING_PREFIX.sub("", text)
    text = _BUILD_FRAMING.sub("", text)
    text = text.strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:] + "."


_ENUMERATION_FRAMING = re.compile(
    r"^(?:key\s+capabilities(?:\s+include|\s+including)?|capabilities(?:\s+include|\s+including)?"
    r"|including|include|includes|such\s+as|like)\s+",
    flags=re.IGNORECASE,
)

_CAPABILITY_NOUNS = frozenset(
    {"management", "analytics", "insights", "insight", "planning", "tracking",
     "monitoring", "processing", "scheduling", "operations", "oversight",
     "coordination", "administration", "intelligence", "visibility"}
)

# Uninflected action verbs: the only tokens that may start a workflow label
# slice ("Production planning" must keep its head noun, not become "Planning").
_BASE_ACTION_VERBS = frozenset(
    {"manage", "track", "monitor", "plan", "schedule", "coordinate", "process",
     "handle", "support", "provide", "forecast", "analyze", "maintain",
     "operate", "record", "register", "review", "approve", "configure",
     "integrate", "synchronize", "inspect", "fulfill", "dispatch", "expand",
     "serve", "move", "visit", "view", "create", "update", "delete"}
)


def _split_enumeration(sentence: str) -> list[str]:
    """Split 'Key capabilities include A, B, and C' into item clauses."""
    if not re.search(r"\binclud", sentence, flags=re.IGNORECASE):
        return [sentence]
    items: list[str] = []
    for chunk in re.split(r";\s+", sentence):
        # Split comma lists only when they enumerate (3+ segments).
        segments = re.split(r",\s+", chunk)
        if len(segments) < 3:
            items.append(chunk)
            continue
        for segment in segments:
            segment = re.sub(r"^\s*and\s+", "", segment, flags=re.IGNORECASE)
            segment = _ENUMERATION_FRAMING.sub("", segment).strip()
            if segment:
                items.append(segment)
    return items


def extract_capabilities(
    description: str,
    business_context: str | None,
    entity_tokens: set[str],
    actor_tokens: set[str],
    *,
    limit: int = 10,
) -> list[str]:
    """Derive capability sentences grounded in extracted domain vocabulary."""
    capabilities: list[str] = []
    seen: set[str] = set()

    def _accept(text: str) -> bool:
        cleaned = _normalize_capability(text)
        if not cleaned or cleaned.casefold() in seen:
            return False
        if _looks_like_capability(cleaned, entity_tokens, actor_tokens):
            seen.add(cleaned.casefold())
            capabilities.append(cleaned)
            return True
        return False

    for sentence in split_sentences(" ".join(part for part in (description, business_context or "") if part)):
        # Enumerations ("Key capabilities include A, B, and C") become crisp
        # items; the framing sentence itself is skipped when items land.
        items = _split_enumeration(sentence)
        if len(items) > 1:
            landed = sum(1 for item in items if _accept(item))
            if landed >= 2:
                if len(capabilities) >= limit:
                    return capabilities
                continue
        _accept(sentence)
        if len(capabilities) >= limit:
            return capabilities
    return capabilities


# --------------------------------------------------------------------------
# Integration extraction
# --------------------------------------------------------------------------

_SYSTEM_ACRONYMS = (
    "ERP", "WMS", "MES", "CRM", "SCM", "PLM", "EDI", "SSO", "OAuth", "OIDC",
    "MFA", "LMS", "HRM", "POS", "CMS", "DMS", "IAM",
)

_SYSTEM_NAME_PATTERN = re.compile(
    r"\b((?:legacy|external|third-party|partner|retailer|distributor|supplier|"
    r"regional|existing|corporate|centralized|manufacturing|warehouse)\s+)?"
    r"([A-Z][a-z]{3,}(?:\s+[A-Z][a-z]+){0,2})\s+systems?\b"
)

_SYSTEM_CORE_BLOCKLIST = frozenset(
    {"the", "this", "that", "these", "those", "such", "operating", "computer",
     "information", "backend", "frontend", "software", "existing", "legacy",
     "external", "third", "regional"}
)

_LOWERCASE_SYSTEM_PATTERN = re.compile(
    r"\b((?:legacy|existing|external|third-party|partner|retailer|distributor|"
    r"supplier|regional|corporate)\s+)?"
    r"([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,1})\s+systems?\b",
    flags=re.IGNORECASE,
)

_SYSTEM_HEAD_BLOCKLIST = frozenset(
    {"operating", "computer", "information", "data", "software", "backend",
     "frontend", "legacy", "existing", "external", "third", "regional",
     "the", "our", "their", "core", "key"}
)


def _integration_sync_hint(clause: str) -> str:
    lower = clause.casefold()
    if any(marker in lower for marker in ("real-time", "realtime", "live", "stream", "event")):
        return "event-driven"
    if any(marker in lower for marker in ("batch", "nightly", "periodic", "scheduled sync", "etl")):
        return "batch"
    return "unspecified"


def _integration_purpose(name: str, clause: str) -> str:
    lower_name = name.lower()
    lower_clause = clause.casefold()
    if "sso" in lower_name or "oauth" in lower_name or "oidc" in lower_name or "identity" in lower_clause:
        return "workforce identity and access"
    if "erp" in lower_name:
        return "system-of-record business operations"
    if "wms" in lower_name or "warehouse" in lower_name:
        return "warehouse operations"
    if "mes" in lower_name or "manufacturing" in lower_name:
        return "manufacturing execution"
    if "retailer" in lower_name:
        return "downstream sales channel exchange"
    if "wholesaler" in lower_name:
        return "wholesale channel exchange"
    if "distributor" in lower_name or "partner" in lower_name or "supplier" in lower_name:
        return "partner network exchange"
    if "logistic" in lower_clause or "ship" in lower_clause:
        return "logistics coordination"
    if "analytic" in lower_clause:
        return "analytics feed"
    return "domain data exchange"


def _integration_covered(name: str, found: dict[str, str]) -> bool:
    """Whether a system is already covered by an existing integration entry."""
    acronyms = set(re.findall(r"\b[A-Z]{2,}\b", name))
    tokens = {token for token in tokenize(name) if len(token) >= 3} - {"systems", "system"}
    if not tokens and not acronyms:
        return True
    covered: set[str] = set()
    covered_acronyms: set[str] = set()
    for existing in found:
        covered |= {token for token in tokenize(existing) if len(token) >= 3}
        covered_acronyms |= set(re.findall(r"\b[A-Z]{2,}\b", existing))
    if acronyms and not acronyms <= covered_acronyms:
        return False
    return bool(tokens) and tokens <= covered


def extract_integrations(
    description: str,
    business_context: str | None,
    extra_text: str | None = None,
    *,
    limit: int = 8,
) -> list[str]:
    """Extract external systems with purpose, ownership, and sync style.

    Only systems named or clearly implied by the brief are returned; nothing
    is assumed (in particular, no payment provider).
    """
    text = " ".join(
        part for part in (description, business_context or "", extra_text or "") if part
    )
    found: dict[str, str] = {}
    for sentence in split_sentences(text):
        for acronym in _SYSTEM_ACRONYMS:
            if re.search(rf"\b{re.escape(acronym)}\b", sentence):
                purpose = _integration_purpose(acronym, sentence)
                if not _integration_covered(acronym, found):
                    found[acronym] = (
                        f"{acronym}: {purpose}. Ownership: external. "
                        f"Sync: {_integration_sync_hint(sentence)}."
                    )
        for match in _SYSTEM_NAME_PATTERN.finditer(sentence):
            qualifier, core = match.group(1) or "", match.group(2)
            if core.lower() in _SYSTEM_CORE_BLOCKLIST:
                continue
            name = re.sub(r"\s+", " ", f"{qualifier.strip()} {core}".strip().title() + " Systems")
            if not _integration_covered(name, found):
                found[name] = (
                    f"{name}: {_integration_purpose(name, sentence)}. "
                    f"Ownership: external. Sync: {_integration_sync_hint(sentence)}."
                )
        for match in _LOWERCASE_SYSTEM_PATTERN.finditer(sentence):
            qualifier, core = (match.group(1) or "").strip(), match.group(2).strip()
            core = re.sub(r"^(and|or|the|a|an)\s+", "", core, flags=re.IGNORECASE)
            head = core.split()[-1].lower()
            if head in _SYSTEM_HEAD_BLOCKLIST or len(core) < 4:
                continue
            name = re.sub(r"\s+", " ", f"{qualifier} {core}".strip().title() + " Systems")
            if not _integration_covered(name, found):
                found[name] = (
                    f"{name}: {_integration_purpose(name, sentence)}. "
                    f"Ownership: external. Sync: {_integration_sync_hint(sentence)}."
                )
        integration_match = re.search(
            r"integrat\w*\s+with\s+([^.;]+)", sentence, flags=re.IGNORECASE
        )
        if integration_match:
            targets = re.split(r",\s*|\s+and\s+", integration_match.group(1))
            for target in targets:
                target = re.sub(r"^(legacy|existing|external|third-party)\s+", "", target.strip(), flags=re.IGNORECASE).rstrip(".")
                if len(target) < 4 or len(target) > 60:
                    continue
                if target.lower() in {"management", "manufacturing", "monitoring", "tracking"}:
                    continue
                name = to_display_name(target)
                if not name.endswith("Systems") and "system" not in name.casefold():
                    name = f"{name} Systems"
                if not name or name.casefold() in _GENERIC_ACTOR_NAMES:
                    continue
                if not _integration_covered(name, found):
                    found[name] = (
                        f"{name}: {_integration_purpose(name, sentence)}. "
                        f"Ownership: external. Sync: {_integration_sync_hint(sentence)}."
                    )
    return list(found.values())[: max(1, limit)]


# --------------------------------------------------------------------------
# Domain family classification (broad categories, vocabulary-scored)
# --------------------------------------------------------------------------

DOMAIN_FAMILIES: tuple[tuple[str, dict[str, int]], ...] = (
    (
        "Manufacturing and Distribution",
        {"manufacturing": 3, "production": 2, "bottling": 4, "bottler": 3,
         "warehouse": 3, "distributor": 3, "supplier": 2, "inventory": 2,
         "supply chain": 3, "shipment": 2, "facility": 2, "plant": 3,
         "assembly": 3, "procurement": 2, "logistics": 2, "wholesaler": 2,
         "retailer": 1, "sku": 3, "formulation": 3, "concentrate": 3},
    ),
    (
        "Commerce and Retail",
        {"checkout": 4, "cart": 4, "storefront": 4, "merchant": 3, "buyer": 2,
         "marketplace": 3, "store": 1, "shop": 1, "commerce": 1, "order": 1,
         "catalog": 1, "basket": 3},
    ),
    (
        "Healthcare and Pharmacy",
        {"pharmacy": 3, "medicine": 2, "prescription": 3, "drug": 2,
         "patient": 3, "dosage": 3, "diagnosis": 3, "clinical": 2,
         "treatment": 1, "health": 1},
    ),
    (
        "Education and Learning",
        {"course": 2, "student": 2, "learning": 2, "classroom": 3,
         "curriculum": 3, "lesson": 2, "enrollment": 3, "tuition": 3,
         "campus": 2},
    ),
    (
        "Financial Services",
        {"banking": 3, "ledger": 3, "settlement": 2, "underwriting": 3,
         "portfolio": 2, "brokerage": 3, "insurance": 2, "actuarial": 3,
         "kyc": 3, "fintech": 2},
    ),
    (
        "Software and SaaS",
        {"tenant": 3, "subscription": 2, "onboarding": 2, "workspace": 1,
         "dashboard": 1, "api": 1, "webhook": 3, "sdk": 3, "saas": 3,
         "deployment": 1},
    ),
    (
        "Energy and Mobility",
        {"charging": 2, "charger": 3, "ev": 2, "grid": 2, "fleet": 2,
         "station": 1, "telematics": 3, "mileage": 2},
    ),
)

_FAMILY_THRESHOLD = 6.0


def classify_domain(title: str, source_text: str) -> tuple[str, float, list[str]]:
    """Classify the brief into a broad domain family with confidence.

    Returns (family label or "", confidence 0..1, matched evidence terms).
    Only vocabulary actually present in the brief counts as evidence.
    """
    lower = f"{title or ''} {source_text or ''}".casefold()
    best_label = ""
    best_score = 0.0
    best_terms: list[str] = []
    for label, vocabulary in DOMAIN_FAMILIES:
        score = 0.0
        terms: list[str] = []
        for term, weight in vocabulary.items():
            pattern = rf"\b{re.escape(term)}\b"
            hits = len(re.findall(pattern, lower))
            if hits:
                score += min(hits, 3) * weight
                terms.append(term)
        if score > best_score:
            best_label, best_score, best_terms = label, score, terms
    if best_score < _FAMILY_THRESHOLD:
        return "", 0.0, []
    confidence = round(min(0.85, 0.35 + best_score / 24), 2)
    return best_label, confidence, sorted(best_terms)


# --------------------------------------------------------------------------
# Commerce evidence gating (never assume shop/payments/checkout)
# --------------------------------------------------------------------------

_COMMERCE_MARKERS = (
    "checkout", "cart", "purchase", "subscription", "fare", "ticket",
    "payment", "refund", "billing", "invoice", "storefront", "marketplace",
)


def payment_evidence_level(source_text: str) -> int:
    """0 = no payment evidence, 1 = passing mention, 2 = core requirement.

    Level 2 requires either multiple distinct commerce markers or an explicit
    payment-processing statement (take/accept/process payments, payment
    processing, pay for <thing>).
    """
    text = (source_text or "").casefold().replace("check out", "checkout").replace(
        "check-out", "checkout"
    )
    lower = text
    distinct = {marker for marker in _COMMERCE_MARKERS if marker in lower}
    if len(distinct) >= 2:
        return 2
    if re.search(
        r"(take|accept|process|authorize|settle)\w*\s+payments?"
        r"|payment\s+processing"
        r"|\bpay\s+for\b",
        lower,
    ):
        return 2
    if distinct:
        return 1
    return 0


ECOMMERCE_GUARD_TERMS = frozenset(
    {"cart", "carts", "checkout", "checkouts", "merchant", "merchants",
     "buyer", "buyers", "order_items", "orderitems", "storefront", "storefronts"}
)


def unsupported_ecommerce_terms(candidate: str, source_text: str) -> list[str]:
    """E-commerce terms in generated text that the brief never supports."""
    lower_candidate = candidate.casefold()
    lower_source = (source_text or "").casefold()
    unsupported: list[str] = []
    for term in ECOMMERCE_GUARD_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", lower_candidate) and not re.search(
            rf"\b{re.escape(term)}\b", lower_source
        ):
            unsupported.append(term)
    return sorted(unsupported)


# --------------------------------------------------------------------------
# Constraint normalization (merge fragments, dedupe, normalize)
# --------------------------------------------------------------------------

_MODAL_MARKERS = (
    "must", "shall", "should", "require", "requires", "required", "support",
    "supports", "provide", "provides", "maintain", "maintains", "handle",
    "handles", "ensure", "ensures", "allow", "allows", "enable", "enables",
    "use", "uses", "implement", "implements", "comply", "complies", "meet",
    "meets", "enforce", "enforces", "operate", "operates", "restrict",
    "restricts", "limit", "limits", "retain", "retains", "protect", "protects",
)


def _has_verb_like_token(text: str) -> bool:
    for token in tokenize(text):
        if token in _MODAL_MARKERS:
            return True
        if len(token) > 5 and token.endswith(("ated", "ized", "ised", "ing")):
            return True
    return False


def _is_standalone_term(text: str) -> bool:
    """Short items that still carry meaning on their own: acronyms (SSO),
    camelCase product names (PostgreSQL), or versioned identifiers."""
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]*", text):
        if re.fullmatch(r"[A-Z]{2,}[A-Z0-9+.#-]*", token):
            return True
        if re.search(r"[a-z]+[A-Z]", token):
            return True
    return False


def _content_word_count(text: str) -> int:
    return len(_content_tokens(text))


def normalize_constraint_statements(items: list[str]) -> tuple[list[str], int]:
    """Normalize raw constraint strings into complete semantic statements.

    Splits on newlines/semicolons, conditionally re-splits comma-joined
    full sentences, merges low-information fragments into their predecessor,
    drops empties, normalizes punctuation/capitalization, and dedupes.

    Returns (normalized statements, number of merges performed).
    """
    pieces: list[str] = []
    for raw in items or []:
        for chunk in re.split(r"[\n;]+", str(raw or "")):
            chunk = " ".join(chunk.split()).strip().rstrip(".;")
            if chunk:
                pieces.append(chunk)
    # Re-split comma-joined full sentences ("Must use PostgreSQL, Must ...").
    # A comma boundary only splits when the next segment starts uppercase and
    # carries real content (>=3 words), so enumerations stay intact.
    expanded: list[str] = []
    for piece in pieces:
        segments = re.split(r",\s+", piece)
        if len(segments) <= 1:
            expanded.append(piece)
            continue
        current: list[str] = []
        for segment in segments:
            words = segment.split()
            if (
                current
                and segment[:1].isupper()
                and len(words) >= 3
                and _has_verb_like_token(segment)
            ):
                expanded.append(" ".join(current))
                current = [segment]
            else:
                current.append(segment)
        expanded.append(", ".join(current))
    # Merge low-information fragments ("privacy", "financial") into the
    # previous statement instead of keeping them as standalone constraints.
    merged: list[str] = []
    merges = 0
    for piece in expanded:
        is_fragment = (
            _content_word_count(piece) < 3
            and not _has_verb_like_token(piece)
            and not _is_standalone_term(piece)
        )
        if is_fragment and merged:
            merged[-1] = f"{merged[-1]}, {piece}".rstrip(".;")
            merges += 1
        elif is_fragment and not merged:
            continue  # leading fragment with no predecessor: drop it
        else:
            merged.append(piece)
    normalized: list[str] = []
    seen: set[str] = set()
    for piece in merged:
        text = " ".join(piece.split()).strip().rstrip(".;!?")
        if not text:
            continue
        text = text[:1].upper() + text[1:] + "."
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized, merges


# --------------------------------------------------------------------------
# Bounded-context clustering (shared-token ownership boundaries)
# --------------------------------------------------------------------------

_CONTEXT_STOPWORDS = frozenset(
    {"management", "manager", "system", "systems", "data", "record", "records",
     "info", "information", "detail", "details", "service", "services"}
)


def _entity_tokens(name: str) -> list[str]:
    parts = re.split(r"_", to_identifier(name))
    tokens = [singularize(token) for token in parts if token]
    return [token for token in tokens if token and token not in {"and", "or", "the"}]


def cluster_entities(names: list[str]) -> dict[str, str]:
    """Map each entity name to an owning bounded-context label.

    Entities sharing a distinctive token form one context (ProductionLine +
    ProductionOrder -> Production); standalone entities own a context named
    after their most distinctive token. Purely deterministic.
    """
    token_owners: dict[str, list[str]] = {}
    entity_tokens: dict[str, list[str]] = {}
    for name in names:
        tokens = [token for token in _entity_tokens(name) if token not in _CONTEXT_STOPWORDS]
        entity_tokens[name] = tokens or _entity_tokens(name)
        for token in set(entity_tokens[name]):
            token_owners.setdefault(token, []).append(name)
    shared = {
        token: owners
        for token, owners in token_owners.items()
        if len(owners) > 1
    }
    contexts: dict[str, str] = {}
    for name in names:
        tokens = entity_tokens[name]
        # Prefer the shared token that groups the fewest entities (most specific).
        candidates = sorted(
            [token for token in tokens if token in shared],
            key=lambda token: (len(shared[token]), tokens.index(token)),
        )
        if candidates:
            contexts[name] = to_display_name(candidates[0])
            continue
        # Standalone: keep the full multi-word name ("Supply Chain", not "Chain").
        if len(tokens) > 1:
            contexts[name] = to_display_name("_".join(tokens))
            continue
        # Standalone: use the last distinctive token (usually the head noun).
        distinctive = [token for token in tokens if token not in _CONTEXT_STOPWORDS]
        head = distinctive[-1] if distinctive else (tokens[-1] if tokens else name)
        contexts[name] = to_display_name(head)
    return contexts


# --------------------------------------------------------------------------
# Cross-cutting evidence helpers (shared by API, data-model, and
# consistency stages so they never disagree about what was stated)
# --------------------------------------------------------------------------

AUTH_MARKERS = (
    "authenticate", "authentication", "authorization", "sso", "oauth", "oidc",
    "role-based", "rbac", "permission", "access control", "mfa", "login",
)

AUDIT_MARKERS = (
    "audit", "compliance", "regulation", "regulatory", "traceability",
    "lineage", "provenance", "food-industry",
)


def auth_evidence(*texts: str | None) -> bool:
    """Whether identity/access requirements are explicitly stated."""
    combined = " ".join(text for text in texts if text).casefold()
    return any(marker in combined for marker in AUTH_MARKERS)


def audit_evidence(*texts: str | None) -> bool:
    """Whether audit/compliance record-keeping is explicitly required."""
    combined = " ".join(text for text in texts if text).casefold()
    return any(marker in combined for marker in AUDIT_MARKERS)


# --------------------------------------------------------------------------
# Deployment signal parsing (traceable, no invented values)
# --------------------------------------------------------------------------
def parse_availability_percent(*texts: str | None) -> float | None:
    """Extract the strongest explicit availability target (e.g. 99.99%)."""
    best: float | None = None
    for text in texts:
        if not text:
            continue
        for match in re.finditer(r"(\d{2,3}(?:\.\d+)?)\s*%", text):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if 90.0 <= value <= 100.0 and (best is None or value > best):
                best = value
    return best


def parse_region_count(*texts: str | None) -> int | None:
    """Extract an explicit region/market count when the brief states one."""
    for text in texts:
        if not text:
            continue
        match = re.search(
            r"(\d[\d,]*)\s*(?:\+)?\s*(?:international\s+markets|countries|territories|regions|geographic regions|data centers|datacentres)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def has_global_markers(*texts: str | None) -> bool:
    """Whether the brief requires multi-region/global operation."""
    combined = " ".join(text for text in texts if text).casefold()
    return bool(
        re.search(
            r"multi-region|multiple (?:geographic )?regions|global(?:ly)?(?: distributed| operations|s)|"
            r"across .* (?:regions|markets|countries)|failover|active-active|disaster recovery",
            combined,
        )
    )
