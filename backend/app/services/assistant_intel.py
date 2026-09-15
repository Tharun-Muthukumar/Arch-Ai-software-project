"""Deterministic resolution layer for the architecture assistant.

The assistant already handled a set of exact commands without Ollama, but the
commonest turns — listing a collection, counting it, explaining why a
requirement exists, tracing what depends on it, asking what is missing,
deleting an item by description, or rewording one — all fell through to the
model. Against a local 8B model that is seconds per turn, and the answer was a
generic "the deeper Ollama analysis did not finish" whenever inference was slow
or unavailable.

Everything in this module is rule-based and runs in single-digit milliseconds.
It answers from the canonical requirement model and the causal graph, cites the
ids it used, refuses to guess when a reference is ambiguous, and proposes
changes as typed ``ProjectAction`` objects so they still travel through the
validated workspace edit pipeline.
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.schemas.domain import (
    ArchitectureChangeProposal,
    ArchitectureRequirementAddition,
    ArchitectureChatRequest,
    ArchitectureChatResponse,
    ArchitectureOption,
    ProjectAction,
    WorkspaceResponse,
)

# --------------------------------------------------------------------- lexicon

STOP_WORDS = {
    "a", "about", "all", "also", "an", "and", "any", "are", "as", "at", "be",
    "been", "being", "but", "by", "can", "could", "did", "do", "does", "each",
    "for", "from", "get", "had", "has", "have", "how", "i", "if", "in", "into",
    "is", "it", "its", "just", "make", "may", "me", "more", "most", "must",
    "my", "need", "needs", "new", "no", "not", "of", "on", "one", "only", "or",
    "other", "our", "out", "over", "please", "shall", "should", "so", "some",
    "such", "system", "than", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "those", "to", "too", "under", "up", "use", "used",
    "very", "want", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "why", "will", "with", "would", "you", "your",
}

_WORD = re.compile(r"[a-z][a-z0-9'-]*")

# Role nouns that confirm an extracted subject really is a person or a role.
ROLE_MARKERS = {
    "admin", "administrator", "agent", "analyst", "applicant", "approver",
    "attendant", "auditor", "author", "borrower", "buyer", "candidate",
    "cashier", "clerk", "client", "coach", "collector", "contractor",
    "contributor", "coordinator", "courier", "curator", "customer", "dealer",
    "dispatcher", "distributor", "doctor", "donor", "driver", "editor",
    "employee", "engineer", "examiner", "farmer", "guard", "guest", "host",
    "inspector", "instructor", "investor", "learner", "lecturer", "lender",
    "librarian", "maintainer", "manager", "mechanic", "member", "merchant",
    "moderator", "nurse", "officer", "operator", "organiser", "organizer",
    "owner", "parent", "participant", "partner", "passenger", "patient",
    "payer", "pharmacist", "physician", "pilot", "planner", "player",
    "principal", "provider", "publisher", "reader", "receptionist",
    "recruiter", "requester", "reviewer", "rider", "scheduler", "secretary",
    "seller", "shopper", "staff", "student", "subscriber", "supervisor",
    "supplier", "teacher", "technician", "tenant", "therapist", "trainer",
    "traveler", "traveller", "tutor", "user", "vendor", "viewer", "visitor",
    "volunteer", "worker",
}

NON_ACTOR_SUBJECTS = {
    "system", "systems", "platform", "application", "app", "product",
    "service", "services", "software", "solution", "module", "component",
    "backend", "frontend", "api", "database", "server", "job", "process",
    "page", "screen", "dashboard", "report", "data", "record", "records",
    "it", "this", "that", "there", "they", "we", "everything", "anyone",
}

QUALITY_CATEGORIES: list[tuple[str, str, str]] = [
    (
        "security",
        r"secur|authenticat|authoris|authoriz|encrypt|privacy|access control|permission|gdpr|hipaa|pii|audit",
        "How should access be controlled, and which data needs protection in transit or at rest?",
    ),
    (
        "performance",
        r"latenc|response time|throughput|performance|p9\d|concurren",
        "What response time or throughput is acceptable for the busiest workflow?",
    ),
    (
        "availability",
        r"availab|uptime|reliab|failover|resilien|disaster|outage|downtime",
        "How much downtime is tolerable, and what should happen during an outage?",
    ),
    (
        "scalability",
        r"scale|scaling|scalab|growth|load|volume|capacity|peak",
        "What volume of users or records should the system be sized for at launch and after growth?",
    ),
    (
        "observability",
        r"monitor|logging|log |metric|trace|alert|observab|telemetry",
        "Which failures must raise an alert, and who is expected to act on them?",
    ),
    (
        "data_retention",
        r"retention|backup|archive|restore|durab|integrity|consistency|immutab",
        "How long must records be kept, and what is the recovery expectation after data loss?",
    ),
]

_PROPER_NOUN = r"(?P<name>[A-Z][\w&-]*(?:\s+[A-Z][\w&-]*){0,3})"
INTEGRATION_PATTERNS = [
    re.compile(p)
    for p in (
        rf"integrat(?:e|es|ed|ing)?\s+with\s+{_PROPER_NOUN}",
        rf"sync(?:s|ed|hronis\w*|hroniz\w*)?\s+with\s+{_PROPER_NOUN}",
        rf"(?:via|through|using)\s+{_PROPER_NOUN}\s+(?:API|api|gateway|service)",
        rf"{_PROPER_NOUN}\s+(?:API|api|gateway|webhook)\b",
    )
]

SUBJECT_PATTERN = re.compile(
    r"(?:^|\.\s+|;\s+|,\s+and\s+|\bwhile\s+|\bwhen\s+|\bso that\s+)"
    r"(?:the\s+|an?\s+|each\s+|every\s+|any\s+)?"
    r"(?P<subject>[A-Za-z][A-Za-z -]{2,40}?)\s+"
    r"(?:can|could|should|shall|must|may|will|needs? to|has to|have to|is able to|are able to)\s",
)

AS_A_PATTERN = re.compile(
    r"\bas an?\s+(?P<subject>[A-Za-z][A-Za-z -]{2,40}?)\s*(?:,|\bi\b|\bwe\b|$)",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def singular(token: str) -> str:
    """A deliberately small stemmer: enough to match plurals, nothing more."""
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("sses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(value: str) -> set[str]:
    return {
        singular(token)
        for token in _WORD.findall(str(value).casefold())
        if token not in STOP_WORDS and len(token) > 2
    }


def similarity(left: str, right: str) -> float:
    """Dice coefficient over meaningful tokens."""
    left_tokens, right_tokens = tokens(left), tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    if not overlap:
        return 0.0
    return (2 * overlap) / (len(left_tokens) + len(right_tokens))


def containment(query: str, candidate: str) -> float:
    query_tokens = tokens(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & tokens(candidate)) / len(query_tokens)


def truncate(value: str, limit: int = 110) -> str:
    cleaned = clean_text(value)
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 1].rstrip()}…"


# Words that describe the act of asking rather than the thing asked about.
# Stripping them leaves the subject, which is what retrieval should score on.
QUERY_NOISE = {
    "explain", "explains", "describe", "describes", "tell", "show", "list",
    "give", "walk", "brief", "summary", "summarise", "summarize", "detail",
    "details", "overview", "question", "answer", "please", "kindly", "know",
    "understand", "information", "info", "everything", "thing", "things",
    "work", "works", "working", "mean", "means", "happen", "happens",
    "project", "app", "application", "platform", "product", "software",
    # Our own vocabulary: every candidate is one of these, so they separate
    # nothing. The collection they name is resolved before retrieval runs.
    "function", "functions", "functionality", "functionalities", "feature",
    "features", "capability", "capabilities", "requirement", "requirements",
}


def strip_query_noise(value: str) -> str:
    """Reduce a question to the terms worth searching for.

    Falls back to the original wording when stripping would leave nothing, so a
    question made entirely of question words still scores against something.
    """
    kept = [
        word
        for word in _WORD.findall(str(value).casefold())
        if word not in STOP_WORDS and word not in QUERY_NOISE and len(word) > 2
    ]
    return " ".join(kept) if kept else clean_text(value)


def plural(count: int, singular_form: str, plural_form: str | None = None) -> str:
    """Grammatical agreement, so answers do not read as templates."""
    if count == 1:
        return singular_form
    return plural_form if plural_form is not None else f"{singular_form}s"


def as_sentence(value: str) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return cleaned
    cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned[-1] in ".?!" else f"{cleaned}."


def title_case_name(value: str) -> str:
    cleaned = clean_text(value).strip("\"'`.,;:")
    if not cleaned:
        return cleaned
    return " ".join(
        word if word.isupper() and len(word) <= 5 else word.capitalize()
        for word in cleaned.split(" ")
        if word
    )


# ----------------------------------------------------------------- collections

# target key -> (requirement-model attribute, id prefix, singular, plural)
COLLECTIONS: dict[str, tuple[str, str, str, str]] = {
    "functional_requirement": (
        "functional_requirements", "FR", "functional requirement", "functional requirements",
    ),
    "non_functional_requirement": (
        "non_functional_requirements", "NFR", "non-functional requirement",
        "non-functional requirements",
    ),
    "constraint": ("constraints", "CON", "constraint", "constraints"),
    "assumption": ("assumptions", "ASM", "assumption", "assumptions"),
    "integration": ("integrations", "INT", "integration", "integrations"),
    "actor": ("actors", "ACTOR", "actor", "actors"),
    "domain_entity": ("domain_entities", "ENTITY-HINT", "domain entity", "domain entities"),
}

MODEL_COLLECTIONS = {"actor", "domain_entity"}

# Ordered longest-phrase-first so "non functional requirement" beats "requirement".
TARGET_PATTERNS: list[tuple[str, str]] = [
    (r"non[- ]?functional requirements?", "non_functional_requirement"),
    (r"nonfunctional requirements?", "non_functional_requirement"),
    (r"quality (?:attributes?|requirements?|goals?)", "non_functional_requirement"),
    (r"\bnfrs?\b", "non_functional_requirement"),
    (r"functional requirements?", "functional_requirement"),
    (r"\bfrs?\b", "functional_requirement"),
    (r"user stor(?:y|ies)", "functional_requirement"),
    # What users call functional requirements when they are not using our
    # vocabulary. A requirement *is* a feature the system provides, so these
    # resolve to the same collection rather than dead-ending.
    (r"use cases?", "functional_requirement"),
    (r"features?", "functional_requirement"),
    (r"functionalit(?:y|ies)", "functional_requirement"),
    (r"functions?", "functional_requirement"),
    (r"capabilit(?:y|ies)", "functional_requirement"),
    (r"domain entit(?:y|ies)", "domain_entity"),
    (r"business objects?", "domain_entity"),
    (r"entit(?:y|ies)", "domain_entity"),
    (r"actors?", "actor"),
    (r"personas?", "actor"),
    (r"stakeholders?", "actor"),
    (r"\broles?\b", "actor"),
    (r"constraints?", "constraint"),
    (r"assumptions?", "assumption"),
    (r"integrations?", "integration"),
    (r"external systems?", "integration"),
]

GENERIC_REQUIREMENT = re.compile(r"\brequirements?\b", re.IGNORECASE)


def detect_target_type(message: str) -> tuple[str | None, bool]:
    for pattern, target_type in TARGET_PATTERNS:
        if re.search(rf"\b{pattern}\b", message, re.IGNORECASE):
            return target_type, False
    if GENERIC_REQUIREMENT.search(message):
        return None, True
    return None, False


@dataclass(frozen=True)
class IndexedItem:
    id: str
    target_type: str
    index: int
    name: str
    text: str

    @property
    def search_text(self) -> str:
        return f"{self.name} {self.text}".strip()


@dataclass
class Resolution:
    item: IndexedItem | None = None
    candidates: list[IndexedItem] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.item is not None


class ProjectIndex:
    """Addressable view of the canonical requirement model."""

    STRONG_MATCH = 0.55
    WEAK_MATCH = 0.3

    def __init__(self, workspace: WorkspaceResponse) -> None:
        self.workspace = workspace
        self.requirements = workspace.requirements
        self.items_by_type: dict[str, list[IndexedItem]] = {}
        self.items_by_id: dict[str, IndexedItem] = {}
        for target_type, (attribute, prefix, _, _) in COLLECTIONS.items():
            values = list(getattr(self.requirements, attribute, []) or [])
            items = [
                IndexedItem(
                    id=f"{prefix}-{position + 1:03d}",
                    target_type=target_type,
                    index=position,
                    name=getattr(value, "name", "") or "",
                    text=(
                        f"{value.name} {value.description}".strip()
                        if target_type in MODEL_COLLECTIONS
                        else str(value)
                    ),
                )
                for position, value in enumerate(values)
            ]
            self.items_by_type[target_type] = items
            for item in items:
                self.items_by_id[item.id] = item

    def items(self, target_type: str) -> list[IndexedItem]:
        return self.items_by_type.get(target_type, [])

    def count(self, target_type: str) -> int:
        return len(self.items(target_type))

    def get(self, item_id: str) -> IndexedItem | None:
        return self.items_by_id.get(item_id.upper())

    def label(self, target_type: str, plural: bool = False) -> str:
        entry = COLLECTIONS.get(target_type)
        if entry is None:
            return target_type.replace("_", " ")
        return entry[3] if plural else entry[2]

    def count_phrase(self, target_type: str) -> str:
        count = self.count(target_type)
        return f"{count} {self.label(target_type, plural=count != 1)}"

    def resolve(self, reference: str, target_type: str | None = None) -> Resolution:
        """Point free text at a single item, or report the candidates."""
        return self.resolve_across(
            reference, {target_type} if target_type else set(COLLECTIONS)
        )

    def resolve_across(self, reference: str, target_types: set[str]) -> Resolution:
        """Resolve over several collections at once.

        Scoring every candidate together matters: resolving each collection
        separately lets a locally unique match win even when another collection
        holds several equally good ones, which is how "the appointment
        requirement" could silently land on a single NFR.
        """
        search_space = [
            item
            for target_type in target_types
            for item in self.items(target_type)
        ]
        if not search_space or not tokens(reference):
            return Resolution()

        scored = sorted(
            ((self._score(reference, item), item) for item in search_space),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score, best_item = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= self.STRONG_MATCH and (
            best_score - runner_up >= 0.08 or runner_up < self.STRONG_MATCH
        ):
            return Resolution(item=best_item)

        candidates = [item for score, item in scored if score >= self.WEAK_MATCH][:5]
        if len(candidates) == 1:
            return Resolution(item=candidates[0])
        return Resolution(candidates=candidates)

    def _score(self, reference: str, item: IndexedItem) -> float:
        score = (0.45 * similarity(reference, item.search_text)) + (
            0.55 * containment(reference, item.search_text)
        )
        if item.name and item.name.casefold() in reference.casefold():
            score = max(score, 0.9)
        return score


# ----------------------------------------------------------------- suggestions


@dataclass
class SuggestionDraft:
    title: str
    detail: str
    category: str
    evidence: list[str] = field(default_factory=list)


class SuggestionEngine:
    """Finds grounded gaps in the requirement model. No model calls, ever."""

    def analyze(
        self,
        workspace: WorkspaceResponse,
        index: ProjectIndex,
        *,
        categories: set[str] | None = None,
        limit: int = 8,
    ) -> list[SuggestionDraft]:
        drafts = [
            *self.missing_actors(workspace, index),
            *self.missing_entities(workspace, index),
            *self.missing_integrations(workspace, index),
            *self.quality_gaps(workspace, index),
            *self.model_risks(workspace, index),
        ]
        if categories:
            drafts = [draft for draft in drafts if draft.category in categories]
        return drafts[:limit]

    # ----------------------------------------------------------------- actors

    def missing_actors(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> list[SuggestionDraft]:
        known = {
            token
            for item in index.items("actor")
            for token in tokens(item.name)
        }
        candidates: dict[str, list[str]] = {}
        for item in index.items("functional_requirement"):
            for name in self._actor_phrases(item.text):
                candidates.setdefault(name, []).append(item.id)
        for name in self._actor_phrases(workspace.original_prompt or ""):
            candidates.setdefault(name, []).append("the project brief")

        drafts: list[SuggestionDraft] = []
        for name, evidence in candidates.items():
            name_tokens = tokens(name)
            if not name_tokens or name_tokens & known:
                continue
            if any(
                similarity(name, existing.name) >= 0.7 for existing in index.items("actor")
            ):
                continue
            display = title_case_name(self._singular_phrase(name))
            drafts.append(
                SuggestionDraft(
                    title=f"Add the {display} actor",
                    detail=(
                        f"{', '.join(evidence[:3])} describe{'s' if len(evidence) == 1 else ''} "
                        f"{display} operating the system, but no matching actor is recorded."
                    ),
                    category="actor",
                    evidence=evidence[:4],
                )
            )
            known |= name_tokens
        return drafts

    def _singular_phrase(self, phrase: str) -> str:
        words = phrase.split()
        if not words:
            return phrase
        words[-1] = singular(words[-1])
        return " ".join(words)

    def _actor_phrases(self, text: str) -> list[str]:
        found: list[str] = []
        for pattern in (SUBJECT_PATTERN, AS_A_PATTERN):
            for match in pattern.finditer(text or ""):
                phrase = clean_text(match.group("subject")).casefold()
                phrase = re.sub(r"^(?:the|a|an|each|every|any|all)\s+", "", phrase)
                if not phrase or phrase in NON_ACTOR_SUBJECTS:
                    continue
                words = phrase.split()
                if len(words) > 3 or not any(singular(w) in ROLE_MARKERS for w in words):
                    continue
                if phrase not in found:
                    found.append(phrase)
        return found

    # --------------------------------------------------------------- entities

    def missing_entities(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> list[SuggestionDraft]:
        known = {
            token for item in index.items("domain_entity") for token in tokens(item.name)
        }
        known |= {
            token
            for entity in workspace.database_design.entities
            for token in tokens(entity.name)
        }
        actor_tokens = {
            token for item in index.items("actor") for token in tokens(item.name)
        }

        occurrences: dict[str, list[str]] = {}
        for item in index.items("functional_requirement"):
            for token in tokens(item.text):
                if len(token) < 4 or token in ROLE_MARKERS or token in actor_tokens:
                    continue
                if token in known or token in NON_ACTOR_SUBJECTS:
                    continue
                occurrences.setdefault(token, [])
                if item.id not in occurrences[token]:
                    occurrences[token].append(item.id)

        drafts: list[SuggestionDraft] = []
        for token, evidence in sorted(
            occurrences.items(), key=lambda pair: len(pair[1]), reverse=True
        ):
            # Two independent requirements naming the same noun is the signal
            # that it is a business record, not incidental wording.
            if len(evidence) < 2 or len(drafts) >= 3:
                continue
            display = title_case_name(token)
            drafts.append(
                SuggestionDraft(
                    title=f"Track {display} as a domain entity",
                    detail=(
                        f"{len(evidence)} requirements ({', '.join(evidence[:3])}) refer to "
                        f"{display.lower()}, but it is not in the domain entity list."
                    ),
                    category="entity",
                    evidence=evidence[:4],
                )
            )
        return drafts

    # ----------------------------------------------------------- integrations

    def missing_integrations(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> list[SuggestionDraft]:
        known = {item.text.casefold() for item in index.items("integration")}
        sources = [(item.id, item.text) for item in index.items("functional_requirement")]
        sources.append(("the project brief", workspace.original_prompt or ""))

        found: dict[str, list[str]] = {}
        for source_id, text in sources:
            for pattern in INTEGRATION_PATTERNS:
                for match in pattern.finditer(text or ""):
                    name = clean_text(match.group("name")).strip(".,;")
                    if len(name) < 3 or name.casefold() in known:
                        continue
                    if any(name.casefold() in existing for existing in known):
                        continue
                    found.setdefault(name, [])
                    if source_id not in found[name]:
                        found[name].append(source_id)

        return [
            SuggestionDraft(
                title=f"Record {name} as an integration",
                detail=(
                    f"{', '.join(evidence[:3])} name{'s' if len(evidence) == 1 else ''} {name} "
                    "as an external system, but it is not in the integration list."
                ),
                category="integration",
                evidence=evidence[:4],
            )
            for name, evidence in list(found.items())[:2]
        ]

    # ----------------------------------------------------------- quality gaps

    def quality_gaps(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> list[SuggestionDraft]:
        covered = " ".join(
            item.text for item in index.items("non_functional_requirement")
        ).casefold()
        evidenced = " ".join(
            [
                *(item.text for item in index.items("functional_requirement")),
                workspace.original_prompt or "",
                workspace.business_context or "",
            ]
        ).casefold()

        drafts: list[SuggestionDraft] = []
        for category, pattern, question in QUALITY_CATEGORIES:
            if re.search(pattern, covered) or not re.search(pattern, evidenced):
                continue
            evidence = [
                item.id
                for item in index.items("functional_requirement")
                if re.search(pattern, item.text, re.IGNORECASE)
            ][:3]
            drafts.append(
                SuggestionDraft(
                    title=f"No {category.replace('_', ' ')} requirement is recorded",
                    detail=question,
                    category="quality",
                    evidence=evidence or ["the project brief"],
                )
            )
            if len(drafts) >= 3:
                break
        return drafts

    # ------------------------------------------------------------ model risks

    def model_risks(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> list[SuggestionDraft]:
        drafts = [
            SuggestionDraft(
                title=f"Consistency issue: {issue.code.replace('-', ' ')}",
                detail=issue.message,
                category="risk",
                evidence=issue.related_ids[:4],
            )
            for issue in workspace.consistency_issues[:2]
        ]
        graph = workspace.causal_graph
        if graph and graph.orphan_node_ids:
            names = [
                node.name for node in graph.nodes if node.id in set(graph.orphan_node_ids[:3])
            ]
            drafts.append(
                SuggestionDraft(
                    title="Some components have no originating requirement",
                    detail=(
                        f"{', '.join(names) or 'Several components'} are not traceable to a "
                        "validated requirement. Justify them with a requirement or remove them."
                    ),
                    category="risk",
                    evidence=graph.orphan_node_ids[:4],
                )
            )
        drafts.extend(
            SuggestionDraft(
                title="Open question still unanswered",
                detail=clean_text(question),
                category="question",
                evidence=["requirements.open_questions"],
            )
            for question in workspace.requirements.open_questions[:2]
        )
        return drafts


# --------------------------------------------------------------- deterministic


LIST_MARKERS = re.compile(
    r"^(?:hey|hi)?[,\s]*(?:please\s+)?(?:can|could|would)?\s*(?:you\s+)?(?:please\s+)?"
    r"(?:list|show|display|give me|what are|which are|name)\b",
    re.IGNORECASE,
)
COUNT_MARKERS = re.compile(r"\bhow many\b", re.IGNORECASE)
HAVE_MARKERS = re.compile(
    r"\bwhat\s+(?:\w+\s+){0,3}(?:do|does|are)\s+(?:we|i|you|there)\b", re.IGNORECASE
)
OVERVIEW_MARKERS = re.compile(
    r"\b(?:overview|summar(?:y|ise|ize)|recap)\b|"
    r"^\s*what (?:is|'s) (?:this|the) project\b|"
    r"\btell me about (?:this|the) project\b",
    re.IGNORECASE,
)
EXPLAIN_MARKERS = re.compile(
    r"\bwhy (?:does|do|is|are|did|was|were)\b|^\s*why\b|\bexplain\b|"
    r"\b(?:rationale|justification) (?:for|behind)\b",
    re.IGNORECASE,
)
SUGGEST_MARKERS = re.compile(
    r"\b(?:suggest|recommend|propose)\b|"
    r"\bwhat(?:'s| is| am i| are we)? missing\b|"
    r"\b(?:am i|are we|is anything|is there anything)\s+missing\b|"
    r"\banything (?:missing|else)\b|"
    r"\bany (?:gaps|holes)\b|"
    r"\bmissing (?:actors?|requirements?|entit(?:y|ies)|integrations?)\b|"
    r"\bwho should\b",
    re.IGNORECASE,
)
DELETE_MARKERS = re.compile(
    r"^(?:please\s+)?(?:delete|remove|drop|get rid of)\s+(?P<rest>.+)$", re.IGNORECASE
)
UPDATE_MARKERS = re.compile(
    r"^(?:please\s+)?(?:change|update|reword|rewrite|revise|edit)\s+(?P<reference>.+?)\s+"
    r"(?:to say|to read|so that it (?:says|reads))\s+(?P<payload>.+)$",
    re.IGNORECASE,
)
# Renaming is the single most common edit and people phrase it many ways. The
# original grammar only accepted "rename actor X to Y" and "change actor X to Y",
# so "change the name of actor driver to user" reached the model and timed out.
COLLECTION_NOUN = (
    r"(?:actor|persona|stakeholder|role|domain\s+entity|business\s+object|entity|component|service)"
)
RENAME_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        # change/update the name of actor driver to user
        rf"^(?:please\s+)?(?:change|update|set|edit|fix|correct)\s+(?:the\s+)?names?\s+of\s+"
        rf"(?:the\s+)?(?:{COLLECTION_NOUN}\s+)?(?P<old>.+?)\s+(?:to|into|as)\s+(?P<new>.+)$",
        # change driver's name to user
        rf"^(?:please\s+)?(?:change|update|set|edit|fix|correct)\s+(?:the\s+)?"
        rf"(?:{COLLECTION_NOUN}\s+)?(?P<old>.+?)(?:'s|s')\s+names?\s+(?:to|into|as)\s+(?P<new>.+)$",
        # rename the driver actor to user
        rf"^(?:please\s+)?rename\s+(?:the\s+)?(?P<old>.+?)\s+{COLLECTION_NOUN}\s+"
        rf"(?:to|into|as)\s+(?P<new>.+)$",
        # rename actor driver to user / rename driver to user
        rf"^(?:please\s+)?rename\s+(?:the\s+)?(?:{COLLECTION_NOUN}\s+)?"
        rf"(?:from\s+)?(?P<old>.+?)\s+(?:to|into|as)\s+(?P<new>.+)$",
        # change the driver actor to user
        rf"^(?:please\s+)?(?:change|update)\s+(?:the\s+)?(?P<old>.+?)\s+{COLLECTION_NOUN}\s+"
        rf"(?:to|into|as)\s+(?P<new>.+)$",
        # call the driver actor user instead
        rf"^(?:please\s+)?call\s+(?:the\s+)?(?:{COLLECTION_NOUN}\s+)?(?P<old>.+?)\s+"
        rf"(?P<new>[\w -]+?)\s+instead$",
    )
]

# Renameable collections and the project action that carries each one.
RENAME_TARGETS: dict[str, tuple[str, str]] = {
    "actor": ("actors", "update_actor"),
    "domain_entity": ("domain_entities", "update_entity"),
}

# "we need X", "there should be X", "the system should X" — how people actually
# state a new requirement. Without these the turn reached the model.
IMPLICIT_ADD_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^(?:we|i)\s+(?:also\s+)?(?:need|want|require)\s+(?:to have\s+)?(?P<text>.+)$",
        r"^there\s+(?:should|must|needs? to)\s+be\s+(?P<text>.+)$",
        r"^(?P<text>(?:the\s+)?(?:system|platform|application|app|product)\s+"
        r"(?:should|must|shall|needs? to|has to|will)\s+.+)$",
        r"^(?P<text>[A-Za-z][A-Za-z -]{2,40}\s+(?:should|must|shall)\s+be\s+able\s+to\s+.+)$",
    )
]

CRITIQUE_MARKERS = re.compile(
    r"\b(?:find|any)\s+problems?\b|\bwhat(?:'s| is)?\s+wrong\b|"
    r"\breview (?:my|the|this) architecture\b|\bcritique\b|"
    r"\bproblems? with (?:my|the|this)\b|\bweakness(?:es)?\b|"
    r"\bwhat would you improve\b|\bhow (?:could|can) (?:this|it|we) (?:be )?improve|"
    # "is my architecture good" is the same question asked casually.
    r"\bis (?:my|the|this) (?:architecture|design|project|system)\s+(?:any )?(?:good|ok|okay|fine|solid|right|correct)\b|"
    r"\b(?:how|is it) good (?:is )?(?:my|the|this)\b|\bany (?:issues?|risks?|concerns?|flaws?)\b|"
    r"\bwhat(?:'s| is) (?:the )?(?:risk|risks|issue|issues)\b|\bis (?:this|it) (?:any )?good\b",
    re.IGNORECASE,
)

# --------------------------------------------------------------- small talk
# A design partner that cannot say hello is not a partner. These turns are
# answered instantly and grounded in the project, never sent to the model.

GREETING = re.compile(
    r"^(?:hi|hey|hello|yo|hiya|sup|good\s+(?:morning|afternoon|evening)|greetings)"
    r"[\s,!.]*(?:there|claude|assistant|bot)?[\s,!.?]*$",
    re.IGNORECASE,
)
GRATITUDE = re.compile(
    r"^(?:thanks?|thank\s+you|thx|ty|cheers|nice|great|cool|awesome|perfect|"
    r"good\s+(?:job|work)|well\s+done|ok(?:ay)?|got\s+it|understood)"
    r"[\s,!.]*(?:a\s+lot|so\s+much|mate|man|buddy)?[\s,!.?]*$",
    re.IGNORECASE,
)
FAREWELL = re.compile(
    r"^(?:bye|goodbye|see\s+you|later|good\s*night|cya)[\s,!.?]*$", re.IGNORECASE
)
CAPABILITY_QUESTION = re.compile(
    r"\bwhat can (?:you|u) do\b|\bwhat (?:are|r) (?:you|u) (?:able to do|capable of)\b|"
    r"\bwhat do (?:you|u) do\b|\bhow (?:do|can) i use (?:you|this assistant|this chat)\b|"
    # Deliberately not "help me" — "help me add a requirement" is an action.
    r"\bwho are (?:you|u)\b|^\s*(?:help|\?+)\s*[.!?]*$|"
    r"\bwhat (?:commands?|questions?) can i ask\b|\bwhat should i ask\b",
    re.IGNORECASE,
)
AUDIENCE_QUESTION = re.compile(
    r"\bwho (?:uses|use|will use|would use|is using)\b|\bwho(?:'s| is| are)? (?:this|it) for\b|"
    r"\bwho are (?:the|my|our) (?:users?|customers?)\b|\bwho interacts with\b|"
    r"\bwho can (?:use|access)\b",
    re.IGNORECASE,
)
COVERAGE_MARKERS = re.compile(
    r"\bcover (?:all|every|the) (?:frs?|requirements?)\b|"
    r"\bdo (?:these|the) apis? (?:actually )?cover\b|"
    r"\b(?:which|what) requirements? (?:are|is) not (?:implemented|covered|built)\b|"
    r"\b(?:un|not )?(?:covered|implemented) requirements?\b|"
    r"\brequirement coverage\b",
    re.IGNORECASE,
)
SPOF_MARKERS = re.compile(
    r"\bsingle point of failure\b|\bspof\b|"
    r"\b(?:which|what) (?:component|service|part) (?:is|has) the (?:biggest|highest|main) risk\b|"
    r"\bmost (?:critical|fragile|risky) (?:component|service)\b|"
    r"\bwhere (?:is|are) the (?:weak|fragile|risk)",
    re.IGNORECASE,
)
JUSTIFY_MARKERS = re.compile(
    r"\bdo (?:we|i) (?:really )?need\s+(?P<ref>.+?)\s*\??$|"
    r"\bis\s+(?P<ref2>.+?)\s+(?:really\s+)?(?:necessary|needed|required|justified)\s*\??$|"
    r"\bwhy (?:do we|are we|is it) using\s+(?P<ref3>.+?)\s*\??$",
    re.IGNORECASE,
)
COMPARE_MARKERS = re.compile(
    r"\bwould (?:a |an )?(?P<ref>.+?)\s+be better\b|"
    r"\bwhy (?:was|were|did you (?:choose|pick|recommend))\b.*\barchitecture\b|"
    r"\bwhy (?:this|that) architecture\b|\bbetter (?:option|architecture|choice)\b|"
    r"\bcompare (?:the )?architectures?\b",
    re.IGNORECASE,
)
SIMULATE_MARKERS = re.compile(
    r"\bwhat (?:would )?happens? (?:if|at|with|when)\b|\bwhat if\b|\bsimulate\b|"
    r"\b\d[\d,.]*\s*(?:million|thousand|billion|k|m)?\s*(?:users?|requests?|orders?)\b|"
    r"\bif (?:traffic|load|users?|volume|the team|availability|latency)\b|"
    r"\b\d+\s*x\s+(?:traffic|load|users?|volume)\b",
    re.IGNORECASE,
)
COMPONENT_WHY = re.compile(
    r"\bwhy (?:is|are|does|do)\s+(?P<ref>.+?)\s+(?:here|used|present|included|in (?:this|the) (?:architecture|design))\b|"
    r"\bwhat (?:is|does)\s+(?P<ref2>.+?)\s+(?:do|for)\s*\??$",
    re.IGNORECASE,
)
# People wrap commands in politeness. Every command pattern in this codebase
# anchors at ^, so "can you add a functional requirement" matched nothing and
# the turn was sent to the model as an architecture change — the worst and
# slowest path for what is actually a one-line edit.
CONVERSATIONAL_PREFIX = re.compile(
    r"^(?:(?:hi|hey|hello|ok|okay)[,!.\s]+)*"
    r"(?:(?:could|can|would|will)\s+(?:you|u)\s+)?"
    r"(?:(?:please|pls|kindly)\s+)*"
    # "help me add X" is the command "add X". Anchored and followed by me/us so
    # a requirement about a help centre is never touched.
    r"(?:help\s+(?:me|us)\s+(?:to\s+)?)?"
    r"(?:(?:please|pls|kindly)\s+)*",
    re.IGNORECASE,
)


def strip_politeness(message: str) -> str:
    """Remove a leading conversational wrapper, keeping the command intact.

    Deliberately narrow: "we need X" and "I want X" carry meaning about what is
    being asked for, so they are left alone for the requirement handlers.
    """
    cleaned = clean_text(message)
    stripped = CONVERSATIONAL_PREFIX.sub("", cleaned, count=1).strip()
    # "hello there" is a greeting, not the command "there". If stripping leaves
    # nothing meaningful behind, the wrapper *was* the message.
    if not stripped or not tokens(stripped):
        return cleaned
    return stripped


BRIEFING_MARKERS = re.compile(
    # "ev*thing" catches everything / evrything / evreything without a spellchecker.
    r"\bev\w*thing\b|\ball of it\b|\bthe whole (?:project|thing|model)\b|"
    r"\b(?:entire|complete|full) (?:project|model|picture)\b|"
    r"\bwalk me through\b|\bbrief me\b|\ba to z\b",
    re.IGNORECASE,
)
BRIEFING_VERBS = re.compile(
    r"\b(?:explain|describe|summar\w*|tell me|show me|list|give me|walk|brief|"
    r"go through|break ?down)\b",
    re.IGNORECASE,
)
# Verbs that ask to be *told about* something rather than to be handed a list.
# "list all the FRs" stays a list; "explain all the FRs" becomes the briefing
# section, which is the same facts with the reasoning attached.
EXPLANATORY_VERBS = re.compile(
    r"\b(?:explain|describe|summar\w*|tell me|walk|brief|go through|break ?down|"
    r"what (?:are|is) (?:all )?(?:the|my|our)|overview of)\b",
    re.IGNORECASE,
)
# A universal quantifier means the user wants the whole of something, not one
# item out of it. Paired with an explanatory verb that is a briefing request.
BROAD_SCOPE = re.compile(
    r"\b(?:all|every|each|entire|whole|full|overall)\b",
    re.IGNORECASE,
)

DANGLING_PRONOUN = re.compile(
    r"^(?:please\s+)?(?:why (?:is|are|does|do)|explain|improve|delete|remove|what depends on|"
    r"what(?:'s| is) wrong with)\s+"
    r"(?:this|that|it|the selected(?: one| item)?|the current one)"
    # "why is this here?" — the trailing locator is part of the phrasing, not a name.
    r"(?:\s+(?:here|there|in (?:this|the) (?:architecture|design|project)))?\s*\??$",
    re.IGNORECASE,
)

PROTOTYPE_MARKERS = re.compile(
    r"\b(?:prototype )?screen\b|\bwhich (?:fr|requirement) created\b|\bthis page\b",
    re.IGNORECASE,
)

EXPLICIT_ID = re.compile(r"\b(FR|NFR|CON|ASM|INT|ACTOR|ENTITY-HINT)[- ]?(\d{1,3})\b", re.IGNORECASE)

REQUIREMENT_TARGETS = {"functional_requirement", "non_functional_requirement"}


# Which of the user-facing categories each handler answers in. A proposal-bearing
# response is an ACTION regardless, which the dispatch loop falls back to.
HANDLER_CATEGORIES: dict[str, str] = {
    "_small_talk": "QUESTION",
    "_capability": "EXPLANATION",
    "_audience": "QUESTION",
    "_concept": "EXPLANATION",
    "_coverage": "ANALYSIS",
    "_spof": "ANALYSIS",
    "_critique": "ANALYSIS",
    "_simulate": "SIMULATION",
    "_justify": "ANALYSIS",
    "_compare": "ANALYSIS",
    "_component_question": "EXPLANATION",
    "_prototype_question": "EXPLANATION",
    "_suggest": "SUGGESTION",
    "_list_or_count": "QUESTION",
    "_overview": "QUESTION",
    "_explain": "EXPLANATION",
    "_update_requirement": "ACTION",
    "_rename_item": "ACTION",
    "_delete_item": "ACTION",
    "_implicit_requirement_addition": "ACTION",
}


class DeterministicAssistant:
    """Answers the common assistant turns from the canonical model alone."""

    def __init__(self) -> None:
        self.suggestions = SuggestionEngine()
        # Imported lazily inside the method to keep the module import graph
        # acyclic: the analysis engine builds on this module's ProjectIndex.
        self._analysis = None

    @property
    def analysis(self):
        if self._analysis is None:
            from app.services.assistant_analysis import AnalysisEngine

            self._analysis = AnalysisEngine()
        return self._analysis

    def respond(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> ArchitectureChatResponse | None:
        message = clean_text(request.message)
        index = ProjectIndex(workspace)
        for handler in (
            # Anchored whole-message patterns, so they cannot swallow anything.
            self._small_talk,
            self._capability,
            self._dangling_pronoun,
            self._briefing,
            self._audience,
            # Analysis first: these are questions, and several of them contain
            # verbs ("improve", "need", "remove") that the mutation handlers
            # would otherwise read as commands.
            self._concept,
            self._coverage,
            self._spof,
            self._critique,
            self._simulate,
            self._justify,
            self._compare,
            self._component_question,
            self._prototype_question,
            self._suggest,
            self._list_or_count,
            self._overview,
            self._explain,
            self._update_requirement,
            self._rename_item,
            self._delete_item,
            self._implicit_requirement_addition,
        ):
            response = handler(workspace, architecture, request, index, message)
            if response is not None:
                declared = response.category != "QUESTION"
                category = (
                    response.category
                    if declared
                    else HANDLER_CATEGORIES.get(
                        handler.__name__,
                        "ACTION" if response.proposal is not None else "QUESTION",
                    )
                )
                return response.model_copy(
                    update={"category": category, "resolved_by": "deterministic"}
                )
        return None

    # -------------------------------------------------------------- briefing

    def _briefing(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """"Explain everything" — read the whole recorded project back.

        Also fires for "explain the FRs and the actors", where the user named
        more than one collection at once and no single-collection handler is
        the right answer.
        """
        if not BRIEFING_VERBS.search(message):
            return None

        wants_everything = bool(BRIEFING_MARKERS.search(message))
        named = self._named_collections(message)
        # "explain all the functions" — a quantifier with an explanatory verb
        # asks for the whole of something. Scoped to whatever was named, or the
        # whole project when nothing was.
        broad = bool(
            BROAD_SCOPE.search(message)
            and EXPLANATORY_VERBS.search(message)
            and not EXPLICIT_ID.search(message)
        )
        # One collection is a list request; two or more is a briefing.
        if not wants_everything and not broad and len(named) < 2:
            return None

        sections = None if wants_everything or not named else named
        return self._as_answer(
            self.analysis.project_briefing(
                workspace, architecture, index, sections=sections
            )
        )

    @staticmethod
    def _named_collections(message: str) -> set[str]:
        """Every collection the message mentions, not just the first."""
        found: set[str] = set()
        for pattern, target_type in TARGET_PATTERNS:
            if re.search(rf"\b{pattern}\b", message, re.IGNORECASE):
                found.add(target_type)
        for pattern, section in (
            (r"\barchitectures?\b|\bcomponents?\b", "architecture"),
            (r"\bapis?\b|\bendpoints?\b", "api"),
            (r"\bdatabases?\b|\btables?\b|\bschema\b", "database"),
            (r"\bdeployments?\b|\binfrastructure\b", "deployment"),
            (r"\bworkflows?\b", "workflow"),
            (r"\btraceability\b|\bcausal\b", "traceability"),
        ):
            if re.search(pattern, message, re.IGNORECASE):
                found.add(section)
        return found

    # ------------------------------------------------------------ selection

    def _dangling_pronoun(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """"Why is this here?" with nothing selected.

        The word "this" only means something when the UI has a selection. With
        none, asking which item is both instant and correct; guessing a target
        from a pronoun is how an assistant deletes the wrong thing.
        """
        if request.selection is not None:
            return None
        if not DANGLING_PRONOUN.match(message.strip()):
            return None
        return ArchitectureChatResponse(
            type="question",
            category="CLARIFICATION",
            confidence="high",
            answer=(
                "Unknown: nothing is selected, so I cannot tell what 'this' refers to and "
                "I will not guess. Select the item in the workspace and ask again, or name "
                "it directly — an identifier such as FR-002, an actor name, or a component "
                "name all work."
            ),
            recommendations=[
                "why does FR-001 exist",
                "what depends on FR-001",
                "list the functional requirements",
            ],
        )

    # -------------------------------------------------------------- analysis

    def _as_answer(self, result):
        """Turn an AnalysisResult into a chat response, keeping its grounding."""
        if result is None:
            return None
        confidence = result.confidence if result.confidence in {"high", "medium", "low"} else "medium"
        return ArchitectureChatResponse(
            type="question",
            answer=result.answer,
            affected_components=[item for item in result.components if item][:12],
            recommendations=result.follow_ups[:8],
            confidence=confidence,  # type: ignore[arg-type]
            evidence_ids=[item for item in result.evidence if item][:20],
        )

    # ----------------------------------------------------------- small talk

    def _project_shape(self, workspace: WorkspaceResponse, index: ProjectIndex) -> str:
        """One line of what the project currently holds, for grounding."""
        counts = [
            (len(index.items("functional_requirement")), "functional requirement"),
            (len(index.items("non_functional_requirement")), "non-functional requirement"),
            (len(index.items("actor")), "actor"),
            (len(index.items("domain_entity")), "domain entity"),
        ]
        parts = [
            f"{count} {plural(count, label, 'domain entities' if label == 'domain entity' else None)}"
            for count, label in counts
            if count
        ]
        return ", ".join(parts) if parts else "nothing recorded yet"

    def _small_talk(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """Hello, thanks, goodbye — answered in a sentence, never sent anywhere."""
        text = message.strip()
        shape = self._project_shape(workspace, index)
        if GREETING.match(text):
            answer = (
                f"Hello. I have {workspace.title} open — it holds {shape}, on the "
                f"{architecture.name} option. Ask me anything about it, or tell me what to "
                f"change and I will propose the edit."
            )
        elif GRATITUDE.match(text):
            answer = f"Any time. {workspace.title} is still open whenever you want to keep going."
        elif FAREWELL.match(text):
            answer = f"Goodbye. {workspace.title} is saved as it stands — nothing is lost."
        else:
            return None
        return ArchitectureChatResponse(
            type="question",
            category="QUESTION",
            confidence="high",
            answer=answer,
            recommendations=[
                "explain everything",
                "find problems with my architecture",
                "suggest missing actors",
            ],
        )

    def _capability(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """"What can you do?" — answered concretely, from this project."""
        if not CAPABILITY_QUESTION.search(message):
            return None
        shape = self._project_shape(workspace, index)
        answer = (
            f"I am the architecture assistant for {workspace.title}, which holds {shape} on "
            f"the {architecture.name} option. I work from the recorded project, not from "
            f"guesswork, and I label every claim Confirmed, Inferred, Recommendation or "
            f"Unknown.\n\n"
            "ASK ME\n"
            "  explain everything — the whole project read back, section by section\n"
            "  why does FR-002 exist — the requirement behind any item, traced\n"
            "  do these APIs cover all FRs — coverage computed from the endpoints and graph\n"
            "  where is the single point of failure — from the recorded dependencies\n"
            "  find problems with my architecture — each finding labelled by certainty\n"
            "  what happens if traffic increases 10x — a simulation over this design\n\n"
            "TELL ME TO CHANGE IT\n"
            "  add a functional requirement: <what someone can do>\n"
            "  change the name of actor <old name> to <new name>\n"
            "  delete FR-004\n"
            "  suggest missing actors\n\n"
            "Every change comes back as a proposal with its impact, so nothing is applied "
            "until you accept it."
        )
        return ArchitectureChatResponse(
            type="question",
            category="EXPLANATION",
            confidence="high",
            answer=answer,
            recommendations=[
                "explain everything",
                "find problems with my architecture",
                "do these APIs cover all FRs",
            ],
        )

    def _audience(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """"Who uses this?" is the actor list, phrased as a person would ask it."""
        if not AUDIENCE_QUESTION.search(message):
            return None
        actors = index.items("actor")
        if not actors:
            return ArchitectureChatResponse(
                type="question",
                category="QUESTION",
                confidence="high",
                answer=(
                    f"Unknown: {workspace.title} has no actors recorded yet, so there is no "
                    "answer I can give from the project. Ask me to suggest missing actors and "
                    "I will propose them from the requirements."
                ),
                recommendations=["suggest missing actors", "explain everything"],
            )
        lines = [
            f"Confirmed: {len(actors)} {plural(len(actors), 'actor')} "
            f"{plural(len(actors), 'uses', 'use')} {workspace.title}."
        ]
        for actor in actors:
            # The recorded text often repeats the name; do not print it twice.
            body = clean_text(actor.text)
            name = clean_text(actor.name)
            if name:
                # The recorded text can lead with the name more than once and in
                # either number ("Operator Operators manage…"), so strip until
                # the sentence actually begins.
                for _ in range(3):
                    for form in (f"{name}s", name):
                        if body.casefold().startswith(form.casefold()):
                            body = body[len(form) :].lstrip(" -—:,.")
                            break
                    else:
                        break
            detail = truncate(body, 160) if body else "No responsibilities recorded."
            lines.append(f"  {actor.id}  {actor.name} — {detail}")
        return ArchitectureChatResponse(
            type="question",
            category="QUESTION",
            confidence="high",
            answer="\n".join(lines),
            evidence_ids=[actor.id for actor in actors][:20],
            recommendations=["suggest missing actors", "explain everything"],
        )

    def _concept(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        return self._as_answer(self.analysis.concept_answer(workspace, index, message))

    def _coverage(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not COVERAGE_MARKERS.search(message):
            return None
        return self._as_answer(self.analysis.coverage_answer(workspace, index))

    def _spof(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not SPOF_MARKERS.search(message):
            return None
        return self._as_answer(self.analysis.spof_answer(workspace, architecture))

    def _critique(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not CRITIQUE_MARKERS.search(message):
            return None
        return self._as_answer(
            self.analysis.critique_answer(workspace, architecture, index)
        )

    def _simulate(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not SIMULATE_MARKERS.search(message):
            return None
        # A "what happens if I remove X" question is a dependency trace, not a
        # workload simulation; leave it to the graph handlers.
        if re.search(r"\b(?:remove|delete|drop)\b", message, re.IGNORECASE):
            return None
        return self._as_answer(self.analysis.simulate_answer(workspace, message))

    def _justify(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        match = JUSTIFY_MARKERS.search(message.strip(" .!?"))
        if match is None:
            return None
        reference = clean_text(
            match.group("ref") or match.group("ref2") or match.group("ref3") or ""
        ).strip(" .?!")
        reference = re.sub(r"^(?:a|an|the)\s+", "", reference, flags=re.IGNORECASE)
        if not reference:
            return None
        # "do we need an Admin actor" is a modelling question, not a technology one.
        target_type, _ = detect_target_type(reference)
        if target_type is not None:
            return None
        return self._as_answer(
            self.analysis.justify_technology(workspace, architecture, index, reference)
        )

    def _compare(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        match = COMPARE_MARKERS.search(message)
        if match is None:
            return None
        reference = ""
        if "ref" in match.groupdict() and match.group("ref"):
            reference = clean_text(match.group("ref"))
        return self._as_answer(self.analysis.compare_answer(workspace, reference))

    def _component_question(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        match = COMPONENT_WHY.search(message.strip(" .!?"))
        if match is None:
            return None
        reference = clean_text(match.group("ref") or match.group("ref2") or "")
        reference = re.sub(r"^(?:a|an|the)\s+", "", reference, flags=re.IGNORECASE)
        if not reference or EXPLICIT_ID.search(reference):
            return None
        # A pronoun means the user is pointing at the current selection, which
        # the selection-aware handler resolves precisely. Never guess a
        # component from "this".
        if re.fullmatch(
            r"(?:this|that|it|here|the selected(?: one| item)?|the current one)",
            reference,
            re.IGNORECASE,
        ):
            return None
        # Requirement-model items are explained by the requirement handler.
        if detect_target_type(reference)[0] is not None:
            return None
        explained = self.analysis.explain_component(
            workspace, architecture, index, reference
        )
        if explained is None:
            # Not in the architecture is itself a grounded answer, and a far
            # better one than handing the turn to a model that will time out.
            explained = self.analysis.component_not_found(
                workspace, architecture, index, reference
            )
        return self._as_answer(explained)

    def _prototype_question(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not PROTOTYPE_MARKERS.search(message):
            return None
        if not re.search(r"\bwhy\b|\bwhich\b|\bwhat\b|\bexplain\b", message, re.IGNORECASE):
            return None
        reference = ""
        selection = request.selection
        if selection is not None and selection.object_type == "prototype_screen":
            reference = selection.name or selection.object_id
        if not reference:
            match = re.search(
                r"(?:screen|page)\s+(?:called\s+|named\s+)?(?P<ref>[\w' -]{2,60})",
                message,
                re.IGNORECASE,
            )
            if match:
                reference = clean_text(match.group("ref"))
        if not reference:
            return None
        return self._as_answer(
            self.analysis.prototype_answer(workspace, index, reference)
        )

    # ------------------------------------------------------------------ list

    def _list_or_count(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        counting = bool(COUNT_MARKERS.search(message))
        listing = bool(LIST_MARKERS.match(message)) or bool(HAVE_MARKERS.search(message))
        if not counting and not listing:
            return None

        target_type, generic = detect_target_type(message)
        if target_type is None and not generic:
            return None
        target_types = (
            ["functional_requirement", "non_functional_requirement"]
            if target_type is None
            else [target_type]
        )

        counts = " and ".join(index.count_phrase(item) for item in target_types)
        if counting:
            return ArchitectureChatResponse(
                type="question", answer=f"Confirmed: this project has {counts}."
            )

        lines: list[str] = []
        for item_type in target_types:
            items = index.items(item_type)
            if not items:
                lines.append(f"No {index.label(item_type, plural=True)} are recorded yet.")
                continue
            body = " ".join(
                f"{item.id}: {truncate(item.text, 120)}" for item in items[:20]
            )
            if len(items) > 20:
                body = f"{body} …and {len(items) - 20} more."
            lines.append(f"{index.label(item_type, plural=True).capitalize()} — {body}")
        return ArchitectureChatResponse(
            type="question",
            answer=f"Confirmed: this project has {counts}. " + " ".join(lines),
        )

    # -------------------------------------------------------------- overview

    def _overview(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not OVERVIEW_MARKERS.search(message) or EXPLICIT_ID.search(message):
            return None
        counts = ", ".join(
            index.count_phrase(target_type)
            for target_type in COLLECTIONS
            if index.count(target_type)
        )
        parts = [
            f"Confirmed: {workspace.title} is a {workspace.requirements.domain} project.",
            truncate(workspace.requirements.summary, 240),
            f"Canonical model: {counts or 'nothing recorded yet'}.",
            f"Recommended architecture: {workspace.recommendation.recommended_architecture_name}.",
        ]
        if workspace.consistency_issues:
            parts.append(f"Open consistency issues: {len(workspace.consistency_issues)}.")
        unknowns = workspace.requirements.open_questions[:3]
        if unknowns:
            parts.append(
                "Unknown: " + "; ".join(truncate(question, 90) for question in unknowns)
            )
        return ArchitectureChatResponse(
            type="question",
            answer=" ".join(parts),
            affected_components=[item.name for item in architecture.components[:4]],
        )

    # --------------------------------------------------------------- explain

    def _explain(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not EXPLAIN_MARKERS.search(message):
            return None
        item = self._referenced_item(index, request, message)
        if item is None:
            return None

        graph = workspace.causal_graph
        parts = [f"Confirmed: {item.id} states '{truncate(item.text, 180)}'."]
        affected: list[str] = []
        if graph is not None and any(node.id == item.id for node in graph.nodes):
            incoming = [
                edge.reason for edge in graph.edges if edge.target_node_id == item.id
            ][:3]
            downstream_ids = {
                edge.target_node_id for edge in graph.edges if edge.source_node_id == item.id
            }
            downstream = [node for node in graph.nodes if node.id in downstream_ids]
            if incoming:
                parts.append("Recorded justification: " + " ".join(incoming))
            if downstream:
                parts.append(
                    "It drives: "
                    + ", ".join(f"{node.id} {truncate(node.name, 40)}" for node in downstream[:6])
                    + "."
                )
                affected = [
                    node.name
                    for node in downstream
                    if node.type in {"architecture_component", "service_module"}
                ][:6]
            else:
                parts.append("No downstream artifact is linked to it yet.")
        else:
            mentions = [
                other.id
                for other in index.items("functional_requirement")
                if other.id != item.id and similarity(item.text, other.text) >= 0.45
            ][:4]
            parts.append(
                "Unknown: no causal-graph node is linked to this item, so this answer comes "
                "from the requirement model rather than the dependency graph."
            )
            if mentions:
                parts.append(f"Closely related requirements: {', '.join(mentions)}.")

        if item.target_type == "actor":
            using = [
                entry.id
                for entry in index.items("functional_requirement")
                if item.name and item.name.casefold() in entry.text.casefold()
            ][:5]
            parts.append(
                f"Requirements that put this actor to work: {', '.join(using)}."
                if using
                else "Unknown: no functional requirement currently names this actor, which "
                "usually means it is unjustified or the wording is missing."
            )
        return ArchitectureChatResponse(
            type="question", answer=" ".join(parts), affected_components=affected
        )

    # --------------------------------------------------------------- suggest

    def _suggest(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        if not SUGGEST_MARKERS.search(message):
            return None
        target_type, _ = detect_target_type(message)
        categories = {
            "actor": {"actor"},
            "domain_entity": {"entity"},
            "non_functional_requirement": {"quality"},
            "integration": {"integration"},
        }.get(target_type or "")

        drafts = self.suggestions.analyze(workspace, index, categories=categories)
        if not drafts:
            scope = (
                f" about {index.label(target_type, plural=True)}" if target_type else ""
            )
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    f"Confirmed: I found no grounded gaps{scope}. Suggestions are only raised "
                    "when the project's own text supports them, so an empty result means "
                    "nothing in the brief or the requirements is going unrecorded."
                ),
            )
        body = " ".join(
            f"{draft.title} — {draft.detail} Evidence: {', '.join(draft.evidence) or 'none'}."
            for draft in drafts
        )
        return ArchitectureChatResponse(
            type="question",
            answer=(
                f"Confirmed: {len(drafts)} grounded gap"
                f"{'s' if len(drafts) != 1 else ''} in the current model. {body} "
                "Recommendation: review each against the cited evidence before adding it."
            ),
            recommendations=[draft.title for draft in drafts[:8]],
        )

    # ---------------------------------------------------------------- update

    def _update_requirement(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        match = UPDATE_MARKERS.match(message.strip(" .!?"))
        if match is None:
            return None
        reference = clean_text(match.group("reference"))
        payload = normalize_requirement_text(match.group("payload"))
        if len(payload) < 3:
            return None

        resolution = self._resolve_reference(index, reference, REQUIREMENT_TARGETS)
        if resolution.item is None:
            return self._ambiguity_response(resolution, reference, "reword")
        item = resolution.item

        action = ProjectAction(
            action="update_requirement",
            target_id=item.id,
            requirement_type=item.target_type,  # type: ignore[arg-type]
            value=payload,
            rationale=f"The user explicitly reworded {item.id}.",
        )
        summary = f"Reword {item.id} to: {truncate(payload, 120)}"
        return self._action_response(
            workspace,
            architecture,
            request,
            action,
            summary=summary,
            answer=(
                f"Confirmed: {item.id} currently states '{truncate(item.text, 120)}'. "
                f"I prepared a structured project action: {summary}"
            ),
            risk="medium",
            auto_apply=False,
        )

    # ---------------------------------------------------------------- rename

    def _rename_item(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """Rename an actor or domain entity, keeping every other recorded fact."""
        body = message.strip(" .!?")
        old_name = new_name = ""
        for pattern in RENAME_PATTERNS:
            match = pattern.match(body)
            if match:
                old_name = clean_text(match.group("old")).strip(" .!?\"'")
                new_name = clean_text(match.group("new")).strip(" .!?\"'")
                break
        if not old_name or not new_name:
            return None

        # Strip a trailing collection noun the pattern left behind, so
        # "the driver actor" resolves as "driver".
        old_name = re.sub(rf"\s+{COLLECTION_NOUN}$", "", old_name, flags=re.IGNORECASE).strip()
        new_name = re.sub(rf"^{COLLECTION_NOUN}\s+", "", new_name, flags=re.IGNORECASE).strip()
        if not old_name or not new_name:
            return None

        if new_name == new_name.casefold():
            new_name = title_case_name(new_name)

        named_type, _ = detect_target_type(body)
        allowed = (
            {named_type}
            if named_type in RENAME_TARGETS
            else set(RENAME_TARGETS)
        )

        item = self._named_item(index, old_name, allowed)
        if item is None:
            resolution = index.resolve_across(old_name, allowed)
            if resolution.item is None:
                if resolution.candidates:
                    return self._ambiguity_response(resolution, old_name, "rename")
                labels = " or ".join(sorted(index.label(name) for name in allowed))
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        f"Unknown: no {labels} named '{truncate(old_name, 60)}' exists in this "
                        f"project, so nothing was renamed. {self._recorded_names(index, allowed)}"
                    ),
                )
            item = resolution.item

        attribute, action_kind = RENAME_TARGETS[item.target_type]
        collection = list(getattr(workspace.requirements, attribute))
        if not 0 <= item.index < len(collection):  # pragma: no cover - index guard
            return None
        current = collection[item.index]

        if current.name.casefold() == new_name.casefold():
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    f"Confirmed: {item.id} is already named '{current.name}', "
                    "so no change was prepared."
                ),
            )
        duplicate = next(
            (
                other.name
                for position, other in enumerate(collection)
                if position != item.index and other.name.casefold() == new_name.casefold()
            ),
            None,
        )
        if duplicate:
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    f"Unknown: {index.label(item.target_type)} '{duplicate}' already exists, so "
                    "the rename was not prepared. Names must stay unique."
                ),
            )

        # Carry every recorded fact forward and record why the name changed.
        value = current.model_dump(mode="json")
        value["name"] = new_name
        value["source_evidence"] = [
            *value.get("source_evidence", []),
            {
                "source_id": "AI-USER-RENAME",
                "source": "explicit assistant command",
                "status": "user-edited",
                "excerpt": request.message,
            },
        ]
        action = ProjectAction(
            action=action_kind,  # type: ignore[arg-type]
            target_id=item.id,
            value=value,
            rationale=(
                f"The user explicitly renamed {index.label(item.target_type)} "
                f"{current.name} to {new_name}; all other recorded facts are preserved."
            ),
        )
        summary = f"Rename {index.label(item.target_type)} {current.name} to {new_name}"
        return self._action_response(
            workspace,
            architecture,
            request,
            action,
            summary=summary,
            answer=(
                f"Confirmed: {item.id} is currently '{current.name}'. "
                f"I prepared a structured project action: {summary}. "
                "Its description, responsibilities and traceability are kept as they are."
            ),
            risk="low",
            auto_apply=True,
        )

    def _named_item(
        self, index: ProjectIndex, name: str, allowed: set[str]
    ) -> IndexedItem | None:
        """Exact, then case-insensitive, then singular/plural name match."""
        needle = name.casefold()
        for target_type in allowed:
            for item in index.items(target_type):
                if item.name.casefold() == needle:
                    return item
        for target_type in allowed:
            for item in index.items(target_type):
                if singular(item.name.casefold()) == singular(needle):
                    return item
        return None

    def _recorded_names(self, index: ProjectIndex, allowed: set[str]) -> str:
        """List what does exist, each collection under its own label."""
        parts: list[str] = []
        for target_type in sorted(allowed):
            names = [item.name for item in index.items(target_type) if item.name]
            label = index.label(target_type, plural=True).capitalize()
            parts.append(f"{label}: {', '.join(names) if names else 'none'}.")
        return " ".join(parts)

    # ---------------------------------------------------------------- delete

    def _delete_item(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        match = DELETE_MARKERS.match(message.strip(" .!?"))
        if match is None:
            return None
        reference = clean_text(match.group("rest"))
        target_type, _ = detect_target_type(reference)
        # Deletions the existing exact-command layer already owns are left alone.
        if target_type in {"actor", "domain_entity"} and not EXPLICIT_ID.search(reference):
            return None
        if re.match(r"^(?:this|the selected)\b", reference, re.IGNORECASE):
            return None

        allowed = (
            {target_type}
            if target_type in COLLECTIONS
            else REQUIREMENT_TARGETS | {"constraint", "assumption", "integration"}
        )
        resolution = self._resolve_reference(index, reference, allowed)
        if resolution.item is None:
            return self._ambiguity_response(resolution, reference, "deletion")
        item = resolution.item

        if item.target_type in REQUIREMENT_TARGETS:
            action = ProjectAction(
                action="delete_requirement",
                target_id=item.id,
                requirement_type=item.target_type,  # type: ignore[arg-type]
                rationale=f"The user explicitly requested deletion of {item.id}.",
            )
        elif item.target_type == "actor":
            action = ProjectAction(
                action="delete_actor",
                target_id=item.id,
                rationale=f"The user explicitly requested removal of actor {item.name}.",
            )
        elif item.target_type == "domain_entity":
            action = ProjectAction(
                action="delete_entity",
                target_id=item.id,
                rationale=f"The user explicitly requested removal of domain entity {item.name}.",
            )
        else:
            # Constraints, assumptions and integrations have no typed project
            # action, so they stay with the existing editor rather than being
            # half-handled here.
            return None

        dependents = self._dependent_summary(workspace, item)
        summary = f"Delete {item.id}: {truncate(item.text, 120)}"
        answer = f"I prepared a structured project action: {summary}"
        if dependents:
            answer = f"{answer} Deleting it would require revalidation of: {dependents}."
        return self._action_response(
            workspace,
            architecture,
            request,
            action,
            summary=summary,
            answer=answer,
            risk="high",
            auto_apply=False,
        )

    # ------------------------------------------------------------ implicit add

    def _implicit_requirement_addition(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        index: ProjectIndex,
        message: str,
    ) -> ArchitectureChatResponse | None:
        """Capture a requirement stated as a need rather than as a command."""
        body = message.strip(" .!?")
        text = ""
        for pattern in IMPLICIT_ADD_PATTERNS:
            match = pattern.match(body)
            if match:
                text = normalize_requirement_text(match.group("text"))
                break
        if len(text) < 6:
            return None
        # A named collection means the explicit command layer owns this turn.
        target_type, _ = detect_target_type(body)
        if target_type is not None:
            return None

        duplicate = next(
            (
                item
                for item in index.items("functional_requirement")
                if similarity(item.text, text) >= 0.85
            ),
            None,
        )
        if duplicate is not None:
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    f"Confirmed: {duplicate.id} already covers that — "
                    f"'{truncate(duplicate.text, 120)}'. No duplicate was proposed."
                ),
            )

        proposal = ArchitectureChangeProposal(
            proposal_id=str(uuid.uuid4()),
            architecture_id=architecture.id,
            base_updated_at=workspace.updated_at,
            request=request.message,
            summary=f"Add functional requirement: {text}",
            reasoning=(
                "The message states a required capability in the user's own words, so it is "
                "captured verbatim as a functional requirement rather than interpreted."
            ),
            requirement_additions=[
                ArchitectureRequirementAddition(
                    target_type="functional_requirement", text=text
                )
            ],
            affected_components=[],
            tradeoffs=[],
            risk_level="low",
            auto_apply_safe=True,
        )
        return ArchitectureChatResponse(
            type="architecture_change",
            answer=(
                f"Reading that as a new functional requirement: '{text}'. "
                "Confirm to add it and refresh its dependent project views."
            ),
            proposal=proposal,
        )

    # --------------------------------------------------------------- helpers

    def _referenced_item(
        self, index: ProjectIndex, request: ArchitectureChatRequest, message: str
    ) -> IndexedItem | None:
        explicit = EXPLICIT_ID.search(message)
        if explicit:
            item = index.get(f"{explicit.group(1).upper()}-{int(explicit.group(2)):03d}")
            if item is not None:
                return item
        if request.selection is not None:
            item = index.get(request.selection.object_id)
            if item is not None:
                return item
        return None

    def _resolve_reference(
        self, index: ProjectIndex, reference: str, allowed: set[str]
    ) -> Resolution:
        explicit = EXPLICIT_ID.search(reference)
        if explicit:
            item = index.get(f"{explicit.group(1).upper()}-{int(explicit.group(2)):03d}")
            return Resolution(item=item) if item is not None else Resolution()

        return index.resolve_across(reference, allowed)

    def _ambiguity_response(
        self, resolution: Resolution, reference: str, operation: str
    ) -> ArchitectureChatResponse:
        if not resolution.candidates:
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    f"Unknown: nothing in the canonical model matches '{truncate(reference, 80)}', "
                    "so no change was prepared. Name the item or use its identifier, such as FR-002."
                ),
            )
        options = "; ".join(
            f"{candidate.id}: {truncate(candidate.text, 90)}"
            for candidate in resolution.candidates
        )
        return ArchitectureChatResponse(
            type="question",
            category="CLARIFICATION",
            confidence="medium",
            answer=(
                f"Unknown: '{truncate(reference, 80)}' matches more than one item, so no "
                f"{operation} was prepared. Candidates: {options}. "
                "Reply with the identifier you mean."
            ),
            recommendations=[candidate.id for candidate in resolution.candidates],
            evidence_ids=[candidate.id for candidate in resolution.candidates],
        )

    def _dependent_summary(self, workspace: WorkspaceResponse, item: IndexedItem) -> str:
        graph = workspace.causal_graph
        if graph is None:
            return ""
        linked = {
            edge.target_node_id for edge in graph.edges if edge.source_node_id == item.id
        }
        names = [node.name for node in graph.nodes if node.id in linked]
        return ", ".join(names[:8])

    def _action_response(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
        action: ProjectAction,
        *,
        summary: str,
        answer: str,
        risk: str,
        auto_apply: bool,
    ) -> ArchitectureChatResponse:
        proposal = ArchitectureChangeProposal(
            proposal_id=str(uuid.uuid4()),
            architecture_id=architecture.id,
            base_updated_at=workspace.updated_at,
            request=request.message,
            summary=summary,
            reasoning=action.rationale,
            project_actions=[action],
            affected_components=[],
            tradeoffs=[
                "Dependent requirements, prototype screens, APIs, diagrams, and traceability "
                "will be revalidated."
            ],
            risk_level=risk,  # type: ignore[arg-type]
            auto_apply_safe=auto_apply,
        )
        return ArchitectureChatResponse(
            type="architecture_change", answer=answer, proposal=proposal
        )


def normalize_requirement_text(value: str) -> str:
    """Turn request phrasing into requirement phrasing without adding words.

    Punctuation is left exactly as the user typed it: the workspace stores
    requirement text verbatim, so this only reshapes "X to be able to Y" into
    "X can Y" and capitalises the opening letter.
    """
    cleaned = clean_text(value)
    match = re.match(
        r"^(?P<subject>.+?)\s+(?:to be able to|being able to)\s+(?P<action>.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        cleaned = f"{match.group('subject')} can {match.group('action')}"
    return f"{cleaned[0].upper()}{cleaned[1:]}" if cleaned else cleaned


def describe_index(workspace: WorkspaceResponse) -> dict[str, Any]:
    """Compact project facts for the model, used instead of the full workspace."""
    index = ProjectIndex(workspace)
    summary: dict[str, Any] = {
        "domain": workspace.requirements.domain,
        "summary": truncate(workspace.requirements.summary, 220),
    }
    for target_type, (_, _, _, plural) in COLLECTIONS.items():
        items = index.items(target_type)
        if items:
            summary[plural.replace(" ", "_").replace("-", "_")] = [
                f"{item.id}: {truncate(item.search_text, 90)}" for item in items[:6]
            ]
    return summary
