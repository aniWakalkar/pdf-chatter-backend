from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

PROVIDER_DEFAULTS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "chat_model": "gemini-3.5-flash-lite",
        "fallback_chat_model": "gemini-3.1-flash-lite,gemini-flash-lite-latest,gemini-3.5-flash",
        "reasoning_effort": "low",
        "embedding_model": "gemini-embedding-001",
    },
    "openai": {
        "base_url": "",
        "chat_model": "gpt-4.1-mini",
        "fallback_chat_model": "",
        "reasoning_effort": "",
        "embedding_model": "text-embedding-3-small",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24
    internal_service_token: str

    ai_provider: str = "gemini"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_chat_model: str = ""
    ai_fallback_chat_model: str | None = None
    ai_reasoning_effort: str | None = None
    ai_embedding_model: str = ""
    embedding_dimensions: int = 768
    embedding_batch_size: int = 100
    llm_timeout_seconds: float = 45
    chat_timeout_seconds: float = 20

    max_upload_mb: int = 20

    chunk_size_chars: int = 3200
    chunk_overlap_chars: int = 480
    retrieval_top_k: int = 5
    min_relevance_score: float = 0.25
    history_messages: int = 6

    auth_service_url: str = "http://127.0.0.1:8001"
    document_service_url: str = "http://127.0.0.1:8002"
    chat_service_url: str = "http://127.0.0.1:8003"
    cors_origins: str = "http://localhost:5173"

    def _provider_default(self, key: str) -> str:
        return PROVIDER_DEFAULTS.get(self.ai_provider.lower(), PROVIDER_DEFAULTS["openai"])[key]

    @property
    def resolved_base_url(self) -> str | None:
        return self.ai_base_url or self._provider_default("base_url") or None

    @property
    def resolved_chat_model(self) -> str:
        return self.ai_chat_model or self._provider_default("chat_model")

    @property
    def resolved_chat_models(self) -> list[str]:
        fallback = self.ai_fallback_chat_model
        if fallback is None:
            fallback = self._provider_default("fallback_chat_model")
        fallbacks = [m.strip() for m in fallback.split(",")]
        return [m for m in dict.fromkeys([self.resolved_chat_model, *fallbacks]) if m]

    @property
    def resolved_reasoning_effort(self) -> str:
        if self.ai_reasoning_effort is not None:
            return self.ai_reasoning_effort
        return self._provider_default("reasoning_effort")

    @property
    def resolved_embedding_model(self) -> str:
        return self.ai_embedding_model or self._provider_default("embedding_model")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
