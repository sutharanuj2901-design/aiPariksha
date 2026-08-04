"""Gemini-backed question provider.

Talks to the Generative Language REST API with ``urllib`` rather than the
``google-genai`` SDK, so the package keeps its zero-dependency promise and this
provider works the moment a key is configured.

Structured output uses ``responseSchema`` with ``responseMimeType:
application/json``, which is Gemini's equivalent of a forced tool call. Gemini
accepts only a subset of JSON Schema (an OpenAPI 3.0 flavour), so
``to_gemini_schema`` strips what it cannot handle instead of letting the API
reject the whole request.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from ..errors import ProviderError
from .base import GenerationCall, ProviderResult, QuestionProvider, parse_json_payload

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

#: HTTP statuses worth retrying with backoff.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

#: Schema keywords Gemini understands. Anything else is dropped.
_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "propertyOrdering",
        "minItems",
        "maxItems",
    }
)


def to_gemini_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema to the subset Gemini accepts.

    Drops unsupported keywords (``additionalProperties``, ``$schema``, ``oneOf``,
    …) recursively, and adds ``propertyOrdering`` so field order in the response
    is stable rather than arbitrary.
    """
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _ALLOWED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, Mapping):
            out["properties"] = {
                name: to_gemini_schema(sub) if isinstance(sub, Mapping) else sub
                for name, sub in value.items()
            }
        elif key == "items" and isinstance(value, Mapping):
            out["items"] = to_gemini_schema(value)
        elif key == "type" and isinstance(value, str):
            # Gemini expects the type name uppercased.
            out["type"] = value.upper()
        else:
            out[key] = value

    if "properties" in out and "propertyOrdering" not in out:
        out["propertyOrdering"] = list(out["properties"].keys())
    return out


class GeminiProvider(QuestionProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        thinking_budget: int | None = None,
        transport: Any | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ProviderError(
                "No Gemini API key configured. Set AIPARIKSHA_GEMINI_API_KEY (or "
                "GEMINI_API_KEY) to enable Gemini-backed generation."
            )
        self._api_key = api_key.strip()
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._thinking_budget = thinking_budget
        #: Injectable for tests: a callable taking (url, body, headers) -> bytes.
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    # ---------------------------------------------------------------- requests

    def complete(self, call: GenerationCall) -> ProviderResult:
        model = call.model or self._model
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": call.system}]},
            "contents": [{"role": "user", "parts": [{"text": call.user}]}],
            "generationConfig": {
                "temperature": call.temperature,
                "maxOutputTokens": call.max_tokens,
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(call.schema),
            },
        }
        url = f"{API_ROOT}/{model}:generateContent"

        if self._thinking_budget is None:
            return self._to_result(self._post(url, payload), model)

        # Thinking control is not accepted by every model or alias -- the
        # "-latest" aliases reject it outright with a bare "invalid argument".
        # Try it, then fall back to a plain request rather than failing the batch.
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": self._thinking_budget}
        try:
            return self._to_result(self._post(url, payload), model)
        except ProviderError as error:
            if "HTTP 400" not in str(error):
                raise
            payload["generationConfig"].pop("thinkingConfig", None)
            result = self._to_result(self._post(url, payload), model)
            return ProviderResult(
                data=result.data,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                warnings=result.warnings
                + (
                    f"{model} rejected a thinking budget, so the request was retried "
                    "without one. Unset AIPARIKSHA_GEMINI_THINKING_BUDGET to skip this.",
                ),
            )

    def _post(self, url: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # Header rather than ?key= so the secret stays out of URLs and logs.
            "x-goog-api-key": self._api_key,
        }

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                if self._transport is not None:
                    text = self._transport(url, body, headers)
                else:
                    request = urllib.request.Request(
                        url, data=body, headers=headers, method="POST"
                    )
                    with urllib.request.urlopen(request, timeout=self._timeout) as response:
                        text = response.read()
                return json.loads(text.decode("utf-8"))

            except urllib.error.HTTPError as error:
                detail = _read_error(error)
                if error.code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    last_error = error
                    time.sleep(1.5 * (2**attempt))
                    continue
                raise ProviderError(_explain(error.code, detail)) from error

            except urllib.error.URLError as error:
                last_error = error
                if attempt < self._max_retries:
                    time.sleep(1.5 * (2**attempt))
                    continue
                raise ProviderError(
                    f"Could not reach the Gemini API: {error.reason}. Check your network "
                    "connection or run with provider='offline'."
                ) from error

            except json.JSONDecodeError as error:
                raise ProviderError(f"Gemini returned a non-JSON response: {error}") from error

        raise ProviderError(f"Gemini request failed after retries: {last_error}")

    def _to_result(self, raw: Mapping[str, Any], model: str) -> ProviderResult:
        warnings: list[str] = []

        blocked = (raw.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise ProviderError(
                f"Gemini declined the request (block reason: {blocked}). This usually means a "
                "safety filter fired on the prompt; try a different topic or chapter."
            )

        candidates = raw.get("candidates") or []
        if not candidates:
            raise ProviderError("Gemini returned no candidates for this request.")

        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            warnings.append(
                "Gemini hit the output token limit and the batch may be truncated; "
                "reduce batch_size."
            )
        elif finish == "SAFETY":
            raise ProviderError(
                "Gemini stopped generation on a safety filter. Try a different chapter or topic."
            )

        text = "".join(
            part.get("text", "")
            for part in ((candidate.get("content") or {}).get("parts") or [])
            if isinstance(part, Mapping)
        )
        # responseMimeType guarantees JSON, but a truncated response still needs
        # the salvage path.
        data = parse_json_payload(text, provider=self.name)

        usage = raw.get("usageMetadata") or {}
        return ProviderResult(
            data=data,
            provider=self.name,
            model=model,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
            warnings=tuple(warnings),
        )


def _read_error(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - the body is best-effort diagnostics
        return ""
    message = (payload.get("error") or {}).get("message")
    return str(message or "")


def _explain(status: int, detail: str) -> str:
    """Turn an HTTP status into something a developer can act on."""
    tail = f" API said: {detail}" if detail else ""
    if status in (401, 403):
        return (
            "Gemini rejected the credential (HTTP "
            f"{status}). Note that Generative Language API keys begin with 'AIza' - an "
            "OAuth access token or gcloud token will not work here. Create a key at "
            f"https://aistudio.google.com/apikey.{tail}"
        )
    if status == 400:
        return f"Gemini rejected the request as malformed (HTTP 400).{tail}"
    if status == 404:
        return (
            "Gemini could not find that model (HTTP 404). Check AIPARIKSHA_GEMINI_MODEL - "
            f"try 'gemini-2.5-flash'.{tail}"
        )
    if status == 429:
        return f"Gemini rate limit or quota exhausted (HTTP 429).{tail}"
    return f"Gemini request failed with HTTP {status}.{tail}"
