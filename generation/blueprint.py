"""Paper blueprinting: decide *what* every question must test before asking a
model to write anything.

Doing the arithmetic here rather than in the prompt is what makes coverage,
weighting and difficulty distribution deterministic and auditable. The model is
handed one fully-specified slot per question and is never asked to decide the
composition of the paper.

Allocation uses the largest-remainder method throughout, so every split sums
exactly to the requested total with no drift.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ..errors import BlueprintError
from ..exams.base import ChapterSpec, ExamPattern, SectionSpec, _norm
from ..models.enums import BloomLevel, Difficulty, QuestionType, TestType
from ..models.request import REVISION_WEAK_SHARE, GenerationRequest

#: Cognitive level implied by each difficulty when the caller does not pin one.
_BLOOM_BY_DIFFICULTY = {
    Difficulty.EASY: BloomLevel.UNDERSTAND,
    Difficulty.MEDIUM: BloomLevel.APPLY,
    Difficulty.HARD: BloomLevel.ANALYZE,
}

#: Adaptive weighting: how much extra blueprint share a weak chapter earns.
_ADAPTIVE_WEAK_BOOST = 2.5
_ADAPTIVE_STRONG_DAMP = 0.4


@dataclass(frozen=True, slots=True)
class QuestionSlot:
    """A complete specification for one question, decided before generation."""

    index: int
    section: str
    subject: str
    chapter: str
    topic: str
    difficulty: Difficulty
    question_type: QuestionType
    marks: float
    negative_marks: float
    partial_marks: float = 0.0
    bloom_level: BloomLevel | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "section": self.section,
            "subject": self.subject,
            "chapter": self.chapter,
            "topic": self.topic,
            "difficulty": str(self.difficulty),
            "question_type": str(self.question_type),
            "marks": self.marks,
            "negative_marks": self.negative_marks,
            "bloom_level": str(self.bloom_level) if self.bloom_level else None,
        }


@dataclass(slots=True)
class Blueprint:
    """The planned composition of a paper."""

    slots: tuple[QuestionSlot, ...]
    #: Sections in paper order, with their allotted time where applicable.
    section_order: tuple[tuple[str, str, int | None], ...] = ()
    target_difficulty: Mapping[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def total_questions(self) -> int:
        return len(self.slots)

    @property
    def max_marks(self) -> float:
        return round(sum(s.marks for s in self.slots), 2)

    def slots_for_section(self, section: str) -> tuple[QuestionSlot, ...]:
        return tuple(s for s in self.slots if s.section == section)

    def _count(self, key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for slot in self.slots:
            value = str(getattr(slot, key))
            counts[value] = counts.get(value, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_questions": self.total_questions,
            "maximum_marks": self.max_marks,
            "questions_per_section": self._count("section"),
            "questions_per_subject": self._count("subject"),
            "questions_per_chapter": self._count("chapter"),
            "questions_per_topic": self._count("topic"),
            "difficulty_target": dict(self.target_difficulty),
            "difficulty_actual": self._count("difficulty"),
            "question_types": self._count("question_type"),
            "notes": list(self.notes),
        }


def build_blueprint(request: GenerationRequest) -> Blueprint:
    """Turn a validated request into an exact per-question plan."""
    pattern = request.pattern
    # Deterministic when a seed is supplied; still varied paper-to-paper when not.
    rng = random.Random(request.seed) if request.seed is not None else random.Random()
    notes: list[str] = []

    sections = _select_sections(pattern, request, notes)
    per_section = _allocate(
        request.num_questions, _section_weights(sections, request, notes)
    )

    # Drop sections that ended up with nothing so the paper has no empty blocks.
    live = [(section, count) for section, count in zip(sections, per_section) if count > 0]
    if not live:
        raise BlueprintError(
            "The requested question count cannot be spread across the selected syllabus."
        )
    if len(live) < len(sections):
        skipped = [s.name for s, c in zip(sections, per_section) if c == 0]
        notes.append(
            f"{request.num_questions} questions could not cover every section; "
            f"omitted: {', '.join(skipped)}."
        )

    weights = _chapter_weights(request)
    slots: list[QuestionSlot] = []
    difficulty_target: dict[str, int] = {}

    for section, count in live:
        chapters = _chapters_for_section(section, request)
        if not chapters:
            continue
        chapter_counts = _allocate(count, [weights.get(_norm(c.name), c.weight) for c in chapters])
        # Difficulty is mixed *within* each section so no section is uniformly
        # easy or uniformly hard.
        difficulties = _difficulty_sequence(count, request, rng)
        for name, number in _tally(difficulties).items():
            difficulty_target[name] = difficulty_target.get(name, 0) + number

        qtypes = _question_types_for(section, request)
        cursor = 0
        for chapter, chapter_count in zip(chapters, chapter_counts):
            topics = _topics_for(chapter, request, chapter_count, rng)
            for offset in range(chapter_count):
                difficulty = difficulties[cursor]
                slots.append(
                    QuestionSlot(
                        index=len(slots) + 1,
                        section=section.name,
                        subject=section.subject,
                        chapter=chapter.name,
                        topic=topics[offset],
                        difficulty=difficulty,
                        question_type=qtypes[cursor % len(qtypes)],
                        marks=section.marks_correct,
                        negative_marks=section.marks_incorrect if request.negative_marking else 0.0,
                        partial_marks=section.partial_marks,
                        bloom_level=request.bloom_level or _BLOOM_BY_DIFFICULTY.get(difficulty),
                    )
                )
                cursor += 1

    if not slots:
        raise BlueprintError("No syllabus content matched the request; nothing to generate.")

    section_order = tuple(
        dict.fromkeys((s.name, s.subject, s.time_minutes) for s, _ in live)
    )
    return Blueprint(
        slots=tuple(slots),
        section_order=section_order,
        target_difficulty=difficulty_target,
        notes=tuple(notes),
    )


# ------------------------------------------------------------------ selection


def _select_sections(
    pattern: ExamPattern, request: GenerationRequest, notes: list[str]
) -> list[SectionSpec]:
    """Which pattern sections this paper draws from, in official order."""
    subjects = {_norm(s) for s in request.subjects} if request.subjects else None
    chapters = {_norm(c) for c in request.chapters} if request.chapters else None
    topics = tuple(request.topics)

    selected: list[SectionSpec] = []
    for section in pattern.sections:
        if subjects is not None and _norm(section.subject) not in subjects:
            continue
        if chapters is not None and not any(_norm(c.name) in chapters for c in section.chapters):
            continue
        if topics and not any(c.has_topic(t) for c in section.chapters for t in topics):
            continue
        selected.append(section)

    if not selected:
        raise BlueprintError(
            f"No {pattern.exam} section covers the requested subjects/chapters/topics."
        )

    # Choice-based exams (CUET) are sat one subject paper at a time.
    if pattern.section_choice and len(selected) > pattern.section_choice and not request.subjects:
        raise BlueprintError(
            f"{pattern.exam} is written as one paper per subject. Specify which "
            f"subject(s) you want: {', '.join(pattern.subjects)}."
        )

    if request.is_full_syllabus and len(selected) > 1:
        notes.append(
            "Full-syllabus paper: questions are distributed across sections in "
            "proportion to the official pattern."
        )
    return selected


def _section_weights(
    sections: list[SectionSpec], request: GenerationRequest, notes: list[str]
) -> list[float]:
    """Per-section weights: the official proportions unless overridden.

    A subject-weightage override applies at the *subject* level, so it is split
    across that subject's sections in their official ratio -- otherwise
    overriding "Physics" on JEE Main would silently rebalance its MCQ and
    numerical sections against each other.
    """
    official = [float(s.questions) for s in sections]
    if not request.subject_weightage:
        return official

    totals: dict[str, float] = {}
    for section, weight in zip(sections, official):
        totals[_norm(section.subject)] = totals.get(_norm(section.subject), 0.0) + weight

    out: list[float] = []
    for section, weight in zip(sections, official):
        key = _norm(section.subject)
        override = next(
            (v for k, v in request.subject_weightage.items() if _norm(k) == key), None
        )
        if override is None:
            out.append(weight)
            continue
        share = weight / totals[key] if totals[key] else 1.0
        out.append(override * share)

    notes.append(
        "Subject weightage was overridden, so section sizes do not match the official pattern."
    )
    return out


def _chapters_for_section(section: SectionSpec, request: GenerationRequest) -> list[ChapterSpec]:
    """Restrict a section's chapters to whatever the request narrowed it to."""
    if request.chapters:
        wanted = {_norm(c) for c in request.chapters}
        chosen = [c for c in section.chapters if _norm(c.name) in wanted]
        if chosen:
            return chosen
    if request.topics:
        chosen = [c for c in section.chapters if any(c.has_topic(t) for t in request.topics)]
        if chosen:
            return chosen
    return list(section.chapters)


