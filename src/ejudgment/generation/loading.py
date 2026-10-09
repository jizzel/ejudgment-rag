"""Build the configured LLM provider. Construction makes no network call.

A provider that is selected but not usable raises :class:`LLMUnavailable` with the reason;
there is never a silent fallback to another provider.
"""

from ejudgment.config import Settings
from ejudgment.generation.base import LLMProvider, LLMUnavailable
from ejudgment.generation.ollama_provider import OllamaProvider


def make_llm(
    settings: Settings, model: str | None = None, provider: str | None = None
) -> LLMProvider:
    chosen = provider or settings.llm_provider
    if chosen == "ollama":
        return OllamaProvider(settings, model=model)
    if chosen == "openai":
        from ejudgment.generation.openai_provider import OpenAIProvider

        if not settings.openai_enabled:
            raise LLMUnavailable("OpenAI is disabled (set OPENAI_ENABLED=true to opt in)")
        if settings.openai_api_key is None:
            raise LLMUnavailable("OPENAI_API_KEY is not set")
        name = model or settings.openai_chat_model
        if name not in settings.openai_prices:
            raise LLMUnavailable(
                f"no price configured for OpenAI model {name!r} (openai_prices); its cost "
                "cannot be estimated, so it is not used"
            )
        return OpenAIProvider(settings, model=name)
    raise LLMUnavailable(f"unsupported llm_provider {chosen!r}")
