"""Blueprinting, prompting, generation and quality gating."""

from __future__ import annotations

from .blueprint import Blueprint, QuestionSlot, build_blueprint
from .generator import GenerationStats, PaperGenerator
from .prompts import QUESTION_BATCH_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from .validator import QualityGate, ValidationOutcome

__all__ = [
    "Blueprint",
    "GenerationStats",
    "PaperGenerator",
    "QUESTION_BATCH_SCHEMA",
    "QualityGate",
    "QuestionSlot",
    "SYSTEM_PROMPT",
    "ValidationOutcome",
    "build_blueprint",
    "build_user_prompt",
]
