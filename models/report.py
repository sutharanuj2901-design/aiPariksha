"""Evaluation and analytics output structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .enums import ReadinessBand, ResponseStatus

#: Attached to every estimate so a relative projection is never mistaken for an
#: official result.
ESTIMATE_DISCLAIMER = (
    "Percentile and readiness figures are internal estimates based on this "
    "attempt and modelled difficulty. They are not official ranks, percentiles "
    "or cut-offs, and they do not predict your actual result."
)


@dataclass(frozen=True, slots=True)
class QuestionResult:
    """Per-question outcome after scoring."""

    question_id: str
    number: int
    section: str
    subject: str
    chapter: str
    topic: str
    difficulty: str
    status: ResponseStatus
    marks_awarded: float
    marks_possible: float
    selected: str = ""
    correct: str = ""
    time_spent_seconds: float = 0.0
    #: True when this question took far longer than the paper's fair-time budget.
    time_overrun: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "number": self.number,
            "section": self.section,
            "subject": self.subject,
            "chapter": self.chapter,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "status": str(self.status),
            "marks_awarded": self.marks_awarded,
            "marks_possible": self.marks_possible,
            "your_answer": self.selected,
            "correct_answer": self.correct,
            "time_spent_seconds": self.time_spent_seconds,
            "time_overrun": self.time_overrun,
        }


@dataclass(slots=True)
class BucketPerformance:
    """Aggregated performance for one slice: a subject, chapter or difficulty."""

    name: str
    total: int = 0
    correct: int = 0
    incorrect: int = 0
    unattempted: int = 0
    partial: int = 0
    marks_awarded: float = 0.0
    marks_possible: float = 0.0
    time_spent_seconds: float = 0.0

    @property
    def attempted(self) -> int:
        return self.correct + self.incorrect + self.partial

    @property
    def accuracy(self) -> float | None:
        """Correct out of *attempted* — the honest measure of accuracy."""
        if self.attempted <= 0:
            return None
        return round(100.0 * (self.correct + 0.5 * self.partial) / self.attempted, 2)

    @property
    def score_percentage(self) -> float | None:
        if self.marks_possible <= 0:
            return None
        return round(100.0 * self.marks_awarded / self.marks_possible, 2)

    @property
    def attempt_rate(self) -> float | None:
        if self.total <= 0:
            return None
        return round(100.0 * self.attempted / self.total, 2)

    @property
    def average_time_seconds(self) -> float | None:
        if self.attempted <= 0 or self.time_spent_seconds <= 0:
            return None
        return round(self.time_spent_seconds / self.attempted, 1)

    def add(self, status: ResponseStatus, awarded: float, possible: float, seconds: float) -> None:
        self.total += 1
        self.marks_awarded = round(self.marks_awarded + awarded, 4)
        self.marks_possible = round(self.marks_possible + possible, 4)
        self.time_spent_seconds = round(self.time_spent_seconds + seconds, 2)
        if status is ResponseStatus.CORRECT:
            self.correct += 1
        elif status is ResponseStatus.INCORRECT:
            self.incorrect += 1
        elif status is ResponseStatus.PARTIAL:
            self.partial += 1
        else:
            self.unattempted += 1

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "total_questions": self.total,
            "attempted": self.attempted,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "unattempted": self.unattempted,
            "marks_awarded": round(self.marks_awarded, 2),
            "marks_possible": round(self.marks_possible, 2),
            "accuracy_percentage": self.accuracy,
            "score_percentage": self.score_percentage,
            "attempt_rate_percentage": self.attempt_rate,
            "average_time_seconds": self.average_time_seconds,
        }
        if self.partial:
            payload["partially_correct"] = self.partial
        return payload


@dataclass(slots=True)
class TimeUtilisation:
    """How the student spent the clock."""

    allotted_seconds: float = 0.0
    used_seconds: float = 0.0
    average_per_question_seconds: float | None = None
    average_per_attempted_seconds: float | None = None
    fair_time_per_question_seconds: float | None = None
    slowest_questions: tuple[Mapping[str, Any], ...] = ()
    #: Present only when the client reported per-question timings.
    timing_data_available: bool = False

    @property
    def utilisation_percentage(self) -> float | None:
        if self.allotted_seconds <= 0 or not self.timing_data_available:
            return None
        return round(100.0 * self.used_seconds / self.allotted_seconds, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timing_data_available": self.timing_data_available,
            "allotted_minutes": round(self.allotted_seconds / 60.0, 2),
            "used_minutes": round(self.used_seconds / 60.0, 2) if self.timing_data_available else None,
            "utilisation_percentage": self.utilisation_percentage,
            "average_seconds_per_question": self.average_per_question_seconds,
            "average_seconds_per_attempted_question": self.average_per_attempted_seconds,
            "fair_seconds_per_question": self.fair_time_per_question_seconds,
            "slowest_questions": [dict(q) for q in self.slowest_questions],
        }


@dataclass(slots=True)
class Recommendation:
    """A single actionable next step."""

    topic: str
    chapter: str = ""
    subject: str = ""
    reason: str = ""
    priority: str = "medium"
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "chapter": self.chapter,
            "subject": self.subject,
            "reason": self.reason,
            "priority": self.priority,
            "suggested_action": self.suggested_action,
        }


@dataclass(slots=True)
class NextTestSuggestion:
    """A ready-to-submit generation request for the student's next paper."""

    rationale: str = ""
    request: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"rationale": self.rationale, "request": dict(self.request)}


