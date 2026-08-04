"""Rebuild domain objects from their JSON form.

Needed because the engine is stateless: a caller generates a paper, stores the
JSON, and later posts it back with a submission for grading. Round-tripping
through here keeps that flow lossless without the engine holding session state.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..errors import ValidationError
from .enums import BloomLevel, Difficulty, Language, QuestionType
from .paper import Option, Paper, PaperSection, Question, Solution


def paper_from_dict(raw: Any) -> Paper:
    """Reconstruct a ``Paper`` from ``Paper.to_dict(reveal=True)`` output.

    A paper serialised without ``reveal=True`` has no answers, so it can be
    reconstructed but not graded; that case raises when grading is attempted
    rather than silently marking everything wrong.
    """
    if not isinstance(raw, Mapping):
        raise ValidationError("paper: expected a JSON object.", field="paper")

    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ValidationError("paper.sections: expected a non-empty list.", field="paper.sections")

    sections: list[PaperSection] = []
    for section_index, section_raw in enumerate(sections_raw):
        if not isinstance(section_raw, Mapping):
            raise ValidationError(
                f"paper.sections[{section_index}]: expected an object.",
                field=f"paper.sections[{section_index}]",
            )
        questions_raw = section_raw.get("questions") or []
        if not isinstance(questions_raw, list):
            raise ValidationError(
                f"paper.sections[{section_index}].questions: expected a list.",
                field=f"paper.sections[{section_index}].questions",
            )
        questions = [
            _question_from_dict(q, section_raw.get("name", ""), section_raw.get("subject", ""), i)
            for i, q in enumerate(questions_raw)
        ]
        sections.append(
            PaperSection(
                name=str(section_raw.get("name") or f"Section {section_index + 1}"),
                subject=str(section_raw.get("subject") or ""),
                questions=questions,
                time_minutes=_opt_int(section_raw.get("time_minutes")),
                instructions=str(section_raw.get("instructions") or ""),
            )
        )

    return Paper(
        paper_id=str(raw.get("paper_id") or ""),
        exam=str(raw.get("exam") or ""),
        title=str(raw.get("test_title") or raw.get("title") or ""),
        pattern_version=str(raw.get("pattern_version") or ""),
        duration_minutes=_opt_int(raw.get("duration_minutes")) or 0,
        marking_scheme=str(raw.get("marking_scheme") or ""),
        sections=sections,
        instructions=tuple(str(i) for i in (raw.get("instructions") or [])),
        language=_parse_language(raw.get("language")),
        negative_marking=bool(raw.get("negative_marking", True)),
        request_summary=dict(raw.get("request") or {}),
        blueprint_summary=dict(raw.get("blueprint") or {}),
        generated_by=dict(raw.get("generated_by") or {}),
        disclaimers=tuple(str(d) for d in (raw.get("disclaimers") or [])),
        quality_report=dict(raw.get("quality_report") or {}),
    )


def has_answers(paper: Paper) -> bool:
    """Whether this paper carries enough information to be graded."""
    return any(q.correct_keys or q.correct_value is not None for q in paper.questions)


# --------------------------------------------------------------------- internals


def _question_from_dict(
    raw: Any, section_name: str, subject: str, position: int
) -> Question:
    if not isinstance(raw, Mapping):
        raise ValidationError(f"questions[{position}]: expected an object.")

    qtype = _parse_enum(QuestionType, raw.get("question_type"), QuestionType.MCQ_SINGLE)
    options = tuple(
        Option(
            key=str(o.get("key") or "").strip().upper()[:1],
            text=str(o.get("text") or ""),
            text_hi=str(o.get("text_hi") or ""),
        )
        for o in (raw.get("options") or [])
        if isinstance(o, Mapping)
    )

    # Numerical questions carry a value, never option keys. Deriving keys from
    # their 'correct_answer' string would turn an answer of "12" into key "1".
    keys: tuple[str, ...] = ()
    correct_value: float | None = None
    if qtype is QuestionType.NUMERICAL:
        correct_value = _opt_float(raw.get("correct_value"))
        if correct_value is None:
            correct_value = _opt_float(raw.get("correct_answer"))
    else:
        correct_keys = raw.get("correct_keys")
        if correct_keys is None:
            answer = raw.get("correct_answer")
            if isinstance(answer, str) and answer.strip():
                cleaned = answer.strip().upper().replace(" ", "")
                correct_keys = cleaned.split(",") if "," in cleaned else [cleaned]
        keys = tuple(
            str(k).strip().upper()[:1] for k in (correct_keys or []) if str(k).strip()
        )
        correct_value = _opt_float(raw.get("correct_value"))

    number = _opt_int(raw.get("number")) or (position + 1)
    return Question(
        number=number,
        section=str(raw.get("section") or section_name),
        subject=str(raw.get("subject") or subject),
        chapter=str(raw.get("chapter") or ""),
        topic=str(raw.get("topic") or ""),
        difficulty=_parse_enum(Difficulty, raw.get("difficulty"), Difficulty.MEDIUM),
        question_type=qtype,
        text=str(raw.get("text") or ""),
        text_hi=str(raw.get("text_hi") or ""),
        options=options,
        correct_keys=keys,
        correct_value=correct_value,
        tolerance=_opt_float(raw.get("tolerance")) or 0.0,
        marks=_opt_float(raw.get("marks")) or 0.0,
        negative_marks=_opt_float(raw.get("negative_marks")) or 0.0,
        partial_marks=_opt_float(raw.get("partial_marks")) or 0.0,
        bloom_level=_parse_enum(BloomLevel, raw.get("bloom_level"), None),
        solution=_solution_from_dict(raw.get("solution")),
        question_id=str(raw.get("question_id") or f"Q{number}"),
    )


def _solution_from_dict(raw: Any) -> Solution | None:
    if not isinstance(raw, Mapping):
        return None
    return Solution(
        correct_answer=str(raw.get("correct_answer") or ""),
        explanation=str(raw.get("explanation") or ""),
        steps=tuple(str(s) for s in (raw.get("steps") or [])),
        formula=str(raw.get("formula_used") or raw.get("formula") or ""),
        common_mistakes=tuple(str(s) for s in (raw.get("common_mistakes") or [])),
        time_saving_tip=str(raw.get("time_saving_tip") or ""),
        final_answer=str(raw.get("final_answer") or ""),
        concept_tested=str(raw.get("concept_tested") or ""),
    )


def _parse_enum(enum_cls: Any, value: Any, fallback: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback
    try:
        return enum_cls.parse(value, enum_cls.__name__)
    except ValueError:
        return fallback


def _parse_language(value: Any) -> Language:
    return _parse_enum(Language, value, Language.ENGLISH)


def _opt_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
