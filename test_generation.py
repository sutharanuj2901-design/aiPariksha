"""Quality gates and generation orchestration."""

from __future__ import annotations

import pytest

from aipariksha.config import Settings
from aipariksha.errors import QualityGateError
from aipariksha.generation.generator import PLACEHOLDER_DISCLAIMER, PaperGenerator
from aipariksha.generation.validator import QualityGate
from aipariksha.models.enums import Language
from aipariksha.models.request import GenerationRequest
from conftest import ScriptedProvider, good_question

BASE = {"exam": "NEET UG", "chapters": ["Kinematics"], "num_questions": 4, "seed": 1}


def build(payload=None, responder=None, **setting_overrides):
    """Generate a paper with a scripted provider."""
    request = GenerationRequest.from_dict({**BASE, **(payload or {})})
    responder = responder or (lambda slots, call: [good_question(s) for s in slots])
    provider = ScriptedProvider(responder)
    options = {"api_key": "", "provider": "offline", "batch_size": 10, **setting_overrides}
    return PaperGenerator(Settings(**options), provider=provider).generate(request), provider


def gate_for(payload=None):
    return QualityGate(GenerationRequest.from_dict({**BASE, **(payload or {})}))


def slot_dict(**overrides):
    base = {
        "index": 1,
        "section": "Physics",
        "subject": "Physics",
        "chapter": "Kinematics",
        "topic": "Projectile motion",
        "difficulty": "Medium",
        "question_type": "MCQ Single Correct",
        "marks": 4.0,
        "negative_marks": -1.0,
    }
    base.update(overrides)
    return base


def only_slot(payload=None, **slot_overrides):
    """A single blueprint slot, for direct gate testing."""
    from aipariksha.generation.blueprint import build_blueprint

    request = GenerationRequest.from_dict({**BASE, **(payload or {})})
    blueprint = build_blueprint(request)
    slot = blueprint.slots[0]
    if slot_overrides:
        from dataclasses import replace

        slot = replace(slot, **slot_overrides)
    return QualityGate(request), slot


# --------------------------------------------------------------- happy path


def test_generation_produces_a_complete_paper():
    paper, provider = build()
    assert paper.total_questions == 4
    assert paper.max_marks == 16.0
    assert paper.paper_id.startswith("neet-ug-")
    assert paper.title
    assert paper.marking_scheme
    assert paper.instructions
    assert provider.calls, "the provider should have been called"
    for question in paper.questions:
        assert question.solution is not None
        assert question.correct_keys
        assert len(question.options) == 4


def test_questions_are_renumbered_contiguously():
    paper, _ = build({"num_questions": 12})
    numbers = [q.number for q in paper.questions]
    ids = [q.question_id for q in paper.questions]
    assert numbers == list(range(1, 13))
    assert ids == [f"Q{i}" for i in range(1, 13)]


def test_paper_records_the_blueprint_and_quality_report():
    paper, _ = build({"num_questions": 8})
    assert paper.blueprint_summary["delivered_questions"] == 8
    assert paper.quality_report["accepted"] == 8
    assert paper.quality_report["rejected"] == 0
    assert paper.generated_by["provider"] == "scripted"


def test_offline_provider_marks_the_paper_as_placeholder():
    request = GenerationRequest.from_dict(BASE)
    paper = PaperGenerator(Settings(api_key="", provider="offline")).generate(request)
    assert any("PLACEHOLDER" in d for d in paper.disclaimers)
    assert paper.disclaimers[0] == PLACEHOLDER_DISCLAIMER


def test_originality_and_pattern_disclaimers_are_always_present():
    paper, _ = build()
    blob = " ".join(paper.disclaimers).lower()
    assert "not reproductions of any official past paper" in blob
    assert "verify against the official notification" in blob


# ------------------------------------------------------------ redaction


def test_student_view_hides_answers_and_solutions():
    paper, _ = build()
    student = paper.to_dict(reveal=False)
    for section in student["sections"]:
        for question in section["questions"]:
            assert "correct_answer" not in question
            assert "correct_keys" not in question
            assert "solution" not in question
    assert "answer_key" not in student

    full = paper.to_dict(reveal=True)
    assert "answer_key" in full
    assert full["sections"][0]["questions"][0]["correct_answer"]


