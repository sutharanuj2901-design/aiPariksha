"""The generation request: parse, validate, and refuse to guess.

Three rules drive this module:

1. **Each generator mode has its own required inputs.** A full mock covers the
   whole official pattern and takes *no* subject or topic selection — if one is
   passed anyway it is ignored, not honoured. A topic-wise drill, at the other
   end, requires subject, chapter and topic. The table in ``_MODES`` is the
   single source of truth for this.
2. **Never assume a required input.** Ask via ``ClarificationNeeded``, and ask
   only about what is missing — never about optional inputs.
3. **Be transparent about what *was* derived.** Anything filled in from the
   official pattern is recorded in ``defaults_applied`` and echoed back, so a
   student always knows what they did not choose themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..errors import ClarificationNeeded, SyllabusError, ValidationError
from ..exams import registry
from ..exams.base import ExamPattern, _norm
from .enums import BloomLevel, Difficulty, Language, QuestionType, SolutionDepth, TestType
from .history import StudentHistory


@dataclass(frozen=True, slots=True)
class ModeRule:
    """What one generator mode needs, and how it treats syllabus scope."""

    #: Required inputs, as internal field names.
    needs: tuple[str, ...] = ()
    #: True for whole-paper modes: any subject/chapter/topic selection passed in
    #: is discarded so the paper covers the full official pattern regardless.
    ignores_scope: bool = False
    #: Question count can be taken from the official paper length.
    count_from_pattern: bool = False
    #: Compact output (title, topic tag, questions, answer key).
    compact: bool = False
    label: str = ""


_MODES: Mapping[TestType, ModeRule] = {
    TestType.FULL_MOCK: ModeRule(
        ignores_scope=True, count_from_pattern=True, label="Full Mock Test"
    ),
    TestType.PREVIOUS_YEAR_PATTERN: ModeRule(
        needs=("reference_years",),
        ignores_scope=True,
        count_from_pattern=True,
        label="Previous-Year-Pattern Paper",
    ),
    TestType.SECTIONAL: ModeRule(needs=("subjects",), label="Sectional Test"),
    TestType.CHAPTER_WISE: ModeRule(
        needs=("subjects", "chapters", "num_questions"), label="Chapter Test"
    ),
    TestType.TOPIC_WISE: ModeRule(
        needs=("subjects", "chapters", "topics", "num_questions"),
        compact=True,
        label="Topic Test",
    ),
    TestType.REVISION: ModeRule(needs=("covered_scope",), label="Revision Paper"),
    TestType.ADAPTIVE: ModeRule(
        needs=("subjects", "starting_difficulty", "length"), label="Adaptive Test"
    ),
}

#: The question the engine asks when a required input is missing.
_PROMPTS: Mapping[str, str] = {
    "subjects": "Which subject should this test cover?",
    "chapters": "Which chapter(s) should it cover?",
    "topics": "Which specific topic should it drill?",
    "num_questions": (
        "How many questions should this test contain? There is no official length "
        "for a partial-syllabus test, so I will not pick one for you."
    ),
    "reference_years": (
        "Which past year's pattern should this paper follow? Give the year, for "
        "example 2023."
    ),
    "covered_scope": (
        "Which subjects or chapters have you already studied? A revision paper "
        "only covers ground you have actually been over."
    ),
    "starting_difficulty": (
        "What difficulty should the adaptive test start at - Easy, Medium or Hard?"
    ),
    "length": (
        "How many questions should the adaptive test run for? Alternatively say "
        "'until stable estimate' and it will stop once your level is clear."
    ),
}

#: Revision papers weight this share of questions toward flagged weak topics.
REVISION_WEAK_SHARE = 0.60


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """A fully-resolved, validated instruction to build one paper."""

    pattern: ExamPattern
    test_type: TestType
    num_questions: int
    time_limit_minutes: int
    difficulty: Difficulty
    language: Language
    solution_depth: SolutionDepth
    negative_marking: bool
    subjects: tuple[str, ...] = ()
    chapters: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    question_types: tuple[QuestionType, ...] = ()
    bloom_level: BloomLevel | None = None
    custom_instructions: str = ""
    pattern_version: str = ""
    history: StudentHistory = field(default_factory=StudentHistory)
    defaults_applied: tuple[str, ...] = ()
    #: Notes the student must see (pattern-drift warnings, personalisation split).
    advisories: tuple[str, ...] = ()
    seed: int | None = None
    title: str = ""
    #: Step 7: the past year(s) whose pattern this paper imitates.
    reference_years: tuple[str, ...] = ()
    #: Step 8: where an adaptive test begins, and whether it may stop early.
    starting_difficulty: Difficulty | None = None
    until_stable: bool = False
    #: Optional overrides. Empty means "use the official pattern".
    subject_weightage: Mapping[str, float] = field(default_factory=dict)
    difficulty_distribution: Mapping[Difficulty, float] = field(default_factory=dict)

    @property
    def exam(self) -> str:
        return self.pattern.exam

    @property
    def rule(self) -> ModeRule:
        return _MODES.get(self.test_type, ModeRule())

    @property
    def is_full_syllabus(self) -> bool:
        return not self.chapters and not self.topics

    @property
    def compact_output(self) -> bool:
        return self.rule.compact

    @property
    def wants_solutions(self) -> bool:
        return self.solution_depth in (SolutionDepth.BRIEF, SolutionDepth.DETAILED)

    @property
    def wants_answer_key(self) -> bool:
        return self.solution_depth is not SolutionDepth.NONE

    def effective_subjects(self) -> tuple[str, ...]:
        return self.subjects or self.pattern.subjects

    def to_dict(self) -> dict[str, Any]:
        return {
            "exam": self.exam,
            "pattern_version": self.pattern_version or self.pattern.pattern_version,
            "test_type": str(self.test_type),
            "subjects": list(self.effective_subjects()),
            "chapters": list(self.chapters),
            "topics": list(self.topics),
            "difficulty": str(self.difficulty),
            "num_questions": self.num_questions,
            "time_limit_minutes": self.time_limit_minutes,
            "language": str(self.language),
            "question_types": [str(q) for q in self.question_types],
            "negative_marking": self.negative_marking,
            "solutions": str(self.solution_depth),
            "bloom_level": str(self.bloom_level) if self.bloom_level else None,
            "custom_instructions": self.custom_instructions,
            "full_syllabus": self.is_full_syllabus,
            "compact_output": self.compact_output,
            "reference_years": list(self.reference_years),
            "starting_difficulty": str(self.starting_difficulty) if self.starting_difficulty else None,
            "until_stable": self.until_stable,
            "subject_weightage": dict(self.subject_weightage),
            "difficulty_distribution": {str(k): v for k, v in self.difficulty_distribution.items()},
            "seed": self.seed,
            "defaults_applied": list(self.defaults_applied),
            "advisories": list(self.advisories),
            "history_supplied": not self.history.is_empty,
        }

    # ------------------------------------------------------------------ parsing

    @classmethod
    def from_dict(cls, raw: Any) -> "GenerationRequest":
        if not isinstance(raw, Mapping):
            raise ValidationError("Request body must be a JSON object.")

        defaults: list[str] = []
        advisories: list[str] = []

        pattern = _resolve_pattern(raw)
        pattern_version = str(_first(raw, "pattern_version", "exam_year", "year") or "").strip()
        if not pattern_version:
            pattern_version = pattern.pattern_version
            defaults.append(f"pattern_version set to the latest known scheme ({pattern_version})")

        history = StudentHistory.from_dict(
            _first(raw, "student_history", "history", "performance_history")
        )

        # --- scope, before we know whether this mode wants it ----------------
        raw_subjects = _as_list(raw, "subjects", "subject")
        raw_chapters = _as_list(raw, "chapters", "chapter")
        raw_topics = _as_list(raw, "topics", "topic")

        test_type = _resolve_test_type(raw, raw_chapters, raw_topics, defaults)
        rule = _MODES.get(test_type, ModeRule())

        if rule.ignores_scope and (raw_subjects or raw_chapters or raw_topics):
            # Step 3: a full-syllabus paper covers the official pattern no matter
            # what scope the caller sends. Discard rather than half-honour it.
            defaults.append(
                f"a {test_type} paper covers the full official pattern, so the "
                "subject/chapter/topic selection you sent was ignored"
            )
            raw_subjects = raw_chapters = raw_topics = ()

        subjects = _resolve_subjects(pattern, raw_subjects)
        chapters = _resolve_chapters(pattern, raw_chapters, subjects)
        topics = _resolve_topics(pattern, raw_topics, subjects)

        if not subjects and (chapters or topics) and not rule.ignores_scope:
            implied = _implied_subjects(pattern, chapters, topics)
            if implied:
                subjects = implied
                defaults.append(
                    f"subjects inferred from your selection: {', '.join(implied)}"
                )

        # --- mode-specific extras --------------------------------------------
        reference_years = _as_list(raw, "reference_years", "reference_year", "past_year")
        if reference_years:
            _check_years(reference_years)
            advisories.extend(_year_advisories(pattern, reference_years))

        starting_raw = _first(raw, "starting_difficulty", "start_difficulty")
        starting_difficulty = (
            Difficulty.parse(starting_raw, "starting_difficulty") if _present(starting_raw) else None
        )
        if starting_difficulty is Difficulty.MIXED:
            raise ValidationError(
                "starting_difficulty must be Easy, Medium or Hard - an adaptive test "
                "begins at one level and moves from there.",
                field="starting_difficulty",
            )

        until_stable = _wants_stable(raw)

        # --- question count ---------------------------------------------------
        num_raw = _first(raw, "num_questions", "number_of_questions", "question_count")
        num_questions = 0
        if _present(num_raw):
            num_questions = _positive_int(num_raw, "num_questions")
        elif rule.count_from_pattern:
            num_questions = pattern.total_questions
            defaults.append(f"num_questions set to the official paper length ({num_questions})")
        elif test_type is TestType.SECTIONAL and subjects:
            num_questions = sum(
                s.questions for subject in subjects for s in pattern.sections_for_subject(subject)
            )
            defaults.append(
                f"num_questions set to the official section length ({num_questions})"
            )
        elif test_type is TestType.REVISION and (chapters or subjects):
            # Derived from what the student says they have covered, not invented.
            basis = len(chapters) if chapters else len(subjects)
            unit = "chapter" if chapters else "subject"
            per = 3 if chapters else 12
            num_questions = max(10, min(pattern.total_questions, basis * per))
            defaults.append(
                f"num_questions set to {num_questions} from the {basis} {unit}(s) you have covered"
            )
        elif test_type is TestType.ADAPTIVE and until_stable:
            num_questions = min(40, pattern.total_questions)
            defaults.append(
                f"adaptive test capped at {num_questions} questions; it will stop earlier "
                "once your level is clear"
            )

        # --- collect every missing requirement, then ask once -----------------
        missing = _missing_fields(
            rule,
            subjects=subjects,
            chapters=chapters,
            topics=topics,
            num_questions=num_questions,
            reference_years=reference_years,
            starting_difficulty=starting_difficulty,
            until_stable=until_stable,
        )
        if test_type is TestType.ADAPTIVE and history.is_empty and "starting_difficulty" not in missing:
            # Step 8 takes a starting difficulty rather than assuming a level, so
            # an empty history is fine here as long as that was supplied.
            advisories.append(
                "No previous performance was supplied, so this adaptive test starts from "
                f"the {starting_difficulty} level you chose and calibrates as you answer."
            )
        if missing:
            raise ClarificationNeeded(
                [_prompt_for(field_name, pattern, subjects) for field_name in missing],
                missing_fields=list(missing),
            )

        if num_questions > 300:
            raise ValidationError(
                "num_questions is capped at 300 per paper to keep generation reliable; "
                "split larger requirements into multiple papers.",
                field="num_questions",
            )

        # --- timing -----------------------------------------------------------
        time_raw = _first(raw, "time_limit_minutes", "time_limit", "duration_minutes")
        if _present(time_raw):
            time_limit = _positive_int(time_raw, "time_limit_minutes")
        else:
            per_question = pattern.total_time_minutes / max(pattern.total_questions, 1)
            time_limit = max(1, round(per_question * num_questions))
            defaults.append(
                f"time_limit_minutes set to {time_limit} using the official pace of "
                f"{per_question:.2f} min/question"
            )

        # --- preferences and overrides ----------------------------------------
        difficulty_raw = _first(raw, "difficulty", "difficulty_level")
        if _present(difficulty_raw):
            difficulty = Difficulty.parse(difficulty_raw, "difficulty")
        elif test_type is TestType.REVISION:
            difficulty = Difficulty.MEDIUM
            defaults.append("difficulty defaulted to Medium, which suits a revision paper")
        else:
            difficulty = Difficulty.MIXED
            defaults.append("difficulty defaulted to Mixed, which mirrors the real exam spread")

        language = _resolve_language(raw, pattern, defaults)
        solution_depth = _resolve_solutions(raw, rule, defaults)
        qtypes = _resolve_question_types(raw, pattern, subjects, defaults)

        neg_raw = _first(raw, "negative_marking")
        if neg_raw is None:
            negative_marking = pattern.negative_marking_default
            defaults.append(
                f"negative_marking taken from the official pattern "
                f"({'on' if negative_marking else 'off'})"
            )
        else:
            negative_marking = _as_bool(neg_raw, "negative_marking")

        weightage = _resolve_weightage(raw, pattern, advisories)
        distribution = _resolve_distribution(raw, advisories)

        if test_type is TestType.REVISION:
            advisories.append(_revision_note(history, chapters))

        bloom_raw = _first(raw, "bloom_level", "blooms_taxonomy_level", "bloom")
        bloom = BloomLevel.parse(bloom_raw, "bloom_level") if _present(bloom_raw) else None
        seed_raw = _first(raw, "seed")

        return cls(
            pattern=pattern,
            test_type=test_type,
            num_questions=num_questions,
            time_limit_minutes=time_limit,
            difficulty=difficulty,
            language=language,
            solution_depth=solution_depth,
            negative_marking=negative_marking,
            subjects=subjects,
            chapters=chapters,
            topics=topics,
            question_types=qtypes,
            bloom_level=bloom,
            custom_instructions=str(_first(raw, "custom_instructions", "instructions") or "").strip(),
            pattern_version=pattern_version,
            history=history,
            defaults_applied=tuple(defaults),
            advisories=tuple(a for a in advisories if a),
            seed=_positive_int(seed_raw, "seed") if _present(seed_raw) else None,
            title=str(_first(raw, "title", "test_title") or "").strip(),
            reference_years=reference_years,
            starting_difficulty=starting_difficulty,
            until_stable=until_stable,
            subject_weightage=weightage,
            difficulty_distribution=distribution,
        )


# ------------------------------------------------------------- mode resolution


def _resolve_pattern(raw: Mapping[str, Any]) -> ExamPattern:
    exam_raw = _first(raw, "exam", "exam_name")
    if not _present(exam_raw):
        raise ClarificationNeeded(
            [
                "Which exam are you preparing for? Supported exams: "
                f"{', '.join(registry.supported_names())}."
            ],
            missing_fields=["exam"],
        )
    pattern = registry.get(str(exam_raw))
    if not pattern.is_supported:
        raise ValidationError(
            f"{pattern.exam} is registered as '{pattern.status}' and cannot generate papers "
            f"yet. {pattern.notes}",
            field="exam",
        )
    return pattern


def _resolve_test_type(
    raw: Mapping[str, Any],
    chapters: tuple[str, ...],
    topics: tuple[str, ...],
    defaults: list[str],
) -> TestType:
    explicit = _first(raw, "test_type", "type", "paper_type", "mode")
    if _present(explicit):
        return TestType.parse(explicit, "test_type")
    if topics:
        defaults.append("test_type inferred as Topic Wise because topics were supplied")
        return TestType.TOPIC_WISE
    if chapters:
        defaults.append("test_type inferred as Chapter Wise because chapters were supplied")
        return TestType.CHAPTER_WISE
    defaults.append("test_type defaulted to Full Mock covering the full official pattern")
    return TestType.FULL_MOCK


def _missing_fields(rule: ModeRule, **supplied: Any) -> tuple[str, ...]:
    """Which of this mode's required inputs are absent."""
    missing: list[str] = []
    for name in rule.needs:
        if name == "covered_scope":
            if not supplied.get("chapters") and not supplied.get("subjects"):
                missing.append(name)
            continue
        if name == "length":
            if not supplied.get("num_questions") and not supplied.get("until_stable"):
                missing.append(name)
            continue
        if not supplied.get(name):
            missing.append(name)
    return tuple(missing)


