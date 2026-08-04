"""Claude-backed question provider.

Uses a forced tool call so the model must emit an object matching our schema —
far more reliable than asking for JSON in prose and parsing it back. Falls back
to text extraction only if a tool block is somehow absent.

The SDK is imported lazily so the rest of the package works without it
installed, which is what keeps the offline path dependency-free.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from ..errors import ProviderError
from .base import GenerationCall, ProviderResult, QuestionProvider, parse_json_payload

#: The single tool the model is forced to call.
_TOOL_NAME = "submit_questions"

#: Errors worth retrying with backoff rather than surfacing immediately.
_RETRYABLE = ("overloaded", "rate_limit", "timeout", "internal_server", "api_error", "503", "429")


class AnthropicProvider(QuestionProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ProviderError(
                "No API key configured. Set AIPARIKSHA_API_KEY to enable model-backed "
                "generation, or run with provider='offline' for placeholder papers."
            )
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._client = client  # Injectable for tests.

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------------ client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic  # noqa: PLC0415 - deliberately lazy
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError(
                "The 'anthropic' package is required for model-backed generation. "
                "Install it with: pip install anthropic"
            ) from exc
        self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout)
        return self._client

    # ---------------------------------------------------------------- requests

    def complete(self, call: GenerationCall) -> ProviderResult:
        client = self._get_client()
        model = call.model or self._model
        tool = {
            "name": _TOOL_NAME,
            "description": (
                "Submit the generated examination questions. Every field is required "
                "unless the schema marks it optional."
            ),
            "input_schema": dict(call.schema),
        }

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=call.max_tokens,
                    temperature=call.temperature,
                    system=call.system,
                    messages=[{"role": "user", "content": call.user}],
                    tools=[tool],
                    tool_choice={"type": "tool", "name": _TOOL_NAME},
                )
            except Exception as exc:  # noqa: BLE001 - SDK raises a family of errors
                last_error = exc
                if attempt < self._max_retries and _is_retryable(exc):
                    time.sleep(1.5 * (2**attempt))
                    continue
                raise ProviderError(f"Claude request failed: {exc}") from exc

            return self._to_result(response, model)

        raise ProviderError(f"Claude request failed after retries: {last_error}")

    def _to_result(self, response: Any, model: str) -> ProviderResult:
        warnings: list[str] = []
        data: Mapping[str, Any] | None = None

        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == _TOOL_NAME:
                candidate = getattr(block, "input", None)
                if isinstance(candidate, Mapping):
                    data = candidate
                    break

        if data is None:
            # No tool block: recover from any text the model did emit.
            text = "".join(
                getattr(b, "text", "")
                for b in getattr(response, "content", []) or []
                if getattr(b, "type", None) == "text"
            )
            warnings.append("Model did not use the tool; JSON was recovered from text output.")
            data = parse_json_payload(text, provider=self.name)

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            warnings.append(
                "Response hit the token limit and may be truncated; reduce batch_size."
            )

        usage = getattr(response, "usage", None)
        return ProviderResult(
            data=data,
            provider=self.name,
            model=model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            warnings=tuple(warnings),
        )


def _is_retryable(exc: Exception) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(token in blob for token in _RETRYABLE)
