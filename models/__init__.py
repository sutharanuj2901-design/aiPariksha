"""JSON-facing data contracts."""

from __future__ import annotations

from .enums import (
    BloomLevel,
    Difficulty,
    Language,
    QuestionType,
    ReadinessBand,
    ResponseStatus,
    SolutionDepth,
    TestType,
)
from .history import AttemptSummary, StudentHistory, Tally
from .paper import OPTION_KEYS, Option, Paper, PaperSection, Question, Solution
from .report import (
    ESTIMATE_DISCLAIMER,
    BucketPerformance,
    EvaluationReport,
    NextTestSuggestion,
    QuestionResult,
    Recommendation,
    TimeUtilisation,
)
from .request import GenerationRequest
from .submission import StudentResponse, Submission

__all__ = [
    "AttemptSummary",
    "BloomLevel",
    "BucketPerformance",
    "Difficulty",
    "ESTIMATE_DISCLAIMER",
    "EvaluationReport",
    "GenerationRequest",
    "Language",
    "NextTestSuggestion",
    "OPTION_KEYS",
    "Option",
    "Paper",
    "PaperSection",
    "Question",
    "QuestionResult",
    "QuestionType",
    "ReadinessBand",
    "Recommendation",
    "ResponseStatus",
    "Solution",
    "SolutionDepth",
    "StudentHistory",
    "StudentResponse",
    "Submission",
    "Tally",
    "TestType",
    "TimeUtilisation",
]
