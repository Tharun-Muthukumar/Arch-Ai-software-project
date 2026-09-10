"""Project-isolated generation cache, compact context, and runtime telemetry."""

from __future__ import annotations

import copy
import json
import threading
from collections import OrderedDict
from hashlib import sha256
from time import perf_counter
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field

from app.schemas.domain import RequirementModel

GENERATOR_VERSION = "parallel-compact-project-v3"
_MAX_CACHE_ENTRIES = 256
T = TypeVar("T")


def stable_input_hash(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


class CompactProjectContext(BaseModel):
    """Only decision-relevant, canonical facts shared by local generators."""

    project_id: str
    input_hash: str
    generator_version: str = GENERATOR_VERSION
    domain: str
    summary: str
    scale_profile: str
    functional_requirements: list[str] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    actors: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    bounded_contexts: list[dict[str, Any]] = Field(default_factory=list)
    integrations: list[dict[str, Any]] = Field(default_factory=list)
    technical_characteristics: list[dict[str, Any]] = Field(default_factory=list)
    security: dict[str, Any] = Field(default_factory=dict)
    project_profile: dict[str, Any] = Field(default_factory=dict)
    confirmed_answers: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        project_id: str,
        requirements: RequirementModel,
        answers: dict[str, str],
    ) -> "CompactProjectContext":
        canonical = {
            "domain": requirements.domain,
            "summary": requirements.summary,
            "scale_profile": requirements.scale_profile,
            "functional_requirements": requirements.functional_requirements,
            "non_functional_requirements": requirements.non_functional_requirements,
            "constraints": requirements.constraints,
            "actors": [item.model_dump(exclude={"description"}) for item in requirements.actors],
            "entities": [item.model_dump() for item in requirements.domain_entities],
            "workflows": [item.model_dump() for item in requirements.domain_workflows],
            "bounded_contexts": [item.model_dump() for item in requirements.bounded_contexts],
            "integrations": [item.model_dump() for item in requirements.integration_details],
            "technical_characteristics": [item.model_dump() for item in requirements.technical_characteristics],
            "security": requirements.security_model.model_dump(),
            "project_profile": requirements.project_profile.model_dump(),
            "confirmed_answers": {
                key: value for key, value in sorted(answers.items()) if value and value.strip()
            },
        }
        return cls(
            project_id=project_id,
            input_hash=stable_input_hash(canonical),
            **canonical,
        )

    def cache_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"project_id"})


class ProjectGenerationCache:
    """Bounded process cache whose key always includes project ownership."""

    def __init__(self, max_entries: int = _MAX_CACHE_ENTRIES) -> None:
        self.max_entries = max_entries
        self._values: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def key(project_id: str, input_hash: str, section: str) -> str:
        if not project_id:
            raise ValueError("project_id is required for generation caching")
        return f"{project_id}:{input_hash}:{GENERATOR_VERSION}:{section}"

    def get(self, project_id: str, input_hash: str, section: str) -> Any | None:
        key = self.key(project_id, input_hash, section)
        with self._lock:
            if key not in self._values:
                return None
            value = self._values.pop(key)
            self._values[key] = value
            return copy.deepcopy(value)

    def put(self, project_id: str, input_hash: str, section: str, value: Any) -> None:
        key = self.key(project_id, input_hash, section)
        with self._lock:
            self._values.pop(key, None)
            self._values[key] = copy.deepcopy(value)
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)

    def get_or_compute(
        self,
        project_id: str,
        section: str,
        payload: Any,
        producer: Callable[[], T],
    ) -> tuple[T, bool, float]:
        input_hash = stable_input_hash(payload)
        cached = self.get(project_id, input_hash, section)
        if cached is not None:
            return cached, True, 0.0
        started = perf_counter()
        value = producer()
        duration_ms = (perf_counter() - started) * 1000
        self.put(project_id, input_hash, section, value)
        return value, False, duration_ms

    def invalidate_project(self, project_id: str) -> None:
        prefix = f"{project_id}:"
        with self._lock:
            for key in [key for key in self._values if key.startswith(prefix)]:
                self._values.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


PROJECT_GENERATION_CACHE = ProjectGenerationCache()


class GenerationTelemetry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] = {}

    def start(self, project_id: str) -> None:
        with self._lock:
            self._data[project_id] = {
                "project_id": project_id,
                "generator_version": GENERATOR_VERSION,
                "started_at": perf_counter(),
                "generation_time_ms": 0.0,
                "llm_calls": 0,
                "llm_stages": [],
                "cache_hits": 0,
                "cache_misses": 0,
                "section_times_ms": {},
            }

    def llm_call(self, project_id: str, stage: str) -> None:
        with self._lock:
            record = self._data.get(project_id)
            if record is not None:
                record["llm_calls"] += 1
                record["llm_stages"].append(stage)

    def section(self, project_id: str, name: str, duration_ms: float, cache_hit: bool) -> None:
        with self._lock:
            record = self._data.get(project_id)
            if record is None:
                return
            record["cache_hits" if cache_hit else "cache_misses"] += 1
            record["section_times_ms"][name] = round(duration_ms, 2)

    def finish(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._data.get(project_id)
            if record is None:
                return {}
            record["generation_time_ms"] = round(
                (perf_counter() - record.pop("started_at", perf_counter())) * 1000,
                2,
            )
            return copy.deepcopy(record)

    def snapshot(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._data.get(project_id)
            if record is None:
                return None
            snapshot = copy.deepcopy(record)
            started = snapshot.pop("started_at", None)
            if started is not None:
                snapshot["generation_time_ms"] = round((perf_counter() - started) * 1000, 2)
            return snapshot

    def invalidate_project(self, project_id: str) -> None:
        with self._lock:
            self._data.pop(project_id, None)


GENERATION_TELEMETRY = GenerationTelemetry()
