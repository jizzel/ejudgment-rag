"""Build the configured LLM provider. Construction makes no network call."""

from ejudgment.config import Settings
from ejudgment.generation.base import LLMProvider
from ejudgment.generation.ollama_provider import OllamaProvider


def make_llm(settings: Settings, model: str | None = None) -> LLMProvider:
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings, model=model)
    raise ValueError(f"unsupported llm_provider {settings.llm_provider!r}")
