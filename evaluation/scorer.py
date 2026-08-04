"""Scoring.

Marking is read off each ``Question`` — which the blueprint set from the exam's
own section rules — so partial credit, per-section marks and disabled negative
marking all work without the scorer knowing which exam it is looking at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models.enums import ResponseStatus
from ..models.paper import Paper, Question
from ..models.report import QuestionResult
from ..models.submission import StudentResponse, Submission

#: A question taking more than this multiple of its fair time budget is flagged.
_OVERRUN_MULTIPLE = 2.0


@dataclass(slots=True)
class ScoreSheet:
    """Per-question outcomes plus the totals derived from them."""

    results: tuple[QuestionResult, ...] = ()
    total_score: float = 0.0
    maximum_marks: float = 0.0
    correct: int = 0
    incorrect: int = 0
    unattempted: int = 0
    partial: int = 0
    negative_marks_lost: float = 0.0
    marks_lost_to_unattempted: float = 0.0
    unmatched_response_ids: tuple[str, ...] = ()
    fair_seconds_per_question: float = 0.0

    @property
    def total_questions(self) -> int:
        return len(self.results)

    @property
    def attempted(self) -> int:
        return self.correct + self.incorrect + self.partial

    @property
    def accuracy_percentage(self) -> float | None:
        """Correct out of attempted. Unattempted questions do not dilute it."""
        if self.attempted <= 0:
            return None
        return round(100.0 * (self.correct + 0.5 * self.partial) / self.attempted, 2)

    @property
    def score_percentage(self) -> float | None:
        if self.maximum_marks <= 0:
            return None
        return round(100.0 * self.total_score / self.maximum_marks, 2)

    @property
    def attempt_rate_percentage(self) -> float | None:
        if not self.results:
            return None
        return round(100.0 * self.attempted / len(self.results), 2)


def score(paper: Paper, submission: Submission) -> ScoreSheet:
    """Grade a submission against its paper."""
    questions = paper.questions
    fair_seconds = (paper.duration_minutes * 60.0) / max(len(questions), 1)

    results: list[QuestionResult] = []
    sheet = ScoreSheet(fair_seconds_per_question=round(fair_seconds, 1))

    for question in questions:
        response = submission.response_for(question.question_id)
        status, awarded = _grade(question, response)
        seconds = response.time_spent_seconds if response else 0.0

        if status is ResponseStatus.CORRECT:
            sheet.correct += 1
        elif status is ResponseStatus.INCORRECT:
            sheet.incorrect += 1
            sheet.negative_marks_lost += min(0.0, awarded)
        elif status is ResponseStatus.PARTIAL:
            sheet.partial += 1
        else:
            sheet.unattempted += 1
            sheet.marks_lost_to_unattempted += question.marks

        sheet.total_score = round(sheet.total_score + awarded, 4)
        sheet.maximum_marks = round(sheet.maximum_marks + question.marks, 4)

        results.append(
            QuestionResult(
                question_id=question.question_id,
                number=question.number,
                section=question.section,
                subject=question.subject,
                chapter=question.chapter,
                topic=question.topic,
                difficulty=str(question.difficulty),
                status=status,
                marks_awarded=round(awarded, 2),
                marks_possible=question.marks,
                selected=_selected_display(response),
                correct=question.answer_display,
                time_spent_seconds=round(seconds, 1),
                time_overrun=bool(seconds > fair_seconds * _OVERRUN_MULTIPLE),
            )
        )

    sheet.results = tuple(results)
    sheet.negative_marks_lost = round(abs(sheet.negative_marks_lost), 2)
    sheet.marks_lost_to_unattempted = round(sheet.marks_lost_to_unattempted, 2)

    known = {q.question_id.upper() for q in questions}
    sheet.unmatched_response_ids = tuple(
        r.question_id for r in submission.responses if r.question_id.upper() not in known
    )
    return sheet


def _grade(question: Question, response: StudentResponse | None) -> tuple[ResponseStatus, float]:
    """Status and marks for one question."""
    if response is None or not response.is_attempted:
        return ResponseStatus.UNATTEMPTED, 0.0

    if question.is_numerical:
        if response.value is None:
            return ResponseStatus.UNATTEMPTED, 0.0
        if question.correct_value is None:
            # Nothing to grade against; do not punish the student for our gap.
            return ResponseStatus.UNATTEMPTED, 0.0
        tolerance = max(question.tolerance, 0.0)
        if abs(response.value - question.correct_value) <= tolerance:
            return ResponseStatus.CORRECT, question.marks
        return ResponseStatus.INCORRECT, question.negative_marks

    selected = set(response.selected)
    correct = set(question.correct_keys)
    if not selected:
        return ResponseStatus.UNATTEMPTED, 0.0

    if question.is_multi_correct:
        # Any wrong option selected forfeits the question outright, which is how
        # partial-credit formats such as JEE Advanced actually work.
        if selected - correct:
            return ResponseStatus.INCORRECT, question.negative_marks
        if selected == correct:
            return ResponseStatus.CORRECT, question.marks
        if question.partial_marks:
            return ResponseStatus.PARTIAL, round(question.partial_marks * len(selected), 2)
        return ResponseStatus.INCORRECT, question.negative_marks

    # Single-correct: selecting more than one option is not a valid answer.
    if len(selected) > 1:
        return ResponseStatus.INCORRECT, question.negative_marks
    if selected == correct:
        return ResponseStatus.CORRECT, question.marks
    return ResponseStatus.INCORRECT, question.negative_marks


def _selected_display(response: StudentResponse | None) -> str:
    if response is None or not response.is_attempted:
        return ""
    if response.selected:
        return ", ".join(response.selected)
    if response.value is not None:
        value = response.value
        return str(int(value)) if float(value).is_integer() else f"{value:g}"
    return ""
