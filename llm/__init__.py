"""Pluggable question providers."""

from __future__ import annotations

from .anthropic_provider import AnthropicProvider
from .base import GenerationCall, ProviderResult, QuestionProvider, parse_json_payload
from .factory import PROVIDERS, get_provider, register_provider
from .offline_provider import OfflineTemplateProvider

__all__ = [
    "AnthropicProvider",
    "GenerationCall",
    "OfflineTemplateProvider",
    "PROVIDERS",
    "ProviderResult",
    "QuestionProvider",
    "get_provider",
    "parse_json_payload",
    "register_provider",
]
