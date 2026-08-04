"""Prompt construction and the response schema.

The prompt never decides the paper's composition — the blueprint already did
that. Each call hands the model a list of fully-specified slots and asks only
for the writing: stem, options, correct answer, and a student-facing solution.

That division is what keeps coverage and difficulty auditable, and it keeps the
prompt short enough to stay fast on a 180-question mock.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..models.enums import Language, SolutionDepth
from ..models.request import GenerationRequest
from .blueprint import QuestionSlot

SYSTEM_PROMPT = """\
You are the question-authoring engine for AIPariksha, an AI-first examination \
platform used by students preparing for Indian competitive exams.

Your only job is to write original, exam-quality questions for the slots you are \
given. Composition, weighting and difficulty distribution have already been \
decided; do not change them.

NON-NEGOTIABLE STANDARDS
- Accuracy first. If you cannot write a question you are certain is correct, write \
an easier question on the same topic rather than a doubtful one.
- Stay strictly inside the stated exam, subject, chapter and topic.
- Exactly one correct answer, unless the slot's question type is explicitly \
multiple-correct.
- Distractors must be plausible, mutually exclusive, and clearly wrong on \
inspection by a prepared student. Never make two options defensible.
- Zero ambiguity. No trick wording, no double negatives, no questions that hinge \
on a misreading. If a question needs an assumption, state it in the stem.
- Self-contained. Never refer to "the passage above", a diagram, a figure or a \
table unless you include its full content in the stem as text.
- Grammatically correct, plain, unambiguous language.
- Test understanding and application over recall wherever the topic allows.
- Original wording. Write in the style of the exam; never reproduce a real past \
paper's question verbatim.
- Every question in a batch must be distinctly different from the others: no \
rephrasing of the same idea, no two questions with the same answer path.
- Avoid "All of the above" and "None of the above" as options.
- Never reference current affairs, dated events, cut-offs or notifications.

DIFFICULTY CALIBRATION
- Easy: one concept, direct formula or definition, solvable in well under the \
average per-question time.
- Medium: standard exam difficulty; concept application or two to three steps.
- Hard: multi-concept integration, higher-order reasoning, or a longer \
computation. Hard must mean genuinely demanding, not merely tedious arithmetic.

SOLUTIONS
Write for a student who got the question wrong. Give the reasoning and the method, \
not a narration of your own thought process. Be concise and instructional.

Return your output by calling the provided tool. Populate one entry per requested \
slot, echoing each slot's index exactly."""


#: JSON Schema for the forced tool call.
QUESTION_BATCH_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "One entry per requested slot, in any order.",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The slot index this question answers. Must match exactly.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The complete, self-contained question stem.",
                    },
                    "text_hi": {
                        "type": "string",
                        "description": "Hindi rendering of the stem. Required for Hindi and Bilingual papers only.",
                    },
                    "options": {
                        "type": "array",
                        "description": "Required for every option-based question type.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "A, B, C or D."},
                                "text": {"type": "string"},
                                "text_hi": {"type": "string"},
                            },
                            "required": ["key", "text"],
                        },
                    },
                    "correct_keys": {
                        "type": "array",
                        "description": "Option key(s) of the correct answer(s).",
                        "items": {"type": "string"},
                    },
                    "correct_value": {
                        "type": "number",
                        "description": "The answer for numerical-value questions.",
                    },
                    "tolerance": {
                        "type": "number",
                        "description": "Accepted absolute tolerance for a numerical answer. Omit for exact integers.",
                    },
                    "solution": {
                        "type": "object",
                        "properties": {
                            "explanation": {
                                "type": "string",
                                "description": "Why the correct option is correct, written for a student.",
                            },
                            "steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "The working, one step per entry.",
                            },
                            "formula_used": {"type": "string"},
                            "common_mistakes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "time_saving_tip": {"type": "string"},
                            "final_answer": {"type": "string"},
                            "concept_tested": {
                                "type": "string",
                                "description": "The specific concept this question targets.",
                            },
                        },
                        "required": ["explanation"],
                    },
                },
                "required": ["index", "text"],
            },
        }
    },
    "required": ["questions"],
}


