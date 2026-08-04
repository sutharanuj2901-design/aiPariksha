"""Self-populating exam registry.

Definition modules under ``aipariksha/exams/definitions/`` are imported on first
access and register themselves. Dropping a new file into that package is the
*entire* cost of supporting a new exam — no imports to update, no dispatch
tables to edit, no core logic to touch.
"""

from __future__ import annotations

import importlib
import pkgutil
import threading
from typing import Iterator

from ..errors import UnknownExamError
from .base import ExamPattern, _norm

_REGISTRY: dict[str, ExamPattern] = {}
_ALIASES: dict[str, str] = {}
_LOCK = threading.RLock()
_DISCOVERED = False


def register(pattern: ExamPattern, *, replace: bool = False) -> ExamPattern:
    """Add an exam to the catalogue. Called by each definition module."""
    with _LOCK:
        key = _norm(pattern.exam)
        if key in _REGISTRY and not replace:
            raise ValueError(f"Exam {pattern.exam!r} is already registered.")
        _REGISTRY[key] = pattern
        for alias in (pattern.slug, *pattern.aliases):
            _ALIASES[_norm(alias)] = key
    return pattern


def _discover() -> None:
    """Import every module in the ``definitions`` sub-package exactly once."""
    global _DISCOVERED
    with _LOCK:
        if _DISCOVERED:
            return
        # Set the flag first: definition modules import from this package, and
        # a re-entrant _discover() would otherwise recurse.
        _DISCOVERED = True
        package = importlib.import_module(f"{__package__}.definitions")
        for info in pkgutil.iter_modules(package.__path__):
            if info.name.startswith("_"):
                continue
            importlib.import_module(f"{package.__name__}.{info.name}")


def get(exam: str) -> ExamPattern:
    """Resolve an exam by name, slug or alias. Raises ``UnknownExamError``."""
    _discover()
    if not isinstance(exam, str) or not exam.strip():
        raise UnknownExamError(str(exam), supported_names())
    key = _norm(exam)
    if key in _REGISTRY:
        return _REGISTRY[key]
    if key in _ALIASES:
        return _REGISTRY[_ALIASES[key]]
    # Last resort: unambiguous substring match ("neet" -> "NEET UG").
    hits = [v for k, v in _REGISTRY.items() if key in k]
    if len(hits) == 1:
        return hits[0]
    raise UnknownExamError(exam, supported_names())


def find(exam: str) -> ExamPattern | None:
    try:
        return get(exam)
    except UnknownExamError:
        return None


def all_patterns() -> tuple[ExamPattern, ...]:
    _discover()
    return tuple(sorted(_REGISTRY.values(), key=lambda p: (p.category, p.exam)))


def supported_names() -> list[str]:
    return [p.exam for p in all_patterns() if p.is_supported]


def catalogue() -> list[dict[str, object]]:
    """Compact listing for a UI's exam picker."""
    return [
        {
            "exam": p.exam,
            "slug": p.slug,
            "category": p.category,
            "pattern_version": p.pattern_version,
            "status": p.status,
            "total_questions": p.total_questions,
            "total_time_minutes": p.total_time_minutes,
            "max_marks": p.max_marks,
            "subjects": list(p.subjects),
            "languages": [str(l) for l in p.languages],
        }
        for p in all_patterns()
    ]


def by_category() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for pattern in all_patterns():
        grouped.setdefault(pattern.category, []).append(pattern.exam)
    return grouped


def __iter__() -> Iterator[ExamPattern]:  # pragma: no cover - convenience
    return iter(all_patterns())
