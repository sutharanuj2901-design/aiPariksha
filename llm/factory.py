"""Provider selection.

Registering a new provider is a single ``PROVIDERS`` entry. Nothing else in the
codebase learns its name.
"""

from __future__ import annotations

from typing import Any, Callable

from ..config import Settings
from ..errors import ProviderError
from .anthropic_provider import AnthropicProvider
from .base import QuestionProvider
from .offline_provider import OfflineTemplateProvider


def _build_anthropic(settings: Settings, *, heavy: bool = False, **kwargs: Any) -> QuestionProvider:
    return AnthropicProvider(
        api_key=settings.api_key,
        model=settings.model_for(heavy=heavy),
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        **kwargs,
    )


def _build_offline(settings: Settings, **_: Any) -> QuestionProvider:
    return OfflineTemplateProvider()


PROVIDERS: dict[str, Callable[..., QuestionProvider]] = {
    "anthropic": _build_anthropic,
    "claude": _build_anthropic,
    "offline": _build_offline,
    "mock": _build_offline,
}


def get_provider(settings: Settings, *, heavy: bool = False, **kwargs: Any) -> QuestionProvider:
    """Instantiate the configured provider.

    With ``provider="auto"`` (the default) this returns the Claude provider when
    an API key is present and the offline provider when it is not.
    """
    name = settings.resolved_provider.lower()
    builder = PROVIDERS.get(name)
    if builder is None:
        raise ProviderError(
            f"Unknown provider {name!r}. Available: {', '.join(sorted(PROVIDERS))}."
        )
    return builder(settings, heavy=heavy, **kwargs)


def register_provider(name: str, builder: Callable[..., QuestionProvider]) -> None:
    """Hook for deployments that ship their own provider."""
    PROVIDERS[name.lower()] = builder
