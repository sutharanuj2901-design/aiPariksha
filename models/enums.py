"""Controlled vocabularies used across every AIPariksha contract.

Every enum here is *open for extension*: new members can be appended without
touching generation, evaluation or analytics logic, because all consumers
dispatch on data (registry lookups / dict tables) rather than on hardcoded
branches.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String-valued enum that survives a JSON round-trip unchanged."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def parse(cls, raw: object, field: str) -> "StrEnum":
        """Coerce loosely-typed JSON input into a member.

        Accepts the canonical value, any case variation, and common
        separator variants ("multiple_choice" == "Multiple Choice").
        """
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str):
            raise ValueError(f"{field}: expected a string, got {type(raw).__name__}")
        needle = raw.strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            candidate = str(member.value).lower().replace("-", "_").replace(" ", "_")
            if candidate == needle or member.name.lower() == needle:
                return member
        allowed = ", ".join(str(m.value) for m in cls)
        raise ValueError(f"{field}: {raw!r} is not supported. Allowed: {allowed}")


class Difficulty(StrEnum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    MIXED = "Mixed"


class Language(StrEnum):
    ENGLISH = "English"
    HINDI = "Hindi"
    BILINGUAL = "Bilingual"


class QuestionType(StrEnum):
    #: Single correct option out of four/five.
    MCQ_SINGLE = "MCQ Single Correct"
    #: One or more correct options (JEE Advanced style, partial marking).
    MCQ_MULTIPLE = "MCQ Multiple Correct"
    #: Integer / numeric value answer, no options.
    NUMERICAL = "Numerical Value"
    ASSERTION_REASON = "Assertion Reason"
    MATCH_THE_FOLLOWING = "Match the Following"
    TRUE_FALSE = "True False"
    #: Reading comprehension / statement-based cluster.
    PASSAGE_BASED = "Passage Based"


class TestType(StrEnum):
    FULL_MOCK = "Full Mock"
    CHAPTER_WISE = "Chapter Wise"
    TOPIC_WISE = "Topic Wise"
    REVISION = "Revision"
    PREVIOUS_YEAR_PATTERN = "Previous Year Pattern"
    ADAPTIVE = "Adaptive"
    SECTIONAL = "Sectional"


class BloomLevel(StrEnum):
    REMEMBER = "Remember"
    UNDERSTAND = "Understand"
    APPLY = "Apply"
    ANALYZE = "Analyze"
    EVALUATE = "Evaluate"
    CREATE = "Create"


class SolutionDepth(StrEnum):
    #: Nothing but the paper.
    NONE = "None"
    #: Correct options only.
    ANSWER_KEY = "Answer Key"
    #: One-or-two line justification.
    BRIEF = "Brief"
    #: Full step-by-step, formula, common mistakes, time-saving tip.
    DETAILED = "Detailed"


class ResponseStatus(StrEnum):
    CORRECT = "Correct"
    INCORRECT = "Incorrect"
    UNATTEMPTED = "Unattempted"
    PARTIAL = "Partially Correct"


class ReadinessBand(StrEnum):
    FOUNDATION = "Foundation Building"
    DEVELOPING = "Developing"
    EXAM_READY = "Exam Ready"
    STRONG = "Strong"