def _chapter_weights(request: GenerationRequest) -> dict[str, float]:
    """Per-chapter blueprint weights.

    Most modes honour the official syllabus weighting so the paper stays
    representative. Two deliberately do not: ``Adaptive`` leans into weak
    chapters, and ``Revision`` splits roughly 60/40 weak-to-general per Step 6.
    Both require history; with none, both fall back to the official weighting and
    the request records that no personalisation happened.
    """
    if request.history.is_empty:
        return {}

    if request.test_type is TestType.ADAPTIVE:
        weights: dict[str, float] = {}
        for name, tally in request.history.weak_chapters(limit=12):
            # The weaker the chapter, the larger its share.
            shortfall = 1.0 - (tally.accuracy or 0.0)
            weights[_norm(name)] = 1.0 + _ADAPTIVE_WEAK_BOOST * shortfall
        for name, _ in request.history.strong_chapters(limit=12):
            weights.setdefault(_norm(name), _ADAPTIVE_STRONG_DAMP)
        return weights

    if request.test_type is TestType.REVISION:
        return _revision_weights(request)

    return {}


def _revision_weights(request: GenerationRequest) -> dict[str, float]:
    """Step 6: about 60% of the paper on flagged weak topics, 40% general.

    Expressed as weights rather than counts so it composes with the existing
    apportionment: each weak chapter is scaled so the weak group collectively
    claims ``REVISION_WEAK_SHARE`` of the total weight.
    """
    weak = request.history.weak_chapters(limit=10)
    if not weak:
        return {}

    scope = {_norm(c) for c in request.chapters} if request.chapters else None
    weak_names = [
        _norm(name) for name, _ in weak if scope is None or _norm(name) in scope
    ]
    if not weak_names:
        return {}

    # Every in-scope chapter carries weight 1.0 by default; give the weak ones
    # enough extra that they hold the target share of the whole.
    total_chapters = len(request.chapters) or len(
        request.pattern.chapters_for(request.subjects[0] if request.subjects else None)
    )
    general_count = max(1, total_chapters - len(weak_names))
    general_weight = float(general_count)
    target = REVISION_WEAK_SHARE
    # weak_total / (weak_total + general_weight) == target
    weak_total = (target * general_weight) / max(1e-9, 1.0 - target)
    per_weak = weak_total / len(weak_names)
    return {name: per_weak for name in weak_names}


