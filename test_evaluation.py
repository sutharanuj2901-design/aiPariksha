"""Scoring, analytics and the JSON engine round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aipariksha import AIPariksha
from aipariksha.config import Settings
from aipariksha.evaluation.scorer import score
from aipariksha.generation.generator import PaperGenerator
from aipariksha.models.enums import Language, QuestionType, ResponseStatus
from aipariksha.models.paper import Option, Paper, PaperSection, Question, Solution
from aipariksha.models.request import GenerationRequest
from aipariksha.models.serialization import paper_from_dict
from aipariksha.models.submission import Submission
from conftest import ScriptedProvider, good_question

OFFLINE = Settings(api_key="", provider="offline", batch_size=10)


def make_question(number, *, qtype=QuestionType.MCQ_SINGLE, marks=4.0, neg=-1.0, **kw):
    defaults = dict(
        number=number,
        section="Physics",
        subject="Physics",
        chapter="Kinematics",
        topic="Projectile motion",
        difficulty=kw.pop("difficulty", None) or __import__(
            "aipariksha.models.enums", fromlist=["Difficulty"]
        ).Difficulty.MEDIUM,
        question_type=qtype,
        text=f"Question number {number} text that is long enough to be valid.",
        marks=marks,
        negative_marks=neg,
    )
    defaults.update(kw)
    if qtype is not QuestionType.NUMERICAL and "options" not in defaults:
        defaults["options"] = tuple(
            Option(key=k, text=f"Option {k} for {number}") for k in "ABCD"
        )
        defaults.setdefault("correct_keys", ("A",))
    return Question(**defaults)


def make_paper(questions, *, duration=10):
    paper = Paper(
        paper_id="test-1",
        exam="NEET UG",
        title="Test Paper",
        pattern_version="2025",
        duration_minutes=duration,
        marking_scheme="+4 / -1",
        sections=[PaperSection(name="Physics", subject="Physics", questions=list(questions))],
    )
    paper.renumber()
    return paper


def submit(**answers):
    return Submission.from_dict({"responses": [
        {"question_id": qid, **(v if isinstance(v, dict) else {"selected": v})}
        for qid, v in answers.items()
    ]})


# ------------------------------------------------------------------- scoring


def test_correct_incorrect_and_unattempted():
    paper = make_paper([make_question(i) for i in range(1, 4)])
    sheet = score(paper, submit(Q1="A", Q2="B"))
    assert [r.status for r in sheet.results] == [
        ResponseStatus.CORRECT,
        ResponseStatus.INCORRECT,
        ResponseStatus.UNATTEMPTED,
    ]
    assert sheet.total_score == 3.0  # +4 - 1 + 0
    assert sheet.maximum_marks == 12.0
    assert sheet.correct == 1 and sheet.incorrect == 1 and sheet.unattempted == 1
    assert sheet.negative_marks_lost == 1.0
    assert sheet.marks_lost_to_unattempted == 4.0


def test_accuracy_excludes_unattempted():
    paper = make_paper([make_question(i) for i in range(1, 5)])
    sheet = score(paper, submit(Q1="A", Q2="B"))
    assert sheet.accuracy_percentage == 50.0  # 1 of 2 attempted
    assert sheet.attempt_rate_percentage == 50.0  # 2 of 4 total


def test_negative_marking_off_never_deducts():
    paper = make_paper([make_question(1, neg=0.0)])
    assert score(paper, submit(Q1="D")).total_score == 0.0


def test_selecting_two_options_on_single_correct_is_wrong():
    paper = make_paper([make_question(1)])
    sheet = score(paper, submit(Q1="A,B"))
    assert sheet.results[0].status is ResponseStatus.INCORRECT


def test_numerical_answer_within_tolerance():
    paper = make_paper([
        make_question(1, qtype=QuestionType.NUMERICAL, correct_value=9.8, tolerance=0.1),
        make_question(2, qtype=QuestionType.NUMERICAL, correct_value=5.0),
    ])
    sheet = score(paper, submit(Q1={"value": 9.85}, Q2={"value": 5.4}))
    assert sheet.results[0].status is ResponseStatus.CORRECT
    assert sheet.results[1].status is ResponseStatus.INCORRECT


def test_multi_correct_partial_credit():
    q = make_question(
        1, qtype=QuestionType.MCQ_MULTIPLE, correct_keys=("A", "B", "C"),
        marks=4.0, neg=-2.0, partial_marks=1.0,
    )
    paper = make_paper([q])
    assert score(paper, submit(Q1="A,B,C")).results[0].status is ResponseStatus.CORRECT
    partial = score(paper, submit(Q1="A,B"))
    assert partial.results[0].status is ResponseStatus.PARTIAL
    assert partial.total_score == 2.0
    wrong = score(paper, submit(Q1="A,D"))
    assert wrong.results[0].status is ResponseStatus.INCORRECT
    assert wrong.total_score == -2.0


def test_answers_for_unknown_questions_are_reported_not_ignored_silently():
    paper = make_paper([make_question(1)])
    sheet = score(paper, submit(Q1="A", Q99="B"))
    assert sheet.unmatched_response_ids == ("Q99",)


def test_negative_total_score_is_handled():
    """Negative marking can push a score below zero; nothing may crash on it."""
    paper = make_paper([make_question(i) for i in range(1, 5)])
    engine = AIPariksha(OFFLINE)
    result = engine.evaluate({
        "paper": paper.to_dict(reveal=True),
        "submission": {"responses": [
            {"question_id": f"Q{i}", "selected": "D"} for i in range(1, 5)]},
    })
    assert result["ok"], result
    assert result["report"]["summary"]["total_score"] == -4.0
    readiness = result["report"]["readiness"]
    assert 0.0 <= readiness["score_out_of_100"] < 10.0
    assert readiness["band"] == "Foundation Building"
    assert "below the 25th percentile" in result["report"]["readiness"]["estimated_percentile_range"]


def test_time_overrun_is_flagged():
    paper = make_paper([make_question(i) for i in range(1, 3)], duration=2)
    sheet = score(paper, submit(
        Q1={"selected": "A", "time_spent_seconds": 300},
        Q2={"selected": "A", "time_spent_seconds": 10},
    ))
    assert sheet.fair_seconds_per_question == 60.0
    assert sheet.results[0].time_overrun is True
    assert sheet.results[1].time_overrun is False


# ----------------------------------------------------------------- analytics


def build_paper(payload):
    request = GenerationRequest.from_dict(payload)
    provider = ScriptedProvider(lambda slots, call: [good_question(s) for s in slots])
    return PaperGenerator(OFFLINE, provider=provider).generate(request)


def test_report_has_every_required_breakdown():
    paper = build_paper({"exam": "SSC CGL", "num_questions": 24, "seed": 5})
    engine = AIPariksha(OFFLINE)
    responses = [
        {"question_id": q.question_id, "selected": q.correct_keys[0], "time_spent_seconds": 30}
        for q in paper.questions
    ]
    result = engine.evaluate({"paper": paper.to_dict(reveal=True), "submission": {"responses": responses}})
    assert result["ok"]
    report = result["report"]
    for key in (
        "summary", "section_performance", "subject_performance", "chapter_performance",
        "topic_performance", "difficulty_performance", "time_utilisation", "strengths",
        "areas_for_improvement", "weak_concepts", "recommended_next_topics",
        "suggested_next_test", "readiness", "revision_plan", "personalised_feedback",
    ):
        assert key in report, key
    assert report["summary"]["accuracy_percentage"] == 100.0
    assert report["readiness"]["band"] == "Strong"


def test_missing_timing_data_is_not_reported_as_zero():
    paper = build_paper({"exam": "NEET UG", "chapters": ["Kinematics"], "num_questions": 4, "seed": 1})
    engine = AIPariksha(OFFLINE)
    result = engine.evaluate({
        "paper": paper.to_dict(reveal=True),
        "submission": {"responses": [{"question_id": "Q1", "selected": "A"}]},
    })
    timing = result["report"]["time_utilisation"]
    assert timing["timing_data_available"] is False
    assert timing["utilisation_percentage"] is None
    assert timing["used_minutes"] is None


def test_no_history_means_no_trend_claims():
    paper = build_paper({"exam": "NEET UG", "chapters": ["Kinematics"], "num_questions": 4, "seed": 1})
    engine = AIPariksha(OFFLINE)
    result = engine.evaluate({
        "paper": paper.to_dict(reveal=True),
        "submission": {"responses": [{"question_id": "Q1", "selected": "A"}]},
    })
    blob = " ".join(result["report"]["disclaimers"])
    assert "no previous performance was supplied" in blob


def test_estimates_are_never_presented_as_official():
    paper = build_paper({"exam": "NEET UG", "chapters": ["Kinematics"], "num_questions": 4, "seed": 1})
    engine = AIPariksha(OFFLINE)
    result = engine.evaluate({
        "paper": paper.to_dict(reveal=True),
        "submission": {"responses": [{"question_id": "Q1", "selected": "A"}]},
    })
    readiness = result["report"]["readiness"]
    assert "not official ranks" in readiness["disclaimer"]
    if readiness["estimated_percentile_range"]:
        assert readiness["estimated_percentile_range"].startswith("estimated")


# ------------------------------------------------------- engine round-trip


def test_generate_evaluate_round_trip_through_json():
    engine = AIPariksha(OFFLINE)
    gen = engine.generate({"exam": "SSC CHSL", "num_questions": 12, "seed": 9})
    assert gen["ok"]
    # Survive a real serialisation boundary.
    paper_json = json.loads(json.dumps(gen["paper"]))
    answers = {q["question_id"]: q["correct_answer"]
               for s in paper_json["sections"] for q in s["questions"]}
    ev = engine.evaluate({"paper": paper_json, "submission": {"responses": [
        {"question_id": qid, "selected": key} for qid, key in answers.items()
    ]}})
    assert ev["ok"]
    assert ev["report"]["summary"]["correct"] == 12
    assert ev["report"]["summary"]["score_percentage"] == 100.0


def test_history_entry_feeds_back_as_adaptive_input():
    engine = AIPariksha(OFFLINE)
    gen = engine.generate({"exam": "IBPS PO", "num_questions": 20, "seed": 3})
    paper = gen["paper"]
    responses = [{"question_id": q["question_id"], "selected": "A"}
                 for s in paper["sections"] for q in s["questions"]]
    ev = engine.evaluate({"paper": paper, "submission": {"responses": responses}})
    history = {"student_id": "s1", "attempts": [ev["history_entry"]]}
    adaptive = engine.generate({
        "exam": "IBPS PO", "test_type": "Adaptive", "num_questions": 20,
        "student_history": history, "seed": 4,
    })
    assert adaptive["ok"], adaptive
    assert adaptive["paper"]["request"]["history_supplied"] is True


def test_student_view_cannot_be_graded():
    engine = AIPariksha(OFFLINE)
    gen = engine.generate({"exam": "SSC CGL", "num_questions": 8, "seed": 2})
    redacted = engine.student_view(gen["paper"])["paper"]
    result = engine.evaluate({"paper": redacted, "submission": {"responses": [
        {"question_id": "Q1", "selected": "A"}]}})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert "no answer key" in result["error"]["message"]


def test_clarification_comes_back_as_an_envelope_not_an_exception():
    engine = AIPariksha(OFFLINE)
    result = engine.generate({"exam": "NEET UG", "test_type": "Chapter Wise"})
    assert result["ok"] is False
    assert result["error"]["code"] == "clarification_needed"
    assert result["error"]["questions"]
    assert "chapters" in result["error"]["missing_fields"]


def test_preview_costs_no_provider_call():
    engine = AIPariksha(OFFLINE)
    result = engine.preview({"exam": "JEE Main", "seed": 1})
    assert result["ok"]
    assert result["blueprint"]["total_questions"] == 75
    assert len(result["slots"]) == 75


def test_catalogue_and_syllabus():
    engine = AIPariksha(OFFLINE)
    assert len(engine.catalogue()["exams"]) == 18
    syllabus = engine.syllabus("NEET UG", "Physics")
    assert syllabus["ok"]
    chapters = syllabus["subjects"][0]["chapters"]
    assert any(c["chapter"] == "Kinematics" for c in chapters)
    assert all(c["topics"] for c in chapters)
    assert engine.syllabus("NEET UG", "Astrology")["ok"] is False


def test_unknown_exam_lists_supported_ones():
    result = AIPariksha(OFFLINE).generate({"exam": "Hogwarts Entrance", "num_questions": 5})
    assert result["ok"] is False
    assert result["error"]["code"] == "unknown_exam"
    assert "NEET UG" in result["error"]["supported_exams"]


def test_paper_serialisation_is_lossless():
    paper = build_paper({"exam": "JEE Main", "num_questions": 12, "seed": 7})
    rebuilt = paper_from_dict(paper.to_dict(reveal=True))
    assert rebuilt.total_questions == paper.total_questions
    assert rebuilt.max_marks == paper.max_marks
    for before, after in zip(paper.questions, rebuilt.questions):
        assert after.text == before.text
        assert after.correct_keys == before.correct_keys
        assert after.correct_value == before.correct_value
        assert after.question_type is before.question_type
        assert after.marks == before.marks


# ------------------------------------------------------------------- the CLI


def test_cli_generate_and_evaluate(tmp_path: Path, capsys):
    from aipariksha.cli import main

    request = tmp_path / "req.json"
    request.write_text(json.dumps({"exam": "SSC CGL", "num_questions": 8, "seed": 1}))
    paper_file = tmp_path / "paper.json"

    assert main(["generate", str(request), "-o", str(paper_file)]) == 0
    envelope = json.loads(paper_file.read_text(encoding="utf-8"))
    assert envelope["ok"]

    answers = {q["question_id"]: q["correct_answer"]
               for s in envelope["paper"]["sections"] for q in s["questions"]}
    submission = tmp_path / "sub.json"
    submission.write_text(json.dumps({"responses": [
        {"question_id": k, "selected": v} for k, v in answers.items()]}))

    capsys.readouterr()
    assert main(["evaluate", str(paper_file), str(submission), "--print"]) == 0
    out = capsys.readouterr().out
    assert "SUBJECT-WISE PERFORMANCE" in out
    assert "READINESS ESTIMATE" in out


def test_cli_reports_failure_with_nonzero_exit(tmp_path: Path, capsys):
    from aipariksha.cli import main

    request = tmp_path / "req.json"
    request.write_text(json.dumps({"test_type": "Chapter Wise"}))
    assert main(["preview", str(request)]) == 1
    assert "clarification_needed" in capsys.readouterr().out


def test_bundled_examples_are_valid(capsys):
    from aipariksha.cli import main

    examples = Path(__file__).resolve().parent.parent / "examples"
    for name, expected in [
        ("request_neet_full_mock.json", 0),
        ("request_jee_chapter_test.json", 0),
        ("request_ssc_topic_test.json", 0),
        ("request_adaptive_with_history.json", 0),
        ("request_missing_inputs.json", 1),  # demonstrates the clarification path
    ]:
        capsys.readouterr()
        assert main(["preview", str(examples / name)]) == expected, name
