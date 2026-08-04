"""AIPariksha — the AI engine behind an AI-first examination platform.

Quick start (no API key needed; you get placeholder content until you add one):

    from aipariksha import AIPariksha

    engine = AIPariksha()
    result = engine.generate({"exam": "NEET UG", "num_questions": 30})
    paper = result["paper"]

    report = engine.evaluate({"paper": paper, "submission": {"responses": [...]}})

Architecture, in dependency order:

* ``exams``      - declarative exam patterns and a self-populating registry
* ``models``     - JSON contracts (request, paper, submission, report, history)
* ``generation`` - blueprinting, prompting, quality gating, orchestration
* ``llm``        - pluggable providers (Claude, offline templates)
* ``evaluation`` - scoring, analytics, recommendations
* ``engine``     - the JSON-in/JSON-out facade
"""

from __future__ import annotations

from .config import Settings, load_settings
from .engine import AIPariksha
from .errors import (
    AIParikshaError,
    BlueprintError,
    ClarificationNeeded,
    ProviderError,
    QualityGateError,
    SyllabusError,
    UnknownExamError,
    ValidationError,
)
from .exams import register, registry

__version__ = "1.0.0"

__all__ = [
    "AIPariksha",
    "AIParikshaError",
    "BlueprintError",
    "ClarificationNeeded",
    "ProviderError",
    "QualityGateError",
    "Settings",
    "SyllabusError",
    "UnknownExamError",
    "ValidationError",
    "__version__",
    "load_settings",
    "register",
    "registry",
]
