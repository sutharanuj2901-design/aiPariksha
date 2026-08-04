"""Quality gates.

Nothing reaches a student without passing through here. The gate converts raw
provider output into a ``Question`` and rejects anything that violates the
non-negotiables: ambiguous option sets, more than one defensible answer,
duplicates, off-slot content, unanswerable references to absent figures, or a
missing solution when one was requested.

Rejections are returned as reasons, not exceptions, so the generator can feed
them back to the provider and ask for a replacement.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..models.enums import Difficulty, Language, QuestionType, SolutionDepth
from ..models.paper import Option, Question, Solution, _normalise_for_dedupe
from ..models.request import GenerationRequest
from .blueprint import QuestionSlot

#: Option texts that make a question ambiguous or guessable by construction.
_BANNED_OPTION_PATTERNS = (
    re.compile(r"^\s*all of the above\s*$", re.I),
    re.compile(r"^\s*none of the above\s*$", re.I),
    re.compile(r"^\s*both\s+[a-d]\s+and\s+[a-d]\s*$", re.I),
    re.compile(r"^\s*(a|b|c|d)\s+and\s+(a|b|c|d)\s+only\s*$", re.I),
)

#: Stems referring to content the student cannot see.
_DANGLING_REFERENCE = re.compile(
    r"\b(?:in|from|see|refer to|based on|according to|as shown in|shown in)\s+"
    r"the\s+(?:figure|diagram|image|graph|circuit|table|passage|paragraph|extract)\s+"
    r"(?:above|below|given|shown|alongside)?\b",
    re.I,
)

#: Phrasing that leaks the model's own process instead of teaching.
_META_LEAK = re.compile(
    r"\b(?:as an ai|i will now|let me think|let's think|my reasoning|i need to|"
    r"chain of thought|internal reasoning|as requested|here is your question)\b",
    re.I,
)

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

_MIN_STEM_CHARS = 20
_MAX_STEM_CHARS = 2000
_MIN_EXPLANATION_CHARS = 25


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Result of gating one raw question."""

    question: Question | None
    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.question is not None and not self.failures