# ------------------------------------------------------------- quality gate


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"text": "Hi?"}, "too short"),
        ({"text": ""}, "empty"),
        (
            {"text": "Using the graph shown in the figure below, find the acceleration of the body."},
            "not included",
        ),
        (
            {"text": "Let me think about this step by step and then produce a suitable question here."},
            "meta commentary",
        ),
        (
            {"text": "The acceleration of a body moving under a constant force is a useful quantity."},
            "does not actually pose a question",
        ),
    ],
)
def test_bad_stems_are_rejected(overrides, expected):
    gate, slot = only_slot()
    outcome = gate.check(good_question(slot_dict(), **overrides), slot)
    assert outcome.question is None
    assert any(expected in f for f in outcome.failures), outcome.failures


def test_two_correct_answers_on_a_single_correct_slot_is_rejected():
    gate, slot = only_slot()
    outcome = gate.check(good_question(slot_dict(), correct_keys=["A", "B"]), slot)
    assert outcome.question is None
    assert any("exactly one correct answer" in f for f in outcome.failures)


def test_answer_outside_the_options_is_rejected():
    gate, slot = only_slot()
    outcome = gate.check(good_question(slot_dict(), correct_keys=["E"]), slot)
    assert outcome.question is None
    assert any("not one of the options" in f for f in outcome.failures)


def test_missing_answer_is_rejected():
    raw = good_question(slot_dict())
    raw.pop("correct_keys")
    gate, slot = only_slot()
    outcome = gate.check(raw, slot)
    assert outcome.question is None
    assert any("No correct answer" in f for f in outcome.failures)


def test_duplicate_option_meanings_are_rejected():
    gate, slot = only_slot()
    raw = good_question(slot_dict())
    raw["options"][1]["text"] = raw["options"][0]["text"]
    outcome = gate.check(raw, slot)
    assert outcome.question is None
    assert any("same meaning" in f for f in outcome.failures)


def test_all_of_the_above_is_rejected():
    gate, slot = only_slot()
    raw = good_question(slot_dict())
    raw["options"][3]["text"] = "All of the above"
    outcome = gate.check(raw, slot)
    assert outcome.question is None
    assert any("banned combined form" in f for f in outcome.failures)


def test_wrong_option_count_is_rejected():
    gate, slot = only_slot()
    raw = good_question(slot_dict())
    raw["options"] = raw["options"][:3]
    outcome = gate.check(raw, slot)
    assert outcome.question is None
    assert any("Expected 4 options" in f for f in outcome.failures)


def test_missing_solution_is_rejected_when_requested():
    gate, slot = only_slot()
    raw = good_question(slot_dict())
    raw.pop("solution")
    outcome = gate.check(raw, slot)
    assert outcome.question is None
    assert any("Solution was requested" in f for f in outcome.failures)


def test_solution_that_leaks_reasoning_is_rejected():
    gate, slot = only_slot()
    raw = good_question(slot_dict())
    raw["solution"]["explanation"] = (
        "My reasoning here is that the first relation must hold, so option A is the answer."
    )
    outcome = gate.check(raw, slot)
    assert outcome.question is None
    assert any("internal reasoning" in f for f in outcome.failures)


def test_solution_is_optional_when_not_requested():
    gate, slot = only_slot({"solutions": "None"})
    raw = good_question(slot_dict())
    raw.pop("solution")
    outcome = gate.check(raw, slot)
    assert outcome.question is not None
    assert outcome.question.solution is None


def test_duplicate_questions_are_rejected():
    gate, slot = only_slot()
    first = good_question(slot_dict())
    assert gate.check(first, slot).question is not None
    outcome = gate.check(dict(first), slot)
    assert outcome.question is None
    assert any("Duplicate" in f for f in outcome.failures)


def test_near_duplicate_questions_are_rejected():
    gate, slot = only_slot()
    first = good_question(slot_dict())
    assert gate.check(first, slot).question is not None
    reworded = dict(first)
    # A cosmetic rewrite of the same question must not slip through.
    reworded["text"] = "In this case, " + first["text"][0].lower() + first["text"][1:]
    assert reworded["text"] != first["text"]
    outcome = gate.check(reworded, slot)
    assert outcome.question is None
    assert any("similar" in f for f in outcome.failures)