def _prompt_for(field_name: str, pattern: ExamPattern, subjects: tuple[str, ...]) -> str:
    prompt = _PROMPTS.get(field_name, f"Please supply {field_name}.")
    if field_name == "subjects":
        return f"{prompt} Available: {', '.join(pattern.subjects)}."
    if field_name == "chapters":
        return f"{prompt} For example: {_sample_names(pattern, subjects)}."
    return prompt


def _implied_subjects(
    pattern: ExamPattern, chapters: tuple[str, ...], topics: tuple[str, ...]
) -> tuple[str, ...]:
    implied: list[str] = []
    for name in chapters:
        hit = pattern.find_chapter(name)
        if hit and hit[0] not in implied:
            implied.append(hit[0])
    for name in topics:
        hit = pattern.find_topic(name)
        if hit and hit[0] not in implied:
            implied.append(hit[0])
    return tuple(implied)


# ------------------------------------------------------------- field resolvers


def _resolve_language(
    raw: Mapping[str, Any], pattern: ExamPattern, defaults: list[str]
) -> Language:
    value = _first(raw, "language", "medium")
    if not _present(value):
        defaults.append("language defaulted to English")
        return Language.ENGLISH
    language = Language.parse(value, "language")
    if language not in pattern.languages:
        raise ValidationError(
            f"{pattern.exam} is modelled for "
            f"{', '.join(str(l) for l in pattern.languages)}; {language} is not available.",
            field="language",
        )
    return language


