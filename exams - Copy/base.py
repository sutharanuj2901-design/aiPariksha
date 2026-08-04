"""Declarative exam-pattern vocabulary.

The whole point of this module is that an exam is **data, not code**. A new
exam is added by writing one definition file that builds an ``ExamPattern`` and
calls ``register()``; nothing in generation, evaluation, analytics or the CLI
needs to change. Anything an exam can vary — number of sections, per-section
marking, optional questions, sectional timing, allowed question types,
languages — is a field here rather than an ``if exam == ...`` somewhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from ..models.enums import Difficulty, Language, QuestionType

#: Shown wherever pattern/marking details are surfaced. The engine must never
#: present exam rules as authoritative.
PATTERN_DISCLAIMER = (
    "Pattern and marking details reflect the most recent scheme known to this "
    "system and may change. Always verify against the official notification "
    "published by the conducting authority."
)


@dataclass(frozen=True, slots=True)
class ChapterSpec:
    """One chapter inside a subject, plus the topics it decomposes into.

    ``weight`` is the chapter's *relative* share of its subject. Absolute
    numbers are never stored, so a blueprint can scale the same syllabus to a
    5-question quiz or a 180-question full mock.
    """

    name: str
    topics: tuple[str, ...] = ()
    weight: float = 1.0

    def matches(self, needle: str) -> bool:
        return _norm(self.name) == _norm(needle)

    def has_topic(self, needle: str) -> bool:
        return any(_norm(t) == _norm(needle) for t in self.topics)


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """A scored block of the paper.

    Marking lives here rather than on the exam because real papers differ
    section by section (JEE Main Section B carries no negative marking; SSC CGL
    Tier-1 English and Reasoning use different per-question marks in some
    cycles).
    """

    name: str
    subject: str
    questions: int
    marks_correct: float
    marks_incorrect: float = 0.0
    question_types: tuple[QuestionType, ...] = (QuestionType.MCQ_SINGLE,)
    chapters: tuple[ChapterSpec, ...] = ()
    #: Minutes allotted if the exam enforces per-section timing.
    time_minutes: int | None = None
    #: Questions the candidate must answer when fewer than ``questions`` are
    #: compulsory (NEET-style "attempt any 10 of 15"). 0 means all compulsory.
    attempt_count: int = 0
    #: Marks awarded per correct option in partial-credit formats.
    partial_marks: float = 0.0
    notes: str = ""

    @property
    def scored_questions(self) -> int:
        """How many questions actually count toward the maximum marks."""
        return self.attempt_count or self.questions

    @property
    def max_marks(self) -> float:
        return round(self.scored_questions * self.marks_correct, 2)

    def chapter(self, name: str) -> ChapterSpec | None:
        for chapter in self.chapters:
            if chapter.matches(name):
                return chapter
        return None


@dataclass(frozen=True, slots=True)
class ExamPattern:
    """Everything the engine needs to know about one exam."""

    exam: str
    slug: str
    category: str
    pattern_version: str
    total_time_minutes: int
    sections: tuple[SectionSpec, ...]
    languages: tuple[Language, ...] = (Language.ENGLISH,)
    #: Default Easy/Medium/Hard split used when the caller asks for "Mixed".
    difficulty_mix: Mapping[Difficulty, float] = field(
        default_factory=lambda: {Difficulty.EASY: 0.3, Difficulty.MEDIUM: 0.5, Difficulty.HARD: 0.2}
    )
    negative_marking_default: bool = True
    sectional_timing: bool = False
    #: How many of the listed sections a candidate actually sits. 0 means all of
    #: them (the usual case). CUET-style exams list many selectable subject
    #: papers but the candidate writes only a few, so summing every section
    #: would overstate the paper by an order of magnitude.
    section_choice: int = 0
    #: "supported" exams can generate papers; "planned" ones are advertised by
    #: the catalogue but refuse generation with a clear message.
    status: str = "supported"
    aliases: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    notes: str = ""

    # ---------------------------------------------------------------- lookups

    @property
    def subjects(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for section in self.sections:
            seen.setdefault(section.subject, None)
        return tuple(seen)

    @property
    def counted_sections(self) -> tuple[SectionSpec, ...]:
        """The sections that make up one sitting of this exam.

        For choice-based exams the heaviest ``section_choice`` sections are used,
        which is deterministic and gives the worst-case paper the candidate could
        face. Which subjects a given student actually sits is decided by the
        blueprint from their request, not here.
        """
        if not self.section_choice:
            return self.sections
        ranked = sorted(self.sections, key=lambda s: (s.max_marks, s.questions), reverse=True)
        return tuple(ranked[: self.section_choice])

    @property
    def total_questions(self) -> int:
        return sum(s.questions for s in self.counted_sections)

    @property
    def scored_questions(self) -> int:
        return sum(s.scored_questions for s in self.counted_sections)

    @property
    def max_marks(self) -> float:
        return round(sum(s.max_marks for s in self.counted_sections), 2)

    @property
    def is_supported(self) -> bool:
        return self.status == "supported"

    def sections_for_subject(self, subject: str) -> tuple[SectionSpec, ...]:
        return tuple(s for s in self.sections if _norm(s.subject) == _norm(subject))

    def section(self, name: str) -> SectionSpec | None:
        for section in self.sections:
            if _norm(section.name) == _norm(name):
                return section
        return None

    def resolve_subject(self, needle: str) -> str | None:
        """Map a caller-supplied subject name onto the canonical one."""
        for subject in self.subjects:
            if _norm(subject) == _norm(needle):
                return subject
        # Tolerate partial names: "Quant" -> "Quantitative Aptitude".
        candidates = [s for s in self.subjects if _norm(needle) in _norm(s)]
        return candidates[0] if len(candidates) == 1 else None

    def chapters_for(self, subject: str | None = None) -> tuple[ChapterSpec, ...]:
        out: list[ChapterSpec] = []
        for section in self.sections:
            if subject and _norm(section.subject) != _norm(subject):
                continue
            out.extend(section.chapters)
        return tuple(out)

    def find_chapter(self, name: str, subject: str | None = None) -> tuple[str, ChapterSpec] | None:
        """Return ``(subject, chapter)`` for a chapter name, if it exists."""
        for section in self.sections:
            if subject and _norm(section.subject) != _norm(subject):
                continue
            chapter = section.chapter(name)
            if chapter is not None:
                return section.subject, chapter
        return None

    def find_topic(self, name: str, subject: str | None = None) -> tuple[str, ChapterSpec] | None:
        """Return ``(subject, owning chapter)`` for a topic name, if it exists."""
        for section in self.sections:
            if subject and _norm(section.subject) != _norm(subject):
                continue
            for chapter in section.chapters:
                if chapter.has_topic(name):
                    return section.subject, chapter
        return None

    def marking_scheme_text(self) -> str:
        parts: list[str] = []
        for section in self.sections:
            penalty = (
                f"{section.marks_incorrect:+g} for incorrect"
                if section.marks_incorrect
                else "no negative marking"
            )
            parts.append(f"{section.name}: +{section.marks_correct:g} for correct, {penalty}")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "exam": self.exam,
            "slug": self.slug,
            "category": self.category,
            "pattern_version": self.pattern_version,
            "status": self.status,
            "total_time_minutes": self.total_time_minutes,
            "total_questions": self.total_questions,
            "scored_questions": self.scored_questions,
            "max_marks": self.max_marks,
            "sectional_timing": self.sectional_timing,
            "section_choice": self.section_choice,
            "languages": [str(l) for l in self.languages],
            "negative_marking_default": self.negative_marking_default,
            "subjects": list(self.subjects),
            "sections": [
                {
                    "name": s.name,
                    "subject": s.subject,
                    "questions": s.questions,
                    "attempt_count": s.attempt_count or s.questions,
                    "marks_correct": s.marks_correct,
                    "marks_incorrect": s.marks_incorrect,
                    "time_minutes": s.time_minutes,
                    "question_types": [str(q) for q in s.question_types],
                    "chapter_count": len(s.chapters),
                }
                for s in self.sections
            ],
            "marking_scheme": self.marking_scheme_text(),
            "disclaimer": PATTERN_DISCLAIMER,
        }


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split())


def chapters(*specs: tuple[str, Iterable[str]] | tuple[str, Iterable[str], float]) -> tuple[ChapterSpec, ...]:
    """Terse helper for definition files.

    ``chapters(("Kinematics", ["Motion in 1D", "Projectiles"], 1.5), ...)``
    """
    out: list[ChapterSpec] = []
    for spec in specs:
        name, topics = spec[0], tuple(spec[1])
        weight = float(spec[2]) if len(spec) > 2 else 1.0
        out.append(ChapterSpec(name=name, topics=topics, weight=weight))
    return tuple(out)
