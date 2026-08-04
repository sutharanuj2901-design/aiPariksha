"""Performance breakdowns.

Bucketing is generic: every slice (section, subject, chapter, topic, difficulty)
is the same aggregation over a different key. New slices cost one line.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, Sequence

from ..models.enums import ResponseStatus
from ..models.paper import Paper
from ..models.report import BucketPerformance, QuestionResult, TimeUtilisation
from ..models.submission import Submission
from .scorer import ScoreSheet

#: How many of the slowest questions to surface in the time analysis.
_SLOWEST_LIMIT = 5


def bucket_by(
    results: Iterable[QuestionResult], key: Callable[[QuestionResult], str]
) -> tuple[BucketPerformance, ...]:
    """Aggregate results into named buckets, preserving first-seen order."""
    buckets: dict[str, BucketPerformance] = {}
    for result in results:
        name = key(result) or "Unspecified"
        bucket = buckets.setdefault(name, BucketPerformance(name=name))
        bucket.add(
            result.status,
            result.marks_awarded,
            result.marks_possible,
            result.time_spent_seconds,
        )
    return tuple(buckets.values())


def by_section(results: Iterable[QuestionResult]) -> tuple[BucketPerformance, ...]:
    return bucket_by(results, lambda r: r.section)


def by_subject(results: Iterable[QuestionResult]) -> tuple[BucketPerformance, ...]:
    return bucket_by(results, lambda r: r.subject)


def by_chapter(results: Iterable[QuestionResult]) -> tuple[BucketPerformance, ...]:
    return bucket_by(results, lambda r: r.chapter)


def by_topic(results: Iterable[QuestionResult]) -> tuple[BucketPerformance, ...]:
    return bucket_by(results, lambda r: r.topic)


def by_difficulty(results: Iterable[QuestionResult]) -> tuple[BucketPerformance, ...]:
    """Difficulty buckets in Easy -> Hard order rather than encounter order."""
    order = {"Easy": 0, "Medium": 1, "Hard": 2}
    buckets = bucket_by(results, lambda r: r.difficulty)
    return tuple(sorted(buckets, key=lambda b: order.get(b.name, 99)))


def time_utilisation(
    paper: Paper, submission: Submission, sheet: ScoreSheet
) -> TimeUtilisation:
    """How the clock was spent.

    When the client reports no timings at all, everything time-related is
    reported as unavailable rather than as zero — a zero would read as "answered
    instantly", which is a different and wrong claim.
    """
    allotted = paper.duration_minutes * 60.0
    has_timing = submission.has_per_question_timing or submission.total_time_spent_seconds > 0
    used = submission.effective_total_time

    attempted = sheet.attempted
    per_question = round(used / len(sheet.results), 1) if has_timing and sheet.results else None
    per_attempted = round(used / attempted, 1) if has_timing and attempted else None

    slowest: list[Mapping[str, object]] = []
    if submission.has_per_question_timing:
        ranked = sorted(sheet.results, key=lambda r: -r.time_spent_seconds)[:_SLOWEST_LIMIT]
        slowest = [
            {
                "question_id": r.question_id,
                "chapter": r.chapter,
                "topic": r.topic,
                "difficulty": r.difficulty,
                "status": str(r.status),
                "seconds": r.time_spent_seconds,
                "fair_seconds": sheet.fair_seconds_per_question,
            }
            for r in ranked
            if r.time_spent_seconds > 0
        ]

    return TimeUtilisation(
        allotted_seconds=allotted,
        used_seconds=used,
        average_per_question_seconds=per_question,
        average_per_attempted_seconds=per_attempted,
        fair_time_per_question_seconds=sheet.fair_seconds_per_question,
        slowest_questions=tuple(slowest),
        timing_data_available=has_timing,
    )


def pacing_observations(sheet: ScoreSheet, utilisation: TimeUtilisation) -> list[str]:
    """Plain-language notes about time management."""
    notes: list[str] = []
    if not utilisation.timing_data_available:
        return notes

    used_share = utilisation.utilisation_percentage
    if used_share is not None:
        if used_share > 100:
            notes.append(
                f"You used {used_share:.0f}% of the allotted time — over the limit. In the real "
                "exam the paper would have been submitted before you finished."
            )
        elif used_share < 60 and sheet.unattempted > 0:
            notes.append(
                f"You used only {used_share:.0f}% of the time yet left {sheet.unattempted} "
                "question(s) unattempted. There was time available to attempt more."
            )

    overruns = [r for r in sheet.results if r.time_overrun]
    if overruns:
        wasted = sum(r.time_spent_seconds for r in overruns if r.status is not ResponseStatus.CORRECT)
        if wasted > 0:
            notes.append(
                f"{len(overruns)} question(s) ran well over the fair time budget, and "
                f"{round(wasted / 60.0, 1)} minutes of that went into questions you did not get "
                "right. Learning to abandon these earlier is worth more marks than solving them."
            )

    return notes


def weakest_buckets(
    buckets: Sequence[BucketPerformance],
    *,
    limit: int = 5,
    min_questions: int = 2,
    threshold: float = 60.0,
) -> list[BucketPerformance]:
    """Buckets worth flagging as weak, lowest accuracy first.

    ``min_questions`` guards against declaring a chapter weak on the strength of
    one missed question.
    """
    candidates = [
        b
        for b in buckets
        if b.total >= min_questions and b.accuracy is not None and b.accuracy < threshold
    ]
    candidates.sort(key=lambda b: (b.accuracy or 0.0, -b.total))
    return candidates[:limit]


def strongest_buckets(
    buckets: Sequence[BucketPerformance],
    *,
    limit: int = 5,
    min_questions: int = 2,
    threshold: float = 80.0,
) -> list[BucketPerformance]:
    candidates = [
        b
        for b in buckets
        if b.total >= min_questions and b.accuracy is not None and b.accuracy >= threshold
    ]
    candidates.sort(key=lambda b: (-(b.accuracy or 0.0), -b.total))
    return candidates[:limit]


def skipped_buckets(
    buckets: Sequence[BucketPerformance], *, limit: int = 5, threshold: float = 50.0
) -> list[BucketPerformance]:
    """Buckets the student mostly left alone — often avoidance, not weakness."""
    candidates = [
        b
        for b in buckets
        if b.total >= 2 and b.attempt_rate is not None and b.attempt_rate <= threshold
    ]
    candidates.sort(key=lambda b: (b.attempt_rate or 0.0, -b.total))
    return candidates[:limit]
