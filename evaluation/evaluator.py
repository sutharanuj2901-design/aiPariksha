"""Composes scoring, analytics and recommendations into one report."""

from __future__ import annotations

from typing import Any, Mapping

from ..exams.base import PATTERN_DISCLAIMER
from ..models.history import StudentHistory
from ..models.paper import Paper
from ..models.report import ESTIMATE_DISCLAIMER, EvaluationReport
from ..models.submission import Submission
from . import analytics, recommender
from .scorer import ScoreSheet, score


def evaluate(
    paper: Paper,
    submission: Submission,
    *,
    history: StudentHistory | None = None,
) -> EvaluationReport:
    """Grade a submission and produce the full analysis.

    ``history`` is optional. Without it, nothing is claimed about trends or
    improvement over time.
    """
    history = history or StudentHistory()
    sheet: ScoreSheet = score(paper, submission)
    results = sheet.results

    section_buckets = analytics.by_section(results)
    subject_buckets = analytics.by_subject(results)
    chapter_buckets = analytics.by_chapter(results)
    topic_buckets = analytics.by_topic(results)
    difficulty_buckets = analytics.by_difficulty(results)

    utilisation = analytics.time_utilisation(paper, submission, sheet)
    pacing = analytics.pacing_observations(sheet, utilisation)

    strength_list = recommender.strengths(subject_buckets, chapter_buckets, difficulty_buckets)
    improvement_list = recommender.improvement_areas(
        sheet, subject_buckets, chapter_buckets, difficulty_buckets, pacing
    )
    index = recommender.build_results_index(paper)
    recommendation_list = recommender.recommendations(chapter_buckets, topic_buckets, index)

    readiness_score, band, readiness_basis = recommender.readiness(
        sheet, difficulty_buckets, history
    )

    disclaimers = [ESTIMATE_DISCLAIMER, PATTERN_DISCLAIMER, *readiness_basis]
    if sheet.unmatched_response_ids:
        disclaimers.append(
            "Some submitted answers did not correspond to any question in this paper."
        )

    return EvaluationReport(
        paper_id=paper.paper_id,
        exam=paper.exam,
        test_title=paper.title,
        student_id=submission.student_id or history.student_id,
        total_score=sheet.total_score,
        maximum_marks=sheet.maximum_marks,
        total_questions=sheet.total_questions,
        correct=sheet.correct,
        incorrect=sheet.incorrect,
        unattempted=sheet.unattempted,
        partial=sheet.partial,
        accuracy_percentage=sheet.accuracy_percentage,
        score_percentage=sheet.score_percentage,
        attempt_rate_percentage=sheet.attempt_rate_percentage,
        negative_marks_lost=sheet.negative_marks_lost,
        marks_lost_to_unattempted=sheet.marks_lost_to_unattempted,
        section_performance=section_buckets,
        subject_performance=subject_buckets,
        chapter_performance=chapter_buckets,
        topic_performance=topic_buckets,
        difficulty_performance=difficulty_buckets,
        time_utilisation=utilisation,
        question_results=results,
        strengths=strength_list,
        improvement_areas=improvement_list,
        weak_concepts=recommender.weak_concepts(topic_buckets),
        recommendations=recommendation_list,
        next_test=recommender.next_test(paper, subject_buckets, chapter_buckets, sheet),
        readiness_band=band,
        readiness_score=readiness_score,
        estimated_percentile_range=recommender.percentile_estimate(sheet),
        personalised_feedback=recommender.personalised_feedback(
            paper, sheet, band, readiness_score, strength_list, improvement_list, history
        ),
        revision_plan=recommender.revision_plan(recommendation_list, sheet),
        unmatched_response_ids=sheet.unmatched_response_ids,
        disclaimers=tuple(disclaimers),
    )


def attempt_summary(report: EvaluationReport) -> dict[str, Any]:
    """Reduce a report to the shape ``StudentHistory`` accepts.

    Lets a caller feed one attempt straight back in as history for the next
    request, which is what makes adaptive tests work without a database.
    """
    def tallies(buckets: Any) -> dict[str, Mapping[str, int]]:
        return {
            b.name: {"attempted": b.attempted, "correct": b.correct}
            for b in buckets
            if b.attempted > 0
        }

    return {
        "paper_id": report.paper_id,
        "exam": report.exam,
        "score": round(report.total_score, 2),
        "max_marks": round(report.maximum_marks, 2),
        "subject_stats": tallies(report.subject_performance),
        "chapter_stats": tallies(report.chapter_performance),
        "difficulty_stats": tallies(report.difficulty_performance),
    }
