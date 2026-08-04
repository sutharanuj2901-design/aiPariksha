# AIPariksha

The AI engine behind an AI-first examination platform: generates exam-pattern
question papers, grades submissions, and produces personalised analytics.

**JSON in, JSON out.** Every capability takes a plain dict and returns a plain
dict with an `ok` flag, so the same engine sits behind a CLI, an HTTP handler, a
queue worker or a notebook without adaptation.

## Status

The API key ships **blank**. With no key the engine runs on an offline template
provider — blueprinting, validation, scoring, analytics, formatting and the CLI
all work end to end — but the questions are structural placeholders, and every
such paper is stamped with a prominent disclaimer. Set `AIPARIKSHA_API_KEY` to
generate real content through the same code path.

```
114 tests passing. Core engine is stdlib-only; anthropic is needed only for
model-backed generation.
```

## Quick start

```bash
python -m pytest                                     # 114 tests, no network needed
python -m aipariksha exams                           # the exam catalogue
python -m aipariksha syllabus "NEET UG" --subject Physics
python -m aipariksha preview examples/request_neet_full_mock.json   # free, no model call
python -m aipariksha generate examples/request_jee_chapter_test.json -o paper.json
python -m aipariksha generate examples/request_jee_chapter_test.json --print --student
python -m aipariksha evaluate paper.json examples/submission_sample.json --print
```

```python
from aipariksha import AIPariksha

engine = AIPariksha()

result = engine.generate({"exam": "NEET UG", "num_questions": 30})
paper = result["paper"]                       # full record, includes answers
student_copy = engine.student_view(paper)     # answers stripped

report = engine.evaluate({
    "paper": paper,
    "submission": {"responses": [{"question_id": "Q1", "selected": "B"}]},
})
```

## Supported exams

| Category | Exams |
|---|---|
| Medical Entrance | NEET UG |
| Engineering Entrance | JEE Main, JEE Advanced |
| University Entrance | CUET UG |
| Government (SSC) | CGL, CHSL, MTS, CPO |
| Banking | IBPS PO, IBPS Clerk, SBI PO, SBI Clerk, RBI Assistant |
| Railway | RRB NTPC, RRB Group D |
| State Level | Haryana CET |
| Civil Services | UPSC Civil Services, State PCS — registered as `planned` |

`planned` exams appear in the catalogue so a UI can advertise them, but refuse
generation with a clear message. Flipping one field to `supported` enables them.

## Architecture

```
exams/       declarative exam patterns + self-populating registry
models/      JSON contracts: request, paper, submission, report, history
generation/  blueprint -> prompt -> quality gate -> repair loop
llm/         pluggable providers (Claude via forced tool call, offline templates)
evaluation/  scoring, analytics, recommendations, readiness
engine.py    the JSON facade      cli.py / formatting.py
```

### Adding an exam requires no core changes

An exam is **data, not code**. Drop one file into
[`aipariksha/exams/definitions/`](aipariksha/exams/definitions/) describing the
pattern and call `register()`. The registry auto-imports it; nothing in
generation, evaluation, analytics or the CLI changes. Anything an exam can vary —
section count, per-section marking, optional questions, sectional timing,
allowed question types, languages — is a field rather than an `if exam == ...`
somewhere else. `test_new_exam_needs_no_core_changes` exercises this.

That design carries real cases already: SSC MTS has no negative marking in
Session I but does in Session II; JEE Main splits each subject into MCQ and
numerical sections with different types; CUET is sat one subject paper at a time;
Haryana CET has no negative marking at all. None of these are special-cased.

### The blueprint decides the paper; the model only writes

Composition is computed before any model call: which section, subject, chapter,
topic, difficulty and question type every single question must have. Allocation
uses largest-remainder apportionment, so splits sum exactly with no drift, and a
low-weight chapter is never silently dropped from a paper large enough to hold
it. The model receives fully-specified slots and is never asked to decide the
shape of the paper — which is what makes coverage and difficulty auditable, and
what makes a bad batch cost a retry instead of a misshapen paper.

