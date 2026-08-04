"""What the student sends back after attempting a paper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class StudentResponse:
    """One answer.

    An empty ``selected`` with no ``value`` means the question was left
    unattempted, which is scored differently from a wrong answer.
    """

    question_id: str
    selected: tuple[str, ...] = ()
    value: float | None = None
    time_spent_seconds: float = 0.0
    marked_for_review: bool = False

    @property
    def is_attempted(self) -> bool:
        return bool(self.selected) or self.value is not None

    @classmethod
    def from_dict(cls, raw: Any, index: int = 0) -> "StudentResponse":
        where = f"responses[{index}]"
        if not isinstance(raw, Mapping):
            raise ValidationError(f"{where}: expected an object.", field=where)

        qid = raw.get("question_id") or raw.get("id") or raw.get("q")
        if not qid:
            raise ValidationError(f"{where}.question_id is required.", field=f"{where}.question_id")

        selected_raw = raw.get("selected")
        if selected_raw is None:
            selected_raw = raw.get("answer") if not isinstance(raw.get("answer"), (int, float)) else None
        if selected_raw is None:
            selected_raw = raw.get("selected_options")

        selected: tuple[str, ...] = ()
        if isinstance(selected_raw, str):
            # "A" or "A,C" or "AC" all mean the same thing.
            cleaned = selected_raw.strip().upper().replace(" ", "")
            if cleaned:
                parts = cleaned.split(",") if "," in cleaned else list(cleaned)
                selected = tuple(dict.fromkeys(p for p in parts if p))
        elif isinstance(selected_raw, Sequence):
            selected = tuple(dict.fromkeys(str(p).strip().upper() for p in selected_raw if str(p).strip()))
        elif selected_raw is not None:
            raise ValidationError(f"{where}.selected: expected a string or list.", field=f"{where}.selected")

        value = raw.get("value")
        if value is None and isinstance(raw.get("answer"), (int, float)) and not isinstance(raw.get("answer"), bool):
            value = raw["answer"]
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValidationError(
                    f"{where}.value: expected a number for a numerical answer.", field=f"{where}.value"
                ) from None

        time_spent = raw.get("time_spent_seconds", raw.get("time_spent", 0)) or 0
        try:
            time_spent = max(0.0, float(time_spent))
        except (TypeError, ValueError):
            raise ValidationError(
                f"{where}.time_spent_seconds: expected a number of seconds.",
                field=f"{where}.time_spent_seconds",
            ) from None

        return cls(
            question_id=str(qid).strip(),
            selected=selected,
            value=value,
            time_spent_seconds=time_spent,
            marked_for_review=bool(raw.get("marked_for_review", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question_id": self.question_id,
            "attempted": self.is_attempted,
            "time_spent_seconds": self.time_spent_seconds,
        }
        if self.selected:
            payload["selected"] = list(self.selected)
        if self.value is not None:
            payload["value"] = self.value
        if self.marked_for_review:
            payload["marked_for_review"] = True
        return payload


@dataclass(frozen=True, slots=True)
class Submission:
    """A student's completed attempt at one paper."""

    paper_id: str = ""
    student_id: str = ""
    responses: tuple[StudentResponse, ...] = ()
    #: Wall-clock time the student actually used, in seconds. Falls back to the
    #: sum of per-question times when the client does not report a total.
    total_time_spent_seconds: float = 0.0

    def response_for(self, question_id: str) -> StudentResponse | None:
        needle = str(question_id).strip().upper()
        for response in self.responses:
            if response.question_id.upper() == needle:
                return response
        return None

    @property
    def effective_total_time(self) -> float:
        if self.total_time_spent_seconds > 0:
            return self.total_time_spent_seconds
        return round(sum(r.time_spent_seconds for r in self.responses), 2)

    @property
    def has_per_question_timing(self) -> bool:
        return any(r.time_spent_seconds > 0 for r in self.responses)

    @classmethod
    def from_dict(cls, raw: Any) -> "Submission":
        if not isinstance(raw, Mapping):
            raise ValidationError("Submission body must be a JSON object.")
        responses_raw = raw.get("responses") or raw.get("answers") or []
        if isinstance(responses_raw, Mapping):
            # Accept the compact {"Q1": "A", "Q2": "C"} shape too.
            responses_raw = [
                {"question_id": k, "selected": v} if not isinstance(v, (int, float)) or isinstance(v, bool)
                else {"question_id": k, "value": v}
                for k, v in responses_raw.items()
            ]
        if not isinstance(responses_raw, list):
            raise ValidationError("responses: expected a list or an object keyed by question id.", field="responses")

        seen: set[str] = set()
        responses: list[StudentResponse] = []
        for index, item in enumerate(responses_raw):
            response = StudentResponse.from_dict(item, index)
            key = response.question_id.upper()
            if key in seen:
                raise ValidationError(
                    f"responses: duplicate answer for {response.question_id}.", field="responses"
                )
            seen.add(key)
            responses.append(response)

        total_time = raw.get("total_time_spent_seconds", raw.get("total_time_spent", 0)) or 0
        try:
            total_time = max(0.0, float(total_time))
        except (TypeError, ValueError):
            raise ValidationError(
                "total_time_spent_seconds: expected a number of seconds.",
                field="total_time_spent_seconds",
            ) from None

        return cls(
            paper_id=str(raw.get("paper_id") or ""),
            student_id=str(raw.get("student_id") or ""),
            responses=tuple(responses),
            total_time_spent_seconds=total_time,
        )
