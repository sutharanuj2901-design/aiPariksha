"""Offline template provider — the no-API-key path.

This exists so the *system* is verifiable without a key: blueprinting,
validation, scoring, analytics, formatting and the CLI all run end to end
against it, and the test suite needs no network.

It does **not** pretend to produce exam-quality questions. Every result is
flagged ``is_placeholder=True``, which the engine turns into a prominent
disclaimer on the paper. Placeholder content must never be shown to a student as
practice material.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .base import GenerationCall, ProviderResult, QuestionProvider

#: Distinct qualifiers give every generated stem a unique fingerprint, so the
#: duplicate detector is genuinely exercised rather than trivially satisfied.
_VARIANTS = (
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi",
    "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
)

_STEM_TEMPLATES = (
    "Placeholder item {variant}: which statement about {topic} is consistent with the standard treatment of {chapter}?",
    "Placeholder item {variant}: a student applies the core result of {topic} to a routine {chapter} setting. Which conclusion follows?",
    "Placeholder item {variant}: identify the relationship that correctly characterises {topic} within {chapter}.",
    "Placeholder item {variant}: under the usual assumptions of {chapter}, what does {topic} predict?",
    "Placeholder item {variant}: which option best describes the role of {topic} in {chapter}?",
    "Placeholder item {variant}: two setups differ only in one parameter of {topic}. Which comparison holds in {chapter}?",
    "Placeholder item {variant}: select the statement that follows from the definition used for {topic} in {chapter}.",
    "Placeholder item {variant}: which reasoning about {topic} would a {chapter} question expect?",
)

_OPTION_TEMPLATES = (
    "The standard result for {topic} applies directly.",
    "The relationship for {topic} is inverted.",
    "{topic} has no bearing on this situation.",
    "The result holds only outside the scope of {chapter}.",
    "Two of the stated conditions for {topic} are swapped.",
)


class OfflineTemplateProvider(QuestionProvider):
    """Deterministic, dependency-free placeholder generator."""

    name = "offline"

    @property
    def model(self) -> str:
        return "template-v1"

    def complete(self, call: GenerationCall) -> ProviderResult:
        slots: Sequence[Mapping[str, Any]] = call.context.get("slots") or ()
        questions = [self._build(slot) for slot in slots]
        return ProviderResult(
            data={"questions": questions},
            provider=self.name,
            model=self.model,
            is_placeholder=True,
            warnings=(
                "Offline template provider produced structural placeholders, not "
                "exam-quality questions. Configure an API key for real content.",
            ),
        )

    # ------------------------------------------------------------------ builder

    def _build(self, slot: Mapping[str, Any]) -> dict[str, Any]:
        index = int(slot.get("index", 1))
        topic = str(slot.get("topic") or slot.get("chapter") or "the selected topic")
        chapter = str(slot.get("chapter") or "this chapter")
        qtype = str(slot.get("question_type", "MCQ Single Correct"))
        variant = _VARIANTS[index % len(_VARIANTS)]

        payload: dict[str, Any] = {
            "index": index,
            "chapter": chapter,
            "topic": topic,
            "difficulty": slot.get("difficulty", "Medium"),
            "question_type": qtype,
            "text": _STEM_TEMPLATES[index % len(_STEM_TEMPLATES)].format(
                variant=variant, topic=topic, chapter=chapter
            ),
        }

        if qtype == "Numerical Value":
            value = round(2.5 * (index % 17) + 1, 2)
            payload["correct_value"] = value
            payload["solution"] = self._solution(topic, chapter, str(value))
            return payload

        # Rotate which key is correct so answer keys are not all "A".
        option_count = 4
        keys = ["A", "B", "C", "D"][:option_count]
        rotation = index % option_count
        texts = [
            _OPTION_TEMPLATES[(rotation + offset) % len(_OPTION_TEMPLATES)].format(
                topic=topic, chapter=chapter
            )
            + f" (variant {variant}-{offset + 1})"
            for offset in range(option_count)
        ]
        payload["options"] = [{"key": key, "text": text} for key, text in zip(keys, texts)]

        if qtype == "MCQ Multiple Correct":
            correct = [keys[rotation], keys[(rotation + 2) % option_count]]
        else:
            correct = [keys[rotation]]
        payload["correct_keys"] = correct
        payload["solution"] = self._solution(topic, chapter, ", ".join(correct))
        return payload

    @staticmethod
    def _solution(topic: str, chapter: str, answer: str) -> dict[str, Any]:
        return {
            "correct_answer": answer,
            "explanation": (
                f"Placeholder explanation. A real solution would state the governing "
                f"principle for {topic}, apply it to the given data, and rule out each "
                f"distractor."
            ),
            "steps": [
                f"Identify what the question is testing within {chapter}.",
                f"Apply the standard result for {topic}.",
                "Check the remaining options against that result.",
            ],
            "formula_used": "",
            "common_mistakes": [
                f"Confusing {topic} with a superficially similar result.",
                "Skipping a unit or sign check before selecting an option.",
            ],
            "time_saving_tip": "Eliminate structurally impossible options before computing.",
            "final_answer": answer,
            "concept_tested": topic,
        }
