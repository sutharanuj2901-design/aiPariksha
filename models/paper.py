"""The question paper and everything inside it.

``Paper.to_dict()`` takes a ``reveal`` flag so the *same* object serves both the
student view (no answers) and the review view (answers plus solutions). Callers
cannot leak an answer key by accident: they have to ask for it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

from .enums import BloomLevel, Difficulty, Language, QuestionType

#: Option labels, in order.
OPTION_KEYS = ("A", "B", "C", "D", "E", "F")


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    text: str
    #: Hindi rendering, used for Hindi and Bilingual papers.
    text_hi: str = ""

    def to_dict(self, *, bilingual: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": self.key, "text": self.text}
        if bilingual and self.text_hi:
            payload["text_hi"] = self.text_hi
        return payload


@dataclass(frozen=True, slots=True)
class Solution:
    """An explanation written for a student, never a dump of model reasoning."""

    correct_answer: str = ""
    explanation: str = ""
    steps: tuple[str, ...] = ()
    formula: str = ""
    common_mistakes: tuple[str, ...] = ()
    time_saving_tip: str = ""
    final_answer: str = ""
    concept_tested: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
        }
        if self.steps:
            payload["steps"] = list(self.steps)
        if self.formula:
            payload["formula_used"] = self.formula
        if self.common_mistakes:
            payload["common_mistakes"] = list(self.common_mistakes)
        if self.time_saving_tip:
            payload["time_saving_tip"] = self.time_saving_tip
        if self.final_answer:
            payload["final_answer"] = self.final_answer
        if self.concept_tested:
            payload["concept_tested"] = self.concept_tested
        return payload


@dataclass(slots=True)
class Question:
    """One scored item.

    ``correct_keys`` covers option-based formats; ``correct_value`` covers
    numerical ones. Exactly one of the two is populated, which the validator
    enforces.
    """

    number: int
    section: str
    subject: str
    chapter: str
    topic: str
    difficulty: Difficulty
    question_type: QuestionType
    text: str
    options: tuple[Option, ...] = ()
    correct_keys: tuple[str, ...] = ()
    correct_value: float | None = None
    #: Accepted absolute tolerance for numerical answers.
    tolerance: float = 0.0
    marks: float = 4.0
    negative_marks: float = 0.0
    partial_marks: float = 0.0
    bloom_level: BloomLevel | None = None
    solution: Solution | None = None
    text_hi: str = ""
    question_id: str = ""
    #: Populated by the validator; surfaced for observability, not shown to students.
    quality_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.question_id:
            self.question_id = f"Q{self.number}"

    @property
    def is_numerical(self) -> bool:
        return self.question_type is QuestionType.NUMERICAL

    @property
    def is_multi_correct(self) -> bool:
        return self.question_type is QuestionType.MCQ_MULTIPLE

    @property
    def answer_display(self) -> str:
        if self.is_numerical:
            return _trim_number(self.correct_value)
        return ", ".join(self.correct_keys)

    def option(self, key: str) -> Option | None:
        for option in self.options:
            if option.key.upper() == str(key).strip().upper():
                return option
        return None

    def fingerprint(self) -> str:
        """Stable hash of the semantic content, used for duplicate detection.

        Normalises whitespace, punctuation, case and numeric formatting so that
        two questions differing only in presentation collide.
        """
        normalised = _normalise_for_dedupe(self.text)
        option_text = "|".join(sorted(_normalise_for_dedupe(o.text) for o in self.options))
        return hashlib.sha256(f"{normalised}||{option_text}".encode()).hexdigest()[:16]

    def to_dict(self, *, reveal: bool = False, bilingual: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question_id": self.question_id,
            "number": self.number,
            "section": self.section,
            "subject": self.subject,
            "chapter": self.chapter,
            "topic": self.topic,
            "difficulty": str(self.difficulty),
            "question_type": str(self.question_type),
            "marks": self.marks,
            "negative_marks": self.negative_marks,
            "text": self.text,
        }
        if bilingual and self.text_hi:
            payload["text_hi"] = self.text_hi
        if self.bloom_level:
            payload["bloom_level"] = str(self.bloom_level)
        if self.options:
            payload["options"] = [o.to_dict(bilingual=bilingual) for o in self.options]
        if self.is_numerical:
            payload["answer_format"] = "numerical"
            if self.tolerance:
                payload["tolerance"] = self.tolerance
        if self.partial_marks:
            payload["partial_marks"] = self.partial_marks
        if reveal:
            payload["correct_answer"] = self.answer_display
            if self.is_numerical:
                payload["correct_value"] = self.correct_value
            else:
                payload["correct_keys"] = list(self.correct_keys)
            if self.solution:
                payload["solution"] = self.solution.to_dict()
        return payload


@dataclass(slots=True)
class PaperSection:
    """A scored block of the generated paper, mirroring one ``SectionSpec``."""

    name: str
    subject: str
    questions: list[Question] = field(default_factory=list)
    time_minutes: int | None = None
    instructions: str = ""

    @property
    def max_marks(self) -> float:
        return round(sum(q.marks for q in self.questions), 2)

    def to_dict(self, *, reveal: bool = False, bilingual: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "subject": self.subject,
            "question_count": len(self.questions),
            "max_marks": self.max_marks,
            "time_minutes": self.time_minutes,
            "instructions": self.instructions,
            "questions": [q.to_dict(reveal=reveal, bilingual=bilingual) for q in self.questions],
        }


@dataclass(slots=True)
class Paper:
    """A complete, ready-to-serve question paper."""

    paper_id: str
    exam: str
    title: str
    pattern_version: str
    duration_minutes: int
    marking_scheme: str
    sections: list[PaperSection] = field(default_factory=list)
    instructions: tuple[str, ...] = ()
    language: Language = Language.ENGLISH
    negative_marking: bool = True
    #: Echo of the resolved request, including the defaults the engine applied.
    request_summary: Mapping[str, Any] = field(default_factory=dict)
    #: Planned composition (subject / chapter / difficulty targets and actuals).
    blueprint_summary: Mapping[str, Any] = field(default_factory=dict)
    #: Provider and model that produced the content.
    generated_by: Mapping[str, Any] = field(default_factory=dict)
    disclaimers: tuple[str, ...] = ()
    quality_report: Mapping[str, Any] = field(default_factory=dict)

    # -------------------------------------------------------------- accessors

    @property
    def questions(self) -> list[Question]:
        return [q for section in self.sections for q in section.questions]

    @property
    def total_questions(self) -> int:
        return sum(len(s.questions) for s in self.sections)

    @property
    def max_marks(self) -> float:
        return round(sum(s.max_marks for s in self.sections), 2)

    @property
    def bilingual(self) -> bool:
        return self.language in (Language.HINDI, Language.BILINGUAL)

    def __iter__(self) -> Iterator[Question]:
        return iter(self.questions)

    def question(self, question_id: str) -> Question | None:
        needle = str(question_id).strip().upper()
        for item in self.questions:
            if item.question_id.upper() == needle:
                return item
        return None

    def renumber(self) -> None:
        """Assign contiguous numbers and ids across sections, in paper order."""
        counter = 1
        for section in self.sections:
            for item in section.questions:
                item.number = counter
                item.question_id = f"Q{counter}"
                counter += 1

    # ------------------------------------------------------------- projections

    def answer_key(self) -> list[dict[str, Any]]:
        return [
            {
                "question_id": q.question_id,
                "number": q.number,
                "section": q.section,
                "chapter": q.chapter,
                "difficulty": str(q.difficulty),
                "correct_answer": q.answer_display,
            }
            for q in self.questions
        ]

    def to_dict(self, *, reveal: bool = False, include_solutions: bool = True) -> dict[str, Any]:
        """Serialise the paper.

        ``reveal=False`` produces the student-facing paper with no answers.
        ``reveal=True`` adds correct answers and, unless suppressed, solutions.
        """
        payload: dict[str, Any] = {
            "paper_id": self.paper_id,
            "exam": self.exam,
            "test_title": self.title,
            "pattern_version": self.pattern_version,
            "duration_minutes": self.duration_minutes,
            "total_questions": self.total_questions,
            "maximum_marks": self.max_marks,
            "marking_scheme": self.marking_scheme,
            "negative_marking": self.negative_marking,
            "language": str(self.language),
            "instructions": list(self.instructions),
            "sections": [
                s.to_dict(reveal=reveal and include_solutions, bilingual=self.bilingual)
                if include_solutions
                else s.to_dict(reveal=reveal, bilingual=self.bilingual)
                for s in self.sections
            ],
            "request": dict(self.request_summary),
            "blueprint": dict(self.blueprint_summary),
            "generated_by": dict(self.generated_by),
            "disclaimers": list(self.disclaimers),
        }
        if reveal:
            payload["answer_key"] = self.answer_key()
        if self.quality_report:
            payload["quality_report"] = dict(self.quality_report)
        return payload


# --------------------------------------------------------------------- helpers

_PUNCT = re.compile(r"[^a-z0-9\s.]+")
_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"\d+\.?\d*")


def _normalise_for_dedupe(text: str) -> str:
    """Aggressively normalise so cosmetic rewrites do not dodge dedupe."""
    lowered = str(text).lower()
    lowered = _PUNCT.sub(" ", lowered)
    # Collapse numeric literals: two questions that differ only in the constants
    # are still near-duplicates for a single paper's purposes.
    lowered = _NUMBER.sub("#", lowered)
    return _SPACE.sub(" ", lowered).strip()


def _trim_number(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def option_keys(count: int) -> tuple[str, ...]:
    return OPTION_KEYS[:count]
