"""The public facade: JSON in, JSON out.

Every method takes a plain dict and returns a plain dict with an ``ok`` flag, so
the same engine sits behind a CLI, an HTTP handler, a queue worker or a notebook
without adaptation.

Designed errors — including ``ClarificationNeeded``, which is how the engine
declines to guess at a missing input — come back as envelopes rather than
exceptions. Genuine programming errors are left to propagate.
"""

from __future__ import annotations

from typing import Any, Mapping

from .config import Settings, load_settings
from .errors import AIParikshaError, ValidationError
from .evaluation.diagnostics import estimate_readiness, identify_weak_areas
from .evaluation.evaluator import attempt_summary, evaluate as run_evaluation
from .exams import registry
from .exams.base import PATTERN_DISCLAIMER
from .generation.adaptive import AdaptiveSessionStore
from .generation.blueprint import build_blueprint
from .generation.generator import PaperGenerator
from .llm.base import QuestionProvider
from .models.enums import TestType
from .models.history import StudentHistory
from .models.request import GenerationRequest
from .models.serialization import has_answers, paper_from_dict
from .models.submission import Submission


class AIPariksha:
    """Entry point for every capability."""

    def __init__(
        self,
        settings: Settings | None = None,
        provider: QuestionProvider | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.generator = PaperGenerator(self.settings, provider=provider)
        self.adaptive_sessions = AdaptiveSessionStore()

    # ------------------------------------------------------------------ catalogue

    def catalogue(self) -> dict[str, Any]:
        """Every registered exam, for an exam picker."""
        return {
            "ok": True,
            "engine": self.settings.describe(),
            "exams": registry.catalogue(),
            "by_category": registry.by_category(),
            "disclaimer": PATTERN_DISCLAIMER,
        }

    def pattern(self, exam: str) -> dict[str, Any]:
        """The full official-pattern description for one exam."""
        try:
            return {"ok": True, "pattern": registry.get(exam).to_dict()}
        except AIParikshaError as error:
            return error.to_dict()

    def syllabus(self, exam: str, subject: str | None = None) -> dict[str, Any]:
        """Subjects, chapters and topics available for generation."""
        try:
            pattern = registry.get(exam)
        except AIParikshaError as error:
            return error.to_dict()

        if subject is not None:
            canonical = pattern.resolve_subject(subject)
            if canonical is None:
                return ValidationError(
                    f"{subject!r} is not a subject in {pattern.exam}. "
                    f"Available: {', '.join(pattern.subjects)}.",
                    field="subject",
                ).to_dict()
            subjects = [canonical]
        else:
            subjects = list(pattern.subjects)

        return {
            "ok": True,
            "exam": pattern.exam,
            "pattern_version": pattern.pattern_version,
            "subjects": [
                {
                    "subject": name,
                    "sections": [s.name for s in pattern.sections_for_subject(name)],
                    "chapters": [
                        {"chapter": c.name, "weight": c.weight, "topics": list(c.topics)}
                        for c in pattern.chapters_for(name)
                    ],
                }
                for name in subjects
            ],
            "disclaimer": PATTERN_DISCLAIMER,
        }

    # ----------------------------------------------------------------- generation

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Blueprint a paper without calling a provider.

        Useful for validating a request, showing the student the planned
        composition, and estimating cost before generating anything.
        """
        try:
            request = GenerationRequest.from_dict(payload)
            blueprint = build_blueprint(request)
        except AIParikshaError as error:
            return error.to_dict()

        return {
            "ok": True,
            "request": request.to_dict(),
            "blueprint": blueprint.to_dict(),
            "slots": [slot.to_dict() for slot in blueprint.slots],
        }

    def generate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Generate a paper.

        The returned paper is the **full internal record**, including answers and
        solutions, so it can be stored and later used for grading. Call
        ``student_view`` on it before showing it to a candidate.
        """
        try:
            request = GenerationRequest.from_dict(payload)
            paper = self.generator.generate(request)
        except AIParikshaError as error:
            return error.to_dict()

        return {
            "ok": True,
            "paper": paper.to_dict(reveal=True, include_solutions=request.wants_solutions),
            "answer_key": paper.answer_key() if request.wants_answer_key else None,
            "notes": {
                "defaults_applied": list(request.defaults_applied),
                "solutions_included": request.wants_solutions,
                "contains_answers": True,
                "reminder": (
                    "Strip answers with student_view() before serving this paper to a candidate."
                ),
            },
        }

    def student_view(self, paper_payload: Mapping[str, Any]) -> dict[str, Any]:
        """Redact a generated paper down to what a candidate should see."""
        try:
            paper = paper_from_dict(paper_payload)
        except AIParikshaError as error:
            return error.to_dict()
        return {"ok": True, "paper": paper.to_dict(reveal=False)}

    # ----------------------------------------------------------------- evaluation

    def evaluate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Grade a submission and return the full analysis.

        Expects ``{"paper": <generated paper>, "submission": {...}}``. The
        submission may also be given inline as top-level ``responses``.
        """
        if not isinstance(payload, Mapping):
            return ValidationError("Request body must be a JSON object.").to_dict()

        paper_payload = payload.get("paper")
        if paper_payload is None:
            return ValidationError(
                "paper is required. Post back the paper object returned by generate().",
                field="paper",
            ).to_dict()

        submission_payload = payload.get("submission")
        if submission_payload is None:
            if "responses" in payload or "answers" in payload:
                submission_payload = payload
            else:
                return ValidationError(
                    "submission is required and must contain 'responses'.", field="submission"
                ).to_dict()

        try:
            paper = paper_from_dict(paper_payload)
            if not has_answers(paper):
                raise ValidationError(
                    "This paper carries no answer key, so it cannot be graded. Store the paper "
                    "returned by generate() (which includes answers) rather than the redacted "
                    "student view.",
                    field="paper",
                )
            submission = Submission.from_dict(submission_payload)
            history = StudentHistory.from_dict(
                payload.get("student_history") or payload.get("history")
            )
            report = run_evaluation(paper, submission, history=history)
        except AIParikshaError as error:
            return error.to_dict()

        include_details = bool(payload.get("include_question_results", True))
        return {
            "ok": True,
            "report": report.to_dict(include_question_results=include_details),
            "history_entry": attempt_summary(report),
        }

    # ------------------------------------------------------------------ adaptive

    def adaptive_start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Step 8: open a stateful adaptive session and serve question one."""
        try:
            request = GenerationRequest.from_dict({**dict(payload), "test_type": str(TestType.ADAPTIVE)})
            session = self.adaptive_sessions.start(request, self.generator)
            question = session.next_question()
        except AIParikshaError as error:
            return error.to_dict()

        return {
            "ok": True,
            "session": session.state(),
            "question": question.to_dict(reveal=False) if question else None,
            "advisories": list(request.advisories),
            "defaults_applied": list(request.defaults_applied),
        }

    def adaptive_answer(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Record an answer, step the difficulty, and serve the next question."""
        session = self.adaptive_sessions.get(str(payload.get("session_id") or ""))
        if session is None:
            return ValidationError(
                "That adaptive session has expired or does not exist. Start a new one.",
                field="session_id",
            ).to_dict()
        try:
            selected = payload.get("selected") or []
            if isinstance(selected, str):
                selected = [selected]
            outcome = session.submit(
                str(payload.get("question_id") or ""),
                selected=selected,
                value=payload.get("value"),
                seconds=payload.get("time_spent_seconds") or 0,
            )
            next_question = session.next_question()
        except AIParikshaError as error:
            return error.to_dict()

        return {
            "ok": True,
            "outcome": outcome,
            "session": session.state(),
            "question": next_question.to_dict(reveal=False) if next_question else None,
        }

    def adaptive_finish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Grade the adaptive session and return the report plus ability estimate."""
        session = self.adaptive_sessions.get(str(payload.get("session_id") or ""))
        if session is None:
            return ValidationError(
                "That adaptive session has expired or does not exist.", field="session_id"
            ).to_dict()
        try:
            paper, submission = session.finish()
            history = StudentHistory.from_dict(
                payload.get("student_history") or payload.get("history")
            )
            report = run_evaluation(paper, submission, history=history)
        except AIParikshaError as error:
            return error.to_dict()

        self.adaptive_sessions.drop(session.session_id)
        return {
            "ok": True,
            "report": report.to_dict(),
            "paper": paper.to_dict(reveal=True),
            "ability_estimate": session.ability_summary(),
            "history_entry": attempt_summary(report),
        }

    # --------------------------------------------------------------- diagnostics

    def diagnostics(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Steps 11 and 12 over a student's accumulated history."""
        try:
            history = StudentHistory.from_dict(
                payload.get("student_history") or payload.get("history") or payload
            )
        except AIParikshaError as error:
            return error.to_dict()

        return {
            "ok": True,
            "weak_areas": identify_weak_areas(history),
            "readiness": estimate_readiness(history),
            "history": history.to_dict(),
        }

    # -------------------------------------------------------------- convenience

    def generate_and_evaluate(
        self, generate_payload: Mapping[str, Any], submission_payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Generate a paper and immediately grade a submission against it.

        Mainly for tests and demos; production flows keep the two calls apart so
        the student sees the paper in between.
        """
        generated = self.generate(generate_payload)
        if not generated.get("ok"):
            return generated
        evaluated = self.evaluate(
            {
                "paper": generated["paper"],
                "submission": submission_payload,
                "student_history": generate_payload.get("student_history"),
            }
        )
        if not evaluated.get("ok"):
            return evaluated
        return {"ok": True, "paper": generated["paper"], **evaluated}