@dataclass(slots=True)
class EvaluationReport:
    """The complete post-submission analysis."""

    paper_id: str
    exam: str
    test_title: str
    student_id: str = ""
    total_score: float = 0.0
    maximum_marks: float = 0.0
    total_questions: int = 0
    correct: int = 0
    incorrect: int = 0
    unattempted: int = 0
    partial: int = 0
    accuracy_percentage: float | None = None
    score_percentage: float | None = None
    attempt_rate_percentage: float | None = None
    negative_marks_lost: float = 0.0
    marks_lost_to_unattempted: float = 0.0
    subject_performance: tuple[BucketPerformance, ...] = ()
    chapter_performance: tuple[BucketPerformance, ...] = ()
    topic_performance: tuple[BucketPerformance, ...] = ()
    difficulty_performance: tuple[BucketPerformance, ...] = ()
    section_performance: tuple[BucketPerformance, ...] = ()
    time_utilisation: TimeUtilisation = field(default_factory=TimeUtilisation)
    question_results: tuple[QuestionResult, ...] = ()
    strengths: tuple[str, ...] = ()
    improvement_areas: tuple[str, ...] = ()
    weak_concepts: tuple[str, ...] = ()
    recommendations: tuple[Recommendation, ...] = ()
    next_test: NextTestSuggestion | None = None
    readiness_band: ReadinessBand | None = None
    readiness_score: float | None = None
    estimated_percentile_range: str = ""
    personalised_feedback: str = ""
    revision_plan: tuple[Mapping[str, Any], ...] = ()
    unmatched_response_ids: tuple[str, ...] = ()
    disclaimers: tuple[str, ...] = ()

    def to_dict(self, *, include_question_results: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paper_id": self.paper_id,
            "exam": self.exam,
            "test_title": self.test_title,
            "student_id": self.student_id,
            "summary": {
                "total_score": round(self.total_score, 2),
                "maximum_marks": round(self.maximum_marks, 2),
                "score_percentage": self.score_percentage,
                "total_questions": self.total_questions,
                "correct": self.correct,
                "incorrect": self.incorrect,
                "unattempted": self.unattempted,
                "partially_correct": self.partial,
                "accuracy_percentage": self.accuracy_percentage,
                "attempt_rate_percentage": self.attempt_rate_percentage,
                "negative_marks_lost": round(self.negative_marks_lost, 2),
                "marks_left_on_the_table": round(self.marks_lost_to_unattempted, 2),
            },
            "section_performance": [b.to_dict() for b in self.section_performance],
            "subject_performance": [b.to_dict() for b in self.subject_performance],
            "chapter_performance": [b.to_dict() for b in self.chapter_performance],
            "topic_performance": [b.to_dict() for b in self.topic_performance],
            "difficulty_performance": [b.to_dict() for b in self.difficulty_performance],
            "time_utilisation": self.time_utilisation.to_dict(),
            "strengths": list(self.strengths),
            "areas_for_improvement": list(self.improvement_areas),
            "weak_concepts": list(self.weak_concepts),
            "recommended_next_topics": [r.to_dict() for r in self.recommendations],
            "suggested_next_test": self.next_test.to_dict() if self.next_test else None,
            "readiness": {
                "band": str(self.readiness_band) if self.readiness_band else None,
                "score_out_of_100": self.readiness_score,
                "estimated_percentile_range": self.estimated_percentile_range or None,
                "disclaimer": ESTIMATE_DISCLAIMER,
            },
            "revision_plan": [dict(p) for p in self.revision_plan],
            "personalised_feedback": self.personalised_feedback,
            "disclaimers": list(self.disclaimers),
        }
        if self.unmatched_response_ids:
            payload["warnings"] = {
                "unmatched_response_ids": list(self.unmatched_response_ids),
                "message": (
                    "These answers did not match any question in the paper and were ignored."
                ),
            }
        if include_question_results:
            payload["question_wise_results"] = [q.to_dict() for q in self.question_results]
        return payload
