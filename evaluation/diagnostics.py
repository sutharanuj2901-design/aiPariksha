"""Steps 11 and 12: weak-area identification and readiness estimation.

Both work off *history*, not a single attempt, and both are explicit about their
own limits:

* A topic is flagged weak only against a stated, consistently-applied threshold,
  and the **reason** matters — low accuracy needs practice, avoidance needs
  exposure, and a time-drain needs technique. Those get different advice.
* Readiness needs enough tests to mean anything. Below the minimum it is labelled
  low-confidence and says what would fix that, rather than projecting from one
  paper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..models.history import StudentHistory, Tally
from ..models.report import EvaluationReport

# --- Step 11 thresholds. Stated in the output every time they are applied. ----

#: Accuracy below this, over at least MIN_ATTEMPTS questions, is "low accuracy".
WEAK_ACCURACY_THRESHOLD = 60.0
#: Minimum questions seen before a verdict is drawn at all.
MIN_ATTEMPTS = 4
#: Attempting less than this share of a topic's questions is avoidance.
AVOIDANCE_ATTEMPT_RATE = 50.0
#: Taking more than this multiple of the fair time budget is a time-drain.
TIME_DRAIN_MULTIPLE = 1.6

# --- Step 12 thresholds ------------------------------------------------------

#: Fewer full tests than this and the readiness estimate is low-confidence.
MIN_TESTS_FOR_READINESS = 3

READINESS_NEEDS_WORK = "Needs Work"
READINESS_ON_TRACK = "On Track"
READINESS_EXAM_READY = "Exam-Ready"


@dataclass(frozen=True, slots=True)
class WeakArea:
    """One flagged area, with why it was flagged and what to do about it."""

    name: str
    scope: str  # "chapter" or "topic"
    reason_tags: tuple[str, ...]
    accuracy: float | None
    attempted: int
    total: int
    impact: float
    detail: str
    suggested_test_type: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "reason_tags": list(self.reason_tags),
            "accuracy_percentage": self.accuracy,
            "attempted": self.attempted,
            "total_seen": self.total,
            "expected_impact": round(self.impact, 2),
            "detail": self.detail,
            "suggested_test_type": self.suggested_test_type,
            "suggested_action": self.suggested_action,
        }


def identify_weak_areas(
    history: StudentHistory,
    *,
    latest: EvaluationReport | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Step 11: a ranked, reasoned list of what to fix next.

    ``latest`` supplies time-on-question data, which history does not carry, so
    the time-drain tag is only available when a fresh report is passed in.
    """
    chapter_stats = history.chapter_accuracy()
    if not chapter_stats:
        return {
            "ok": True,
            "threshold_used": _threshold_text(),
            "weak_areas": [],
            "message": (
                "No completed attempts are on record yet, so there is nothing to "
                "diagnose. Take a test and this will populate."
            ),
        }

    drains = _time_drains(latest)
    avoided = _avoided(latest)

    candidates: list[WeakArea] = []
    for name, tally in chapter_stats.items():
        area = _classify(name, tally, drains, avoided)
        if area is not None:
            candidates.append(area)

    # Rank by expected impact: how many marks are realistically recoverable.
    candidates.sort(key=lambda a: -a.impact)
    insufficient = [
        name
        for name, tally in chapter_stats.items()
        if tally.attempted < MIN_ATTEMPTS and (tally.accuracy or 1.0) < 0.75
    ]

    return {
        "ok": True,
        "threshold_used": _threshold_text(),
        "attempts_analysed": len(history.attempts),
        "weak_areas": [a.to_dict() for a in candidates[:limit]],
        "flagged_total": len(candidates),
        "needs_more_evidence": insufficient[:8],
        "message": (
            f"{len(candidates)} area(s) met the weakness threshold; showing the top "
            f"{min(limit, len(candidates))} by expected score impact."
        )
        if candidates
        else (
            "Nothing met the weakness threshold across your history. Keep taking "
            "full-length papers to surface finer gaps."
        ),
    }


def _classify(
    name: str,
    tally: Tally,
    drains: Mapping[str, float],
    avoided: Mapping[str, float],
) -> WeakArea | None:
    """Decide whether an area is weak, and why."""
    accuracy = None if tally.accuracy is None else round(tally.accuracy * 100, 1)
    attempt_rate = avoided.get(name)
    drain_ratio = drains.get(name)

    tags: list[str] = []
    details: list[str] = []

    # Avoidance is judged on attempt rate, so it does not need MIN_ATTEMPTS.
    if attempt_rate is not None and attempt_rate <= AVOIDANCE_ATTEMPT_RATE:
        tags.append("Avoided/low attempts")
        details.append(
            f"you attempted only {attempt_rate:.0f}% of the questions offered here"
        )

    if tally.attempted >= MIN_ATTEMPTS and accuracy is not None and accuracy < WEAK_ACCURACY_THRESHOLD:
        tags.append("Low accuracy")
        details.append(
            f"{tally.correct}/{tally.attempted} correct ({accuracy:.0f}%) across your history"
        )

    if drain_ratio is not None and drain_ratio >= TIME_DRAIN_MULTIPLE:
        tags.append("Time-drain")
        details.append(
            f"you spent about {drain_ratio:.1f}x the fair time budget on these questions"
        )

    if not tags:
        return None

    # Impact: marks plausibly recoverable if this area were brought up to par.
    if "Avoided/low attempts" in tags and "Low accuracy" not in tags:
        gap = 0.5  # unknown ability, but the questions are going unclaimed
        seen = max(tally.attempted, 1)
    else:
        gap = max(0.0, (WEAK_ACCURACY_THRESHOLD - (accuracy or 0.0)) / 100.0)
        seen = max(tally.attempted, 1)
    impact = gap * seen

    test_type, action = _prescription(tags, name)
    return WeakArea(
        name=name,
        scope="chapter",
        reason_tags=tuple(tags),
        accuracy=accuracy,
        attempted=tally.attempted,
        total=tally.attempted,
        impact=impact,
        detail="; ".join(details).capitalize() + ".",
        suggested_test_type=test_type,
        suggested_action=action,
    )