def _topics_for(
    chapter: ChapterSpec, request: GenerationRequest, count: int, rng: random.Random
) -> list[str]:
    """Spread ``count`` questions across a chapter's topics without repetition
    until every topic has been used once."""
    pool = list(chapter.topics)
    if request.topics:
        narrowed = [t for t in pool if any(_norm(t) == _norm(r) for r in request.topics)]
        if narrowed:
            pool = narrowed
    if not pool:
        # A chapter with no topic breakdown still needs a label.
        return [chapter.name] * count

    chosen: list[str] = []
    while len(chosen) < count:
        cycle = pool[:]
        rng.shuffle(cycle)
        chosen.extend(cycle[: count - len(chosen)])
    return chosen


def _question_types_for(
    section: SectionSpec, request: GenerationRequest
) -> tuple[QuestionType, ...]:
    if request.question_types:
        allowed = tuple(q for q in request.question_types if q in section.question_types)
        if allowed:
            return allowed
        # The caller asked for types this section does not use; fall back to the
        # official types rather than producing an off-pattern paper.
        return section.question_types
    return section.question_types or (QuestionType.MCQ_SINGLE,)


# ----------------------------------------------------------------- difficulty


def _difficulty_sequence(
    count: int, request: GenerationRequest, rng: random.Random
) -> list[Difficulty]:
    """Build the exact difficulty list for one section, then interleave it."""
    # An explicit distribution override wins over everything, including a single
    # requested difficulty -- it is the more specific instruction.
    if request.difficulty_distribution:
        mix = dict(request.difficulty_distribution)
    elif request.difficulty is not Difficulty.MIXED:
        return [request.difficulty] * count
    else:
        mix = dict(request.pattern.difficulty_mix)
        if request.test_type is TestType.ADAPTIVE and not request.history.is_empty:
            mix = _adapted_mix(mix, request)

    order = [Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD]
    counts = _allocate(count, [float(mix.get(d, 0.0)) for d in order])
    sequence = [d for d, n in zip(order, counts) for _ in range(n)]
    rng.shuffle(sequence)
    return sequence


