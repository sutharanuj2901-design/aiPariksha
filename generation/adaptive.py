"""Step 8: the stateful adaptive test.

Unlike every other mode, this one cannot be blueprinted up front — the next
question depends on how the last one went. So the session holds state: a running
ability estimate, a per-topic estimate, and the difficulty the next question
should be pitched at.

Ability moves on a continuous 0-1 scale rather than by jumping between named
levels, which is what makes the steps gradual: a single lucky answer nudges the
estimate, it does not vault the student from Easy to Hard. The named difficulty
handed to the generator is that scale, banded.
"""

from __future__ import annotations

import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..errors import AIParikshaError, ValidationError
from ..models.enums import BloomLevel, Difficulty, QuestionType
from ..models.paper import Paper, PaperSection, Question
from ..models.request import GenerationRequest
from ..models.submission import StudentResponse, Submission
from .blueprint import QuestionSlot
from .generator import PaperGenerator

#: Ability value each named difficulty sits at.
_LEVEL_VALUE: Mapping[Difficulty, float] = {
    Difficulty.EASY: 0.25,
    Difficulty.MEDIUM: 0.52,
    Difficulty.HARD: 0.80,
}

#: Band edges mapping a continuous ability back to a question difficulty.
_EASY_CEILING = 0.40
_HARD_FLOOR = 0.68

#: Starting step size. Decays as evidence accumulates so the estimate settles
#: instead of oscillating.
_BASE_STEP = 0.16
_MIN_STEP = 0.04

#: "Until stable estimate" needs at least this many answers before it may stop,
#: and the recent movement must be under this much.
_MIN_FOR_STABLE = 8
_STABLE_WINDOW = 4
_STABLE_DRIFT = 0.05

SESSION_TTL_SECONDS = 6 * 3600
#: Hard ceiling so an "until stable" run cannot go on forever.
MAX_QUESTIONS = 60