def _resolve_solutions(
    raw: Mapping[str, Any], rule: ModeRule, defaults: list[str]
) -> SolutionDepth:
    value = _first(raw, "solutions", "solution_preference", "solution_depth")
    if _present(value):
        return _parse_solution_depth(value)
    if rule.compact:
        # Step 5: a quick drill ships the answer key, not full write-ups.
        defaults.append("solutions defaulted to Answer Key for this compact drill")
        return SolutionDepth.ANSWER_KEY
    defaults.append("solutions defaulted to Detailed")
    return SolutionDepth.DETAILED


def _resolve_question_types(
    raw: Mapping[str, Any],
    pattern: ExamPattern,
    subjects: tuple[str, ...],
    defaults: list[str],
) -> tuple[QuestionType, ...]:
    qtypes = tuple(
        QuestionType.parse(v, "question_types")
        for v in _as_list(raw, "question_types", "question_type")
    )
    if not qtypes:
        defaults.append("question_types taken from the official section-wise pattern")
        return ()
    allowed = _allowed_question_types(pattern, subjects)
    for qtype in qtypes:
        if qtype not in allowed:
            raise ValidationError(
                f"{qtype} is not part of the {pattern.exam} pattern for the selected "
                f"subjects. Allowed: {', '.join(str(a) for a in allowed)}.",
                field="question_types",
            )
    return qtypes


