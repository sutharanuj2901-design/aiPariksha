"""Turning numbers into next actions.

Two constraints shape everything here:

* **No invented data.** Every claim traces to this attempt or to supplied
  history. With no history, nothing is said about trends.
* **No official-sounding predictions.** Readiness and percentile are labelled
  estimates with a stated basis, never presented as ranks or cut-offs.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..models.enums import Difficulty, ReadinessBand, SolutionDepth, TestType
from ..models.history import StudentHistory
from ..models.paper import Paper
from ..models.report import BucketPerformance, NextTestSuggestion, Recommendation
from .analytics import (
    pacing_observations,
    skipped_buckets,
    strongest_buckets,
    weakest_buckets,
)
from .scorer import ScoreSheet

#: Readiness band cut-offs on the internal 0-100 readiness score.
_BANDS = (
    (80.0, ReadinessBand.STRONG),
    (65.0, ReadinessBand.EXAM_READY),
    (45.0, ReadinessBand.DEVELOPING),
    (0.0, ReadinessBand.FOUNDATION),
)

#: Coarse score-percentage -> estimated percentile band. Deliberately wide.
_PERCENTILE_TABLE = (
    (85.0, "98th percentile or above"),
    (70.0, "90th to 98th percentile"),
    (55.0, "75th to 90th percentile"),
    (40.0, "50th to 75th percentile"),
    (25.0, "25th to 50th percentile"),
    (0.0, "below the 25th percentile"),
)


def strengths(
    subject_buckets: Sequence[BucketPerformance],
    chapter_buckets: Sequence[BucketPerformance],
    difficulty_buckets: Sequence[BucketPerformance],
) -> tuple[str, ...]:
    """What actually went well, stated with the evidence."""
    out: list[str] = []
    for bucket in strongest_buckets(subject_buckets, limit=3):
        out.append(
            f"{bucket.name}: {bucket.accuracy:.0f}% accuracy on {bucket.attempted} attempted "
            f"question(s) — your most reliable area in this paper."
        )
    for bucket in strongest_buckets(chapter_buckets, limit=3, min_questions=2):
        out.append(f"{bucket.name}: {bucket.correct}/{bucket.total} correct.")

    hard = next((b for b in difficulty_buckets if b.name == str(Difficulty.HARD)), None)
    if hard and hard.accuracy is not None and hard.accuracy >= 60 and hard.attempted >= 2:
        out.append(
            f"You solved {hard.accuracy:.0f}% of the Hard questions you attempted, which "
            "indicates real conceptual depth rather than pattern matching."
        )
    return tuple(dict.fromkeys(out))


def improvement_areas(
    sheet: ScoreSheet,
    subject_buckets: Sequence[BucketPerformance],
    chapter_buckets: Sequence[BucketPerformance],
    difficulty_buckets: Sequence[BucketPerformance],
    pacing: Sequence[str],
) -> tuple[str, ...]:
    """Specific, evidence-backed problems — not generic advice."""
    out: list[str] = []

    # Only the worst subject earns the "biggest drag" framing; the rest are
    # listed plainly so the ranking stays meaningful.
    for position, bucket in enumerate(weakest_buckets(subject_buckets, limit=3)):
        tail = (
            " This is the biggest single drag on your score."
            if position == 0
            else " This is holding your total back too."
        )
        out.append(
            f"{bucket.name}: {bucket.accuracy:.0f}% accuracy on {bucket.attempted} attempted "
            f"question(s).{tail}"
        )
    for bucket in weakest_buckets(chapter_buckets, limit=4, min_questions=2):
        out.append(f"{bucket.name}: {bucket.correct}/{bucket.total} correct.")

    for bucket in skipped_buckets(chapter_buckets, limit=3):
        out.append(
            f"{bucket.name}: you attempted only {bucket.attempt_rate:.0f}% of these questions. "
            "Skipping a whole chapter costs more than getting some of it wrong."
        )

    # Negative marking discipline: wrong answers that cost more than they could win.
    if sheet.negative_marks_lost > 0 and sheet.attempted:
        accuracy = sheet.accuracy_percentage or 0.0
        if accuracy < 60:
            out.append(
                f"Negative marking cost you {sheet.negative_marks_lost:g} marks at "
                f"{accuracy:.0f}% accuracy. At this accuracy, guessing loses marks on average, "
                "so attempt fewer questions and be surer of each."
            )

    if sheet.unattempted and sheet.marks_lost_to_unattempted > 0:
        share = 100.0 * sheet.unattempted / max(sheet.total_questions, 1)
        if share >= 25:
            out.append(
                f"You left {sheet.unattempted} question(s) ({share:.0f}% of the paper) "
                f"unattempted, worth {sheet.marks_lost_to_unattempted:g} marks."
            )

    easy = next((b for b in difficulty_buckets if b.name == str(Difficulty.EASY)), None)
    if easy and easy.accuracy is not None and easy.accuracy < 75 and easy.attempted >= 3:
        out.append(
            f"Only {easy.accuracy:.0f}% of the Easy questions were correct. Errors here are the "
            "cheapest marks to recover and usually come from misreading, not from lack of knowledge."
        )

    out.extend(pacing)
    return tuple(dict.fromkeys(out))


def weak_concepts(topic_buckets: Sequence[BucketPerformance], limit: int = 8) -> tuple[str, ...]:
    """Topic-level misses — the granularity a student can actually revise."""
    weak = [
        b
        for b in topic_buckets
        if b.attempted > 0 and b.accuracy is not None and b.accuracy < 100 and b.correct < b.total
    ]
    weak.sort(key=lambda b: (b.accuracy or 0.0, -b.total))
    return tuple(b.name for b in weak[:limit])


def recommendations(
    chapter_buckets: Sequence[BucketPerformance],
    topic_buckets: Sequence[BucketPerformance],
    results_index: Mapping[str, tuple[str, str]],
    limit: int = 6,
) -> tuple[Recommendation, ...]:
    """Ranked next topics, each with a reason and a concrete action."""
    out: list[Recommendation] = []

    for bucket in weakest_buckets(chapter_buckets, limit=limit, min_questions=2, threshold=70.0):
        subject, _ = results_index.get(bucket.name, ("", ""))
        priority = "high" if (bucket.accuracy or 0) < 40 else "medium"
        out.append(
            Recommendation(
                topic=bucket.name,
                chapter=bucket.name,
                subject=subject,
                reason=(
                    f"{bucket.correct}/{bucket.total} correct "
                    f"({bucket.accuracy:.0f}% accuracy on attempted questions)."
                ),
                priority=priority,
                suggested_action=(
                    f"Re-read the core theory for {bucket.name}, then take a 15-question "
                    "chapter-wise test on it before your next full mock."
                ),
            )
        )

    # Fill the remainder with topic-level gaps not already covered by a chapter.
    covered = {r.chapter for r in out}
    for bucket in topic_buckets:
        if len(out) >= limit:
            break
        if bucket.accuracy is None or bucket.accuracy >= 60 or bucket.total < 1:
            continue
        subject, chapter = results_index.get(bucket.name, ("", ""))
        if chapter and chapter in covered:
            continue
        out.append(
            Recommendation(
                topic=bucket.name,
                chapter=chapter,
                subject=subject,
                reason=f"{bucket.correct}/{bucket.total} correct on this topic.",
                priority="medium" if (bucket.accuracy or 0) < 50 else "low",
                suggested_action=f"Practise 8 to 10 targeted questions on {bucket.name}.",
            )
        )

    return tuple(out[:limit])


def readiness(
    sheet: ScoreSheet,
    difficulty_buckets: Sequence[BucketPerformance],
    history: StudentHistory,
) -> tuple[float, ReadinessBand, list[str]]:
    """A 0-100 readiness estimate, its band, and how it was derived.

    Weighted toward score (what the exam actually pays for) but penalising the
    two habits that do not survive a real exam hall: low accuracy under negative
    marking, and leaving large parts of the paper untouched.
    """
    basis: list[str] = []
    score_pct = sheet.score_percentage or 0.0
    accuracy = sheet.accuracy_percentage or 0.0
    attempt_rate = sheet.attempt_rate_percentage or 0.0

    value = 0.55 * score_pct + 0.30 * accuracy + 0.15 * attempt_rate
    basis.append(
        f"Blended from score ({score_pct:.0f}%), accuracy ({accuracy:.0f}%) and "
        f"attempt rate ({attempt_rate:.0f}%)."
    )

    hard = next((b for b in difficulty_buckets if b.name == str(Difficulty.HARD)), None)
    if hard and hard.attempted >= 2 and hard.accuracy is not None:
        adjustment = (hard.accuracy - 50.0) * 0.06
        value += adjustment
        basis.append(
            f"Adjusted by {adjustment:+.1f} for {hard.accuracy:.0f}% accuracy on Hard questions."
        )

    if not history.is_empty:
        trend = history.trend()
        if trend == "improving":
            value += 2.0
            basis.append("Adjusted +2.0 for an improving trend across your recent attempts.")
        elif trend == "declining":
            value -= 2.0
            basis.append("Adjusted -2.0 for a declining trend across your recent attempts.")
    else:
        basis.append(
            "Based on this attempt alone; no previous performance was supplied, so no trend "
            "was assumed."
        )

    value = round(max(0.0, min(100.0, value)), 1)
    band = next(b for threshold, b in _BANDS if value >= threshold)
    return value, band, basis


def percentile_estimate(sheet: ScoreSheet) -> str:
    """A deliberately wide, clearly-labelled relative estimate.

    Negative marking can drive the score below zero, which no percentile band
    covers; the lowest band is the floor rather than a lookup failure.
    """
    score_pct = sheet.score_percentage
    if score_pct is None:
        return ""
    band = next(
        (text for threshold, text in _PERCENTILE_TABLE if score_pct >= threshold),
        _PERCENTILE_TABLE[-1][1],
    )
    return f"estimated {band} among students at a similar preparation stage"


def next_test(
    paper: Paper,
    subject_buckets: Sequence[BucketPerformance],
    chapter_buckets: Sequence[BucketPerformance],
    sheet: ScoreSheet,
) -> NextTestSuggestion:
    """A ready-to-submit request for the student's next paper."""
    weak = weakest_buckets(chapter_buckets, limit=4, min_questions=2, threshold=70.0)
    exam = paper.exam

    # A short paper spreads one question per chapter, which is not enough to call
    # any chapter weak. Fall back to the subject level rather than implying the
    # chapters were all fine.
    thin_chapter_data = not any(b.total >= 2 for b in chapter_buckets)
    if thin_chapter_data and not weak:
        weak_subjects = weakest_buckets(subject_buckets, limit=2, min_questions=2, threshold=70.0)
        if weak_subjects:
            return NextTestSuggestion(
                rationale=(
                    "This paper had too few questions per chapter to pinpoint chapter-level "
                    f"gaps, but {weak_subjects[0].name} clearly underperformed. A longer "
                    "sectional test will show which chapters are responsible."
                ),
                request={
                    "exam": exam,
                    "test_type": str(TestType.SECTIONAL),
                    "subjects": [b.name for b in weak_subjects],
                    "num_questions": 25,
                    "difficulty": str(Difficulty.MIXED),
                    "solutions": str(SolutionDepth.DETAILED),
                },
            )

    if weak:
        chapters = [b.name for b in weak]
        count = min(30, max(10, 5 * len(chapters)))
        return NextTestSuggestion(
            rationale=(
                "Target the chapters that cost you the most marks in this paper before "
                "attempting another full mock."
            ),
            request={
                "exam": exam,
                "test_type": str(TestType.CHAPTER_WISE),
                "chapters": chapters,
                "num_questions": count,
                "difficulty": str(Difficulty.MIXED),
                "solutions": str(SolutionDepth.DETAILED),
            },
        )

    accuracy = sheet.accuracy_percentage or 0.0
    if accuracy >= 80:
        return NextTestSuggestion(
            rationale=(
                "No chapter stands out as weak and your accuracy is high. Step up the "
                "difficulty rather than repeating work at this level."
            ),
            request={
                "exam": exam,
                "test_type": str(TestType.FULL_MOCK),
                "difficulty": str(Difficulty.HARD),
                "solutions": str(SolutionDepth.DETAILED),
            },
        )

    return NextTestSuggestion(
        rationale=(
            "No single chapter stands out from this attempt, but accuracy has room to grow. "
            "Another full-length paper at exam difficulty will build consistency."
        ),
        request={
            "exam": exam,
            "test_type": str(TestType.FULL_MOCK),
            "difficulty": str(Difficulty.MIXED),
            "solutions": str(SolutionDepth.DETAILED),
        },
    )


