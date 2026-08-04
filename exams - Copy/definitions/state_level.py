"""State-level common eligibility and recruitment tests."""

from __future__ import annotations

from ...models.enums import Difficulty, Language
from ..base import ExamPattern, SectionSpec, chapters
from ..registry import register
from ._common import ENGLISH, GENERAL_AWARENESS, GENERAL_SCIENCE, QUANT_ARITHMETIC, REASONING

_HARYANA_GK = chapters(
    ("Haryana History", ["Ancient Haryana", "Freedom movement in Haryana", "Formation of the state in 1966"], 1.2),
    ("Haryana Geography", ["Districts and divisions", "Rivers and canals", "Soil and crops", "Climate", "National parks"], 1.4),
    ("Haryana Polity and Administration", ["State legislature", "Panchayati Raj in Haryana", "Districts and administrative setup"], 1.0),
    ("Haryana Economy", ["Agriculture and irrigation", "Industries", "Major schemes", "Power and transport"], 1.2),
    ("Haryana Art and Culture", ["Folk dances", "Folk songs", "Fairs and festivals", "Dialects", "Cuisine"], 1.2),
    ("Haryana Current Affairs", ["State schemes and initiatives", "Appointments", "Sports achievements", "Awards"], 1.4),
    ("Haryana Sports and Personalities", ["Prominent sportspersons", "Sports policy", "Notable personalities"], 1.0),
)

_HINDI = chapters(
    ("व्याकरण (Grammar)", ["संधि", "समास", "उपसर्ग और प्रत्यय", "कारक", "वाच्य"], 1.2),
    ("शब्द ज्ञान (Vocabulary)", ["पर्यायवाची", "विलोम", "अनेकार्थी शब्द", "वाक्यांश के लिए एक शब्द"], 1.2),
    ("वाक्य शुद्धि (Sentence Correction)", ["वाक्य में अशुद्धि", "वर्तनी शुद्धि"], 1.0),
    ("मुहावरे और लोकोक्तियाँ (Idioms and Proverbs)", ["प्रचलित मुहावरे", "लोकोक्तियाँ"], 1.0),
    ("अपठित गद्यांश (Comprehension)", ["गद्यांश आधारित प्रश्न"], 1.0),
    ("रस, छंद और अलंकार", ["रस के भेद", "छंद के भेद", "अलंकार के भेद"], 0.8),
)

# HSSC CET Group C: 100 questions in 105 minutes, no negative marking, with
# roughly three quarters general subjects and one quarter Haryana-specific GK.
register(
    ExamPattern(
        exam="Haryana CET",
        slug="haryana-cet",
        category="State Level",
        pattern_version="2025 (Group C)",
        total_time_minutes=105,
        sections=(
            SectionSpec("General Awareness", "General Awareness", 15, 1.0, 0.0, chapters=GENERAL_AWARENESS),
            SectionSpec("Reasoning", "Reasoning", 15, 1.0, 0.0, chapters=REASONING),
            SectionSpec("Mathematics", "Quantitative Aptitude", 15, 1.0, 0.0, chapters=QUANT_ARITHMETIC),
            SectionSpec("General Science", "General Science", 15, 1.0, 0.0, chapters=GENERAL_SCIENCE),
            SectionSpec("English", "English", 8, 1.0, 0.0, chapters=ENGLISH),
            SectionSpec("Hindi", "Hindi", 7, 1.0, 0.0, chapters=_HINDI),
            SectionSpec("Haryana General Knowledge", "Haryana GK", 25, 1.0, 0.0, chapters=_HARYANA_GK),
        ),
        languages=(Language.ENGLISH, Language.HINDI, Language.BILINGUAL),
        difficulty_mix={Difficulty.EASY: 0.45, Difficulty.MEDIUM: 0.42, Difficulty.HARD: 0.13},
        negative_marking_default=False,
        aliases=("hssc cet", "haryana common eligibility test", "cet haryana"),
        instructions=(
            "100 objective questions carrying 100 marks in 105 minutes.",
            "There is no negative marking, so attempt every question.",
            "One quarter of the paper tests Haryana-specific general knowledge.",
            "Qualifying this test makes you eligible for subsequent HSSC recruitment stages.",
        ),
        notes=(
            "HSSC has revised CET weightage and eligibility norms more than once. "
            "The 75:25 general-to-Haryana split modelled here follows the most recent "
            "scheme known to this system; confirm against the current HSSC notification."
        ),
    )
)