def _resolve_weightage(
    raw: Mapping[str, Any], pattern: ExamPattern, advisories: list[str]
) -> dict[str, float]:
    """Optional per-subject weight override (Step 3)."""
    value = _first(raw, "subject_weightage", "subject_weights", "weightage")
    if not _present(value):
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError(
            "subject_weightage must be an object mapping subject names to weights.",
            field="subject_weightage",
        )
    out: dict[str, float] = {}
    for name, weight in value.items():
        canonical = pattern.resolve_subject(str(name))
        if canonical is None:
            raise SyllabusError(
                f"{name!r} is not a subject in {pattern.exam}. "
                f"Available: {', '.join(pattern.subjects)}.",
                field="subject_weightage",
            )
        parsed = _non_negative_float(weight, f"subject_weightage.{name}")
        if parsed > 0:
            out[canonical] = parsed
    if not out:
        raise ValidationError(
            "subject_weightage must give at least one subject a positive weight.",
            field="subject_weightage",
        )
    advisories.append(
        "You overrode the official subject weightage, so this paper is deliberately "
        "not proportional to the real exam."
    )
    return out


def _resolve_distribution(
    raw: Mapping[str, Any], advisories: list[str]
) -> dict[Difficulty, float]:
    """Optional Easy/Medium/Hard split override."""
    value = _first(raw, "difficulty_distribution", "difficulty_mix")
    if not _present(value):
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError(
            "difficulty_distribution must be an object like "
            '{"Easy": 0.3, "Medium": 0.5, "Hard": 0.2}.',
            field="difficulty_distribution",
        )
    out: dict[Difficulty, float] = {}
    for name, share in value.items():
        level = Difficulty.parse(name, "difficulty_distribution")
        if level is Difficulty.MIXED:
            raise ValidationError(
                "difficulty_distribution takes Easy, Medium and Hard, not Mixed.",
                field="difficulty_distribution",
            )
        out[level] = _non_negative_float(share, f"difficulty_distribution.{name}")
    total = sum(out.values())
    if total <= 0:
        raise ValidationError(
            "difficulty_distribution must contain at least one positive share.",
            field="difficulty_distribution",
        )
    # Accept percentages or fractions by normalising.
    normalised = {level: share / total for level, share in out.items()}
    advisories.append(
        "You overrode the difficulty curve, so this paper does not follow the exam's "
        "usual spread."
    )
    return normalised


