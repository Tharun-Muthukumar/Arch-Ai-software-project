import json
import logging
from hashlib import sha256
from time import perf_counter
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.ai.prompts import build_structured_prompt

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
    ) -> dict[str, Any] | None:
        if not self.settings.ollama_enabled:
            return None

        source_fingerprint = None
        if raw_requirement := input_data.get("raw_requirement"):
            serialized_source = json.dumps(raw_requirement, sort_keys=True, ensure_ascii=True)
            source_fingerprint = sha256(serialized_source.encode("utf-8")).hexdigest()[:12]
            logger.info(
                "Calling Ollama for %s with raw requirement fingerprint=%s",
                stage,
                source_fingerprint,
            )

        payload = {
            "model": self.settings.ollama_model,
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
                {
                    "role": "user",
                    "content": build_structured_prompt(stage, input_data),
                },
            ],
        }

        try:
            started_at = perf_counter()
            with httpx.Client(
                base_url=self.settings.ollama_base_url,
                timeout=max(self.settings.request_timeout_seconds, minimum_timeout_seconds),
            ) as client:
                response = client.post("/api/chat", json=payload)
                response.raise_for_status()
                response_body = response.json()
                content = response_body["message"]["content"]
                refined = json.loads(content)
                if isinstance(refined, dict):
                    logger.info(
                        "Applied Ollama output for %s%s in %.1fs (%s output tokens)",
                        stage,
                        f" fingerprint={source_fingerprint}" if source_fingerprint else "",
                        perf_counter() - started_at,
                        response_body.get("eval_count", "unknown"),
                    )
                    return refined
        except Exception as exc:  # pragma: no cover - network failures are expected locally
            logger.info("Skipping Ollama refinement for %s: %s", stage, exc)

        return None

    def refine(self, stage: str, seed: dict[str, Any]) -> dict[str, Any] | None:
        return self.generate(stage, seed)

