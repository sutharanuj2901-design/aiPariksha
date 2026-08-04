"""Exam catalogue: declarative patterns plus a self-populating registry."""

from __future__ import annotations

from .base import PATTERN_DISCLAIMER, ChapterSpec, ExamPattern, SectionSpec, chapters
from .registry import all_patterns, by_category, catalogue, find, get, register, supported_names

__all__ = [
    "PATTERN_DISCLAIMER",
    "ChapterSpec",
    "ExamPattern",
    "SectionSpec",
    "chapters",
    "all_patterns",
    "by_category",
    "catalogue",
    "find",
    "get",
    "register",
    "supported_names",
]
