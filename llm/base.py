"""Provider abstraction.

Generation code depends only on ``QuestionProvider``. Adding a provider means
adding a class here and one line in ``factory.py``; nothing in the generator,
validator or engine changes.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..errors import ProviderError


@dataclass(frozen=True, slots=True)
class GenerationCall:
    """One request for a batch of questions."""

    system: str
    user: str
    #: JSON Schema the response must satisfy. Providers that support forced tool
    #: use pass this straight through; others append it to the prompt.
    schema: Mapping[str, Any]
    max_tokens: int = 8000
    temperature: float = 0.6
    model: str | None = None
    #: Machine-readable form of what the prompt asks for (the blueprint slots).
    #: Model-backed providers ignore this; the offline provider builds from it
    #: instead of parsing English back out of the prompt.
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """A parsed provider response plus what it cost."""

    data: Mapping[str, Any]
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    #: True when the content is placeholder material rather than exam-quality
    #: generated content. Propagated into the paper's disclaimers.
    is_placeholder: bool = False
    warnings: tuple[str, ...] = ()


class QuestionProvider(ABC):
    """Produces structured question data from a prompt."""

    name: str = "provider"

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the model (or strategy) behind this provider."""

    @abstractmethod
    def complete(self, call: GenerationCall) -> ProviderResult:
        """Run one generation call and return parsed JSON."""

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model}


# ------------------------------------------------------------- JSON extraction

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_payload(text: str, *, provider: str) -> dict[str, Any]:
    """Best-effort parse of a model's textual response into an object.

    Providers that support forced tool use should never need this. It exists for
    text-mode fallbacks, where a model may wrap JSON in a fence or add a
    sentence of preamble.
    """
    if not text or not text.strip():
        raise ProviderError(f"{provider} returned an empty response.")

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)

    fenced = _FENCE.search(stripped)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    # Widest balanced braces, for responses with prose around the JSON.
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"questions": parsed}

    preview = stripped[:200].replace("\n", " ")
    raise ProviderError(f"{provider} did not return valid JSON. Response began: {preview!r}")
