"""Blueprint arithmetic: exact totals, proportional coverage, difficulty spread."""

from __future__ import annotations

import pytest

from aipariksha.errors import BlueprintError
from aipariksha.exams import registry
from aipariksha.generation.blueprint import _allocate, build_blueprint
from aipariksha.models.enums import Difficulty, QuestionType
from aipariksha.models.request import GenerationRequest


def plan(payload: dict):
    return build_blueprint(GenerationRequest.from_dict(payload))


# ------------------------------------------------------------------ allocation


@pytest.mark.parametrize(
    "total,weights",
    [
        (10, [1.0, 1.0, 1.0]),
        (180, [45.0, 45.0, 45.0, 45.0]),
        (7, [0.6, 1.4, 1.0, 1.2]),
        (1, [1.0, 2.0, 3.0]),
        (100, [1.0]),
        (3, [1.0, 1.0, 1.0, 1.0, 1.0]),
        (25, [0.5, 0.5, 3.0]),
    ],
)
def test_allocation_always_sums_exactly(total, weights):
    counts = _allocate(total, weights)
    assert sum(counts) == total
    assert all(c >= 0 for c in counts)


def test_allocation_covers_every_bucket_when_there_is_room():
    counts = _allocate(10, [0.1, 5.0, 0.1, 0.1])
    assert all(c >= 1 for c in counts), "a low-weight chapter must not be dropped silently"


def test_allocation_prefers_heaviest_when_starved():
    counts = _allocate(2, [1.0, 9.0, 5.0])
    assert counts == [0, 1, 1]


def test_allocation_handles_degenerate_input():
    assert _allocate(0, [1.0, 2.0]) == [0, 0]
    assert _allocate(5, []) == []
    assert sum(_allocate(5, [0.0, 0.0])) == 5


# -------------------------------------------------------------------- coverage


def test_full_mock_matches_official_totals():
    blueprint = plan({"exam": "NEET UG", "seed": 1})
    assert blueprint.total_questions == 180
    assert blueprint.max_marks == 720.0
    per_subject = blueprint.to_dict()["questions_per_subject"]
    assert per_subject == {"Physics": 45, "Chemistry": 45, "Biology": 90}


def test_full_syllabus_coverage_is_proportional():
    blueprint = plan({"exam": "SSC CGL", "num_questions": 40, "seed": 2})
    per_subject = blueprint.to_dict()["questions_per_subject"]
    # Four equal 25-question sections scaled to 40 questions.
    assert per_subject == {
        "Reasoning": 10,
        "General Awareness": 10,
        "Quantitative Aptitude": 10,
        "English": 10,
    }


def test_jee_main_preserves_mcq_and_numerical_split():
    blueprint = plan({"exam": "JEE Main", "seed": 3})
    assert blueprint.total_questions == 75
    types = blueprint.to_dict()["question_types"]
    assert types[str(QuestionType.MCQ_SINGLE)] == 60
    assert types[str(QuestionType.NUMERICAL)] == 15


def test_chapter_test_stays_inside_selected_chapters():
    blueprint = plan(
        {
            "exam": "NEET UG",
            "chapters": ["Kinematics", "Laws of Motion"],
            "num_questions": 12,
            "seed": 4,
        }
    )
    chapters = blueprint.to_dict()["questions_per_chapter"]
    assert set(chapters) == {"Kinematics", "Laws of Motion"}
    assert sum(chapters.values()) == 12


def test_topic_test_stays_inside_selected_topics():
    blueprint = plan(
        {
            "exam": "SSC CGL",
            "topics": ["Pipes and cisterns", "Boats and streams"],
            "num_questions": 10,
            "seed": 5,
        }
    )
    topics = blueprint.to_dict()["questions_per_topic"]
    assert set(topics) == {"Pipes and cisterns", "Boats and streams"}
    assert sum(topics.values()) == 10


def test_chapter_questions_spread_across_topics():
    blueprint = plan(
        {"exam": "NEET UG", "chapters": ["Kinematics"], "num_questions": 4, "seed": 6}
    )
    topics = blueprint.to_dict()["questions_per_topic"]
    # Kinematics has 4 topics, so 4 questions should hit each exactly once.
    assert len(topics) == 4
    assert set(topics.values()) == {1}


