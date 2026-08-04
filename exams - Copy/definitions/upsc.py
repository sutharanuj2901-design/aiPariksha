"""Civil services exams.

Registered with ``status="planned"``: they appear in the catalogue so a UI can
advertise them, but the generator refuses to produce papers until the syllabus
mapping is complete. Flipping ``status`` to ``"supported"`` is the only change
needed to enable them — no other module knows the difference.
"""

from __future__ import annotations

from ...models.enums import Difficulty, Language
from ..base import ExamPattern, SectionSpec, chapters
from ..registry import register
from ._common import GENERAL_AWARENESS, QUANT_ARITHMETIC, REASONING

_GS_PRELIMS = chapters(
    ("Indian Polity and Governance", ["Constitution", "Political system", "Panchayati Raj", "Rights issues"], 1.4),
    ("History of India and National Movement", ["Ancient", "Medieval", "Modern", "Freedom struggle"], 1.4),
    ("Indian and World Geography", ["Physical geography", "Social geography", "Economic geography"], 1.2),
    ("Economic and Social Development", ["Sustainable development", "Poverty", "Demographics", "Social sector initiatives"], 1.2),
    ("Environment, Ecology and Biodiversity", ["Ecosystems", "Climate change", "Conservation", "Environmental governance"], 1.2),
    ("General Science and Technology", ["Science in everyday life", "Space and defence technology", "Biotechnology", "IT"], 1.0),
    ("Current Events of National and International Importance", ["Government schemes", "International relations", "Reports and indices"], 1.4),
)

_CSAT = chapters(
    ("Comprehension", ["Passage based reasoning", "Author's argument"], 1.6),
    ("Logical Reasoning and Analytical Ability", ["Syllogism", "Statement and assumption", "Arrangements", "Puzzles"], 1.4),
    ("Decision Making and Problem Solving", ["Situational judgement", "Ethical decision making"], 1.0),
    ("Basic Numeracy", ["Number system", "Percentage", "Ratio", "Averages", "Time and work"], 1.2),
    ("Data Interpretation", ["Tables", "Charts", "Data sufficiency"], 1.2),
)

register(
    ExamPattern(
        exam="UPSC Civil Services",
        slug="upsc-cse",
        category="Civil Services",
        pattern_version="Prelims (indicative)",
        total_time_minutes=120,
        sections=(
            SectionSpec("General Studies Paper I", "General Studies", 100, 2.0, -2 / 3,
                        chapters=_GS_PRELIMS, time_minutes=120),
            SectionSpec("CSAT Paper II", "Aptitude", 80, 2.5, -5 / 6,
                        chapters=_CSAT, time_minutes=120,
                        notes="Qualifying paper requiring 33 percent."),
        ),
        languages=(Language.ENGLISH, Language.HINDI, Language.BILINGUAL),
        difficulty_mix={Difficulty.EASY: 0.20, Difficulty.MEDIUM: 0.45, Difficulty.HARD: 0.35},
        status="planned",
        aliases=("upsc", "ias", "upsc prelims", "civil services exam"),
        instructions=(
            "Paper I carries 100 questions and 200 marks; Paper II carries 80 questions and 200 marks.",
            "Each paper runs for 120 minutes and deducts one third of the allotted marks per incorrect answer.",
            "Paper II is qualifying in nature; only Paper I counts toward the prelims merit list.",
        ),
        notes=(
            "Support is planned. The structure above is indicative for planning purposes "
            "only and the syllabus mapping is not yet deep enough for exam-quality "
            "generation. Verify all details against the official UPSC notification."
        ),
    )
)

register(
    ExamPattern(
        exam="State PCS",
        slug="state-pcs",
        category="Civil Services",
        pattern_version="Generic Prelims (indicative)",
        total_time_minutes=120,
        sections=(
            SectionSpec("General Studies", "General Studies", 100, 2.0, -2 / 3, chapters=_GS_PRELIMS),
            SectionSpec("State Specific General Knowledge", "State GK", 50, 2.0, -2 / 3,
                        chapters=GENERAL_AWARENESS,
                        notes="Replaced per state once that state's PCS is added as its own definition."),
        ),
        languages=(Language.ENGLISH, Language.HINDI, Language.BILINGUAL),
        difficulty_mix={Difficulty.EASY: 0.25, Difficulty.MEDIUM: 0.45, Difficulty.HARD: 0.30},
        status="planned",
        aliases=("pcs", "state psc", "provincial civil services"),
        notes=(
            "A placeholder umbrella entry. Each state commission sets its own pattern, "
            "marking and state-GK weightage, so individual states should be added as "
            "separate definition files rather than configured through this one."
        ),
    )
)
