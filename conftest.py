"""Shared fixtures and a scriptable provider for testing the quality gate."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import pytest

from aipariksha.config import Settings
from aipariksha.llm.base import GenerationCall, ProviderResult, QuestionProvider


class ScriptedProvider(QuestionProvider):
    """Returns whatever the test tells it to.

    ``responder`` receives the slot dicts for one batch and returns the list of
    raw question entries to hand back, so a test can inject malformed output and
    assert on how the gate reacts.
    """

    name = "scripted"

    def __init__(
        self,
        responder: Callable[[Sequence[Mapping[str, Any]], int], list[dict[str, Any]]],
    ) -> None:
        self._responder = responder
        self.calls: list[GenerationCall] = []

    @property
    def model(self) -> str:
        return "scripted-v1"

    def complete(self, call: GenerationCall) -> ProviderResult:
        self.calls.append(call)
        slots = call.context.get("slots") or []
        questions = self._responder(slots, len(self.calls))
        return ProviderResult(
            data={"questions": questions},
            provider=self.name,
            model=self.model,
        )


#: Distinct content words per slot. The dedupe check deliberately collapses
#: numeric literals, so varying only "case 1 / case 2" would (correctly) read as
#: duplicates — a fixture has to differ in actual wording.
_SUBJECTS = (
    "trolley", "pendulum", "flywheel", "gas cylinder", "copper wire", "glass prism",
    "steel rod", "water column", "magnet", "capacitor", "spring", "turbine blade",
    "lens", "resistor coil", "piston", "satellite", "balloon", "tuning fork",
    "crystal lattice", "electrolyte bath", "conveyor belt", "gyroscope",
    "thermistor", "diffraction slit", "ball bearing", "solenoid", "manometer",
    "centrifuge", "photocell", "transformer core",
)

_VERBS = (
    "released from rest", "held under tension", "heated steadily", "cooled rapidly",
    "displaced slightly", "rotated at constant speed", "immersed fully",
    "connected in series", "illuminated uniformly", "compressed slowly",
)

_CONTEXTS = (
    "in a vacuum chamber", "on a frictionless track", "inside a sealed vessel",
    "against a rigid wall", "within a uniform field", "beside a graduated scale",
    "on an inclined surface",
)

_TEMPLATES = (
    "A {thing} is {action} {context}, following the conditions described in {topic}. Which conclusion about the {thing} is correct?",
    "{context}, a {thing} is {action}. Using the standard treatment of {topic}, what must be true?",
    "Consider a {thing} {action} {context}. According to {topic}, which statement holds?",
    "During a {topic} demonstration, a {thing} is {action} {context}. Identify the correct outcome.",
    "A laboratory {thing}, {action} {context}, is studied under {topic}. Select the valid conclusion.",
    "Suppose a {thing} were {action} {context}. Which prediction does {topic} support?",
    "Working through {topic}, a student examines a {thing} {action} {context}. What follows?",
    "Given a {thing} {action} {context}, determine which claim about {topic} is accurate.",
)


def good_question(slot: Mapping[str, Any], **overrides: Any) -> dict[str, Any]:
    """A question that passes every gate, as a base for mutation.

    Varies along four independent dimensions with coprime strides, so any two
    slot indices below 200 differ in at least two of them. A fixture that varied
    only one word would be rejected as a near-duplicate — correctly — and the
    test would be measuring the fixture rather than the code.
    """
    index = slot["index"]
    thing = _SUBJECTS[index % len(_SUBJECTS)]
    action = _VERBS[(index * 3) % len(_VERBS)]
    context = _CONTEXTS[(index * 3) % len(_CONTEXTS)]
    template = _TEMPLATES[index % len(_TEMPLATES)]

    payload: dict[str, Any] = {
        "index": index,
        "text": template.format(
            thing=thing, action=action, context=context, topic=slot["topic"]
        ),
        "options": [
            {"key": "A", "text": f"The stated relationship holds for the {thing}."},
            {"key": "B", "text": f"The relationship is reversed for the {thing}."},
            {"key": "C", "text": f"No such relationship applies to the {thing}."},
            {"key": "D", "text": f"The outcome for the {thing} depends on an unstated factor."},
        ],
        "correct_keys": ["A"],
        "solution": {
            "explanation": (
                "The governing relationship applies directly here, which rules out the other "
                "three options in turn."
            ),
            "steps": ["State the relationship.", "Substitute the given data.", "Compare options."],
            "formula_used": "v = u + at",
            "common_mistakes": ["Mixing up the sign convention."],
            "time_saving_tip": "Check dimensions before computing.",
            "final_answer": "A",
            "concept_tested": slot["topic"],
        },
    }
    if slot.get("question_type") == "Numerical Value":
        payload.pop("options")
        payload.pop("correct_keys")
        payload["correct_value"] = 12.0
    payload.update(overrides)
    return payload


@pytest.fixture
def settings() -> Settings:
    """Deterministic, offline settings with repair rounds enabled."""
    return Settings(
        api_key="",
        provider="offline",
        batch_size=10,
        max_repair_rounds=2,
        temperature=0.0,
    )


@pytest.fixture
def scripted() -> Callable[..., ScriptedProvider]:
    return ScriptedProvider