def test_bilingual_paper_requires_hindi():
    gate, slot = only_slot({"language": "Bilingual"})
    outcome = gate.check(good_question(slot_dict()), slot)
    assert outcome.question is None
    assert any("Hindi version of the stem" in f for f in outcome.failures)


def test_bilingual_paper_accepts_hindi():
    gate, slot = only_slot({"language": "Bilingual"})
    raw = good_question(slot_dict())
    raw["text_hi"] = "निम्नलिखित में से कौन सा कथन इस स्थिति के लिए सही है?"
    for option in raw["options"]:
        option["text_hi"] = "यह विकल्प हिंदी में है।"
    outcome = gate.check(raw, slot)
    assert outcome.question is not None, outcome.failures
    assert outcome.question.text_hi


def test_numerical_slot_requires_a_value():
    gate, slot = only_slot(
        {"exam": "JEE Main", "chapters": ["Kinematics"], "num_questions": 5},
    )
    from dataclasses import replace

    from aipariksha.models.enums import QuestionType

    numeric_slot = replace(slot, question_type=QuestionType.NUMERICAL)
    raw = good_question(slot_dict(question_type="Numerical Value"))
    raw.pop("correct_value")
    outcome = gate.check(raw, numeric_slot)
    assert outcome.question is None
    assert any("no correct_value" in f for f in outcome.failures)


# --------------------------------------------------------------- repair loop


def test_rejected_questions_are_retried_and_replaced():
    """First call returns junk for every slot; the retry returns good questions."""

    def responder(slots, call_number):
        if call_number == 1:
            return [good_question(s, text="Bad.") for s in slots]
        return [good_question(s) for s in slots]

    paper, provider = build(responder=responder, max_repair_rounds=2)
    assert paper.total_questions == 4, "the repair round should have refilled every slot"
    assert len(provider.calls) >= 2
    assert paper.generated_by["repair_rounds"] >= 1
    # The retry prompt must tell the model what went wrong.
    assert "rejected for the following reasons" in provider.calls[-1].user


def test_persistent_failures_beyond_tolerance_raise():
    def responder(slots, call_number):
        return [good_question(s, text="No.") for s in slots]

    with pytest.raises(QualityGateError) as exc:
        build(responder=responder, max_repair_rounds=1)
    assert "quality checks" in str(exc.value)
    assert exc.value.failures


def test_small_shortfall_is_tolerated_and_disclosed():
    """One irreparably bad slot out of ten should not void the paper."""

    def responder(slots, call_number):
        return [
            good_question(s, text="X.") if s["index"] == 1 else good_question(s)
            for s in slots
        ]

    paper, _ = build({"num_questions": 10}, responder=responder, max_repair_rounds=1)
    assert paper.total_questions == 9
    assert paper.generated_by["dropped_slots"] == 1
    assert any("omitted" in w for w in paper.generated_by["warnings"])


def test_unmatched_indices_fall_back_to_position():
    """A provider that drops the index must not void the whole batch."""

    def responder(slots, call_number):
        entries = [good_question(s) for s in slots]
        for entry in entries:
            entry["index"] = 999
        return entries

    paper, _ = build(responder=responder)
    assert paper.total_questions == 4


def test_prompt_carries_the_avoid_list_between_batches():
    paper, provider = build({"num_questions": 20}, batch_size=5)
    later_calls = [c for c in provider.calls[1:] if "ALREADY USED IN THIS PAPER" in c.user]
    assert later_calls, "batches after the first must be told what is already in the paper"


def test_batches_never_span_sections():
    request = GenerationRequest.from_dict({"exam": "SSC CGL", "num_questions": 40, "seed": 2})
    provider = ScriptedProvider(lambda slots, call: [good_question(s) for s in slots])
    PaperGenerator(
        Settings(api_key="", provider="offline", batch_size=30), provider=provider
    ).generate(request)
    for call in provider.calls:
        sections = {s["section"] for s in call.context["slots"]}
        assert len(sections) == 1, f"batch mixed sections: {sections}"