Every paper reports its plan against what was delivered:

```json
"blueprint": {
  "questions_per_subject": {"Physics": 45, "Chemistry": 45, "Biology": 90},
  "difficulty_target": {"Easy": 63, "Medium": 81, "Hard": 36},
  "difficulty_actual": {"Easy": 63, "Medium": 81, "Hard": 36}
}
```

### Quality gates

Nothing reaches a student without passing them. Rejected questions are fed back
to the provider with the reasons and regenerated. Rejections are returned as
data, not exceptions.

Enforced: exactly one correct answer (unless the type is multiple-correct);
4 distinct, mutually-exclusive options; no "All/None of the above"; no reference
to a figure, table or passage that isn't included; no meta-commentary; no
duplicates — including near-duplicates by token overlap, with numeric literals
collapsed so two questions differing only in their constants still collide;
Hindi present for bilingual papers; a real explanation when solutions were
requested.

A paper that loses more than a third of its questions is refused rather than
served short; a smaller shortfall is delivered with the omission disclosed in
`generated_by.warnings`.

### It asks instead of assuming

A missing required input returns `clarification_needed` with the exact questions
to put in front of the student — never a guess:

```bash
$ python -m aipariksha preview examples/request_missing_inputs.json
{
  "ok": false,
  "error": {
    "code": "clarification_needed",
    "questions": ["Which chapter(s) should this chapter-wise test cover? ..."],
    "missing_fields": ["chapters", "num_questions"]
  }
}
```

Anything genuinely derivable from the official pattern *is* filled in — but
disclosed, every time, in `defaults_applied`:

```
pattern_version set to the latest known scheme (2025)
num_questions set to the official paper length (180)
time_limit_minutes set to 20 using the official pace of 1.00 min/question
negative_marking taken from the official pattern (on)
```

An adaptive test with no performance history is refused, not started from an
invented skill level.

### Evaluation

Produces score, correct/incorrect/unattempted, accuracy (out of *attempted*, so
skipping doesn't flatter it), section/subject/chapter/topic/difficulty
breakdowns, time utilisation, strengths, improvement areas, weak concepts,
ranked next topics, a revision plan, a readiness band, and a ready-to-submit
request for the next paper.

Analysis is evidence-bound. A chapter isn't called weak on one missed question.
When a paper is too short to judge chapters, the report says so and drops to
subject level instead of implying the chapters were fine. If the client reported
no timings, everything time-related comes back `null` — not `0`, which would
read as "answered instantly".

`history_entry` in the response is shaped to feed straight back in as
`student_history` for the next request, which is what makes adaptive tests work
without a database.

### Integrity

- No fabricated notifications, cut-offs or answer keys.
- Pattern details carry a disclaimer to verify with the conducting authority;
  where a scheme is known to vary (JEE Advanced changes yearly by design), the
  definition says so rather than implying certainty.
- Readiness and percentile are labelled estimates with their basis stated, and
  are never presented as official ranks or predictions.
- Answers can't leak by accident: `to_dict()` hides them unless a caller
  explicitly asks, and a redacted student paper is *refused* for grading rather
  than silently marking everything wrong.

## Configuration

All settings resolve as: explicit argument > environment variable > default.
See [.env.example](.env.example). Default model is Sonnet — the blueprint already
fixes composition, so the model's job is well-scoped writing and fast response is
a product requirement. Hard papers route to Opus automatically.

## Known limitations

- Syllabus chapter/topic lists are representative rather than exhaustive; they
  are the main thing to extend for production.
- UPSC and State PCS are structural placeholders pending deeper syllabus mapping.
- CUET models ten domain subjects out of the many NTA offers.
- Hindi and bilingual output is validated for presence of Devanagari, not for
  translation quality.
