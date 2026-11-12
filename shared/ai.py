import json
import logging
import re
from functools import lru_cache

import openai
from openai import OpenAI

from shared.config import get_settings

logger = logging.getLogger("ai")

class AIConfigurationError(RuntimeError):
    pass


@lru_cache
def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.ai_api_key:
        raise AIConfigurationError("AI_API_KEY is not configured")
    return OpenAI(
        api_key=settings.ai_api_key,
        base_url=settings.resolved_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=5,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    client = get_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), settings.embedding_batch_size):
        batch = texts[start : start + settings.embedding_batch_size]
        response = client.embeddings.create(
            model=settings.resolved_embedding_model,
            input=batch,
            dimensions=settings.embedding_dimensions,
        )
        items = response.data
        if all(item.index is not None for item in items):
            items = sorted(items, key=lambda d: d.index)
        if len(items) != len(batch):
            raise AIConfigurationError("The embedding service returned an unexpected number of vectors")
        for item in items:
            if len(item.embedding) != settings.embedding_dimensions:
                raise AIConfigurationError(
                    f"Embedding size {len(item.embedding)} does not match EMBEDDING_DIMENSIONS"
                )
            vectors.append(item.embedding)
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


RETRYABLE_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.RateLimitError,
    openai.NotFoundError,
)


def _complete(client: OpenAI, model: str, messages: list[dict], reasoning_effort: str) -> str:
    options = {"response_format": {"type": "json_object"}}
    if reasoning_effort:
        options["reasoning_effort"] = reasoning_effort
    try:
        response = client.chat.completions.create(model=model, messages=messages, temperature=0.1, **options)
    except openai.BadRequestError:
        response = client.chat.completions.create(model=model, messages=messages, temperature=0.1)
    return response.choices[0].message.content or "{}"


def chat_json(messages: list[dict]) -> str:
    settings = get_settings()
    client = get_client().with_options(max_retries=1, timeout=settings.chat_timeout_seconds)
    last_error: Exception | None = None
    for model in settings.resolved_chat_models:
        try:
            return _complete(client, model, messages, settings.resolved_reasoning_effort)
        except RETRYABLE_ERRORS as exc:
            logger.warning("Chat model %s failed: %s", model, type(exc).__name__)
            last_error = exc
    raise last_error or AIConfigurationError("No chat model configured")


def extract_json(raw: str) -> dict | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None
