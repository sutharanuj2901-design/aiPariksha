"""Student performance history.

Consumed by the adaptive planner and the recommender. Entirely optional: when no
history is supplied every consumer degrades to pattern defaults rather than
inventing a prior skill level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..errors import ValidationError
from .enums import Difficulty


@dataclass(frozen=True, slots=True)
class Tally:
    """Attempted / correct counts for one bucket."""

    attempted: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float | None:
        """Fraction correct out of attempted, or ``None`` when never attempted."""
        if self.attempted <= 0:
            return None
        return round(self.correct / self.attempted, 4)

    def merged(self, other: "Tally") -> "Tally":
        return Tally(self.attempted + other.attempted, self.correct + other.correct)

    @classmethod
    def from_dict(cls, raw: Any, field_name: str) -> "Tally":
        if not isinstance(raw, Mapping):
            raise ValidationError(f"{field_name}: expected an object with 'attempted' and 'correct'.", field=field_name)
        attempted = _int(raw.get("attempted", 0), f"{field_name}.attempted")
        correct = _int(raw.get("correct", 0), f"{field_name}.correct")
        if correct > attempted:
            raise ValidationError(f"{field_name}: correct ({correct}) cannot exceed attempted ({attempted}).", field=field_name)
        return cls(attempted, correct)

    def to_dict(self) -> dict[str, Any]:
        return {"attempted": self.attempted, "correct": self.correct, "accuracy": self.accuracy}


@dataclass(frozen=True, slots=True)
class AttemptSummary:
    """One completed test, reduced to the numbers the planner needs."""

    paper_id: str
    exam: str
    #: ISO date string. Kept as text so the engine never needs a clock.
    taken_on: str = ""
    score: float = 0.0
    max_marks: float = 0.0
    subject_stats: Mapping[str, Tally] = field(default_factory=dict)
    chapter_stats: Mapping[str, Tally] = field(default_factory=dict)
    difficulty_stats: Mapping[str, Tally] = field(default_factory=dict)

    @property
    def percentage(self) -> float | None:
        if self.max_marks <= 0:
            return None
        return round(100.0 * self.score / self.max_marks, 2)

    @classmethod
    def from_dict(cls, raw: Any, index: int = 0) -> "AttemptSummary":
        where = f"attempts[{index}]"
        if not isinstance(raw, Mapping):
            raise ValidationError(f"{where}: expected an object.", field=where)
        return cls(
            paper_id=str(raw.get("paper_id") or f"attempt-{index + 1}"),
            exam=str(raw.get("exam") or ""),
            taken_on=str(raw.get("taken_on") or raw.get("date") or ""),
            score=_float(raw.get("score", 0), f"{where}.score"),
            max_marks=_float(raw.get("max_marks", 0), f"{where}.max_marks"),
            subject_stats=_tallies(raw.get("subject_stats"), f"{where}.subject_stats"),
            chapter_stats=_tallies(raw.get("chapter_stats"), f"{where}.chapter_stats"),
            difficulty_stats=_tallies(raw.get("difficulty_stats"), f"{where}.difficulty_stats"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "exam": self.exam,
            "taken_on": self.taken_on,
            "score": self.score,
            "max_marks": self.max_marks,
            "percentage": self.percentage,
            "subject_stats": {k: v.to_dict() for k, v in self.subject_stats.items()},
            "chapter_stats": {k: v.to_dict() for k, v in self.chapter_stats.items()},
            "difficulty_stats": {k: v.to_dict() for k, v in self.difficulty_stats.items()},
        }


@dataclass(frozen=True, slots=True)
class StudentHistory:
    """Aggregated view over a student's past attempts."""

    student_id: str = ""
    attempts: tuple[AttemptSummary, ...] = ()

    #: Buckets with fewer attempts than this are treated as "insufficient data"
    #: rather than as evidence of weakness.
    MIN_SAMPLE = 4

    @property
    def is_empty(self) -> bool:
        return not self.attempts

    # ------------------------------------------------------------ aggregation

    def _merge(self, key: str) -> dict[str, Tally]:
        """Sum one stat family across every attempt, newest last."""
        out: dict[str, Tally] = {}
        for attempt in self.attempts:
            for name, tally in getattr(attempt, key).items():
                out[name] = out.get(name, Tally()).merged(tally)
        return out

    def chapter_accuracy(self) -> dict[str, Tally]:
        return self._merge("chapter_stats")

    def subject_accuracy(self) -> dict[str, Tally]:
        return self._merge("subject_stats")

    def difficulty_accuracy(self) -> dict[str, Tally]:
        return self._merge("difficulty_stats")

    def overall_accuracy(self) -> float | None:
        merged = Tally()
        for tally in self.chapter_accuracy().values():
            merged = merged.merged(tally)
        return merged.accuracy

    def recent_percentage(self, window: int = 3) -> float | None:
        """Mean percentage over the most recent ``window`` attempts."""
        scored = [a.percentage for a in self.attempts[-window:] if a.percentage is not None]
        if not scored:
            return None
        return round(sum(scored) / len(scored), 2)

    def trend(self, window: int = 3) -> str | None:
        """"improving" / "declining" / "steady" over the last two windows."""
        scored = [a.percentage for a in self.attempts if a.percentage is not None]
        if len(scored) < 2:
            return None
        recent = scored[-window:]
        earlier = scored[:-window] or scored[:1]
        delta = (sum(recent) / len(recent)) - (sum(earlier) / len(earlier))
        if delta >= 3:
            return "improving"
        if delta <= -3:
            return "declining"
        return "steady"

    def weak_chapters(self, limit: int = 5, threshold: float = 0.60) -> list[tuple[str, Tally]]:
        """Chapters below ``threshold`` accuracy with enough attempts to trust."""
        scored = [
            (name, tally)
            for name, tally in self.chapter_accuracy().items()
            if tally.attempted >= self.MIN_SAMPLE
            and tally.accuracy is not None
            and tally.accuracy < threshold
        ]
        scored.sort(key=lambda item: (item[1].accuracy or 0.0, -item[1].attempted))
        return scored[:limit]

    def strong_chapters(self, limit: int = 5, threshold: float = 0.80) -> list[tuple[str, Tally]]:
        scored = [
            (name, tally)
            for name, tally in self.chapter_accuracy().items()
            if tally.attempted >= self.MIN_SAMPLE
            and tally.accuracy is not None
            and tally.accuracy >= threshold
        ]
        scored.sort(key=lambda item: (-(item[1].accuracy or 0.0), -item[1].attempted))
        return scored[:limit]

    # ------------------------------------------------------------------- I/O

    @classmethod
    def from_dict(cls, raw: Any) -> "StudentHistory":
        if raw is None:
            return cls()
        if isinstance(raw, StudentHistory):
            return raw
        if not isinstance(raw, Mapping):
            raise ValidationError("student_history: expected an object.", field="student_history")
        attempts_raw = raw.get("attempts") or []
        if not isinstance(attempts_raw, list):
            raise ValidationError("student_history.attempts: expected a list.", field="student_history.attempts")
        return cls(
            student_id=str(raw.get("student_id") or ""),
            attempts=tuple(AttemptSummary.from_dict(a, i) for i, a in enumerate(attempts_raw)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "attempt_count": len(self.attempts),
            "overall_accuracy": self.overall_accuracy(),
            "recent_percentage": self.recent_percentage(),
            "trend": self.trend(),
            "attempts": [a.to_dict() for a in self.attempts],
        }


def _tallies(raw: Any, field_name: str) -> dict[str, Tally]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValidationError(f"{field_name}: expected an object keyed by name.", field=field_name)
    return {str(k): Tally.from_dict(v, f"{field_name}.{k}") for k, v in raw.items()}


def _int(raw: Any, field_name: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name}: expected an integer, got {raw!r}.", field=field_name) from None


def _float(raw: Any, field_name: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name}: expected a number, got {raw!r}.", field=field_name) from None