def _revision_note(history: StudentHistory, chapters: tuple[str, ...]) -> str:
    """Step 6: state the split, and never claim personalisation without data."""
    if history.is_empty:
        return (
            "No previous performance data is available, so this is a balanced revision "
            "paper across what you have covered - it is not personalised."
        )
    weak = history.weak_chapters(limit=8)
    if not weak:
        return (
            "Your history shows no chapter below the weakness threshold, so this "
            "revision paper is balanced across everything you have covered."
        )
    names = ", ".join(name for name, _ in weak[:4])
    return (
        f"Personalised from your history: about {int(REVISION_WEAK_SHARE * 100)}% of the "
        f"questions target your flagged weak topics ({names}) and the remaining "
        f"{100 - int(REVISION_WEAK_SHARE * 100)}% is general revision."
    )


def _year_advisories(pattern: ExamPattern, years: tuple[str, ...]) -> list[str]:
    """Step 7: flag drift rather than inventing a past year's specifics."""
    notes = [
        f"Pattern Reference: {', '.join(years)}. These are newly written questions in that "
        "year's style and difficulty - not actual past-paper questions."
    ]
    current = _leading_year(pattern.pattern_version)
    for year in years:
        parsed = _leading_year(year)
        if current and parsed and current - parsed >= 3:
            notes.append(
                f"The {year} pattern is several cycles behind the {pattern.pattern_version} "
                "scheme modelled here, and the syllabus or marking may have changed since. "
                "Verify against the official notification before relying on the structure."
            )
            break
    return notes


