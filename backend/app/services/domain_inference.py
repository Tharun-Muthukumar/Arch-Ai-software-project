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
    million millions thousand thousands year years credential credentials check
    checks webhook webhooks format formats protocol protocols realtime real time
    availability security identity authentication authorization
    asynchronously asynchronous synchronously synchronous encryption encrypted
    auditability financial modernization modernize incremental regional
    authoritative strong consistency idempotency duplicate prevention
    operator operators manager managers administrator administrators engineer engineers
    logistic logistics operational operation near real realtime
    status statuses change changes update updates
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
    if lower in {"sales", "analytics", "news", "premises", "series", "species", "headquarters", "customs"}:
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
    """Return complete semantic statements without comma-fragmentation.

    Newlines and bullets are legitimate statement boundaries; commas are not.
    A conjunction-led or low-information continuation is joined to its parent
    instead of becoming an orphan such as ``And tracking.`` or ``Billing.``.
    This function is the sole sentence splitter used by domain extraction.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s*", "", normalized)
    raw_parts = re.split(r"(?<=[.!?;])(?:\s+|$)|\n+", normalized)
    statements: list[str] = []
    for raw in raw_parts:
        candidate = " ".join(raw.split()).strip()
        if not candidate:
            continue
        candidate = candidate.rstrip("; ")
        words = tokenize(candidate)
        conjunction_led = bool(re.match(r"^(?:and|or|while|because|but|with|including)\b", candidate, re.I))
        low_information = len([word for word in words if word not in _ENGLISH_STOPWORDS]) < 3
        if statements and (conjunction_led or low_information):
            connector = " " if statements[-1].endswith((".", "!", "?")) else ", "
            statements[-1] = f"{statements[-1]}{connector}{candidate}"
            continue
        statements.append(candidate)
    return statements


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
    passenger traveler traveller crew attendant personnel
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
    r"passengers?|travelers?|travellers?|crew|staff|personnel|attendants?|"
    r"learners?|instructors?|teachers?|tutors?|doctors?|nurses?|pharmacists?|"
    r"partners?|suppliers?|distributors?|retailers?|wholesalers?|vendors?|"
    r"manufacturers?|bottlers?|carriers?|brokers?|dealers?|resellers?|"
    r"technicians?|inspectors?|handlers?|marketers?|sellers?|merchants?|"
    r"buyers?|owners?|directors?|executives?|assistants?|teams?|users?|"
    r"controllers?|devices?|sensors?|instruments?))\b",
    flags=re.IGNORECASE,
)


_INVALID_ACTOR_MODIFIERS = frozenset(
    """
    that which who whom whose what whatever whoever this these those
    each every any all some many much more most such where when how why if whether
    both either neither one other another its their our your my his her the a an
    allow allows allowing allowed
    provide provides providing provided
    enable enables enabling enabled
    ensure ensures ensuring ensured
    deliver delivers delivering delivered
    resolve resolves resolving resolved
    help helps helping helped
    require requires requiring required
    include includes including included
    support supports supporting supported
    serve serves serving served
    connect connects connecting connected
    send sends sending sent
    receive receives receiving received
    perform performs performing performed
    handle handles handling handled
    manage manages managing managed
    process processes processing processed
    track tracks tracking tracked
    place places placing placed
    make makes making made
    take takes taking took
    get gets getting got
    give gives giving gave
    let lets letting
    have has had having
    do does did doing
    create creates creating created
    update updates updating updated
    delete deletes deleting deleted
    view views viewing viewed
    search searches searching searched
    access accesses accessing accessed
    order orders ordering ordered
    pay pays paying paid
    ship ships shipping shipped
    book books booking booked
    cancel cancels canceling canceled
    refund refunds refunding refunded
    protect protects protecting protected
    notify notifies notifying notified
    authenticate authenticates authenticating authenticated
    verify verifies verifying verified
    authorize authorizes authorizing
    assign assigns assigning assigned
    register registers registering registered
    record records recording recorded
    submit submits submitting submitted
    review reviews reviewing reviewed
    approve approves approving approved
    execute executes executing executed
    run runs running ran
    monitor monitors monitoring monitored
    collect collects collecting collected
    coordinate coordinates coordinating coordinated
    stream streams streaming streamed
    generate generates generating generated
    build builds building built
    use uses using used
    need needs needing needed
    want wants wanting wanted
    expect expects expecting expected
    facilitate facilitates facilitating facilitated
    assist assists assisting assisted
    operate operates operating operated
    offer offers offering offered
    to for from with by in on at of into onto through across over under
    before after during as and or but while because since so plus via per
    about against among between without within
    must should shall can could may might will would
    is are was were be been being
    shipment shipments issue issues item items product products feature features
    detail details data information request requests response responses
    error errors message messages result results option options report reports
    document documents file files transaction transactions account accounts
    payment payments solution solutions application applications platform platforms
    system systems software capability capabilities website tool tools module modules
    commerce exchange flow movement
    secure safely securely safe fast quick easy simple good better best
    real-time realtime automated automatic seamless reliable scalable
    efficient effective complete accurate robust flexible online digital mobile web
    directly easily automatically manually daily weekly monthly
    """.split()
)

_VALID_ROLE_PREFIXES = frozenset(
    """
    delivery station fleet platform system store warehouse plant facility
    customer client sales marketing operations support technical security
    field quality logistics dispatch product project cloud data help desk
    regional global corporate central independent external internal third
    local national senior junior chief lead key strategic primary secondary
    licensed certified registered approved authorized designated dedicated
    remote onsite partner affiliated contracted service team
    """.split()
)


def _normalize_role(raw: str) -> str:
    # Regex look-behind can capture preceding clause objects ("samples and reviewers").
    if re.search(r"\b(?:and|while|but)\b", raw, flags=re.I):
        raw = re.split(r"\b(?:and|while|but)\b", raw, flags=re.I)[-1]
    # Keep hyphens between words for compound titles like "customer-service"
    raw_cleaned = raw.replace("-", " ")
    words = [word.strip("/-.,;:'\"") for word in raw_cleaned.strip().split() if word.strip("/-.,;:'\"")]
    words = [word for word in words if word.lower() not in {"the", "a", "an", "and", "of", "for", "to", "in", "on", "at"}]

    # Strip any leading words that cannot legitimately modify a role
    while len(words) > 1:
        w0 = words[0].lower()
        w0_stem = singularize(w0)
        w0_base = re.sub(r"(?:ing|ed|es|s)$", "", w0)
        if (
            w0 in _INVALID_ACTOR_MODIFIERS
            or w0_stem in _INVALID_ACTOR_MODIFIERS
            or w0_base in _INVALID_ACTOR_MODIFIERS
            or w0 in _ENGLISH_STOPWORDS
            or w0 in _PREPOSITIONS
        ):
            # Do not strip if it is an explicitly recognized domain role prefix
            if w0 not in _VALID_ROLE_PREFIXES and w0_stem not in _VALID_ROLE_PREFIXES:
                words = words[1:]
                continue
        break

    if not words or len(words) > 4:
        return ""
    if any(w.lower() in {"from", "into", "onto", "under", "over"} for w in words):
        return ""
    if len(words) == 1:
        w = words[0].lower()
        if w in _INVALID_ACTOR_MODIFIERS or w in _GENERIC_ACTOR_NAMES or w in _ENGLISH_STOPWORDS:
            return ""
        return singularize(words[0]).capitalize()

    normalized = [
        *(word.capitalize() for word in words[:-1]),
        singularize(words[-1]).capitalize(),
    ]
    name = " ".join(normalized)
    if "/" in name:
        name = name.split("/", 1)[1].strip()
    if name.casefold() in _GENERIC_ACTOR_NAMES:
        return ""
    return name


def _classify_role(name: str) -> str:
    """Classify an actor as human, organizational, external-system, or machine."""
    tokens = set(tokenize(name))
    if tokens & _MACHINE_ROLE_NOUNS:
        # Devices/sensors/controllers are machine participants; named
        # integration endpoints (gateway, webhook, ERP) are external systems.
        if tokens & {"gateway", "gateways", "webhook", "webhooks", "api", "apis", "erp", "integration", "integrations"}:
            return "external-system"
        return "machine"
    if tokens & {"partner", "partners", "supplier", "suppliers", "vendor", "vendors", "provider", "providers", "retailer", "retailers", "wholesaler", "wholesalers", "distributor", "distributors", "carrier", "carriers", "manufacturer", "manufacturers"}:
        return "external-partner"
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
     "hybrid", "independent", "food", "near-real-time", "real-time", "realtime", "high-volume", "low-volume"}
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

_ENUMERATION_ENTITY_BLOCKLIST = frozenset(
    {"high-volume", "low-volume", "real-time", "near-real-time", "global", "regional",
     "secure", "regulated", "business", "operational", "clinical", "audit", "workflow",
     "trail", "risk", "processing", "management", "operations", "information"}
)

# Concrete record/aggregate heads that are meaningful even when the brief uses
# them in the singular.  The extractor still requires the word to be present;
# this list does not inject entities into unrelated domains.
_EXPLICIT_ENTITY_HEADS = frozenset(
    """
    account appointment assessment beneficiary booking card catalog course
    customer delivery device enrollment event facility forecast ingredient
    inspection invoice ledger lesson measurement notification order patient
    payment prescription product reading report reservation risk sensor
    shipment station student submission supplier transaction transfer warehouse
    """.split()
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

    # Singular business concepts are common in compact briefs (for example,
    # "the ledger is authoritative"). Preserve only exact, concrete heads.
    for token in tokenize(lower):
        singular = singularize(token)
        if singular in _EXPLICIT_ENTITY_HEADS:
            add(singular, 2.4)

    # In compound record phrases such as "aircraft assignments" or "device
    # readings", the modifier is often the durable business object while the
    # head is a property/event. Recover that object structurally instead of
    # maintaining a list of domain-specific nouns.
    property_heads = (
        "assignments?", "bookings?", "schedules?", "events?", "notifications?",
        "statuses?", "updates?", "changes?", "information", "operations?",
        "readings?", "measurements?",
    )
    for match in re.finditer(
        rf"\b([a-z][a-z-]{{2,}})\s+(?:{'|'.join(property_heads)})\b",
        lower,
    ):
        modifier = singularize(match.group(1))
        if (
            modifier not in _NON_ENTITY_NOUNS
            and modifier not in _CAPABILITY_VERBS
            and modifier not in _ADJECTIVE_TOPICS
        ):
            add(modifier, 2.6)

    # A small number of compound records are semantically implied by explicit
    # domain language. They remain inferred downstream and keep source
    # evidence; no vendor or architecture choice is introduced here.
    if "ledger" in lower and re.search(r"\b(?:double-entry|authoritative|posting|journal)\b", lower):
        add("ledger_entry", 4.5)
        scores.pop("ledger", None)
    if re.search(r"\bfraud\b", lower) and re.search(r"\b(?:assess|assessment|score|scoring|investigat)\w*\b", lower):
        add("risk_assessment", 3.8)
        scores.pop("assessment", None)
        scores.pop("risk", None)
    if re.search(r"\b(?:regulatory|compliance)\b", lower) and re.search(r"\breport\w*\b", lower):
        add("regulatory_report", 3.8)
        scores.pop("report", None)

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

    # Explicit capability lists often use singular nouns ("production,
    # bottling, inventory, warehouses...").  The old plural-only heuristic
    # dropped the most important concepts in exactly these statements.  This
    # structural rule accepts sibling items only in a list of three or more
    # and always takes the noun head; it is not a domain keyword table.
    for sentence in split_sentences(lower):
        if not re.search(r"\b(?:manage|track|monitor|process|coordinate|support|include|cover)\w*\b", sentence):
            continue
        segments = [part.strip(" .") for part in re.split(r",\s*|\s+and\s+", sentence)]
        if len(segments) < 3:
            continue
        for segment in segments:
            words = [word for word in tokenize(segment) if word not in _ENGLISH_STOPWORDS]
            if not words:
                continue
            while words and (words[0] in _CAPABILITY_VERBS or words[0].rstrip("s") in _CAPABILITY_VERBS):
                words = words[1:]
            if not words:
                continue
            head = singularize(words[-1])
            if head in _NON_ENTITY_NOUNS or head in _ENUMERATION_ENTITY_BLOCKLIST or len(head) < 3:
                continue
            identifier = head if len(words) == 1 or head not in _COMPOUND_KEEP_HEADS else "_".join(singularize(word) for word in words)
            add(identifier, 2.25)

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
    invalid_exact = {
        "retail", "reporting", "residency", "analyst", "officer", "operator",
        "asynchronously", "synchronously", "financial", "auditability",
        "encryption", "modernization", "suspicious", "assess",
    }
    # Occupational roles are actors, not persisted business records. A small
    # set of domain parties (customer, patient, student, member, client) can
    # legitimately be both and remains eligible.
    invalid_exact |= _HUMAN_ROLE_NOUNS - {
        "customer", "client", "member", "patient", "student", "learner",
        "supplier", "partner", "carrier", "vendor", "provider", "passenger",
        "traveler", "traveller",
    }
    role_tokens = _HUMAN_ROLE_NOUNS | {"business"}
    ranked = sorted(scores, key=lambda key: (-scores[key], order.get(key, 10**9), key))
    ranked = [
        identifier for identifier in ranked
        if identifier not in invalid_exact
        and not (set(identifier.split("_")) & (_CAPABILITY_VERBS - _EXPLICIT_ENTITY_HEADS))
        and not (
            len(identifier.split("_")) > 1
            and set(identifier.split("_")) & role_tokens
        )
    ]
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
    search searches searching book books booking check checks checking
    receive receives receiving send sends sending cancel cancels cancelling
    make makes making
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
     "coordination", "administration", "intelligence", "visibility", "search",
     "upload", "verification", "checkout", "control", "controls", "update",
     "updates"}
)

# Uninflected action verbs: the only tokens that may start a workflow label
# slice ("Production planning" must keep its head noun, not become "Planning").
_BASE_ACTION_VERBS = frozenset(
    {"manage", "track", "monitor", "plan", "schedule", "coordinate", "process",
     "handle", "support", "provide", "forecast", "analyze", "maintain",
     "operate", "record", "register", "review", "approve", "configure",
     "integrate", "synchronize", "inspect", "fulfill", "dispatch", "expand",
     "serve", "move", "visit", "view", "create", "update", "delete",
     "search", "book", "check", "receive", "make", "send", "cancel"}
)


def _split_enumeration(sentence: str) -> list[str]:
    """Split 'Key capabilities include A, B, and C' into item clauses."""
    if re.search(r"\binclud", sentence, flags=re.IGNORECASE):
        list_source = sentence
    elif re.match(r"^(?:build|create|develop)\b", sentence, flags=re.I) and re.search(
        r"\bwith\b", sentence, flags=re.I
    ):
        # "Build a product with search, upload, verification, ..." is a
        # capability list. Keeping it as one FR causes diagrams to truncate
        # the actual behavior to the framing noun ("Online pharmacy").
        list_source = re.split(r"\bwith\b", sentence, maxsplit=1, flags=re.I)[1]
    else:
        return [sentence]
    items: list[str] = []
    for chunk in re.split(r";\s+", list_source):
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
    if re.search(r"\b(?:real-time|realtime|live|streams?|events?|event-driven|webhooks?)\b", lower):
        return "event-driven"
    if re.search(r"\b(?:batch|nightly|periodic|scheduled sync|etl)\b", lower):
        return "batch"
    if re.search(r"\b(?:rest|graphql|grpc|soap|request/response|request-response)\b", lower):
        return "synchronous"
    return "unspecified"


def _boundary_evidence(name: str, source_text: str) -> str:
    """Return non-integration clauses that describe a named boundary.

    Purpose and transport are taken from nearby source evidence. A missing
    purpose stays explicitly unknown instead of becoming a generic, invented
    ``domain data exchange`` contract.
    """
    boundary_tokens = {
        singularize(token) for token in tokenize(name)
        if token not in {"external", "legacy", "system", "systems"}
    }
    evidence: list[str] = []
    for sentence in split_sentences(source_text):
        if re.search(r"\bintegrat\w*\s+with\b", sentence, re.I):
            continue
        sentence_tokens = {singularize(token) for token in tokenize(sentence)}
        if boundary_tokens and boundary_tokens & sentence_tokens:
            evidence.append(sentence)
    return " ".join(evidence)


def _integration_purpose(name: str, clause: str, source_text: str = "") -> str:
    evidence = _boundary_evidence(name, source_text)
    boundary_tokens = [
        singularize(token) for token in tokenize(name)
        if token not in {"external", "legacy", "system", "systems"}
    ]
    if len(boundary_tokens) > 1:
        boundary_tokens = boundary_tokens[-1:]
    terms: list[str] = []
    for boundary in boundary_tokens:
        for match in re.finditer(
            rf"\b{re.escape(boundary)}s?\s+([a-z][a-z-]+(?:\s+[a-z][a-z-]+)?)",
            evidence,
            re.I,
        ):
            following = " ".join(tokenize(match.group(1))[:2])
            following = re.split(
                r"\b(?:and|or|while|with|through|across|because|must|should|can|using|without|that)\b",
                following,
                maxsplit=1,
            )[0].strip()
            if following and following.split()[0] not in {
                "system", "systems", "platform", "staff", "network",
            }:
                terms.append(f"{boundary} {following}")
    terms = list(dict.fromkeys(terms))[:3]
    if terms:
        return "Support " + ", ".join(terms)
    # The integration clause itself proves the boundary, but not its business
    # purpose. Preserve that epistemic distinction for downstream review.
    return "Purpose not specified in the brief"


def _integration_record(name: str, clause: str, source_text: str) -> str:
    evidence = " ".join((clause, _boundary_evidence(name, source_text)))
    purpose = _integration_purpose(name, clause, source_text)
    protocols = [
        value for value in ("REST", "GraphQL", "gRPC", "SOAP", "EDI", "SFTP", "Webhook")
        if re.search(
            rf"(?<![a-z0-9]){re.escape(value)}{'s?' if value == 'Webhook' else ''}(?![a-z0-9])",
            evidence,
            re.I,
        )
    ]
    formats = [
        value for value in ("JSON", "XML", "CSV", "Avro", "Parquet")
        if re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", evidence, re.I)
    ]
    parts = [f"{name}: {purpose}.", "Ownership: external."]
    if protocols:
        parts.append(f"Protocol: {'/'.join(protocols)}.")
    if formats:
        parts.append(f"Formats: {'/'.join(formats)}.")
    parts.append(f"Sync: {_integration_sync_hint(evidence)}.")
    return " ".join(parts)


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
                if not _integration_covered(acronym, found):
                    found[acronym] = _integration_record(acronym, sentence, text)
        for match in _SYSTEM_NAME_PATTERN.finditer(sentence):
            qualifier, core = match.group(1) or "", match.group(2)
            if core.lower() in _SYSTEM_CORE_BLOCKLIST:
                continue
            name = re.sub(r"\s+", " ", f"{qualifier.strip()} {core}".strip().title() + " Systems")
            if not _integration_covered(name, found):
                found[name] = _integration_record(name, sentence, text)
        for match in _LOWERCASE_SYSTEM_PATTERN.finditer(sentence):
            qualifier, core = (match.group(1) or "").strip(), match.group(2).strip()
            core = re.sub(r"^(and|or|the|a|an)\s+", "", core, flags=re.IGNORECASE)
            head = core.split()[-1].lower()
            if head in _SYSTEM_HEAD_BLOCKLIST or len(core) < 4:
                continue
            name = re.sub(r"\s+", " ", f"{qualifier} {core}".strip().title() + " Systems")
            if not _integration_covered(name, found):
                found[name] = _integration_record(name, sentence, text)
        integration_match = re.search(
            r"integrat\w*\s+with\s+([^.;]+)", sentence, flags=re.IGNORECASE
        )
        if integration_match:
            targets = re.split(r",\s*|\s+and\s+", integration_match.group(1))
            for target in targets:
                target = re.sub(r"^(legacy|existing|external|third-party)\s+", "", target.strip(), flags=re.IGNORECASE).rstrip(".")
                target = re.split(
                    r"\s+(?:while|so\s+that|in\s+order\s+to|to\s+allow|using|via|over)\b",
                    target,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip()
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
                    found[name] = _integration_record(name, sentence, text)
    return list(found.values())[: max(1, limit)]


# --------------------------------------------------------------------------
# Domain family classification (broad categories, vocabulary-scored)
# --------------------------------------------------------------------------

DOMAIN_FAMILIES: tuple[tuple[str, dict[str, int]], ...] = (
    (
        "Logistics and Transportation",
        {"parcel": 4, "shipment": 3, "tracking": 2, "carrier": 3,
         "route": 3, "vehicle": 2, "delivery": 3, "customs": 3,
         "warehouse": 2, "fleet": 3, "consignment": 4, "dispatch": 2,
         "facility": 1, "logistics": 3},
    ),
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
        "Media and Streaming",
        {"media": 3, "streaming": 4, "video": 3, "audio": 2,
         "content": 2, "playback": 4, "viewer": 3, "subscriber": 2,
         "recommendation": 2, "encoding": 3, "transcoding": 4,
         "catalog": 1, "live broadcast": 4, "cdn": 3},
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

_SEMANTIC_CONTEXT_FAMILIES: tuple[tuple[str, frozenset[str]], ...] = (
    ("Ledger and Accounts", frozenset({"ledger", "balance", "account", "transaction", "journal"})),
    ("Payments and Transfers", frozenset({"payment", "transfer", "beneficiary", "card", "settlement", "invoice"})),
    ("Risk and Compliance", frozenset({"fraud", "risk", "assessment", "compliance", "regulatory"})),
    ("Identity and Access", frozenset({"identity", "credential", "permission", "role", "session"})),
    ("Communications", frozenset({"notification", "message", "alert", "preference"})),
    ("Orders and Fulfillment", frozenset({"order", "shipment", "delivery", "booking", "reservation", "checkout"})),
    ("Catalog and Inventory", frozenset({"product", "catalog", "inventory", "sku", "ingredient", "recipe"})),
    ("Learning", frozenset({"course", "lesson", "enrollment", "student", "submission"})),
    ("Care Delivery", frozenset({"patient", "appointment", "prescription", "treatment", "clinical"})),
    ("Production", frozenset({"production", "manufacturing", "inspection", "facility", "plant"})),
    ("Supply Network", frozenset({"supplier", "warehouse", "distributor", "carrier", "logistic"})),
    ("Telemetry", frozenset({"sensor", "device", "reading", "measurement", "telemetry"})),
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
        semantic = next(
            (label for label, family_tokens in _SEMANTIC_CONTEXT_FAMILIES if set(tokens) & family_tokens),
            None,
        )
        if semantic:
            contexts[name] = semantic
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