def build_user_prompt(
    request: GenerationRequest,
    slots: Sequence[QuestionSlot],
    *,
    seconds_per_question: float,
    avoid_stems: Sequence[str] = (),
    repair_notes: Sequence[str] = (),
) -> str:
    """Assemble the per-batch instruction."""
    pattern = request.pattern
    lines: list[str] = [
        f"EXAM: {pattern.exam} ({request.pattern_version})",
        f"PAPER TYPE: {request.test_type}",
        f"LANGUAGE: {request.language}",
        f"PACE: approximately {seconds_per_question:.0f} seconds per question in the real exam.",
        "",
        f"Write {len(slots)} question(s) for the slots below. Each slot fixes the "
        "section, subject, chapter, topic, difficulty and question type — honour all of them.",
        "",
    ]

    for slot in slots:
        parts = [
            f"- index {slot.index}",
            f"subject: {slot.subject}",
            f"chapter: {slot.chapter}",
            f"topic: {slot.topic}",
            f"difficulty: {slot.difficulty}",
            f"type: {slot.question_type}",
            f"marks: +{slot.marks:g}",
        ]
        if slot.negative_marks:
            parts.append(f"penalty: {slot.negative_marks:g}")
        if slot.bloom_level:
            parts.append(f"cognitive level: {slot.bloom_level}")
        lines.append(" | ".join(parts))

    lines.extend(["", _language_rule(request.language), _solution_rule(request.solution_depth)])

    numerical = [s for s in slots if s.question_type.value == "Numerical Value"]
    if numerical:
        lines.append(
            "For numerical-value slots omit 'options' and give 'correct_value'. Design them so "
            "the answer is a clean number a student can key in."
        )
    multi = [s for s in slots if s.question_type.value == "MCQ Multiple Correct"]
    if multi:
        lines.append(
            "For multiple-correct slots list every correct key in 'correct_keys'. At least one "
            "option must be wrong, and at least two must be right."
        )

    if request.custom_instructions:
        lines.extend(
            [
                "",
                "ADDITIONAL INSTRUCTIONS FROM THE STUDENT (follow unless they conflict with the "
                "standards above):",
                request.custom_instructions,
            ]
        )

    if avoid_stems:
        lines.extend(
            [
                "",
                "ALREADY USED IN THIS PAPER — do not repeat these ideas or rephrase them:",
                *(f"- {stem}" for stem in avoid_stems),
            ]
        )

    if repair_notes:
        lines.extend(
            [
                "",
                "A previous attempt at these slots was rejected for the following reasons. "
                "Fix them:",
                *(f"- {note}" for note in repair_notes),
            ]
        )

    return "\n".join(lines)


def _language_rule(language: Language) -> str:
    if language is Language.HINDI:
        return (
            "Write the stem and every option in Hindi in 'text_hi', and also supply the English "
            "equivalent in 'text' for internal review. Technical terms may stay in English where "
            "that is the convention in Indian classrooms."
        )
    if language is Language.BILINGUAL:
        return (
            "This is a bilingual paper. Supply English in 'text' and Hindi in 'text_hi' for the "
            "stem and for every option. Both versions must be exactly equivalent in meaning and "
            "difficulty."
        )
    return "Write everything in clear, simple English."


def _solution_rule(depth: SolutionDepth) -> str:
    if depth is SolutionDepth.DETAILED:
        return (
            "Provide a full solution for every question: explanation, numbered steps, the formula "
            "used where one applies, the common mistake students make, a time-saving tip where "
            "one genuinely exists, and the final answer."
        )
    if depth is SolutionDepth.BRIEF:
        return "Provide a two-to-three sentence explanation per question. Steps are optional."
    if depth is SolutionDepth.ANSWER_KEY:
        return "Provide the correct answer and a one-line explanation. Detailed steps are not needed."
    return "A one-line explanation per question is sufficient; it will not be shown to the student."