def _leading_year(text: str) -> int | None:
    digits = ""
    for char in str(text):
        if char.isdigit():
            digits += char
            if len(digits) == 4:
                return int(digits)
        elif digits:
            break
    return None


def _check_years(years: tuple[str, ...]) -> None:
    for year in years:
        parsed = _leading_year(year)
        if parsed is None or not (1990 <= parsed <= 2100):
            raise ValidationError(
                f"{year!r} is not a usable reference year. Give a four-digit year, e.g. 2023.",
                field="reference_years",
            )


def _wants_stable(raw: Mapping[str, Any]) -> bool:
    if _as_bool_or_none(raw.get("until_stable")) is True:
        return True
    for key in ("num_questions", "number_of_questions", "length", "question_count"):
        value = raw.get(key)
        if isinstance(value, str) and "stable" in value.lower():
            return True
    return False


# --------------------------------------------------------------------- helpers


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _first(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and _present(raw[key]):
            return raw[key]
    return None


def _as_list(raw: Mapping[str, Any], *keys: str) -> tuple[str, ...]:
    value = _first(raw, *keys)
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, (int, float)):
        parts = [str(value)]
    elif isinstance(value, Sequence):
        parts = [str(p).strip() for p in value]
    else:
        raise ValidationError(f"{keys[0]}: expected a string or list of strings.", field=keys[0])
    seen: dict[str, None] = {}
    for part in parts:
        if part:
            seen.setdefault(part, None)
    return tuple(seen)


def _as_bool_or_none(value: Any) -> bool | None:
    try:
        return _as_bool(value, "flag") if value is not None else None
    except ValidationError:
        return None


