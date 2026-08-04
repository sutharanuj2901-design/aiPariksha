"""Runtime configuration.

The API key ships **blank** on purpose. With no key configured the engine selects
the offline template provider so the whole pipeline — blueprint, validation,
scoring, analytics — runs end to end without network access. Drop a key in and
the same code path produces exam-quality content from the model.

Resolution order for every setting: explicit argument > environment variable >
default below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any

#: Left blank deliberately. Set AIPARIKSHA_API_KEY (or ANTHROPIC_API_KEY) to
#: enable model-backed generation.
DEFAULT_API_KEY = ""

#: Sonnet is the default: the blueprint already fixes the paper's composition,
#: so the model's job is well-scoped writing, and "fast response" is one of the
#: platform's core principles. Override with AIPARIKSHA_MODEL for harder papers.
DEFAULT_MODEL = "claude-sonnet-5"

#: Model used when a request asks for the hardest tiers (JEE Advanced, Hard mixes).
DEFAULT_HEAVY_MODEL = "claude-opus-5"


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything tunable, in one immutable object."""

    api_key: str = DEFAULT_API_KEY
    provider: str = "auto"
    model: str = DEFAULT_MODEL
    heavy_model: str = DEFAULT_HEAVY_MODEL
    #: Questions requested from the model per call. Batching keeps latency and
    #: token limits manageable on a 180-question full mock.
    batch_size: int = 15
    max_tokens: int = 8000
    #: Low but non-zero: papers should vary between attempts without the model
    #: drifting off the blueprint.
    temperature: float = 0.6
    timeout_seconds: float = 120.0
    max_retries: int = 2
    #: Extra attempts allowed to replace questions rejected by the quality gate.
    max_repair_rounds: int = 2
    #: Reject a paper if more than this fraction of questions fail validation.
    quality_failure_tolerance: float = 0.34

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def resolved_provider(self) -> str:
        """Which provider ``auto`` means right now."""
        if self.provider != "auto":
            return self.provider
        return "anthropic" if self.has_api_key else "offline"

    def model_for(self, *, heavy: bool = False) -> str:
        return self.heavy_model if heavy else self.model

    def with_overrides(self, **kwargs: Any) -> "Settings":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self

    def describe(self) -> dict[str, Any]:
        """Safe to log or return: never includes the key itself."""
        return {
            "provider": self.resolved_provider,
            "model": self.model,
            "api_key_configured": self.has_api_key,
            "batch_size": self.batch_size,
            "temperature": self.temperature,
        }


def load_settings(**overrides: Any) -> Settings:
    """Build settings from the environment, then apply explicit overrides."""
    env = os.environ
    settings = Settings(
        api_key=env.get("AIPARIKSHA_API_KEY") or env.get("ANTHROPIC_API_KEY") or DEFAULT_API_KEY,
        provider=env.get("AIPARIKSHA_PROVIDER", "auto"),
        model=env.get("AIPARIKSHA_MODEL", DEFAULT_MODEL),
        heavy_model=env.get("AIPARIKSHA_HEAVY_MODEL", DEFAULT_HEAVY_MODEL),
        batch_size=_int(env.get("AIPARIKSHA_BATCH_SIZE"), 15),
        max_tokens=_int(env.get("AIPARIKSHA_MAX_TOKENS"), 8000),
        temperature=_float(env.get("AIPARIKSHA_TEMPERATURE"), 0.6),
        timeout_seconds=_float(env.get("AIPARIKSHA_TIMEOUT"), 120.0),
        max_retries=_int(env.get("AIPARIKSHA_MAX_RETRIES"), 2),
    )
    return settings.with_overrides(**overrides)


def _int(raw: str | None, fallback: int) -> int:
    try:
        return int(raw) if raw not in (None, "") else fallback
    except ValueError:
        return fallback


def _float(raw: str | None, fallback: float) -> float:
    try:
        return float(raw) if raw not in (None, "") else fallback
    except ValueError:
        return fallback
