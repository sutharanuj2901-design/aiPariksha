"""Human-readable rendering.

The JSON contract is the product surface; this module exists so a paper can be
printed, pasted into a document, or eyeballed during review without a client
application.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_WIDTH = 78


def render_paper(
    paper: Mapping[str, Any], *, include_solutions: bool = False, include_key: bool = False
) -> str:
    """Format a paper dict (as returned by ``generate``) for printing."""
    lines: list[str] = []
    _header(lines, str(paper.get("exam", "")), str(paper.get("test_title", "")))

    lines.append(f"Pattern version : {paper.get('pattern_version', '-')}")
    lines.append(f"Duration        : {paper.get('duration_minutes', '-')} minutes")
    lines.append(f"Total questions : {paper.get('total_questions', '-')}")
    lines.append(f"Maximum marks   : {paper.get('maximum_marks', '-')}")
    lines.append(f"Language        : {paper.get('language', '-')}")
    lines.append(f"Marking scheme  : {paper.get('marking_scheme', '-')}")
    lines.append("")

    instructions = paper.get("instructions") or []
    if instructions:
        lines.append("INSTRUCTIONS")
        lines.extend(f"  {i}. {text}" for i, text in enumerate(instructions, 1))
        lines.append("")

    reveal_any = False
    for section in paper.get("sections") or []:
        lines.append("-" * _WIDTH)
        header = str(section.get("name", ""))
        meta = section.get("instructions") or ""
        lines.append(f"{header}".upper())
        if meta:
            lines.append(f"({meta})")
        if section.get("time_minutes"):
            lines.append(f"Sectional time limit: {section['time_minutes']} minutes")
        lines.append("-" * _WIDTH)
        lines.append("")

        for question in section.get("questions") or []:
            lines.extend(_render_question(question, include_solutions=include_solutions))
            reveal_any = reveal_any or "correct_answer" in question

    if include_key and reveal_any:
        lines.append("=" * _WIDTH)
        lines.append("ANSWER KEY")
        lines.append("=" * _WIDTH)
        key = paper.get("answer_key") or _collect_key(paper)
        row: list[str] = []
        for entry in key:
            row.append(f"{entry.get('question_id', '')}: {entry.get('correct_answer', '')}")
            if len(row) == 5:
                lines.append("  " + " | ".join(row))
                row = []
        if row:
            lines.append("  " + " | ".join(row))
        lines.append("")

    disclaimers = paper.get("disclaimers") or []
    if disclaimers:
        lines.append("=" * _WIDTH)
        lines.append("IMPORTANT")
        for text in disclaimers:
            lines.extend(_wrap(str(text), prefix="  - "))
        lines.append("")

    return "\n".join(lines)


def render_report(report: Mapping[str, Any]) -> str:
    """Format an evaluation report for printing."""
    lines: list[str] = []
    _header(lines, str(report.get("exam", "")), f"Result: {report.get('test_title', '')}")

    summary = report.get("summary") or {}
    lines.append(
        f"Score           : {summary.get('total_score')} / {summary.get('maximum_marks')}"
        f"  ({_pct(summary.get('score_percentage'))})"
    )
    lines.append(
        f"Correct         : {summary.get('correct')}   "
        f"Incorrect: {summary.get('incorrect')}   "
        f"Unattempted: {summary.get('unattempted')}"
    )
    lines.append(f"Accuracy        : {_pct(summary.get('accuracy_percentage'))} of attempted questions")
    lines.append(f"Attempt rate    : {_pct(summary.get('attempt_rate_percentage'))}")
    lines.append(f"Lost to penalty : {summary.get('negative_marks_lost')} marks")
    lines.append(f"Left unattempted: {summary.get('marks_left_on_the_table')} marks")
    lines.append("")

    for label, key in (
        ("SUBJECT-WISE PERFORMANCE", "subject_performance"),
        ("CHAPTER-WISE PERFORMANCE", "chapter_performance"),
        ("DIFFICULTY-WISE PERFORMANCE", "difficulty_performance"),
    ):
        buckets = report.get(key) or []
        if not buckets:
            continue
        lines.append(label)
        lines.append(f"  {'Area':<38}{'Correct':>9}{'Attempt':>9}{'Accuracy':>10}")
        for bucket in buckets:
            lines.append(
                f"  {_clip(str(bucket.get('name', '')), 36):<38}"
                f"{str(bucket.get('correct')) + '/' + str(bucket.get('total_questions')):>9}"
                f"{str(bucket.get('attempted')):>9}"
                f"{_pct(bucket.get('accuracy_percentage')):>10}"
            )
        lines.append("")

    timing = report.get("time_utilisation") or {}
    if timing.get("timing_data_available"):
        lines.append("TIME UTILISATION")
        lines.append(
            f"  Used {timing.get('used_minutes')} of {timing.get('allotted_minutes')} minutes "
            f"({_pct(timing.get('utilisation_percentage'))})"
        )
        if timing.get("average_seconds_per_attempted_question"):
            lines.append(
                f"  Average {timing['average_seconds_per_attempted_question']}s per attempted "
                f"question against a fair budget of {timing.get('fair_seconds_per_question')}s"
            )
        lines.append("")

    _bullets(lines, "STRENGTHS", report.get("strengths"))
    _bullets(lines, "AREAS FOR IMPROVEMENT", report.get("areas_for_improvement"))
    _bullets(lines, "WEAK CONCEPTS", report.get("weak_concepts"))

    recommendations = report.get("recommended_next_topics") or []
    if recommendations:
        lines.append("RECOMMENDED NEXT TOPICS")
        for item in recommendations:
            lines.append(
                f"  [{str(item.get('priority', '')).upper():<6}] {item.get('topic', '')}"
            )
            if item.get("reason"):
                lines.extend(_wrap(str(item["reason"]), prefix="           "))
            if item.get("suggested_action"):
                lines.extend(_wrap(f"-> {item['suggested_action']}", prefix="           "))
        lines.append("")

    plan = report.get("revision_plan") or []
    if plan:
        lines.append("REVISION PLAN")
        for entry in plan:
            lines.append(f"  Day {entry.get('day')}: {entry.get('focus')}")
            lines.extend(_wrap(str(entry.get("activity", "")), prefix="          "))
        lines.append("")

    next_test = report.get("suggested_next_test") or {}
    if next_test.get("request"):
        lines.append("SUGGESTED NEXT TEST")
        lines.extend(_wrap(str(next_test.get("rationale", "")), prefix="  "))
        request = next_test["request"]
        lines.append(
            "  Request: "
            + ", ".join(f"{k}={v}" for k, v in request.items())
        )
        lines.append("")

    readiness = report.get("readiness") or {}
    if readiness.get("band"):
        lines.append("READINESS ESTIMATE")
        lines.append(
            f"  {readiness['band']} - {readiness.get('score_out_of_100')}/100"
        )
        if readiness.get("estimated_percentile_range"):
            lines.append(f"  {readiness['estimated_percentile_range']}")
        lines.extend(_wrap(str(readiness.get("disclaimer", "")), prefix="  "))
        lines.append("")

    if report.get("personalised_feedback"):
        lines.append("FEEDBACK")
        lines.extend(_wrap(str(report["personalised_feedback"]), prefix="  "))
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------- internals


def _render_question(question: Mapping[str, Any], *, include_solutions: bool) -> list[str]:
    lines: list[str] = []
    number = question.get("number", "")
    tag = f"[{question.get('difficulty', '')} | {question.get('chapter', '')}]"
    lines.append(f"Q{number}. {question.get('text', '')}")
    if question.get("text_hi"):
        lines.append(f"      {question['text_hi']}")
    lines.append(f"      {tag}  (+{question.get('marks', '')}"
                 + (f" / {question.get('negative_marks')}" if question.get("negative_marks") else "")
                 + ")")

    for option in question.get("options") or []:
        lines.append(f"      ({option.get('key')}) {option.get('text')}")
        if option.get("text_hi"):
            lines.append(f"          {option['text_hi']}")
    if question.get("answer_format") == "numerical":
        lines.append("      Answer: ____________ (numerical value)")

    if include_solutions and "correct_answer" in question:
        lines.append(f"      >> Correct answer: {question['correct_answer']}")
        solution = question.get("solution") or {}
        if solution.get("explanation"):
            lines.extend(_wrap(str(solution["explanation"]), prefix="         "))
        for step_index, step in enumerate(solution.get("steps") or [], 1):
            lines.extend(_wrap(f"{step_index}. {step}", prefix="         "))
        if solution.get("formula_used"):
            lines.append(f"         Formula: {solution['formula_used']}")
        for mistake in solution.get("common_mistakes") or []:
            lines.extend(_wrap(f"Common mistake: {mistake}", prefix="         "))
        if solution.get("time_saving_tip"):
            lines.extend(_wrap(f"Tip: {solution['time_saving_tip']}", prefix="         "))
        if solution.get("final_answer"):
            lines.append(f"         Final answer: {solution['final_answer']}")

    lines.append("")
    return lines


def _header(lines: list[str], exam: str, title: str) -> None:
    lines.append("=" * _WIDTH)
    lines.append(exam.upper().center(_WIDTH))
    if title:
        lines.append(title.center(_WIDTH))
    lines.append("=" * _WIDTH)
    lines.append("")


def _bullets(lines: list[str], label: str, items: Sequence[Any] | None) -> None:
    if not items:
        return
    lines.append(label)
    for item in items:
        lines.extend(_wrap(str(item), prefix="  - "))
    lines.append("")


def _wrap(text: str, *, prefix: str = "") -> list[str]:
    """Wrap text to the page width, indenting continuation lines under prefix."""
    words = text.split()
    if not words:
        return []
    indent = " " * len(prefix)
    out: list[str] = []
    current = prefix
    for word in words:
        candidate = f"{current}{word} "
        if len(candidate.rstrip()) > _WIDTH and current.strip() not in ("", prefix.strip()):
            out.append(current.rstrip())
            current = f"{indent}{word} "
        else:
            current = candidate
    if current.strip():
        out.append(current.rstrip())
    return out


def _collect_key(paper: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for section in paper.get("sections") or []:
        for question in section.get("questions") or []:
            if "correct_answer" in question:
                out.append(
                    {
                        "question_id": question.get("question_id"),
                        "correct_answer": question.get("correct_answer"),
                    }
                )
    return out


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f}%"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
