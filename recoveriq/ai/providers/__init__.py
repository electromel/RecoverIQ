"""Registre des fournisseurs LLM disponibles (ordre = ordre d'affichage)."""

from __future__ import annotations

from recoveriq.ai.providers.anthropic import AnthropicProvider
from recoveriq.ai.providers.base import (
    Completion,
    LLMProvider,
    ProviderConfig,
    ProviderError,
    ProviderTimeout,
    TestResult,
)
from recoveriq.ai.providers.gemini import GeminiProvider
from recoveriq.ai.providers.openai_compat import CustomProvider, MistralProvider, OpenAIProvider

PROVIDER_CLASSES: tuple[type[LLMProvider], ...] = (
    AnthropicProvider, OpenAIProvider, GeminiProvider, MistralProvider, CustomProvider,
)


def build_registry() -> dict[str, LLMProvider]:
    return {cls.id: cls() for cls in PROVIDER_CLASSES}


__all__ = [
    "PROVIDER_CLASSES", "build_registry", "Completion", "LLMProvider", "ProviderConfig",
    "ProviderError", "ProviderTimeout", "TestResult",
]