@dataclass(slots=True)
class TopicAbility:
    """Running per-topic estimate."""

    topic: str
    chapter: str
    subject: str
    attempted: int = 0
    correct: int = 0
    ability: float = 0.5

    @property
    def accuracy(self) -> float | None:
        if self.attempted <= 0:
            return None
        return round(100.0 * self.correct / self.attempted, 1)

    @property
    def confidence(self) -> str:
        if self.attempted >= 4:
            return "moderate"
        if self.attempted >= 2:
            return "low"
        return "very low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "chapter": self.chapter,
            "subject": self.subject,
            "attempted": self.attempted,
            "correct": self.correct,
            "accuracy_percentage": self.accuracy,
            "estimated_level": _band(self.ability).value,
            "ability_0_to_1": round(self.ability, 3),
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class AdaptiveSession:
    """One in-progress adaptive test."""

    session_id: str
    request: GenerationRequest
    generator: PaperGenerator
    target_count: int
    until_stable: bool
    ability: float
    #: Every question served, in order.
    asked: list[Question] = field(default_factory=list)
    #: question_id -> the student's response.
    responses: dict[str, StudentResponse] = field(default_factory=dict)
    #: question_id -> whether it was answered correctly.
    outcomes: dict[str, bool] = field(default_factory=dict)
    topics: dict[str, TopicAbility] = field(default_factory=dict)
    ability_trail: list[float] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    #: Set when the offline provider produced the content.
    placeholder: bool = False
    _pool: list[tuple[str, str, str]] = field(default_factory=list)
    _rng: random.Random = field(default_factory=random.Random)

    # ------------------------------------------------------------------ lifecycle

    @property
    def answered_count(self) -> int:
        return len(self.outcomes)

    @property
    def current_difficulty(self) -> Difficulty:
        return _band(self.ability)

    @property
    def is_complete(self) -> bool:
        if self.finished:
            return True
        if self.answered_count >= min(self.target_count, MAX_QUESTIONS):
            return True
        return self.until_stable and self._is_stable()

    def _is_stable(self) -> bool:
        """True once the estimate has stopped moving much."""
        if self.answered_count < _MIN_FOR_STABLE:
            return False
        window = self.ability_trail[-_STABLE_WINDOW:]
        if len(window) < _STABLE_WINDOW:
            return False
        return (max(window) - min(window)) <= _STABLE_DRIFT

    # ------------------------------------------------------------------- serving

    def next_question(self) -> Question | None:
        """Generate the next question at the current estimated level."""
        if self.is_complete:
            return None

        # An unanswered question already on the table is re-served rather than
        # replaced, so a page refresh does not skip it.
        if self.asked and self.asked[-1].question_id not in self.outcomes:
            return self.asked[-1]

        slot = self._build_slot()
        filled, stats, _pending = self.generator.fill_slots(
            self.request, [slot], seconds_per_question=self._seconds_per_question()
        )
        self.placeholder = self.placeholder or stats.is_placeholder

        question = filled.get(slot.index)
        if question is None:
            raise AIParikshaError(
                "Could not generate the next adaptive question to standard. "
                "Finish the test to see your report for the questions so far."
            )
        question.number = len(self.asked) + 1
        question.question_id = f"Q{question.number}"
        self.asked.append(question)
        return question

    def _seconds_per_question(self) -> float:
        pattern = self.request.pattern
        return (pattern.total_time_minutes * 60.0) / max(pattern.total_questions, 1)

    def _build_slot(self) -> QuestionSlot:
        """Pick what the next question should test.

        Prefers topics with the fewest attempts so the test spreads out rather
        than drilling whatever came up first.
        """
        if not self._pool:
            self._pool = self._candidate_topics()
        if not self._pool:
            raise ValidationError(
                "No topics are available for the selected subjects.", field="subjects"
            )

        least = min(
            self._pool,
            key=lambda entry: (
                self.topics[entry[2]].attempted if entry[2] in self.topics else 0,
                self._rng.random(),
            ),
        )
        subject, chapter, topic = least
        section = self._section_for(subject)
        difficulty = self.current_difficulty

        return QuestionSlot(
            index=len(self.asked) + 1,
            section=section.name if section else subject,
            subject=subject,
            chapter=chapter,
            topic=topic,
            difficulty=difficulty,
            question_type=QuestionType.MCQ_SINGLE,
            marks=section.marks_correct if section else 1.0,
            negative_marks=(
                section.marks_incorrect if section and self.request.negative_marking else 0.0
            ),
            bloom_level=self.request.bloom_level or _BLOOM.get(difficulty),
        )

    def _candidate_topics(self) -> list[tuple[str, str, str]]:
        pattern = self.request.pattern
        wanted = self.request.subjects or pattern.subjects
        out: list[tuple[str, str, str]] = []
        for subject in wanted:
            for section in pattern.sections_for_subject(subject):
                for chapter in section.chapters:
                    if self.request.chapters and chapter.name not in self.request.chapters:
                        continue
                    for topic in chapter.topics or (chapter.name,):
                        if self.request.topics and topic not in self.request.topics:
                            continue
                        out.append((subject, chapter.name, topic))
        return out

    def _section_for(self, subject: str):
        sections = self.request.pattern.sections_for_subject(subject)
        return sections[0] if sections else None

    # ------------------------------------------------------------------ answering

    def submit(
        self,
        question_id: str,
        *,
        selected: Sequence[str] = (),
        value: float | None = None,
        seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Record one answer and move the estimate."""
        question = next((q for q in self.asked if q.question_id == question_id), None)
        if question is None:
            raise ValidationError(
                f"{question_id} is not part of this adaptive session.", field="question_id"
            )
        if question_id in self.outcomes:
            raise ValidationError(
                f"{question_id} has already been answered.", field="question_id"
            )

        keys = tuple(str(k).strip().upper()[:1] for k in selected if str(k).strip())
        response = StudentResponse(
            question_id=question_id,
            selected=keys,
            value=value,
            time_spent_seconds=max(0.0, float(seconds or 0.0)),
        )
        self.responses[question_id] = response

        if question.is_numerical:
            correct = (
                value is not None
                and question.correct_value is not None
                and abs(value - question.correct_value) <= max(question.tolerance, 0.0)
            )
        else:
            correct = bool(keys) and set(keys) == set(question.correct_keys)
        self.outcomes[question_id] = correct

        before = self.ability
        self._update_ability(question.difficulty, correct)
        self._update_topic(question, correct)
        self.ability_trail.append(self.ability)

        return {
            "question_id": question_id,
            "correct": correct,
            "correct_answer": question.answer_display,
            "ability_before": round(before, 3),
            "ability_after": round(self.ability, 3),
            "next_difficulty": str(self.current_difficulty),
            "direction": "up" if self.ability > before else "down" if self.ability < before else "level",
            "answered": self.answered_count,
            "complete": self.is_complete,
        }

    def _update_ability(self, asked_at: Difficulty, correct: bool) -> None:
        """Nudge the estimate toward or away from the level just tested.

        The step shrinks with evidence and with how expected the outcome was: a
        correct answer on an easy question moves the estimate far less than a
        correct answer on a hard one.
        """
        step = max(_MIN_STEP, _BASE_STEP / (1.0 + 0.22 * self.answered_count))
        level = _LEVEL_VALUE.get(asked_at, 0.5)
        # Crude expected-success probability given ability vs question level.
        expected = 1.0 / (1.0 + pow(2.718281828, -8.0 * (self.ability - level)))
        surprise = (1.0 - expected) if correct else expected
        delta = step * (1.0 + surprise)
        self.ability = _clamp(self.ability + delta if correct else self.ability - delta)

    def _update_topic(self, question: Question, correct: bool) -> None:
        entry = self.topics.get(question.topic)
        if entry is None:
            entry = TopicAbility(
                topic=question.topic,
                chapter=question.chapter,
                subject=question.subject,
                ability=self.ability,
            )
            self.topics[question.topic] = entry
        entry.attempted += 1
        if correct:
            entry.correct += 1
        # Blend toward the global estimate, weighted by this topic's evidence.
        weight = 1.0 / (1.0 + entry.attempted)
        target = _LEVEL_VALUE.get(question.difficulty, 0.5)
        observed = target + (0.12 if correct else -0.12)
        entry.ability = _clamp(entry.ability * (1 - weight) + observed * weight)

    # ------------------------------------------------------------------- finish

    def finish(self) -> tuple[Paper, Submission]:
        """Freeze the session into a gradeable paper plus the submission."""
        self.finished = True
        if not self.asked:
            raise ValidationError("This adaptive test has no questions yet.", field="session_id")

        # Only answered questions are scored; a served-but-unanswered final
        # question would otherwise count as a wrong answer the student never saw.
        scored = [q for q in self.asked if q.question_id in self.outcomes]
        if not scored:
            raise ValidationError(
                "No questions were answered, so there is nothing to grade.", field="session_id"
            )

        sections: dict[str, PaperSection] = {}
        for question in scored:
            section = sections.get(question.section)
            if section is None:
                section = PaperSection(name=question.section, subject=question.subject)
                sections[question.section] = section
            section.questions.append(question)

        minutes = max(1, round(len(scored) * self._seconds_per_question() / 60.0))
        paper = Paper(
            paper_id=f"adaptive-{self.session_id}",
            exam=self.request.exam,
            title=f"{self.request.exam} Adaptive Practice Test",
            pattern_version=self.request.pattern_version,
            duration_minutes=minutes,
            marking_scheme=(
                f"+{scored[0].marks:g} for each correct answer"
                + (f", {scored[0].negative_marks:g} for each incorrect answer"
                   if scored[0].negative_marks else ", no negative marking")
            ),
            sections=list(sections.values()),
            language=self.request.language,
            negative_marking=self.request.negative_marking,
            request_summary=self.request.to_dict(),
            instructions=(
                "Adaptive test: each question's difficulty was chosen from your running "
                "performance, so this paper is unique to this attempt.",
            ),
        )
        submission = Submission(
            paper_id=paper.paper_id,
            responses=tuple(self.responses[q.question_id] for q in scored),
            total_time_spent_seconds=sum(
                self.responses[q.question_id].time_spent_seconds for q in scored
            ),
        )
        return paper, submission

    def ability_summary(self) -> dict[str, Any]:
        """The per-topic estimate, plus the honest confidence caveat."""
        ranked = sorted(
            (t.to_dict() for t in self.topics.values()),
            key=lambda t: (t["ability_0_to_1"], -t["attempted"]),
        )
        return {
            "questions_answered": self.answered_count,
            "overall_estimated_level": str(self.current_difficulty),
            "overall_ability_0_to_1": round(self.ability, 3),
            "stopped_early": self.until_stable and self._is_stable(),
            "ability_trail": [round(a, 3) for a in self.ability_trail],
            "per_topic": ranked,
            "caveat": (
                "Ability levels are estimated live from a small number of questions and "
                "are indicative only. Topics marked 'very low' or 'low' confidence were "
                "seen too few times to judge."
            ),
        }

    def state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "answered": self.answered_count,
            "target": min(self.target_count, MAX_QUESTIONS),
            "until_stable": self.until_stable,
            "current_difficulty": str(self.current_difficulty),
            "ability_0_to_1": round(self.ability, 3),
            "complete": self.is_complete,
            "placeholder": self.placeholder,
        }


class AdaptiveSessionStore:
    """Bounded, thread-safe store of live adaptive sessions."""

    def __init__(self, limit: int = 32) -> None:
        self._sessions: dict[str, AdaptiveSession] = {}
        self._lock = threading.Lock()
        self._limit = limit

    def start(self, request: GenerationRequest, generator: PaperGenerator) -> AdaptiveSession:
        start_level = request.starting_difficulty or Difficulty.MEDIUM
        session = AdaptiveSession(
            session_id=secrets.token_hex(6),
            request=request,
            generator=generator,
            target_count=request.num_questions or 20,
            until_stable=request.until_stable,
            ability=_LEVEL_VALUE.get(start_level, 0.5),
            _rng=random.Random(request.seed) if request.seed is not None else random.Random(),
        )
        with self._lock:
            self._prune()
            if len(self._sessions) >= self._limit:
                oldest = min(self._sessions.values(), key=lambda s: s.started_at)
                self._sessions.pop(oldest.session_id, None)
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AdaptiveSession | None:
        with self._lock:
            self._prune()
            return self._sessions.get(str(session_id))

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(str(session_id), None)

    def _prune(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        for key in [k for k, v in self._sessions.items() if v.started_at < cutoff]:
            self._sessions.pop(key, None)


_BLOOM = {
    Difficulty.EASY: BloomLevel.UNDERSTAND,
    Difficulty.MEDIUM: BloomLevel.APPLY,
    Difficulty.HARD: BloomLevel.ANALYZE,
}


def _band(ability: float) -> Difficulty:
    if ability < _EASY_CEILING:
        return Difficulty.EASY
    if ability >= _HARD_FLOOR:
        return Difficulty.HARD
    return Difficulty.MEDIUM


def _clamp(value: float) -> float:
    return max(0.02, min(0.98, value))
