"""Railway Recruitment Board exams."""

from __future__ import annotations

from ...models.enums import Difficulty, Language
from ..base import ExamPattern, SectionSpec
from ..registry import register
from ._common import GENERAL_AWARENESS, GENERAL_SCIENCE, QUANT_ARITHMETIC, REASONING

_LANGS = (Language.ENGLISH, Language.HINDI, Language.BILINGUAL)

# RRB deducts one third of a mark per wrong answer across its CBTs.
_NEG = -1 / 3

register(
    ExamPattern(
        exam="RRB NTPC",
        slug="rrb-ntpc",
        category="Railway",
        pattern_version="2025 CBT-1",
        total_time_minutes=90,
        sections=(
            SectionSpec("Mathematics", "Quantitative Aptitude", 30, 1.0, _NEG, chapters=QUANT_ARITHMETIC),
            SectionSpec("General Intelligence and Reasoning", "Reasoning", 30, 1.0, _NEG, chapters=REASONING),
            SectionSpec("General Awareness", "General Awareness", 40, 1.0, _NEG, chapters=GENERAL_AWARENESS),
        ),
        languages=_LANGS,
        difficulty_mix={Difficulty.EASY: 0.40, Difficulty.MEDIUM: 0.45, Difficulty.HARD: 0.15},
        aliases=("ntpc", "rrb ntpc cbt 1", "non technical popular categories"),
        instructions=(
            "100 objective questions carrying 100 marks in 90 minutes.",
            "Each correct answer earns 1 mark; one third of a mark is deducted for each incorrect answer.",
            "CBT-1 is a screening stage; scores are normalised across shifts.",
            "Candidates with benchmark disabilities receive 120 minutes.",
        ),
    )
)

register(
    ExamPattern(
        exam="RRB Group D",
        slug="rrb-group-d",
        category="Railway",
        pattern_version="2025 CBT",
        total_time_minutes=90,
        sections=(
            SectionSpec("General Science", "General Science", 25, 1.0, _NEG, chapters=GENERAL_SCIENCE),
            SectionSpec("Mathematics", "Quantitative Aptitude", 25, 1.0, _NEG, chapters=QUANT_ARITHMETIC),
            SectionSpec("General Intelligence and Reasoning", "Reasoning", 30, 1.0, _NEG, chapters=REASONING),
            SectionSpec("General Awareness and Current Affairs", "General Awareness", 20, 1.0, _NEG, chapters=GENERAL_AWARENESS),
        ),
        languages=_LANGS,
        difficulty_mix={Difficulty.EASY: 0.50, Difficulty.MEDIUM: 0.38, Difficulty.HARD: 0.12},
        aliases=("group d", "rrb level 1", "rrc group d"),
        instructions=(
            "100 objective questions carrying 100 marks in 90 minutes.",
            "Each correct answer earns 1 mark; one third of a mark is deducted for each incorrect answer.",
            "General Science is pitched at the class 10 level.",
            "Candidates with benchmark disabilities receive 120 minutes.",
        ),
    )
)
