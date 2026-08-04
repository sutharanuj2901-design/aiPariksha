"""Registry, pattern integrity, and request validation."""

from __future__ import annotations

import pytest

from aipariksha.errors import ClarificationNeeded, SyllabusError, UnknownExamError, ValidationError
from aipariksha.exams import registry
from aipariksha.models.enums import Difficulty, Language, SolutionDepth, TestType
from aipariksha.models.request import GenerationRequest

EXPECTED_EXAMS = {
    "NEET UG",
    "JEE Main",
    "JEE Advanced",
    "CUET UG",
    "SSC CGL",
    "SSC CHSL",
    "SSC MTS",
    "SSC CPO",
    "IBPS PO",
    "IBPS Clerk",
    "SBI PO",
    "SBI Clerk",
    "RBI Assistant",
    "RRB NTPC",
    "RRB Group D",
    "Haryana CET",
    "UPSC Civil Services",
    "State PCS",
}


def test_every_advertised_exam_is_registered():
    assert {p.exam for p in registry.all_patterns()} == EXPECTED_EXAMS


def test_planned_exams_are_listed_but_not_generatable():
    planned = [p for p in registry.all_patterns() if not p.is_supported]
    assert {p.exam for p in planned} == {"UPSC Civil Services", "State PCS"}
    with pytest.raises(ValidationError, match="planned"):
        GenerationRequest.from_dict({"exam": "UPSC", "num_questions": 10})


@pytest.mark.parametrize("pattern", registry.all_patterns(), ids=lambda p: p.slug)
def test_pattern_is_internally_consistent(pattern):
    assert pattern.sections, f"{pattern.exam} has no sections"
    assert pattern.total_time_minutes > 0
    assert pattern.max_marks > 0
    assert abs(sum(pattern.difficulty_mix.values()) - 1.0) < 1e-6, "difficulty mix must sum to 1"
    for section in pattern.sections:
        assert section.questions > 0, f"{pattern.exam}/{section.name} has no questions"
        assert section.marks_correct > 0
        assert section.marks_incorrect <= 0, "penalty must be zero or negative"
        assert section.chapters, f"{pattern.exam}/{section.name} has no syllabus"
        for chapter in section.chapters:
            assert chapter.weight > 0
            assert chapter.topics, f"{chapter.name} has no topics"


def test_exam_lookup_is_forgiving():
    assert registry.get("neet").exam == "NEET UG"
    assert registry.get("NEET UG").exam == "NEET UG"
    assert registry.get("jee-main").exam == "JEE Main"
    assert registry.get("hssc cet").exam == "Haryana CET"
    with pytest.raises(UnknownExamError):
        registry.get("Kaun Banega Crorepati")


def test_new_exam_needs_no_core_changes():
    """The extensibility promise, exercised."""
    from aipariksha.exams.base import ExamPattern, SectionSpec, chapters

    pattern = ExamPattern(
        exam="Test Board Exam",
        slug="test-board",
        category="Testing",
        pattern_version="v1",
        total_time_minutes=60,
        sections=(
            SectionSpec(
                "Logic", "Logic", 20, 2.0, -0.5,
                chapters=chapters(("Propositions", ["Truth tables", "Negation"])),
            ),
        ),
    )
    registry.register(pattern, replace=True)
    try:
        request = GenerationRequest.from_dict({"exam": "Test Board Exam", "num_questions": 6})
        assert request.pattern.exam == "Test Board Exam"
        assert request.num_questions == 6
    finally:
        registry._REGISTRY.pop("test board exam", None)


# ------------------------------------------------------------------- requests


def test_missing_exam_asks_instead_of_guessing():
    with pytest.raises(ClarificationNeeded) as exc:
        GenerationRequest.from_dict({"num_questions": 10})
    assert "exam" in exc.value.missing_fields
    assert exc.value.questions


def test_chapter_test_without_chapters_asks():
    with pytest.raises(ClarificationNeeded) as exc:
        GenerationRequest.from_dict(
            {"exam": "NEET UG", "test_type": "Chapter Wise", "num_questions": 10}
        )
    assert "chapters" in exc.value.missing_fields


def test_partial_syllabus_test_without_count_asks():
    with pytest.raises(ClarificationNeeded) as exc:
        GenerationRequest.from_dict(
            {"exam": "NEET UG", "test_type": "Chapter Wise", "chapters": ["Kinematics"]}
        )
    assert "num_questions" in exc.value.missing_fields


def test_adaptive_test_without_history_asks():
    with pytest.raises(ClarificationNeeded) as exc:
        GenerationRequest.from_dict(
            {"exam": "IBPS PO", "test_type": "Adaptive", "num_questions": 20}
        )
    assert "student_history" in exc.value.missing_fields


def test_full_mock_derives_length_from_official_pattern():
    request = GenerationRequest.from_dict({"exam": "NEET UG"})
    assert request.num_questions == 180
    assert request.time_limit_minutes == 180
    assert request.test_type is TestType.FULL_MOCK
    assert any("official paper length" in note for note in request.defaults_applied)


def test_every_derived_value_is_disclosed():
    request = GenerationRequest.from_dict({"exam": "SSC CGL"})
    applied = " ".join(request.defaults_applied)
    for expected in ("pattern_version", "test_type", "difficulty", "language", "solutions"):
        assert expected in applied


def test_timing_is_derived_from_official_pace():
    request = GenerationRequest.from_dict({"exam": "SSC CGL", "num_questions": 25})
    # SSC CGL is 100 questions in 60 minutes, so 25 questions is 15 minutes.
    assert request.time_limit_minutes == 15


def test_subject_is_inferred_from_chapter_selection():
    request = GenerationRequest.from_dict(
        {"exam": "NEET UG", "chapters": ["Kinematics"], "num_questions": 10}
    )
    assert request.subjects == ("Physics",)
    assert request.test_type is TestType.CHAPTER_WISE


def test_off_syllabus_selections_are_rejected():
    with pytest.raises(SyllabusError, match="not a chapter"):
        GenerationRequest.from_dict(
            {"exam": "SSC CGL", "chapters": ["Quantum Field Theory"], "num_questions": 5}
        )
    with pytest.raises(SyllabusError, match="not a subject"):
        GenerationRequest.from_dict(
            {"exam": "SSC CGL", "subjects": ["Astrophysics"], "num_questions": 5}
        )
    with pytest.raises(SyllabusError, match="not a topic"):
        GenerationRequest.from_dict(
            {"exam": "NEET UG", "topics": ["Warp drive tuning"], "num_questions": 5}
        )


def test_unavailable_language_is_rejected():
    with pytest.raises(ValidationError, match="not available"):
        GenerationRequest.from_dict(
            {"exam": "JEE Advanced", "num_questions": 10, "language": "Bilingual"}
        )


def test_loose_json_input_is_accepted():
    request = GenerationRequest.from_dict(
        {
            "exam_name": "ssc cgl",
            "subject": "Reasoning, English",
            "number_of_questions": "20",
            "difficulty_level": "hard",
            "negative_marking": "no",
            "solution_preference": "step-by-step",
            "language": "english",
        }
    )
    assert request.subjects == ("Reasoning", "English")
    assert request.num_questions == 20
    assert request.difficulty is Difficulty.HARD
    assert request.negative_marking is False
    assert request.solution_depth is SolutionDepth.DETAILED
    assert request.language is Language.ENGLISH


def test_question_count_is_capped():
    with pytest.raises(ValidationError, match="capped"):
        GenerationRequest.from_dict({"exam": "NEET UG", "num_questions": 5000})
