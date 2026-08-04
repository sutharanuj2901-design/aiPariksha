"""Staff Selection Commission exams."""

from __future__ import annotations

from ...models.enums import Difficulty, Language
from ..base import ExamPattern, SectionSpec
from ..registry import register
from ._common import ENGLISH, GENERAL_AWARENESS, QUANT_ARITHMETIC, REASONING

_LANGS = (Language.ENGLISH, Language.HINDI, Language.BILINGUAL)
_MIX = {Difficulty.EASY: 0.35, Difficulty.MEDIUM: 0.45, Difficulty.HARD: 0.20}

register(
    ExamPattern(
        exam="SSC CGL",
        slug="ssc-cgl",
        category="Government Exams",
        pattern_version="2025 Tier-I",
        total_time_minutes=60,
        sections=(
            SectionSpec("General Intelligence and Reasoning", "Reasoning", 25, 2.0, -0.5, chapters=REASONING),
            SectionSpec("General Awareness", "General Awareness", 25, 2.0, -0.5, chapters=GENERAL_AWARENESS),
            SectionSpec("Quantitative Aptitude", "Quantitative Aptitude", 25, 2.0, -0.5, chapters=QUANT_ARITHMETIC),
            SectionSpec("English Comprehension", "English", 25, 2.0, -0.5, chapters=ENGLISH),
        ),
        languages=_LANGS,
        difficulty_mix=_MIX,
        aliases=("cgl", "ssc cgl tier 1", "combined graduate level"),
        instructions=(
            "100 objective questions carrying 200 marks in 60 minutes.",
            "Each correct answer earns 2 marks; 0.50 marks are deducted for each incorrect answer.",
            "The English Comprehension section is available in English only.",
        ),
    )
)

register(
    ExamPattern(
        exam="SSC CHSL",
        slug="ssc-chsl",
        category="Government Exams",
        pattern_version="2025 Tier-I",
        total_time_minutes=60,
        sections=(
            SectionSpec("General Intelligence", "Reasoning", 25, 2.0, -0.5, chapters=REASONING),
            SectionSpec("General Awareness", "General Awareness", 25, 2.0, -0.5, chapters=GENERAL_AWARENESS),
            SectionSpec("Quantitative Aptitude", "Quantitative Aptitude", 25, 2.0, -0.5, chapters=QUANT_ARITHMETIC),
            SectionSpec("English Language", "English", 25, 2.0, -0.5, chapters=ENGLISH),
        ),
        languages=_LANGS,
        difficulty_mix={Difficulty.EASY: 0.45, Difficulty.MEDIUM: 0.40, Difficulty.HARD: 0.15},
        aliases=("chsl", "ssc 10+2", "combined higher secondary"),
        instructions=(
            "100 objective questions carrying 200 marks in 60 minutes.",
            "Each correct answer earns 2 marks; 0.50 marks are deducted for each incorrect answer.",
            "Difficulty is pitched at the 10+2 level.",
        ),
    )
)

# MTS runs as two separately timed sessions; Session I carries no negative
# marking while Session II does. Per-section marking makes this pure data.
register(
    ExamPattern(
        exam="SSC MTS",
        slug="ssc-mts",
        category="Government Exams",
        pattern_version="2025 (two-session CBE)",
        total_time_minutes=90,
        sections=(
            SectionSpec(
                "Session I - Numerical and Mathematical Ability", "Quantitative Aptitude",
                20, 3.0, 0.0, chapters=QUANT_ARITHMETIC, time_minutes=45,
                notes="No negative marking in Session I.",
            ),
            SectionSpec(
                "Session I - Reasoning Ability and Problem Solving", "Reasoning",
                20, 3.0, 0.0, chapters=REASONING, time_minutes=45,
                notes="No negative marking in Session I.",
            ),
            SectionSpec(
                "Session II - General Awareness", "General Awareness",
                25, 3.0, -1.0, chapters=GENERAL_AWARENESS, time_minutes=45,
            ),
            SectionSpec(
                "Session II - English Language and Comprehension", "English",
                25, 3.0, -1.0, chapters=ENGLISH, time_minutes=45,
            ),
        ),
        languages=_LANGS,
        difficulty_mix={Difficulty.EASY: 0.50, Difficulty.MEDIUM: 0.38, Difficulty.HARD: 0.12},
        sectional_timing=True,
        aliases=("mts", "multi tasking staff", "ssc havaldar"),
        instructions=(
            "The examination runs in two separately timed sessions of 45 minutes each.",
            "Session I carries no negative marking. Session II deducts 1 mark per incorrect answer.",
            "Every question carries 3 marks.",
            "Both sessions are compulsory; you cannot return to Session I after it ends.",
        ),
    )
)

register(
    ExamPattern(
        exam="SSC CPO",
        slug="ssc-cpo",
        category="Government Exams",
        pattern_version="2025 Paper-I",
        total_time_minutes=120,
        sections=(
            SectionSpec("General Intelligence and Reasoning", "Reasoning", 50, 1.0, -0.25, chapters=REASONING),
            SectionSpec("General Knowledge and General Awareness", "General Awareness", 50, 1.0, -0.25, chapters=GENERAL_AWARENESS),
            SectionSpec("Quantitative Aptitude", "Quantitative Aptitude", 50, 1.0, -0.25, chapters=QUANT_ARITHMETIC),
            SectionSpec("English Language and Comprehension", "English", 50, 1.0, -0.25, chapters=ENGLISH),
        ),
        languages=_LANGS,
        difficulty_mix=_MIX,
        aliases=("cpo", "ssc si", "sub inspector delhi police"),
        instructions=(
            "200 objective questions carrying 200 marks in 120 minutes.",
            "Each correct answer earns 1 mark; 0.25 marks are deducted for each incorrect answer.",
            "Paper-I is qualifying for the Physical Endurance and Measurement Test.",
        ),
    )
)
