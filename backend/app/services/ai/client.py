import json
import logging
from hashlib import sha256
from time import perf_counter
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.ai.prompts import build_structured_prompt
from app.services.generation_runtime import (
    GENERATION_TELEMETRY,
    PROJECT_GENERATION_CACHE,
    stable_input_hash,
)

logger = logging.getLogger(__name__)


class OllamaStructuredClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate(
        self,
        stage: str,
        input_data: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None = None,
        num_predict: int = 256,
        num_ctx: int = 2048,
        minimum_timeout_seconds: int = 0,
        timeout_seconds: int | None = None,
        model: str | None = None,
        images: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if not self.settings.ollama_enabled:
            return None

        project_id = str(input_data.get("project_id") or "")
        selected_model = model or self.settings.ollama_model
        cache_payload = {
            "stage": stage,
            "model": selected_model,
            "input": input_data,
            "images": [sha256(image.encode("ascii")).hexdigest() for image in images or []],
            "schema": response_schema,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        }
        cache_hash = stable_input_hash(cache_payload)
        if project_id:
            cached = PROJECT_GENERATION_CACHE.get(
                project_id, cache_hash, f"llm:{stage}"
            )
            if cached is not None:
                GENERATION_TELEMETRY.section(project_id, f"llm:{stage}", 0.0, True)
                return cached

        source_fingerprint = None
        if raw_requirement := input_data.get("raw_requirement"):
            serialized_source = json.dumps(raw_requirement, sort_keys=True, ensure_ascii=True)
            source_fingerprint = sha256(serialized_source.encode("utf-8")).hexdigest()[:12]
            logger.info(
                "Calling Ollama for %s with raw requirement fingerprint=%s",
                stage,
                source_fingerprint,
            )

        prompt = build_structured_prompt(stage, input_data)
        if images:
            prompt = (
                "One image is attached to this user message. Inspect its visible content first, "
                "then answer the raw requirement using only visible image evidence and supplied "
                f"project facts.\n{prompt}"
            )
        user_message: dict[str, Any] = {
            "role": "user",
            "content": prompt,
        }
        if images:
            user_message["images"] = images

        payload = {
            "model": selected_model,
            "stream": False,
            "format": response_schema or "json",
            "think": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0,
                "seed": 42,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
            "messages": [
                {
                    "role": "system",
                    "content": "You return structured JSON only.",
                },
                user_message,
            ],
        }

        try:
            started_at = perf_counter()
            if project_id:
                GENERATION_TELEMETRY.llm_call(project_id, stage)
            with httpx.Client(
                base_url=self.settings.ollama_base_url,
                timeout=(
                    timeout_seconds
                    if timeout_seconds is not None
                    else max(self.settings.request_timeout_seconds, minimum_timeout_seconds)
                ),
            ) as client:
                response = client.post("/api/chat", json=payload)
                response.raise_for_status()
                response_body = response.json()
                content = response_body["message"]["content"]
                refined = json.loads(content)
                if isinstance(refined, dict):
                    duration_ms = (perf_counter() - started_at) * 1000
                    if project_id:
                        PROJECT_GENERATION_CACHE.put(
                            project_id, cache_hash, f"llm:{stage}", refined
                        )
                        GENERATION_TELEMETRY.section(
                            project_id, f"llm:{stage}", duration_ms, False
                        )
                    logger.info(
                        "Applied Ollama output for %s%s in %.1fs (%s output tokens)",
                        stage,
                        f" fingerprint={source_fingerprint}" if source_fingerprint else "",
                        duration_ms / 1000,
                        response_body.get("eval_count", "unknown"),
                    )
                    return refined
        except Exception as exc:  # pragma: no cover - network failures are expected locally
            logger.info("Skipping Ollama refinement for %s: %s", stage, exc)

        return None

    def refine(self, stage: str, seed: dict[str, Any]) -> dict[str, Any] | None:
        return self.generate(stage, seed)
