import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.domain import WorkspaceCreateRequest
from app.services.ai.client import OllamaStructuredClient


class ProjectDescriptionAnalysisError(RuntimeError):
    pass


class ProjectDescriptionExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=120)
    business_context_excerpts: list[str] = Field(default_factory=list, max_length=6)
    explicit_constraint_excerpts: list[str] = Field(default_factory=list, max_length=12)
    preferred_cloud: Literal["AWS", "Azure", "GCP", "On-premise", "No preference"] | None = None
    team_size: int | None = Field(default=None, ge=1, le=1000)


class ProjectDescriptionAnalyzer:
    _constraint_marker = re.compile(
        r"\b(?:must(?:\s+not)?|required?|requires|shall|only|cannot|can't|"
        r"needs?\s+to|has\s+to|at\s+least|at\s+most|no\s+more\s+than|"
        r"no\s+less\s+than)\b",
        re.IGNORECASE,
    )
    _team_patterns = (
        re.compile(
            r"\bteam(?:\s+size)?\s*(?:of|is|:)?\s*(\d{1,4})\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(\d{1,4})\s+(?:software\s+)?(?:engineers?|developers?)\b",
            re.IGNORECASE,
        ),
    )
    _cloud_patterns = {
        "AWS": re.compile(r"\b(?:aws|amazon\s+web\s+services)\b", re.IGNORECASE),
        "Azure": re.compile(r"\b(?:azure|microsoft\s+azure)\b", re.IGNORECASE),
        "GCP": re.compile(r"\b(?:gcp|google\s+cloud(?:\s+platform)?)\b", re.IGNORECASE),
        "On-premise": re.compile(r"\bon[ -]?prem(?:ise|ises)?\b", re.IGNORECASE),
    }
    _generic_title_words = {
        "a", "an", "and", "application", "build", "create", "develop", "for",
        "i", "me", "my", "need", "platform", "project", "solution", "system",
        "the", "to", "want", "we",
    }

    def __init__(self, ai_client: OllamaStructuredClient | None = None) -> None:
        self.ai_client = ai_client or OllamaStructuredClient()

    def analyze(self, prompt: str) -> WorkspaceCreateRequest:
        source = prompt.strip()
        raw = self.ai_client.generate(
            "project-description-extraction",
            {"raw_requirement": source},
            response_schema=ProjectDescriptionExtraction.model_json_schema(),
            num_predict=512,
            num_ctx=4096,
            minimum_timeout_seconds=180,
        )
        if raw is None:
            raise ProjectDescriptionAnalysisError(
                "ArchAI could not analyze this description with Ollama. Confirm Ollama "
                "and the configured Qwen model are available, then try again."
            )

        try:
            extraction = ProjectDescriptionExtraction.model_validate(raw)
        except ValidationError as exc:
            raise ProjectDescriptionAnalysisError(
                "Ollama returned an invalid project analysis. Please try again."
            ) from exc

        return WorkspaceCreateRequest(
            title=self._ground_title(extraction.title, source),
            description=source,
            business_context=self._business_context(
                extraction.business_context_excerpts, source
            ),
            preferred_cloud=self._explicit_cloud(source),
            constraints=self._constraints(
                extraction.explicit_constraint_excerpts, source
            ),
            team_size=self._explicit_team_size(source),
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    def _source_excerpt(self, value: str, source: str) -> str | None:
        excerpt = " ".join(value.split()).strip(" -.;,")
        normalized_excerpt = self._normalize(excerpt)
        if len(normalized_excerpt) < 4:
            return None
        if normalized_excerpt not in self._normalize(source):
            return None
        return excerpt

    def _business_context(self, values: list[str], source: str) -> str | None:
        excerpts: list[str] = []
        normalized_source = self._normalize(source)
        for value in values:
            excerpt = self._source_excerpt(value, source)
            if not excerpt:
                continue
            if len(self._normalize(excerpt)) >= len(normalized_source) * 0.75:
                continue
            if self._normalize(excerpt) not in {
                self._normalize(existing) for existing in excerpts
            }:
                excerpts.append(excerpt)
        return "\n".join(excerpts) or None

    def _constraints(self, values: list[str], source: str) -> list[str]:
        constraints: list[str] = []
        seen: set[str] = set()
        for value in values:
            excerpt = self._source_excerpt(value, source)
            if not excerpt or not self._constraint_marker.search(excerpt):
                continue
            normalized = self._normalize(excerpt)
            if normalized not in seen:
                seen.add(normalized)
                constraints.append(excerpt)
        return constraints

    def _explicit_team_size(self, source: str) -> int | None:
        for pattern in self._team_patterns:
            if match := pattern.search(source):
                value = int(match.group(1))
                return value if 1 <= value <= 1000 else None
        return None

    def _explicit_cloud(self, source: str) -> str | None:
        if re.search(r"\bno\s+(?:cloud\s+)?preference\b", source, re.IGNORECASE):
            return "No preference"

        matches = [
            name for name, pattern in self._cloud_patterns.items() if pattern.search(source)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) < 2:
            return None

        explicitly_preferred = [
            name
            for name in matches
            if re.search(
                rf"\b(?:prefer(?:red)?|must\s+use|deploy\s+(?:on|to))\b[^.\n]{{0,32}}"
                rf"{self._cloud_patterns[name].pattern}",
                source,
                re.IGNORECASE,
            )
        ]
        return explicitly_preferred[0] if len(explicitly_preferred) == 1 else None

    def _ground_title(self, title: str, source: str) -> str:
        candidate = " ".join(title.split()).strip(" -:.;,\"")
        source_words = set(re.findall(r"[a-z0-9]+", source.casefold()))
        candidate_words = [
            word
            for word in re.findall(r"[a-z0-9]+", candidate.casefold())
            if word not in self._generic_title_words
        ]
        grounded = [word for word in candidate_words if word in source_words]
        if candidate_words and len(grounded) / len(candidate_words) >= 0.6:
            return candidate[:120]

        fallback_words = [
            word
            for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", source)
            if word.casefold() not in self._generic_title_words
        ][:7]
        return " ".join(fallback_words).title()[:120] or "Untitled Project"
