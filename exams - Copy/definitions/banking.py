"""Banking recruitment exams (preliminary stages)."""

from __future__ import annotations

from ...models.enums import Difficulty, Language
from ..base import ExamPattern, SectionSpec
from ..registry import register
from ._common import ENGLISH, QUANT_ARITHMETIC, REASONING

_LANGS = (Language.ENGLISH, Language.HINDI, Language.BILINGUAL)
_PO_MIX = {Difficulty.EASY: 0.30, Difficulty.MEDIUM: 0.50, Difficulty.HARD: 0.20}
_CLERK_MIX = {Difficulty.EASY: 0.45, Difficulty.MEDIUM: 0.42, Difficulty.HARD: 0.13}

_PRELIMS_INSTRUCTIONS = (
    "100 objective questions carrying 100 marks.",
    "Each correct answer earns 1 mark; 0.25 marks are deducted for each incorrect answer.",
    "Each section is separately timed at 20 minutes; you cannot return to a section once its time expires.",
    "The English Language section is available in English only.",
)


def _prelims(
    exam: str,
    slug: str,
    *,
    pattern_version: str,
    reasoning_label: str,
    quant_label: str,
    difficulty_mix: dict,
    aliases: tuple[str, ...],
    total_time_minutes: int = 60,
    sectional_time: int | None = 20,
    sectional_timing: bool = True,
    instructions: tuple[str, ...] = _PRELIMS_INSTRUCTIONS,
) -> ExamPattern:
    """Build the common 30/35/35 banking prelims shape.

    A local factory, not core logic: the shared structure is expressed once and
    each exam still declares its own labels, timing and difficulty profile.
    """
    return ExamPattern(
        exam=exam,
        slug=slug,
        category="Banking",
        pattern_version=pattern_version,
        total_time_minutes=total_time_minutes,
        sections=(
            SectionSpec("English Language", "English", 30, 1.0, -0.25,
                        chapters=ENGLISH, time_minutes=sectional_time),
            SectionSpec(quant_label, "Quantitative Aptitude", 35, 1.0, -0.25,
                        chapters=QUANT_ARITHMETIC, time_minutes=sectional_time),
            SectionSpec(reasoning_label, "Reasoning", 35, 1.0, -0.25,
                        chapters=REASONING, time_minutes=sectional_time),
        ),
        languages=_LANGS,
        difficulty_mix=difficulty_mix,
        sectional_timing=sectional_timing,
        aliases=aliases,
        instructions=instructions,
    )


register(_prelims(
    "IBPS PO", "ibps-po",
    pattern_version="2025 Prelims",
    reasoning_label="Reasoning Ability",
    quant_label="Quantitative Aptitude",
    difficulty_mix=_PO_MIX,
    aliases=("ibps po prelims", "ibps probationary officer"),
))

register(_prelims(
    "IBPS Clerk", "ibps-clerk",
    pattern_version="2025 Prelims",
    reasoning_label="Reasoning Ability",
    quant_label="Numerical Ability",
    difficulty_mix=_CLERK_MIX,
    aliases=("ibps clerk prelims",),
))

register(_prelims(
    "SBI PO", "sbi-po",
    pattern_version="2025 Prelims",
    reasoning_label="Reasoning Ability",
    quant_label="Quantitative Aptitude",
    difficulty_mix={Difficulty.EASY: 0.25, Difficulty.MEDIUM: 0.48, Difficulty.HARD: 0.27},
    aliases=("sbi po prelims", "state bank po"),
))

register(_prelims(
    "SBI Clerk", "sbi-clerk",
    pattern_version="2025 Prelims",
    reasoning_label="Reasoning Ability",
    quant_label="Numerical Ability",
    difficulty_mix=_CLERK_MIX,
    aliases=("sbi clerk prelims", "sbi junior associate"),
))

# RBI Assistant prelims is composite-timed rather than sectionally timed.
register(_prelims(
    "RBI Assistant", "rbi-assistant",
    pattern_version="2025 Prelims",
    reasoning_label="Reasoning Ability",
    quant_label="Numerical Ability",
    difficulty_mix=_CLERK_MIX,
    aliases=("rbi assistant prelims",),
    total_time_minutes=45,
    sectional_time=None,
    sectional_timing=False,
    instructions=(
        "100 objective questions carrying 100 marks in a composite 45 minutes.",
        "Each correct answer earns 1 mark; 0.25 marks are deducted for each incorrect answer.",
        "There is no sectional time limit; manage the full 45 minutes across all three sections.",
        "Speed and accuracy matter more here than in any other banking prelims.",
    ),
))