# ------------------------------------------------------------------ difficulty


def test_single_difficulty_is_honoured_exactly():
    blueprint = plan({"exam": "SSC CGL", "num_questions": 20, "difficulty": "Hard", "seed": 7})
    actual = blueprint.to_dict()["difficulty_actual"]
    assert actual == {str(Difficulty.HARD): 20}


def test_mixed_difficulty_follows_the_exam_profile():
    blueprint = plan({"exam": "NEET UG", "num_questions": 100, "seed": 8})
    actual = blueprint.to_dict()["difficulty_actual"]
    assert sum(actual.values()) == 100
    # NEET is modelled 35/45/20; each section allocates independently, so allow drift.
    assert 28 <= actual[str(Difficulty.EASY)] <= 42
    assert 38 <= actual[str(Difficulty.MEDIUM)] <= 52
    assert 14 <= actual[str(Difficulty.HARD)] <= 26


def test_target_and_actual_difficulty_agree():
    blueprint = plan({"exam": "SSC CPO", "num_questions": 60, "seed": 9})
    summary = blueprint.to_dict()
    assert summary["difficulty_target"] == summary["difficulty_actual"]


def test_adaptive_weighting_targets_weak_chapters():
    history = {
        "attempts": [
            {
                "exam": "IBPS PO",
                "chapter_stats": {
                    "Data Interpretation": {"attempted": 12, "correct": 2},
                    "Syllogism": {"attempted": 10, "correct": 10},
                },
            }
        ]
    }
    blueprint = plan(
        {
            "exam": "IBPS PO",
            "test_type": "Adaptive",
            "num_questions": 40,
            "student_history": history,
            "seed": 10,
        }
    )
    chapters = blueprint.to_dict()["questions_per_chapter"]
    assert chapters.get("Data Interpretation", 0) > chapters.get("Syllogism", 0), (
        "an adaptive paper must lean into the weak chapter"
    )


def test_non_adaptive_test_ignores_history_weighting():
    history = {
        "attempts": [
            {
                "exam": "IBPS PO",
                "chapter_stats": {"Data Interpretation": {"attempted": 12, "correct": 1}},
            }
        ]
    }
    weighted = plan(
        {"exam": "IBPS PO", "num_questions": 40, "student_history": history, "seed": 10}
    ).to_dict()["questions_per_chapter"]
    plain = plan({"exam": "IBPS PO", "num_questions": 40, "seed": 10}).to_dict()[
        "questions_per_chapter"
    ]
    assert weighted == plain, "only Adaptive tests may re-weight the official syllabus"


# ----------------------------------------------------------------- constraints


def test_seed_makes_the_blueprint_reproducible():
    first = plan({"exam": "NEET UG", "num_questions": 30, "seed": 42}).to_dict()
    second = plan({"exam": "NEET UG", "num_questions": 30, "seed": 42}).to_dict()
    assert first == second


def test_choice_based_exam_requires_a_subject():
    with pytest.raises(BlueprintError, match="one paper per subject"):
        plan({"exam": "CUET UG", "num_questions": 50})

    blueprint = plan({"exam": "CUET UG", "subjects": ["Physics"], "num_questions": 50, "seed": 11})
    assert blueprint.total_questions == 50
    assert blueprint.max_marks == 250.0


def test_short_paper_reports_which_sections_it_dropped():
    blueprint = plan({"exam": "SSC MTS", "num_questions": 2, "seed": 12})
    assert blueprint.total_questions == 2
    assert any("omitted" in note for note in blueprint.notes)


def test_sectional_marking_carries_into_slots():
    blueprint = plan({"exam": "SSC MTS", "num_questions": 90, "seed": 13})
    session_one = [s for s in blueprint.slots if s.section.startswith("Session I -")]
    session_two = [s for s in blueprint.slots if s.section.startswith("Session II -")]
    assert session_one and session_two
    assert all(s.negative_marks == 0.0 for s in session_one), "Session I has no negative marking"
    assert all(s.negative_marks == -1.0 for s in session_two)


def test_disabling_negative_marking_zeroes_every_penalty():
    blueprint = plan({"exam": "NEET UG", "num_questions": 20, "negative_marking": False, "seed": 14})
    assert all(s.negative_marks == 0.0 for s in blueprint.slots)