def _as_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "on", "1"}:
            return True
        if lowered in {"false", "no", "n", "off", "0"}:
            return False
    raise ValidationError(f"{field_name}: expected a boolean.", field=field_name)


def _positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"{field_name}: expected an integer, got {value!r}.", field=field_name
        ) from None
    if parsed <= 0:
        raise ValidationError(f"{field_name}: must be greater than zero.", field=field_name)
    return parsed


def _non_negative_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"{field_name}: expected a number, got {value!r}.", field=field_name
        ) from None
    if parsed < 0:
        raise ValidationError(f"{field_name}: cannot be negative.", field=field_name)
    return parsed


def _parse_solution_depth(value: Any) -> SolutionDepth:
    if isinstance(value, bool):
        return SolutionDepth.DETAILED if value else SolutionDepth.NONE
    text = str(value).strip().lower()
    shorthand = {
        "": SolutionDepth.DETAILED,
        "full": SolutionDepth.DETAILED,
        "detailed": SolutionDepth.DETAILED,
        "step by step": SolutionDepth.DETAILED,
        "step-by-step": SolutionDepth.DETAILED,
        "short": SolutionDepth.BRIEF,
        "brief": SolutionDepth.BRIEF,
        "answers only": SolutionDepth.ANSWER_KEY,
        "answer key": SolutionDepth.ANSWER_KEY,
        "key": SolutionDepth.ANSWER_KEY,
        "none": SolutionDepth.NONE,
        "no": SolutionDepth.NONE,
    }
    if text in shorthand:
        return shorthand[text]
    return SolutionDepth.parse(value, "solutions")


def _resolve_subjects(pattern: ExamPattern, names: tuple[str, ...]) -> tuple[str, ...]:
    resolved: list[str] = []
    for name in names:
        canonical = pattern.resolve_subject(name)
        if canonical is None:
            raise SyllabusError(
                f"{name!r} is not a subject in the {pattern.exam} pattern. "
                f"Available subjects: {', '.join(pattern.subjects)}.",
                field="subjects",
            )
        if canonical not in resolved:
            resolved.append(canonical)
    return tuple(resolved)


def _resolve_chapters(
    pattern: ExamPattern, names: tuple[str, ...], subjects: tuple[str, ...]
) -> tuple[str, ...]:
    resolved: list[str] = []
    for name in names:
        hit = None
        for subject in subjects or (None,):
            hit = pattern.find_chapter(name, subject)
            if hit:
                break
        if hit is None:
            raise SyllabusError(
                f"{name!r} is not a chapter in the {pattern.exam} syllabus"
                + (f" for {', '.join(subjects)}" if subjects else "")
                + f". Try one of: {_sample_names(pattern, subjects)}.",
                field="chapters",
            )
        if hit[1].name not in resolved:
            resolved.append(hit[1].name)
    return tuple(resolved)


def _resolve_topics(
    pattern: ExamPattern, names: tuple[str, ...], subjects: tuple[str, ...]
) -> tuple[str, ...]:
    resolved: list[str] = []
    for name in names:
        hit = None
        for subject in subjects or (None,):
            hit = pattern.find_topic(name, subject)
            if hit:
                break
        if hit is None:
            raise SyllabusError(
                f"{name!r} is not a topic in the {pattern.exam} syllabus"
                + (f" for {', '.join(subjects)}" if subjects else "")
                + ". Check the syllabus listing for the exact topic names.",
                field="topics",
            )
        if name not in resolved:
            resolved.append(name)
    return tuple(resolved)


def _allowed_question_types(
    pattern: ExamPattern, subjects: tuple[str, ...]
) -> tuple[QuestionType, ...]:
    allowed: dict[QuestionType, None] = {}
    for section in pattern.sections:
        if subjects and _norm(section.subject) not in {_norm(s) for s in subjects}:
            continue
        for qtype in section.question_types:
            allowed.setdefault(qtype, None)
    return tuple(allowed)


def _sample_names(pattern: ExamPattern, subjects: tuple[str, ...], limit: int = 6) -> str:
    names = [c.name for c in pattern.chapters_for(subjects[0] if subjects else None)]
    shown = names[:limit]
    suffix = f", ... (+{len(names) - limit} more)" if len(names) > limit else ""
    return ", ".join(shown) + suffix
