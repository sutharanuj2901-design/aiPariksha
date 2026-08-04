"""Typed errors.

Every failure mode maps to a JSON-serialisable envelope so callers never have
to parse tracebacks. ``ClarificationNeeded`` is deliberately *not* an internal
error: it is the mechanism by which the engine refuses to guess at a missing
required input, as mandated by the product spec.
"""

from __future__ import annotations

from typing import Any


class AIParikshaError(Exception):
    """Base class for everything this package raises on purpose."""

    code = "engine_error"
    http_status = 500

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
            },
        }


class ValidationError(AIParikshaError):
    """Input was present but malformed (wrong type, out of range, unknown enum)."""

    code = "invalid_input"
    http_status = 422

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.field:
            payload["error"]["field"] = self.field
        return payload


class ClarificationNeeded(AIParikshaError):
    """A required input is missing.

    The engine asks instead of assuming. Carries the exact questions to put in
    front of the student, plus the machine-readable field names so a UI can
    focus the right inputs.
    """

    code = "clarification_needed"
    http_status = 400

    def __init__(self, questions: list[str], *, missing_fields: list[str] | None = None) -> None:
        super().__init__("Additional information is required before a paper can be generated.")
        self.questions = questions
        self.missing_fields = missing_fields or []

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["error"]["questions"] = list(self.questions)
        payload["error"]["missing_fields"] = list(self.missing_fields)
        return payload


class UnknownExamError(ValidationError):
    code = "unknown_exam"
    http_status = 404

    def __init__(self, exam: str, supported: list[str]) -> None:
        super().__init__(
            f"{exam!r} is not a registered exam. Supported: {', '.join(supported)}.",
            field="exam",
        )
        self.supported = supported

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["error"]["supported_exams"] = list(self.supported)
        return payload


class SyllabusError(ValidationError):
    """A requested subject / chapter / topic is outside the exam syllabus."""

    code = "outside_syllabus"
    http_status = 422


class BlueprintError(AIParikshaError):
    """The requested shape of paper cannot be satisfied by the exam pattern."""

    code = "blueprint_infeasible"
    http_status = 422


class ProviderError(AIParikshaError):
    """The underlying model call failed or returned unusable content."""

    code = "provider_error"
    http_status = 502


class QualityGateError(AIParikshaError):
    """Generated content failed the non-negotiable quality checks."""

    code = "quality_gate_failed"
    http_status = 502

    def __init__(self, message: str, *, failures: list[str] | None = None) -> None:
        super().__init__(message)
        self.failures = failures or []

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["error"]["failures"] = list(self.failures)
        return payload