@dataclass(slots=True)
class QualityGate:
    """Validates questions and tracks paper-level state such as duplicates."""

    request: GenerationRequest
    _fingerprints: dict[str, int] = field(default_factory=dict)
    _stems: list[str] = field(default_factory=list)
    #: Reason -> how many questions were rejected for it, for the quality report.
    rejections: dict[str, int] = field(default_factory=dict)
    accepted_count: int = 0

    # ------------------------------------------------------------------- public

    def check(self, raw: Any, slot: QuestionSlot) -> ValidationOutcome:
        """Build and validate one question against its slot."""
        if not isinstance(raw, Mapping):
            return self._reject(["Provider returned a non-object question entry."])

        failures: list[str] = []
        notes: list[str] = []

        stem = str(raw.get("text") or "").strip()
        stem_hi = str(raw.get("text_hi") or "").strip()
        failures.extend(self._check_stem(stem, stem_hi))

        options, option_failures, option_notes = self._check_options(raw, slot)
        failures.extend(option_failures)
        notes.extend(option_notes)

        correct_keys: tuple[str, ...] = ()
        correct_value: float | None = None
        if slot.question_type is QuestionType.NUMERICAL:
            correct_value, numeric_failures = self._check_numerical(raw)
            failures.extend(numeric_failures)
        else:
            correct_keys, key_failures = self._check_keys(raw, options, slot)
            failures.extend(key_failures)

        solution, solution_failures = self._check_solution(raw, correct_keys, correct_value)
        failures.extend(solution_failures)

        if failures:
            return self._reject(failures, notes)

        question = Question(
            number=slot.index,
            section=slot.section,
            subject=slot.subject,
            chapter=slot.chapter,
            topic=slot.topic,
            difficulty=slot.difficulty,
            question_type=slot.question_type,
            text=stem,
            text_hi=stem_hi,
            options=options,
            correct_keys=correct_keys,
            correct_value=correct_value,
            tolerance=_safe_float(raw.get("tolerance"), 0.0),
            marks=slot.marks,
            negative_marks=slot.negative_marks,
            partial_marks=slot.partial_marks,
            bloom_level=slot.bloom_level,
            solution=solution,
        )

        # Duplicate detection runs last: it needs the assembled question, and a
        # question that failed other checks is never registered as "seen".
        fingerprint = question.fingerprint()
        if fingerprint in self._fingerprints:
            return self._reject(
                [
                    "Duplicate of a question already in this paper "
                    f"(matches Q{self._fingerprints[fingerprint]})."
                ],
                notes,
            )

        if self._is_near_duplicate(stem):
            return self._reject(["Too similar to another question already in this paper."], notes)

        self._fingerprints[fingerprint] = slot.index
        self._stems.append(_normalise_for_dedupe(stem))
        self.accepted_count += 1
        question.quality_notes = tuple(notes)
        return ValidationOutcome(question=question, notes=tuple(notes))

    def recent_stems(self, limit: int = 12) -> list[str]:
        """Short stems to send back to the provider as "do not repeat"."""
        return [s[:140] for s in self._stems[-limit:]]

    def report(self, questions: list[Question]) -> dict[str, Any]:
        """Paper-level quality summary."""
        key_spread = _answer_key_spread(questions)
        report: dict[str, Any] = {
            "accepted": self.accepted_count,
            "rejected": sum(self.rejections.values()),
            "rejection_reasons": dict(sorted(self.rejections.items(), key=lambda kv: -kv[1])),
            "answer_key_distribution": key_spread,
            "duplicate_check": "passed",
        }
        warnings: list[str] = []
        skew = _max_share(key_spread)
        if skew is not None and skew > 0.45:
            warnings.append(
                f"One option letter holds {skew:.0%} of the answers; a real paper is flatter."
            )
        difficulty_actual = _tally(str(q.difficulty) for q in questions)
        report["difficulty_actual"] = difficulty_actual
        if warnings:
            report["warnings"] = warnings
        return report

    # ------------------------------------------------------------------ checks

    def _check_stem(self, stem: str, stem_hi: str) -> list[str]:
        failures: list[str] = []
        if not stem:
            failures.append("Question text is empty.")
            return failures
        if len(stem) < _MIN_STEM_CHARS:
            failures.append(f"Question text is too short to be a real question ({len(stem)} chars).")
        if len(stem) > _MAX_STEM_CHARS:
            failures.append("Question text is implausibly long; it likely bundles several questions.")
        if _DANGLING_REFERENCE.search(stem):
            failures.append(
                "Stem refers to a figure, table or passage that is not included, so it cannot be answered."
            )
        if _META_LEAK.search(stem):
            failures.append("Stem contains meta commentary instead of question content.")
        if stem.count("?") == 0 and not re.search(r"\b(?:find|calculate|choose|select|identify|which|what|state|determine|evaluate|match|complete|fill)\b", stem, re.I):
            failures.append("Stem does not actually pose a question or instruct an action.")

        language = self.request.language
        if language is Language.BILINGUAL:
            if not stem_hi:
                failures.append("Bilingual paper requires a Hindi version of the stem.")
            elif not _DEVANAGARI.search(stem_hi):
                failures.append("Hindi stem contains no Devanagari text.")
        elif language is Language.HINDI and not (_DEVANAGARI.search(stem_hi) or _DEVANAGARI.search(stem)):
            failures.append("Hindi paper requires the question in Devanagari script.")
        return failures

    def _check_options(
        self, raw: Mapping[str, Any], slot: QuestionSlot
    ) -> tuple[tuple[Option, ...], list[str], list[str]]:
        if slot.question_type is QuestionType.NUMERICAL:
            return (), [], []

        raw_options = raw.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            return (), ["Option-based question has no options."], []

        failures: list[str] = []
        notes: list[str] = []
        options: list[Option] = []
        seen_keys: set[str] = set()
        seen_texts: set[str] = set()

        for position, item in enumerate(raw_options):
            if not isinstance(item, Mapping):
                failures.append("An option entry is not an object.")
                continue
            key = str(item.get("key") or "").strip().upper()[:1]
            text = str(item.get("text") or "").strip()
            if not key:
                key = "ABCDEF"[position] if position < 6 else str(position)
                notes.append(f"Missing option key filled in as {key}.")
            if not text:
                failures.append(f"Option {key} has no text.")
                continue
            if key in seen_keys:
                failures.append(f"Duplicate option key {key}.")
                continue
            normalised = _normalise_for_dedupe(text)
            if normalised in seen_texts:
                failures.append("Two options have the same meaning, so the question is ambiguous.")
                continue
            if any(pattern.match(text) for pattern in _BANNED_OPTION_PATTERNS):
                failures.append(f"Option {key} uses a banned combined form ({text!r}).")
                continue
            seen_keys.add(key)
            seen_texts.add(normalised)
            options.append(
                Option(key=key, text=text, text_hi=str(item.get("text_hi") or "").strip())
            )

        if len(options) < 4:
            failures.append(f"Expected 4 options, got {len(options)}.")
        elif len(options) > 4 and slot.question_type is not QuestionType.MCQ_MULTIPLE:
            notes.append(f"{len(options)} options supplied; the pattern normally uses 4.")

        if self.request.language is Language.BILINGUAL and options and not all(o.text_hi for o in options):
            failures.append("Bilingual paper requires a Hindi version of every option.")

        return tuple(options), failures, notes

    def _check_keys(
        self, raw: Mapping[str, Any], options: tuple[Option, ...], slot: QuestionSlot
    ) -> tuple[tuple[str, ...], list[str]]:
        raw_keys = raw.get("correct_keys")
        if raw_keys is None:
            raw_keys = raw.get("correct_answer") or raw.get("answer")
        if isinstance(raw_keys, str):
            cleaned = raw_keys.strip().upper().replace(" ", "")
            raw_keys = cleaned.split(",") if "," in cleaned else list(cleaned)
        if not isinstance(raw_keys, list) or not raw_keys:
            return (), ["No correct answer was supplied."]

        available = {o.key for o in options}
        keys: list[str] = []
        failures: list[str] = []
        for item in raw_keys:
            key = str(item).strip().upper()[:1]
            if not key:
                continue
            if key not in available:
                failures.append(f"Correct answer {key!r} is not one of the options.")
                continue
            if key not in keys:
                keys.append(key)

        expected_multiple = slot.question_type is QuestionType.MCQ_MULTIPLE
        if not expected_multiple and len(keys) > 1:
            failures.append(
                f"{slot.question_type} must have exactly one correct answer, got {len(keys)}."
            )
        if expected_multiple:
            if len(keys) < 2:
                failures.append("Multiple-correct question must have at least two correct options.")
            elif options and len(keys) >= len(options):
                failures.append("Every option is marked correct, so the question is meaningless.")
        if not keys and not failures:
            failures.append("No valid correct answer key.")
        return tuple(keys), failures

    def _check_numerical(self, raw: Mapping[str, Any]) -> tuple[float | None, list[str]]:
        value = raw.get("correct_value")
        if value is None:
            value = raw.get("answer") if isinstance(raw.get("answer"), (int, float)) else None
        if value is None:
            return None, ["Numerical question has no correct_value."]
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None, [f"correct_value {value!r} is not a number."]
        if math.isnan(parsed) or math.isinf(parsed):
            return None, ["correct_value is not a finite number."]
        return parsed, []

    def _check_solution(
        self,
        raw: Mapping[str, Any],
        correct_keys: tuple[str, ...],
        correct_value: float | None,
    ) -> tuple[Solution | None, list[str]]:
        depth = self.request.solution_depth
        raw_solution = raw.get("solution")
        answer_display = ", ".join(correct_keys) if correct_keys else _fmt(correct_value)

        if depth is SolutionDepth.NONE:
            return None, []

        if not isinstance(raw_solution, Mapping):
            if depth is SolutionDepth.ANSWER_KEY:
                # Only the key was requested; a missing explanation is acceptable.
                return Solution(correct_answer=answer_display, final_answer=answer_display), []
            return None, ["Solution was requested but none was supplied."]

        explanation = str(raw_solution.get("explanation") or "").strip()
        failures: list[str] = []
        if depth in (SolutionDepth.BRIEF, SolutionDepth.DETAILED):
            if not explanation:
                failures.append("Solution has no explanation.")
            elif len(explanation) < _MIN_EXPLANATION_CHARS:
                failures.append("Solution explanation is too short to teach anything.")
            if _META_LEAK.search(explanation):
                failures.append("Solution exposes internal reasoning instead of explaining the concept.")

        solution = Solution(
            correct_answer=answer_display,
            explanation=explanation,
            steps=_str_tuple(raw_solution.get("steps")),
            formula=str(raw_solution.get("formula_used") or raw_solution.get("formula") or "").strip(),
            common_mistakes=_str_tuple(raw_solution.get("common_mistakes")),
            time_saving_tip=str(raw_solution.get("time_saving_tip") or "").strip(),
            final_answer=str(raw_solution.get("final_answer") or answer_display).strip(),
            concept_tested=str(raw_solution.get("concept_tested") or "").strip(),
        )
        return solution, failures

    # ------------------------------------------------------------------ helpers

    def _is_near_duplicate(self, stem: str, threshold: float = 0.85) -> bool:
        """Token-overlap check, for rewordings the exact fingerprint misses."""
        tokens = set(_normalise_for_dedupe(stem).split())
        if len(tokens) < 6:
            return False
        for existing in self._stems:
            other = set(existing.split())
            if len(other) < 6:
                continue
            overlap = len(tokens & other) / len(tokens | other)
            if overlap >= threshold:
                return True
        return False

    def _reject(self, failures: list[str], notes: list[str] | None = None) -> ValidationOutcome:
        for failure in failures:
            self.rejections[failure] = self.rejections.get(failure, 0) + 1
        return ValidationOutcome(question=None, failures=tuple(failures), notes=tuple(notes or ()))


def _str_tuple(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw.strip(),) if raw.strip() else ()
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _safe_float(raw: Any, fallback: float) -> float:
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return fallback
    return fallback if math.isnan(parsed) or math.isinf(parsed) else parsed


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _answer_key_spread(questions: list[Question]) -> dict[str, int]:
    spread: dict[str, int] = {}
    for question in questions:
        if question.is_numerical:
            spread["numerical"] = spread.get("numerical", 0) + 1
            continue
        for key in question.correct_keys:
            spread[key] = spread.get(key, 0) + 1
    return dict(sorted(spread.items()))


def _max_share(spread: Mapping[str, int]) -> float | None:
    total = sum(spread.values())
    if total <= 0:
        return None
    return max(spread.values()) / total


def _tally(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts
