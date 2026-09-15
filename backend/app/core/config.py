from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ArchAI"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./archai.db"
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5175",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:3000",
        ]
    )
    allowed_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_assistant_model: str = "qwen3:8b"
    ollama_vision_model: str = "qwen3-vl:4b-instruct"
    # Ollama unloads the model after this idle window. At the old hardcoded 5m
    # every assistant turn after a short pause paid a multi-second reload before
    # inference even started.
    ollama_keep_alive: str = "30m"
    request_timeout_seconds: int = 180
    # Deadlines for the turns that genuinely need the model. Past these the
    # assistant answers from canonical evidence instead of blocking the UI.
    # Per-attempt deadlines. These are deliberately short: a local model that
    # has not answered in this long is not about to.
    assistant_question_timeout_seconds: int = 10
    assistant_change_timeout_seconds: int = 14
    assistant_risk_timeout_seconds: int = 25
    # Hard ceiling on the WHOLE turn, retries and fallback included. Without
    # this, adding a retry ladder made the worst case longer rather than more
    # reliable, and the user just watched a spinner.
    assistant_total_budget_seconds: int = 22
    assistant_risk_budget_seconds: int = 40
    # One controlled retry, then a smaller model that answers faster. Set the
    # fallback to "" to disable it. Neither can guarantee a response, which is
    # why every assistant path ends in a grounded deterministic answer.
    assistant_retry_once: bool = True
    assistant_fallback_model: str = "qwen3:1.7b"
    assistant_fallback_timeout_seconds: int = 8
    auth_session_hours: int = 8
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="ARCHAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        return [origin.strip() for origin in value.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
