"""Paper generation orchestration.

Flow: blueprint the paper, request questions in batches, gate every one, retry
the rejects, then assemble. The provider is only ever asked to write content for
slots the blueprint already specified, so a bad batch costs a retry rather than a
misshapen paper.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..config import Settings, load_settings
from ..errors import QualityGateError
from ..exams.base import PATTERN_DISCLAIMER
from ..llm.base import GenerationCall, ProviderResult, QuestionProvider
from ..llm.factory import get_provider
from ..models.enums import Difficulty, SolutionDepth, TestType
from ..models.paper import Paper, PaperSection, Question
from ..models.request import GenerationRequest
from .blueprint import Blueprint, QuestionSlot, build_blueprint
from .prompts import QUESTION_BATCH_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from .validator import QualityGate

ORIGINALITY_DISCLAIMER = (
    "All questions are generated for practice and are written in the style of the "
    "exam. They are not reproductions of any official past paper, and they are not "
    "predictions of questions that will appear."
)

PLACEHOLDER_DISCLAIMER = (
    "THIS PAPER IS STRUCTURAL PLACEHOLDER CONTENT, NOT EXAM-QUALITY QUESTIONS. It was "
    "produced without a configured model API key and must not be used as study "
    "material. Set AIPARIKSHA_API_KEY to generate real questions."
)


@dataclass(slots=True)
class GenerationStats:
    """Observability for one generation run."""

    provider: str = ""
    model: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    slots_requested: int = 0
    questions_accepted: int = 0
    repair_rounds: int = 0
    dropped_slots: int = 0
    warnings: tuple[str, ...] = ()
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "model": self.model,
            "provider_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "slots_requested": self.slots_requested,
            "questions_accepted": self.questions_accepted,
            "repair_rounds": self.repair_rounds,
        }
        if self.dropped_slots:
            payload["dropped_slots"] = self.dropped_slots
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


class PaperGenerator:
    """Builds papers. Stateless between calls; safe to share across requests."""

    def __init__(
        self,
        settings: Settings | None = None,
        provider: QuestionProvider | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self._provider_override = provider

    # -------------------------------------------------------------------- public

    def provider_for(self, request: GenerationRequest) -> QuestionProvider:
        """The provider this request should use."""
        return self._provider_override or get_provider(
            self.settings, heavy=_needs_heavy_model(request)
        )

    def fill_slots(
        self,
        request: GenerationRequest,
        slots: Sequence[QuestionSlot],
        *,
        gate: QualityGate | None = None,
        provider: QuestionProvider | None = None,
        seconds_per_question: float | None = None,
    ) -> tuple[dict[int, Question], GenerationStats, list[QuestionSlot]]:
        """Generate and gate questions for the given slots.

        Returns the questions that passed, run statistics, and any slots that
        could never be filled. Shared by whole-paper generation and by the
        adaptive engine, which asks for one slot at a time.
        """
        provider = provider or self.provider_for(request)
        gate = gate if gate is not None else QualityGate(request)
        stats = GenerationStats(
            provider=provider.name, model=provider.model, slots_requested=len(slots)
        )
        if seconds_per_question is None:
            seconds_per_question = (request.time_limit_minutes * 60.0) / max(len(slots), 1)

        filled: dict[int, Question] = {}
        pending: list[QuestionSlot] = list(slots)
        repair_notes: list[str] = []
        warnings: list[str] = []
        is_placeholder = False

        for round_index in range(self.settings.max_repair_rounds + 1):
            if not pending:
                break
            if round_index:
                stats.repair_rounds += 1

            still_pending: list[QuestionSlot] = []
            round_notes: list[str] = []

            for batch in _batches(pending, self.settings.batch_size):
                result = self._request_batch(
                    provider,
                    request,
                    batch,
                    seconds_per_question=seconds_per_question,
                    avoid_stems=gate.recent_stems(),
                    repair_notes=repair_notes,
                )
                stats.calls += 1
                stats.input_tokens += result.input_tokens
                stats.output_tokens += result.output_tokens
                is_placeholder = is_placeholder or result.is_placeholder
                for warning in result.warnings:
                    if warning not in warnings:
                        warnings.append(warning)

                by_index = _index_responses(result.data, batch)
                for slot in batch:
                    outcome = gate.check(by_index.get(slot.index), slot)
                    if outcome.question is not None:
                        filled[slot.index] = outcome.question
                    else:
                        still_pending.append(slot)
                        round_notes.extend(outcome.failures)

            pending = still_pending
            repair_notes = list(dict.fromkeys(round_notes))[:8]

        stats.questions_accepted = len(filled)
        stats.dropped_slots = len(pending)
        stats.warnings = tuple(warnings)
        stats.is_placeholder = is_placeholder
        return filled, stats, pending

    def generate(self, request: GenerationRequest) -> Paper:
        blueprint = build_blueprint(request)
        provider = self.provider_for(request)

        gate = QualityGate(request)
        stats = GenerationStats(
            provider=provider.name,
            model=provider.model,
            slots_requested=blueprint.total_questions,
        )
        warnings: list[str] = []
        is_placeholder = False

        seconds_per_question = (request.time_limit_minutes * 60.0) / max(blueprint.total_questions, 1)
        filled: dict[int, Question] = {}
        pending: list[QuestionSlot] = list(blueprint.slots)
        repair_notes: list[str] = []

        for round_index in range(self.settings.max_repair_rounds + 1):
            if not pending:
                break
            if round_index:
                stats.repair_rounds += 1

            still_pending: list[QuestionSlot] = []
            round_notes: list[str] = []

            for batch in _batches(pending, self.settings.batch_size):
                result = self._request_batch(
                    provider,
                    request,
                    batch,
                    seconds_per_question=seconds_per_question,
                    avoid_stems=gate.recent_stems(),
                    repair_notes=repair_notes,
                )
                stats.calls += 1
                stats.input_tokens += result.input_tokens
                stats.output_tokens += result.output_tokens
                is_placeholder = is_placeholder or result.is_placeholder
                for warning in result.warnings:
                    if warning not in warnings:
                        warnings.append(warning)

                by_index = _index_responses(result.data, batch)
                for slot in batch:
                    outcome = gate.check(by_index.get(slot.index), slot)
                    if outcome.question is not None:
                        filled[slot.index] = outcome.question
                    else:
                        still_pending.append(slot)
                        round_notes.extend(outcome.failures)

            pending = still_pending
            # Feed a deduplicated, bounded set of reasons into the next attempt.
            repair_notes = list(dict.fromkeys(round_notes))[:8]

        stats.questions_accepted = len(filled)

        if pending:
            shortfall = len(pending) / max(blueprint.total_questions, 1)
            if shortfall > self.settings.quality_failure_tolerance:
                raise QualityGateError(
                    f"Only {len(filled)} of {blueprint.total_questions} questions passed the "
                    "quality checks, which is too few to serve a paper. This usually means the "
                    "requested scope is too narrow for the question count, or the provider is "
                    "misconfigured.",
                    failures=sorted(gate.rejections)[:10],
                )
            stats.dropped_slots = len(pending)
            warnings.append(
                f"{len(pending)} question(s) could not be generated to standard and were "
                f"omitted, so the paper is shorter than requested."
            )

        paper = self._assemble(request, blueprint, filled, stats, warnings, gate, is_placeholder)
        return paper

    # ------------------------------------------------------------------ internals

    def _request_batch(
        self,
        provider: QuestionProvider,
        request: GenerationRequest,
        batch: Sequence[QuestionSlot],
        *,
        seconds_per_question: float,
        avoid_stems: Sequence[str],
        repair_notes: Sequence[str],
    ) -> ProviderResult:
        user_prompt = build_user_prompt(
            request,
            batch,
            seconds_per_question=seconds_per_question,
            avoid_stems=avoid_stems,
            repair_notes=repair_notes,
        )
        call = GenerationCall(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            schema=QUESTION_BATCH_SCHEMA,
            max_tokens=self.settings.max_tokens,
            temperature=self.settings.temperature,
            context={"slots": [slot.to_dict() for slot in batch]},
        )
        return provider.complete(call)

    def _assemble(
        self,
        request: GenerationRequest,
        blueprint: Blueprint,
        filled: Mapping[int, Question],
        stats: GenerationStats,
        warnings: list[str],
        gate: QualityGate,
        is_placeholder: bool,
    ) -> Paper:
        pattern = request.pattern

        sections: list[PaperSection] = []
        for name, subject, time_minutes in blueprint.section_order:
            questions = [
                filled[slot.index]
                for slot in blueprint.slots_for_section(name)
                if slot.index in filled
            ]
            if not questions:
                continue
            sections.append(
                PaperSection(
                    name=name,
                    subject=subject,
                    questions=questions,
                    time_minutes=time_minutes if pattern.sectional_timing else None,
                    instructions=_section_instructions(questions),
                )
            )

        disclaimers = [ORIGINALITY_DISCLAIMER, PATTERN_DISCLAIMER]
        if pattern.notes:
            disclaimers.append(pattern.notes)
        if is_placeholder:
            disclaimers.insert(0, PLACEHOLDER_DISCLAIMER)

        stats.warnings = tuple(warnings)

        paper = Paper(
            paper_id=_paper_id(request),
            exam=pattern.exam,
            title=request.title or _title(request),
            pattern_version=request.pattern_version or pattern.pattern_version,
            duration_minutes=request.time_limit_minutes,
            marking_scheme=_marking_scheme(request, blueprint),
            sections=sections,
            instructions=_instructions(request, blueprint),
            language=request.language,
            negative_marking=request.negative_marking,
            request_summary=request.to_dict(),
            generated_by=stats.to_dict(),
            disclaimers=tuple(disclaimers),
        )
        paper.renumber()

        blueprint_summary = blueprint.to_dict()
        blueprint_summary["delivered_questions"] = paper.total_questions
        paper.blueprint_summary = blueprint_summary
        paper.quality_report = gate.report(paper.questions)
        return paper


# --------------------------------------------------------------------- helpers


def _batches(slots: Sequence[QuestionSlot], size: int) -> Iterable[list[QuestionSlot]]:
    """Chunk slots, never splitting across sections.

    Keeping a batch inside one section gives the model a coherent context and
    makes its "do not repeat" list far more useful.
    """
    size = max(1, size)
    current: list[QuestionSlot] = []
    current_section: str | None = None
    for slot in slots:
        if current and (slot.section != current_section or len(current) >= size):
            yield current
            current = []
        current.append(slot)
        current_section = slot.section
    if current:
        yield current


def _index_responses(
    data: Mapping[str, Any], batch: Sequence[QuestionSlot]
) -> dict[int, Any]:
    """Map provider entries onto slot indices.

    Prefers the echoed index; falls back to positional order for providers that
    drop or mangle it, so a single missing field does not void the whole batch.
    """
    raw = data.get("questions")
    if not isinstance(raw, list):
        raw = [data] if data else []

    by_index: dict[int, Any] = {}
    leftovers: list[Any] = []
    valid = {slot.index for slot in batch}

    for entry in raw:
        index = entry.get("index") if isinstance(entry, Mapping) else None
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = None
        if index in valid and index not in by_index:
            by_index[index] = entry
        else:
            leftovers.append(entry)

    if leftovers:
        for slot in batch:
            if slot.index in by_index:
                continue
            if not leftovers:
                break
            by_index[slot.index] = leftovers.pop(0)
    return by_index


def _needs_heavy_model(request: GenerationRequest) -> bool:
    """Route the hardest papers to the stronger model."""
    if request.difficulty is Difficulty.HARD:
        return True
    if request.pattern.difficulty_mix.get(Difficulty.HARD, 0.0) >= 0.40:
        return True
    return request.bloom_level is not None and str(request.bloom_level) in {"Evaluate", "Create"}


def _paper_id(request: GenerationRequest) -> str:
    """Stable id when seeded, unique otherwise."""
    slug = request.pattern.slug
    if request.seed is not None:
        digest = hashlib.sha256(
            f"{slug}|{request.seed}|{request.num_questions}|{request.test_type}|"
            f"{','.join(request.chapters)}|{','.join(request.topics)}|{request.difficulty}".encode()
        ).hexdigest()[:12]
        return f"{slug}-{digest}"
    return f"{slug}-{uuid.uuid4().hex[:12]}"


def _title(request: GenerationRequest) -> str:
    pattern = request.pattern
    scope = ""
    if request.topics:
        scope = _join(request.topics, 2)
    elif request.chapters:
        scope = _join(request.chapters, 2)
    elif request.subjects and len(request.subjects) < len(pattern.subjects):
        scope = _join(request.subjects, 3)

    label = {
        TestType.FULL_MOCK: "Full Mock Test",
        TestType.CHAPTER_WISE: "Chapter Test",
        TestType.TOPIC_WISE: "Topic Test",
        TestType.REVISION: "Revision Paper",
        TestType.PREVIOUS_YEAR_PATTERN: "Previous-Year-Pattern Paper",
        TestType.ADAPTIVE: "Adaptive Practice Test",
        TestType.SECTIONAL: "Sectional Test",
    }.get(request.test_type, "Practice Test")

    base = f"{pattern.exam} {label}"
    if scope:
        return f"{base} - {scope}"
    if request.test_type is TestType.FULL_MOCK:
        return f"{base} - Full Syllabus"
    return base


def _join(items: Sequence[str], limit: int) -> str:
    shown = list(items[:limit])
    if len(items) > limit:
        shown.append(f"+{len(items) - limit} more")
    return ", ".join(shown)


def _marking_scheme(request: GenerationRequest, blueprint: Blueprint) -> str:
    """Describe marking from what the paper actually contains."""
    groups: dict[tuple[float, float], list[str]] = {}
    for slot in blueprint.slots:
        groups.setdefault((slot.marks, slot.negative_marks), []).append(slot.section)

    parts: list[str] = []
    for (marks, penalty), sections in groups.items():
        where = "all questions" if len(groups) == 1 else ", ".join(dict.fromkeys(sections))
        penalty_text = f"{penalty:g} deducted for each incorrect answer" if penalty else "no negative marking"
        parts.append(f"{where}: +{marks:g} for each correct answer, {penalty_text}")

    scheme = "; ".join(parts)
    if not request.negative_marking and request.pattern.negative_marking_default:
        scheme += " (negative marking disabled at your request; the real exam does penalise wrong answers)"
    return scheme


def _instructions(request: GenerationRequest, blueprint: Blueprint) -> tuple[str, ...]:
    pattern = request.pattern
    lines: list[str] = [
        f"This paper contains {blueprint.total_questions} questions carrying "
        f"{blueprint.max_marks:g} maximum marks.",
        f"Total time allowed: {request.time_limit_minutes} minutes.",
    ]
    if pattern.sectional_timing:
        timed = [
            f"{name} ({time} min)"
            for name, _, time in blueprint.section_order
            if time
        ]
        if timed:
            lines.append(
                "This exam is sectionally timed. Sections and their limits: " + "; ".join(timed) + "."
            )
    lines.extend(pattern.instructions)
    if not request.negative_marking:
        lines.append("Negative marking is switched off for this practice paper.")
    if request.solution_depth is SolutionDepth.NONE:
        lines.append("Solutions were not requested for this paper.")
    lines.append("Read every question carefully; each one is self-contained.")
    return tuple(dict.fromkeys(lines))


def _section_instructions(questions: Sequence[Question]) -> str:
    types = list(dict.fromkeys(str(q.question_type) for q in questions))
    marks = list(dict.fromkeys(f"+{q.marks:g}" for q in questions))
    return f"{len(questions)} question(s) | {', '.join(types)} | {', '.join(marks)} mark(s) each"