def _prescription(tags: Sequence[str], name: str) -> tuple[str, str]:
    """Different failure modes need different remedies."""
    if "Avoided/low attempts" in tags and "Low accuracy" not in tags:
        return (
            "Topic Wise",
            f"You are skipping {name} rather than getting it wrong. Start with a short "
            "topic-wise drill at Easy difficulty to build exposure and confidence, then "
            "attempt these in a full paper instead of passing over them.",
        )
    if "Time-drain" in tags and "Low accuracy" not in tags:
        return (
            "Topic Wise",
            f"You get {name} right but slowly. Drill it against a clock and learn the "
            "shortcut methods; the marks are already there, the time is not.",
        )
    if "Time-drain" in tags:
        return (
            "Chapter Wise",
            f"{name} is costing you both accuracy and time. Rebuild the fundamentals "
            "first, then a timed chapter test - do not practise speed on shaky theory.",
        )
    return (
        "Chapter Wise",
        f"Re-read the core theory for {name}, then take a 15-question chapter-wise test "
        "on it and review every mistake before your next full mock.",
    )


def _time_drains(report: EvaluationReport | None) -> dict[str, float]:
    """Chapter -> multiple of the fair time budget spent on it."""
    if report is None:
        return {}
    fair = report.time_utilisation.fair_time_per_question_seconds
    if not fair or not report.time_utilisation.timing_data_available:
        return {}
    out: dict[str, float] = {}
    for bucket in report.chapter_performance:
        average = bucket.average_time_seconds
        if average and bucket.attempted >= 2:
            out[bucket.name] = average / fair
    return out


def _avoided(report: EvaluationReport | None) -> dict[str, float]:
    """Chapter -> attempt rate, for telling avoidance apart from inability."""
    if report is None:
        return {}
    return {
        bucket.name: bucket.attempt_rate
        for bucket in report.chapter_performance
        if bucket.total >= 2 and bucket.attempt_rate is not None
    }


def _threshold_text() -> str:
    return (
        f"A chapter is flagged 'Low accuracy' below {WEAK_ACCURACY_THRESHOLD:.0f}% accuracy "
        f"over at least {MIN_ATTEMPTS} attempted questions; 'Avoided/low attempts' at or "
        f"below a {AVOIDANCE_ATTEMPT_RATE:.0f}% attempt rate; 'Time-drain' above "
        f"{TIME_DRAIN_MULTIPLE:.1f}x the fair per-question time. The same thresholds are "
        "applied to every student."
    )


# ------------------------------------------------------------------- readiness


def estimate_readiness(history: StudentHistory) -> dict[str, Any]:
    """Step 12: a trend-aware readiness estimate that admits its own confidence."""
    scored = [a for a in history.attempts if a.percentage is not None]
    count = len(scored)

    if count == 0:
        return {
            "ok": True,
            "label": None,
            "confidence": "none",
            "reasoning": "No completed tests are on record yet.",
            "improve_confidence": (
                f"Complete {MIN_TESTS_FOR_READINESS} full-length mocks for a readiness "
                "estimate with a meaningful trend behind it."
            ),
            "caveat": _CAVEAT,
        }

    recent = history.recent_percentage(window=3) or 0.0
    trend = history.trend() or "flat"
    trend_word = {"improving": "improving", "declining": "declining", "steady": "flat"}.get(
        trend, "flat"
    )

    # Absolute level and trend together, per the spec -- not one test's score.
    if recent >= 70:
        label = READINESS_EXAM_READY
    elif recent >= 50:
        label = READINESS_ON_TRACK
    else:
        label = READINESS_NEEDS_WORK

    # A declining trend at the boundary should not read as comfortably ready.
    if label == READINESS_EXAM_READY and trend_word == "declining" and recent < 78:
        label = READINESS_ON_TRACK

    confidence = "moderate" if count >= MIN_TESTS_FOR_READINESS else "low"
    if count >= 6:
        confidence = "reasonable"

    reasoning = (
        f"Based on your last {min(count, 3)} of {count} completed test(s), averaging "
        f"{recent:.0f}%, with a {trend_word} trend."
    )
    improve = ""
    if confidence == "low":
        needed = MIN_TESTS_FOR_READINESS - count
        improve = (
            f"This is a low-confidence estimate from {count} test(s). Complete {needed} "
            f"more full mock(s) for a reliable trend."
        )

    return {
        "ok": True,
        "label": label,
        "confidence": confidence,
        "tests_analysed": count,
        "recent_average_percentage": round(recent, 1),
        "trend": trend_word,
        "reasoning": reasoning,
        "improve_confidence": improve,
        "caveat": _CAVEAT,
    }


_CAVEAT = (
    "This is an estimate based on your recent performance in this app. It is not an "
    "official rank, percentile or predicted result, and it carries no guarantee."
)