def _adapted_mix(
    mix: Mapping[Difficulty, float], request: GenerationRequest
) -> dict[Difficulty, float]:
    """Shift the difficulty spread toward the student's demonstrated level.

    Deliberately conservative: one step in either direction, never a jump from
    mostly-easy to mostly-hard on the strength of a single attempt.
    """
    accuracy = request.history.overall_accuracy()
    if accuracy is None:
        return dict(mix)

    adapted = dict(mix)
    if accuracy >= 0.80:
        shift = min(0.15, adapted.get(Difficulty.EASY, 0.0))
        adapted[Difficulty.EASY] = adapted.get(Difficulty.EASY, 0.0) - shift
        adapted[Difficulty.HARD] = adapted.get(Difficulty.HARD, 0.0) + shift
    elif accuracy < 0.50:
        shift = min(0.15, adapted.get(Difficulty.HARD, 0.0))
        adapted[Difficulty.HARD] = adapted.get(Difficulty.HARD, 0.0) - shift
        adapted[Difficulty.EASY] = adapted.get(Difficulty.EASY, 0.0) + shift
    return adapted


# ------------------------------------------------------------------- helpers


def _allocate(total: int, weights: Sequence[float]) -> list[int]:
    """Split ``total`` across ``weights`` so the parts sum exactly to ``total``.

    Largest-remainder (Hare-Niemeyer) apportionment, then a coverage pass: any
    positive weight that rounded down to zero is topped up to one by taking a
    unit from the largest bucket, provided there is room.

    Order matters. Seeding every bucket with one unit *before* apportioning would
    distort the proportions — on JEE Main's 20/5 section split that alone moved
    three questions out of Section A and into Section B.
    """
    n = len(weights)
    if n == 0 or total <= 0:
        return [0] * n

    positive = [i for i, w in enumerate(weights) if w > 0]
    if not positive:
        # No weighting information: spread as evenly as possible.
        base, extra = divmod(total, n)
        return [base + (1 if i < extra else 0) for i in range(n)]

    # Too few units to touch every bucket: cover the heaviest ones.
    if total < len(positive):
        ranked = set(sorted(positive, key=lambda i: (-weights[i], i))[:total])
        return [1 if i in ranked else 0 for i in range(n)]

    counts = [0] * n
    pool = sum(weights[i] for i in positive)
    shares = {i: (weights[i] / pool) * total for i in positive}
    for i, share in shares.items():
        counts[i] = int(share)

    leftover = total - sum(counts)
    if leftover > 0:
        remainders = sorted(
            ((i, shares[i] - int(shares[i])) for i in positive),
            key=lambda item: (-item[1], item[0]),
        )
        for i, _ in remainders[:leftover]:
            counts[i] += 1

    # Coverage pass: nothing with a positive weight should be silently dropped.
    for i in (j for j in positive if counts[j] == 0):
        donor = max(
            (j for j in positive if counts[j] > 1), key=lambda j: counts[j], default=None
        )
        if donor is None:
            break
        counts[donor] -= 1
        counts[i] += 1

    return counts


def _tally(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts
