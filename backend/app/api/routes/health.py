from fastapi import APIRouter
import httpx

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str | bool]:
    settings = get_settings()
    ollama_reachable = False
    ollama_model_available = False
    ollama_assistant_model_available = False
    ollama_vision_model_available = False

    if settings.ollama_enabled:
        try:
            response = httpx.get(
                f"{settings.ollama_base_url.rstrip('/')}/api/tags",
                timeout=1.5,
            )
            response.raise_for_status()
            model_names = {
                model.get("name", "")
                for model in response.json().get("models", [])
                if isinstance(model, dict)
            }
            ollama_reachable = True
            ollama_model_available = settings.ollama_model in model_names
            ollama_assistant_model_available = (
                settings.ollama_assistant_model in model_names
            )
            ollama_vision_model_available = settings.ollama_vision_model in model_names
        except (httpx.HTTPError, ValueError, TypeError):
            pass

    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "ollama_enabled": settings.ollama_enabled,
        "ollama_reachable": ollama_reachable,
        "ollama_model": settings.ollama_model,
        "ollama_model_available": ollama_model_available,
        "ollama_assistant_model": settings.ollama_assistant_model,
        "ollama_assistant_model_available": ollama_assistant_model_available,
        "ollama_vision_model": settings.ollama_vision_model,
        "ollama_vision_model_available": ollama_vision_model_available,
    }