def revision_plan(
    recommendation_list: Sequence[Recommendation],
    sheet: ScoreSheet,
    days: int = 7,
) -> tuple[Mapping[str, Any], ...]:
    """A concrete short-cycle plan built from this attempt's gaps."""
    if not recommendation_list:
        return ()

    plan: list[Mapping[str, Any]] = []
    topics = [r.topic for r in recommendation_list]
    # Leave the last two days for consolidation rather than new material.
    study_days = max(1, days - 2)

    for day in range(1, study_days + 1):
        focus = topics[(day - 1) % len(topics)]
        plan.append(
            {
                "day": day,
                "focus": focus,
                "activity": (
                    f"Revise the theory for {focus}, then solve 15 to 20 practice questions "
                    "and review every mistake before moving on."
                ),
            }
        )

    plan.append(
        {
            "day": study_days + 1,
            "focus": "Mixed practice",
            "activity": (
                "Take a sectional test covering all the chapters revised this week, under time."
            ),
        }
    )
    plan.append(
        {
            "day": study_days + 2,
            "focus": "Full-length mock",
            "activity": (
                "Attempt a full mock in one sitting at the real exam time, then analyse it the "
                "same day while the reasoning is still fresh."
            ),
        }
    )
    return tuple(plan)


def personalised_feedback(
    paper: Paper,
    sheet: ScoreSheet,
    band: ReadinessBand,
    readiness_score: float,
    strength_list: Sequence[str],
    improvement_list: Sequence[str],
    history: StudentHistory,
) -> str:
    """A short, direct paragraph. Honest before encouraging."""
    parts: list[str] = [
        f"You scored {sheet.total_score:g} out of {sheet.maximum_marks:g} "
        f"({sheet.score_percentage:.1f}%) on this {paper.exam} paper, attempting "
        f"{sheet.attempted} of {sheet.total_questions} questions with "
        f"{sheet.accuracy_percentage:.0f}% accuracy on what you attempted."
        if sheet.score_percentage is not None and sheet.accuracy_percentage is not None
        else f"You attempted {sheet.attempted} of {sheet.total_questions} questions."
    ]

    if strength_list:
        parts.append(f"Working well: {strength_list[0]}")
    if improvement_list:
        parts.append(f"The clearest priority: {improvement_list[0]}")

    if not history.is_empty:
        trend = history.trend()
        recent = history.recent_percentage()
        if trend and recent is not None:
            parts.append(
                f"Across your recent attempts you are {trend}, averaging {recent:.0f}%."
            )

    parts.append(
        f"Overall this places you in the '{band}' band at an internal readiness estimate of "
        f"{readiness_score:.0f}/100. That is a measure of this attempt, not a prediction of "
        "your result."
    )
    return " ".join(parts)


def build_results_index(paper: Paper) -> dict[str, tuple[str, str]]:
    """Map chapter and topic names to their ``(subject, chapter)`` for labelling."""
    index: dict[str, tuple[str, str]] = {}
    for question in paper.questions:
        index.setdefault(question.chapter, (question.subject, question.chapter))
        index.setdefault(question.topic, (question.subject, question.chapter))
    return index
