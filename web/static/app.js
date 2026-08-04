/* AIPariksha UI.

   Flow: auth -> exam -> generator mode -> mode-specific options -> attempt -> report.

   Every mode declares what it needs in MODES below, and the options screen is
   built from that declaration. That is what keeps the rule "a full mock takes no
   subject or topic selection" true in the UI rather than only in the engine.

   All model-generated text (stems, options, solutions) reaches the DOM through
   textContent or esc() -- never interpolated as HTML. */

"use strict";

const $ = (id) => document.getElementById(id);

async function call(path, body) {
  const options = body === undefined
    ? { credentials: "same-origin" }
    : {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      };
  const res = await fetch(path, options);
  try {
    return await res.json();
  } catch {
    return { ok: false, error: { code: "bad_response", message: `HTTP ${res.status}` } };
  }
}

/* ------------------------------------------------------------------- modes */

/** The generator catalogue. `needs` drives which option fields appear. */
const MODES = [
  {
    id: "Full Mock",
    name: "Full Mock Test",
    desc: "A full-length paper mirroring the latest official pattern, with every subject in its real proportion.",
    needs: [],
    tag: "No selection needed",
    tagClass: "is-none",
    fullSyllabus: true,
  },
  {
    id: "Chapter Wise",
    name: "Chapter-wise Test",
    desc: "Focused practice on one or more chapters, with sub-topics covered proportionally.",
    needs: ["subject", "chapters", "count"],
    tag: "Subject + chapters",
  },
  {
    id: "Topic Wise",
    name: "Topic-wise Drill",
    desc: "The narrowest mode. Every question stays inside one topic, with the angle varied so it never feels repetitive.",
    needs: ["subject", "chapters", "topics", "count"],
    tag: "Subject + chapter + topic",
  },
  {
    id: "Sectional",
    name: "Sectional Test",
    desc: "One full section of the paper, at the official section length and marking.",
    needs: ["subject"],
    tag: "Subject only",
  },
  {
    id: "Revision",
    name: "Revision Paper",
    desc: "Reinforcement over ground you have already covered. With enough history, about 60% targets your flagged weak topics.",
    needs: ["covered"],
    tag: "What you've studied",
  },
  {
    id: "Previous Year Pattern",
    name: "Previous-Year Pattern",
    desc: "New questions matching a past year's structure, difficulty and topic emphasis — never copies of real past questions.",
    needs: ["years"],
    tag: "Reference year",
    fullSyllabus: true,
  },
  {
    id: "Adaptive",
    name: "Adaptive Test",
    desc: "Difficulty moves with you, question by question, and you get a per-topic ability estimate at the end.",
    needs: ["subject", "adaptive"],
    tag: "Live difficulty",
    tagClass: "is-adaptive",
    adaptive: true,
  },
];

/* ------------------------------------------------------------------- state */

const state = {
  user: null,
  catalogue: [],
  byCategory: {},
  pattern: null,
  syllabus: null,
  mode: MODES[0],
  selectedSubjects: new Set(),
  selectedChapters: new Set(),
  selectedTopics: new Set(),

  paper: null,
  paperId: null,
  questions: [],
  responses: new Map(),
  current: 0,
  deadline: null,
  tickHandle: null,
  lastFocusAt: null,
  submitted: false,

  adaptive: null, // {sessionId, question, answered, target, difficulty, untilStable}
};

/* ----------------------------------------------------------------- helpers */

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}
function pct(value, digits = 1) {
  return value === null || value === undefined ? "n/a" : `${Number(value).toFixed(digits)}%`;
}
function num(value) {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
}
function overlay(text) {
  $("overlayText").textContent = text || "Working…";
  $("overlay").hidden = false;
}
const hideOverlay = () => { $("overlay").hidden = true; };

function show(view) {
  ["dash", "options", "test", "report", "progress"].forEach((name) => {
    const el = $(`view-${name}`);
    if (el) el.hidden = name !== view;
  });
  window.scrollTo(0, 0);
}

function banner(html, isError) {
  const el = $("banner");
  if (!html) { el.hidden = true; el.innerHTML = ""; return; }
  el.innerHTML = html;
  el.classList.toggle("is-error", Boolean(isError));
  el.hidden = false;
}

/** Render a failure envelope, including the clarification path. */
function showError(result, statusEl) {
  const error = (result && result.error) || {};
  if (error.code === "clarification_needed") {
    banner(
      `<strong>I need a bit more before I can build this</strong>
       <ul>${(error.questions || []).map((q) => `<li>${esc(q)}</li>`).join("")}</ul>`,
      false
    );
  } else {
    banner(`<strong>${esc(error.code || "Something went wrong")}</strong>${esc(error.message || "")}`, true);
  }
  if (statusEl) {
    statusEl.textContent = error.message || "Could not continue.";
    statusEl.classList.add("is-error");
  }
}

/* -------------------------------------------------------------------- auth */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
    $("loginForm").hidden = tab.dataset.auth !== "login";
    $("registerForm").hidden = tab.dataset.auth !== "register";
  });
});

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("loginError").textContent = "";
  const result = await call("/api/auth/login", {
    email: $("loginEmail").value,
    password: $("loginPassword").value,
  });
  if (!result.ok) {
    $("loginError").textContent = (result.error && result.error.message) || "Sign in failed.";
    return;
  }
  await enterApp(result.user);
});

$("registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("registerError").textContent = "";
  const result = await call("/api/auth/register", {
    name: $("regName").value,
    email: $("regEmail").value,
    password: $("regPassword").value,
    target_exam: $("regExam").value,
  });
  if (!result.ok) {
    $("registerError").textContent = (result.error && result.error.message) || "Could not create the account.";
    return;
  }
  await enterApp(result.user);
});

$("btnLogout").addEventListener("click", async () => {
  await call("/api/auth/logout", {});
  state.user = null;
  stopClock();
  $("app").hidden = true;
  $("view-auth").hidden = false;
  $("loginPassword").value = "";
});

/* -------------------------------------------------------------------- boot */

async function boot() {
  const cfg = await call("/api/config");
  const engine = (cfg && cfg.engine) || {};
  const badge = $("engineBadge");
  if (engine.api_key_configured) {
    badge.textContent = `live · ${engine.model}`;
    badge.className = "badge badge-live";
  } else {
    badge.textContent = "placeholder questions";
    badge.className = "badge badge-warn";
    badge.title =
      "No API key configured. Structure, marking, scoring and analytics are real; question text is placeholder. Set AIPARIKSHA_API_KEY for real content.";
  }

  const cat = await call("/api/exams");
  state.catalogue = cat.exams || [];
  state.byCategory = cat.by_category || {};
  fillExamSelect($("regExam"));
  fillExamSelect($("exam"));

  const me = await call("/api/auth/me");
  if (me.ok) await enterApp(me.user);
  else { $("view-auth").hidden = false; $("app").hidden = true; }
}

function fillExamSelect(select) {
  select.innerHTML = "";
  Object.keys(state.byCategory).forEach((category) => {
    const group = document.createElement("optgroup");
    group.label = category;
    state.byCategory[category].forEach((name) => {
      const row = state.catalogue.find((e) => e.exam === name) || {};
      const option = document.createElement("option");
      option.value = name;
      option.textContent = row.status === "planned" ? `${name} (planned)` : name;
      option.disabled = row.status === "planned";
      group.appendChild(option);
    });
    select.appendChild(group);
  });
  select.value = "NEET UG";
}

async function enterApp(user) {
  state.user = user;
  $("view-auth").hidden = true;
  $("app").hidden = false;
  $("userLine").textContent = `${user.name} · ${user.attempt_count} test(s) completed`;
  if (user.target_exam) $("exam").value = user.target_exam;
  renderModes();
  await onExamChange();
  show("dash");
}

/* ------------------------------------------------------------ exam + modes */

async function onExamChange() {
  const exam = $("exam").value;
  state.selectedSubjects.clear();
  state.selectedChapters.clear();
  state.selectedTopics.clear();
  banner(null);
  $("previewCard").hidden = true;

  const [pattern, syllabus] = await Promise.all([
    call(`/api/pattern?exam=${encodeURIComponent(exam)}`),
    call(`/api/syllabus?exam=${encodeURIComponent(exam)}`),
  ]);
  state.pattern = pattern.ok ? pattern.pattern : null;
  state.syllabus = syllabus.ok ? syllabus : null;

  renderPatternStrip();
  renderPatternCard();

  const langSelect = $("language");
  langSelect.innerHTML = "";
  ((state.pattern && state.pattern.languages) || ["English"]).forEach((lang) => {
    const option = document.createElement("option");
    option.value = lang;
    option.textContent = lang;
    langSelect.appendChild(option);
  });
  $("negativeMarking").checked = Boolean(state.pattern && state.pattern.negative_marking_default);

  if (state.user) call("/api/profile", { target_exam: exam });
}

function renderPatternStrip() {
  const p = state.pattern;
  if (!p) { $("patternStrip").textContent = ""; return; }
  const cells = [
    ["Pattern", p.pattern_version],
    ["Questions", p.total_questions],
    ["Marks", num(p.max_marks)],
    ["Duration", `${p.total_time_minutes} min`],
    ["Sections", (p.sections || []).length],
    ["Negative marking", p.negative_marking_default ? "Yes" : "No"],
  ];
  $("patternStrip").innerHTML = cells
    .map(([k, v]) => `<div><span>${esc(k)}</span><span>${esc(v)}</span></div>`)
    .join("");
}

/** The side panel on the options screen: full official pattern for this exam. */
function renderPatternCard() {
  const p = state.pattern;
  const body = $("patternBody");
  if (!body) return;
  if (!p) {
    body.textContent = "Pattern unavailable.";
    return;
  }
  const rows = [
    ["Pattern version", p.pattern_version],
    ["Questions", p.total_questions],
    ["Maximum marks", num(p.max_marks)],
    ["Duration", `${p.total_time_minutes} min`],
    ["Sectional timing", p.sectional_timing ? "Yes" : "No"],
    ["Negative marking", p.negative_marking_default ? "Yes" : "No"],
  ];
  const sections = (p.sections || [])
    .map(
      (s) => `<tr>
        <td>${esc(s.name)}</td>
        <td class="num">${s.questions}</td>
        <td class="num">+${num(s.marks_correct)}</td>
        <td class="num">${s.marks_incorrect ? num(s.marks_incorrect) : "—"}</td>
      </tr>`
    )
    .join("");

  body.innerHTML = `
    <dl style="margin:0">
      ${rows.map(([k, v]) => `<div class="kv"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}
    </dl>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>Section</th><th class="num">Q</th><th class="num">Right</th><th class="num">Wrong</th></tr></thead>
      <tbody>${sections}</tbody>
    </table></div>
    ${p.disclaimer ? `<p class="note">${esc(p.disclaimer)}</p>` : ""}`;
}

function renderModes() {
  $("modeGrid").innerHTML = MODES.map(
    (mode) => `
    <button class="mode" type="button" data-mode="${esc(mode.id)}">
      <span class="mode-tag ${mode.tagClass || ""}">${esc(mode.tag)}</span>
      <span class="mode-name">${esc(mode.name)}</span>
      <span class="mode-desc">${esc(mode.desc)}</span>
      <span class="mode-needs">${
        mode.needs.length ? `<b>You choose:</b> ${esc(mode.tag.toLowerCase())}` : "<b>Nothing to choose</b> — full official pattern"
      }</span>
    </button>`
  ).join("");
  document.querySelectorAll(".mode").forEach((btn) => {
    btn.addEventListener("click", () => openOptions(btn.dataset.mode));
  });
}

/* ----------------------------------------------------------------- options */

function openOptions(modeId) {
  state.mode = MODES.find((m) => m.id === modeId) || MODES[0];
  const mode = state.mode;
  const needs = new Set(mode.needs);

  $("optionsTitle").textContent = mode.name;
  $("optionsBlurb").textContent = mode.desc;

  // Show only the fields this mode actually requires.
  $("scopeBlock").hidden = !(needs.has("subject") || needs.has("covered"));
  $("subjectField").hidden = !(needs.has("subject") || needs.has("covered"));
  $("chapterField").hidden = !(needs.has("chapters") || needs.has("covered"));
  $("topicField").hidden = !needs.has("topics");
  $("yearField").hidden = !needs.has("years");
  $("adaptiveFields").hidden = !needs.has("adaptive");
  $("countField").hidden = needs.has("adaptive");
  $("weightageField").hidden = !mode.fullSyllabus;

  // Required-vs-optional labelling, per mode.
  $("countReq").textContent = needs.has("count") ? "required" : "auto";
  $("countReq").className = needs.has("count") ? "req" : "muted";
  $("numQuestions").placeholder = needs.has("count")
    ? "e.g. 20"
    : state.pattern
    ? `official: ${state.pattern.total_questions}`
    : "";
  $("timeLimit").placeholder = state.pattern
    ? `official pace: ${state.pattern.total_time_minutes} min for the full paper`
    : "";

  const subjectLabel = $("subjectField").querySelector("label");
  if (subjectLabel) {
    subjectLabel.innerHTML = needs.has("covered")
      ? 'Subjects you have covered <span class="req">required</span>'
      : 'Subject <span class="req">required</span>';
  }
  const chapterLabel = $("chapterField").querySelector("label");
  if (chapterLabel) {
    chapterLabel.innerHTML = needs.has("covered")
      ? 'Chapters you have covered <span class="muted">optional — narrows the revision</span>'
      : 'Chapter(s) <span class="req">required</span>';
  }

  $("fullSyllabusBlock").hidden = !mode.fullSyllabus;
  if (mode.fullSyllabus && state.pattern) {
    const sections = (state.pattern.sections || [])
      .map((s) => `${s.name} (${s.questions})`)
      .join(", ");
    $("fullSyllabusText").textContent =
      `This mode covers every subject in the official proportion, so there is no ` +
      `subject or topic to pick. Composition: ${sections}. ` +
      `Verify the pattern against the official notification before relying on it.`;
  }

  $("numQuestions").value = "";
  $("timeLimit").value = "";
  $("setupStatus").textContent = "";
  $("setupStatus").classList.remove("is-error");
  $("previewCard").hidden = true;
  $("solutions").value = "";
  banner(null);

  renderSubjects();
  renderChapters();
  renderTopics();
  renderWeightage();
  show("options");
}

function renderSubjects() {
  const host = $("subjects");
  host.innerHTML = "";
  const single = !state.mode.needs.includes("covered") && state.mode.id !== "Sectional";
  ((state.pattern && state.pattern.subjects) || []).forEach((subject) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.textContent = subject;
    btn.setAttribute("aria-pressed", state.selectedSubjects.has(subject) ? "true" : "false");
    btn.addEventListener("click", () => {
      if (state.selectedSubjects.has(subject)) {
        state.selectedSubjects.delete(subject);
      } else {
        // Chapter and topic modes work within one subject at a time.
        if (single) state.selectedSubjects.clear();
        state.selectedSubjects.add(subject);
      }
      state.selectedChapters.clear();
      state.selectedTopics.clear();
      renderSubjects();
      renderChapters();
      renderTopics();
    });
    host.appendChild(btn);
  });
}

function visibleSubjects() {
  const all = (state.syllabus && state.syllabus.subjects) || [];
  if (!state.selectedSubjects.size) return all;
  return all.filter((s) => state.selectedSubjects.has(s.subject));
}

function renderChapters() {
  const host = $("chapters");
  const filter = $("chapterSearch").value.trim().toLowerCase();
  host.innerHTML = "";
  if (!state.selectedSubjects.size) {
    host.innerHTML = '<p class="tiny" style="padding:8px">Pick a subject first.</p>';
    $("chapterCount").textContent = "";
    return;
  }
  const subjects = visibleSubjects();
  const multi = subjects.length > 1;
  const single = state.mode.needs.includes("topics"); // topic drill: one chapter

  subjects.forEach((subject) => {
    const matching = subject.chapters.filter((c) => !filter || c.chapter.toLowerCase().includes(filter));
    if (!matching.length) return;
    if (multi) {
      const head = document.createElement("div");
      head.className = "grp";
      head.textContent = subject.subject;
      host.appendChild(head);
    }
    matching.forEach((chapter) => {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = single ? "radio" : "checkbox";
      box.name = "chapterPick";
      box.checked = state.selectedChapters.has(chapter.chapter);
      box.addEventListener("change", () => {
        if (single) state.selectedChapters.clear();
        if (box.checked) state.selectedChapters.add(chapter.chapter);
        else {
          state.selectedChapters.delete(chapter.chapter);
          chapter.topics.forEach((t) => state.selectedTopics.delete(t));
        }
        if (single) state.selectedTopics.clear();
        renderChapters();
        renderTopics();
      });
      const text = document.createElement("span");
      text.textContent = chapter.chapter;
      label.append(box, text);
      host.appendChild(label);
    });
  });
  $("chapterCount").textContent = state.selectedChapters.size
    ? `${state.selectedChapters.size} chapter(s) selected`
    : single
    ? "Select exactly one chapter for a topic drill."
    : "";
}

function renderTopics() {
  const host = $("topics");
  host.innerHTML = "";
  if (!state.selectedChapters.size) {
    host.innerHTML = '<p class="tiny" style="padding:8px">Pick a chapter first.</p>';
    return;
  }
  visibleSubjects().forEach((subject) => {
    subject.chapters.forEach((chapter) => {
      if (!state.selectedChapters.has(chapter.chapter)) return;
      chapter.topics.forEach((topic) => {
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = state.selectedTopics.has(topic);
        box.addEventListener("change", () => {
          if (box.checked) state.selectedTopics.add(topic);
          else state.selectedTopics.delete(topic);
        });
        const text = document.createElement("span");
        text.textContent = topic;
        label.append(box, text);
        host.appendChild(label);
      });
    });
  });
}

function renderWeightage() {
  const host = $("weightage");
  host.innerHTML = "";
  ((state.pattern && state.pattern.subjects) || []).forEach((subject) => {
    const wrap = document.createElement("label");
    wrap.textContent = subject;
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.placeholder = "official";
    input.dataset.subject = subject;
    input.className = "weight-input";
    wrap.appendChild(input);
    host.appendChild(wrap);
  });
}

/** Collect the form into the engine's request shape, omitting blanks. */
function buildRequest() {
  const mode = state.mode;
  const needs = new Set(mode.needs);
  const request = { exam: $("exam").value, test_type: mode.id };
  const put = (key, value) => {
    if (value !== "" && value !== null && value !== undefined) request[key] = value;
  };

  // Scope only where the mode uses it. A full mock deliberately sends none:
  // the engine would ignore it anyway, and sending it would be misleading.
  if (needs.has("subject") || needs.has("covered")) {
    if (state.selectedSubjects.size) request.subjects = [...state.selectedSubjects];
  }
  if (needs.has("chapters") || needs.has("covered")) {
    if (state.selectedChapters.size) request.chapters = [...state.selectedChapters];
  }
  if (needs.has("topics") && state.selectedTopics.size) {
    request.topics = [...state.selectedTopics];
  }
  if (needs.has("years")) put("reference_years", $("referenceYears").value.trim());
  if (needs.has("adaptive")) {
    put("starting_difficulty", $("startingDifficulty").value);
    const length = $("adaptiveLength").value;
    if (length === "stable") request.until_stable = true;
    else request.num_questions = Number(length);
  } else {
    put("num_questions", $("numQuestions").value ? Number($("numQuestions").value) : "");
  }

  put("time_limit_minutes", $("timeLimit").value ? Number($("timeLimit").value) : "");
  put("difficulty", $("difficulty").value);
  put("language", $("language").value);
  put("solutions", $("solutions").value);
  put("custom_instructions", $("customInstructions").value.trim());
  put("seed", $("seed").value ? Number($("seed").value) : "");
  request.negative_marking = $("negativeMarking").checked;

  const dist = {
    Easy: Number($("distEasy").value || 0),
    Medium: Number($("distMedium").value || 0),
    Hard: Number($("distHard").value || 0),
  };
  if (dist.Easy + dist.Medium + dist.Hard > 0) request.difficulty_distribution = dist;

  const weights = {};
  document.querySelectorAll(".weight-input").forEach((input) => {
    if (input.value) weights[input.dataset.subject] = Number(input.value);
  });
  if (Object.keys(weights).length) request.subject_weightage = weights;

  return request;
}

/** Bar list from a {name: count} map. Direct-labelled. */
function barlist(map, total, unit) {
  const entries = Object.entries(map || {});
  if (!entries.length) return '<p class="muted">No data.</p>';
  const max = Math.max(...entries.map(([, v]) => Number(v) || 0), 1);
  return `<div class="barlist">${entries
    .map(([name, value]) => {
      const width = ((Number(value) || 0) / max) * 100;
      const share = total ? ` (${Math.round((Number(value) / total) * 100)}%)` : "";
      return `<div class="barrow">
        <span class="barrow-label" title="${esc(name)}">${esc(name)}</span>
        <span class="bartrack"><span class="barfill" style="width:${width.toFixed(1)}%"></span></span>
        <span class="barvalue">${num(value)} ${esc(unit)}${share}</span>
      </div>`;
    })
    .join("")}</div>`;
}

async function doPreview() {
  const status = $("setupStatus");
  status.textContent = "Blueprinting…";
  status.classList.remove("is-error");
  banner(null);

  const result = await call("/api/preview", buildRequest());
  if (!result.ok) {
    $("previewCard").hidden = true;
    showError(result, status);
    return;
  }

  const bp = result.blueprint;
  const req = result.request;
  const applied = req.defaults_applied || [];
  const advisories = req.advisories || [];

  $("previewBody").innerHTML = `
    <div class="kv"><dt>Questions</dt><dd>${bp.total_questions}</dd></div>
    <div class="kv"><dt>Maximum marks</dt><dd>${num(bp.maximum_marks)}</dd></div>
    <div class="kv"><dt>Duration</dt><dd>${req.time_limit_minutes} min</dd></div>
    <h4 style="margin:14px 0 4px;font-size:12.5px">Per subject</h4>
    ${barlist(bp.questions_per_subject, bp.total_questions, "q")}
    <h4 style="margin:14px 0 4px;font-size:12.5px">Difficulty</h4>
    ${barlist(bp.difficulty_actual, bp.total_questions, "q")}
    ${advisories.length ? `<div class="notice" style="margin-top:14px">${advisories.map(esc).join("<br>")}</div>` : ""}
    ${
      applied.length
        ? `<details class="disclose"><summary>${applied.length} value(s) filled in for you</summary>
           <ul class="bullets">${applied.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>`
        : ""
    }
    ${(bp.notes || []).length ? `<p class="note">${bp.notes.map(esc).join(" ")}</p>` : ""}`;
  $("previewCard").hidden = false;
  status.textContent = `Blueprint ready: ${bp.total_questions} questions across ${
    Object.keys(bp.questions_per_chapter).length
  } chapter(s). No model call was made.`;
}

async function doGenerate() {
  const status = $("setupStatus");
  status.classList.remove("is-error");
  banner(null);

  if (state.mode.adaptive) return startAdaptive();

  overlay("Generating your paper…");
  const result = await call("/api/generate", buildRequest());
  hideOverlay();
  if (!result.ok) { showError(result, status); return; }
  startTest(result);
}

/* --------------------------------------------------------------- fixed test */

function startTest(result) {
  state.adaptive = null;
  state.paper = result.paper;
  state.paperId = result.paper_id;
  state.questions = [];
  state.responses = new Map();
  state.submitted = false;

  (result.paper.sections || []).forEach((section) => {
    (section.questions || []).forEach((q) => {
      state.questions.push({ ...q, _section: section.name });
      state.responses.set(q.question_id, {
        selected: new Set(), value: null, seen: false, marked: false, seconds: 0,
      });
    });
  });

  const notes = [];
  const placeholder = (result.disclaimers || []).find((d) => d.includes("PLACEHOLDER"));
  if (placeholder) notes.push(esc(placeholder));
  ((result.request && result.request.advisories) || []).forEach((a) => notes.push(esc(a)));
  banner(notes.length ? `<strong>Before you start</strong>${notes.join("<br>")}` : null, false);

  $("testTitle").textContent = result.paper.test_title;
  $("testMeta").textContent = `${result.paper.total_questions} questions · ${num(
    result.paper.maximum_marks
  )} marks · ${result.paper.duration_minutes} min · ${result.paper.marking_scheme}`;

  // Step 4: chapter-wise papers state their coverage under the title.
  const chapters = Object.keys((result.blueprint && result.blueprint.questions_per_chapter) || {});
  const topics = Object.keys((result.blueprint && result.blueprint.questions_per_topic) || {});
  const needs = new Set(state.mode.needs);
  if (needs.has("topics")) {
    $("coverageLine").textContent = `Topic coverage: ${topics.join(", ")}`;
  } else if (needs.has("chapters") && chapters.length <= 8) {
    $("coverageLine").textContent = `Chapter coverage: ${chapters.join(", ")}`;
  } else {
    $("coverageLine").textContent = "";
  }

  $("adaptiveChip").hidden = true;
  $("paletteTitle").textContent = "Question palette";
  $("btnSubmit").textContent = "Submit test";

  state.current = 0;
  state.deadline = Date.now() + result.paper.duration_minutes * 60000;
  state.lastFocusAt = Date.now();
  startClock();

  show("test");
  renderPalette();
  renderQuestion();
}

function startClock() {
  stopClock();
  state.tickHandle = setInterval(tick, 500);
  tick();
}
function stopClock() {
  if (state.tickHandle) clearInterval(state.tickHandle);
  state.tickHandle = null;
}

function tick() {
  if (state.deadline === null) return;
  const remaining = Math.max(0, state.deadline - Date.now());
  const total = (state.paper ? state.paper.duration_minutes : 30) * 60000;
  const mins = Math.floor(remaining / 60000);
  const secs = Math.floor((remaining % 60000) / 1000);
  const el = $("timer");
  el.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  el.classList.toggle("is-warning", remaining < total * 0.2 && remaining > 60000);
  el.classList.toggle("is-critical", remaining <= 60000);

  if (remaining <= 0 && !state.submitted) {
    stopClock();
    submitTest(true);
  }
}

function bankTime() {
  const q = state.questions[state.current];
  if (!q || state.lastFocusAt === null) return;
  const response = state.responses.get(q.question_id);
  if (response) response.seconds += (Date.now() - state.lastFocusAt) / 1000;
  state.lastFocusAt = Date.now();
}

function goTo(index) {
  if (state.adaptive) return; // adaptive is strictly forward-only
  if (index < 0 || index >= state.questions.length) return;
  bankTime();
  state.current = index;
  state.lastFocusAt = Date.now();
  renderQuestion();
  renderPalette();
}

function renderQuestion() {
  const q = state.questions[state.current];
  if (!q) return;
  const response = state.responses.get(q.question_id);
  response.seen = true;

  const counter = state.adaptive
    ? `Question ${state.adaptive.answered + 1}${
        state.adaptive.untilStable ? "" : ` of ${state.adaptive.target}`
      }`
    : `Question ${q.number} of ${state.questions.length}`;

  $("questionHead").innerHTML = `
    <span class="qnum">${esc(counter)}</span>
    <span class="tag">${esc(q._section || q.section || "")}</span>
    <span class="tag">${esc(q.chapter)}</span>
    <span class="tag">${esc(q.difficulty)}</span>
    <span class="tag tag-marks">+${num(q.marks)}${q.negative_marks ? ` / ${num(q.negative_marks)}` : ""}</span>`;

  const body = $("questionBody");
  body.innerHTML = "";

  const stem = document.createElement("p");
  stem.className = "qtext";
  stem.textContent = q.text;
  body.appendChild(stem);
  if (q.text_hi) {
    const hindi = document.createElement("p");
    hindi.className = "qtext-hi";
    hindi.textContent = q.text_hi;
    body.appendChild(hindi);
  }

  if (q.answer_format === "numerical") {
    const wrap = document.createElement("div");
    wrap.className = "field numeric-answer";
    const label = document.createElement("label");
    label.textContent = "Your answer (numerical value)";
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.value = response.value === null ? "" : response.value;
    input.addEventListener("input", () => {
      response.value = input.value === "" ? null : Number(input.value);
      renderPalette();
    });
    wrap.append(label, input);
    body.appendChild(wrap);
  } else {
    const multi = q.question_type === "MCQ Multiple Correct";
    const list = document.createElement("div");
    list.className = "options";
    (q.options || []).forEach((option) => {
      const label = document.createElement("label");
      label.className = "option";
      if (response.selected.has(option.key)) label.classList.add("is-selected");

      const input = document.createElement("input");
      input.type = multi ? "checkbox" : "radio";
      input.name = `q-${q.question_id}`;
      input.checked = response.selected.has(option.key);
      input.addEventListener("change", () => {
        if (multi) {
          if (input.checked) response.selected.add(option.key);
          else response.selected.delete(option.key);
        } else {
          response.selected.clear();
          if (input.checked) response.selected.add(option.key);
        }
        renderQuestion();
        renderPalette();
      });

      const key = document.createElement("span");
      key.className = "option-key";
      key.textContent = `(${option.key})`;
      const text = document.createElement("span");
      text.textContent = option.text_hi ? `${option.text} / ${option.text_hi}` : option.text;
      label.append(input, key, text);
      list.appendChild(label);
    });
    body.appendChild(list);
    if (multi) {
      const hint = document.createElement("p");
      hint.className = "tiny";
      hint.textContent = "More than one option is correct. Selecting a wrong option forfeits the question.";
      body.appendChild(hint);
    }
  }

  $("btnMark").setAttribute("aria-pressed", response.marked ? "true" : "false");
  $("btnPrev").disabled = Boolean(state.adaptive) || state.current === 0;
  $("btnMark").disabled = Boolean(state.adaptive);
  $("btnNext").disabled = !state.adaptive && state.current === state.questions.length - 1;
  $("btnNext").textContent = state.adaptive ? "Submit answer" : "Next";
}

function renderPalette() {
  const host = $("palette");
  host.innerHTML = "";
  let answered = 0;
  let marked = 0;

  state.questions.forEach((q, index) => {
    const response = state.responses.get(q.question_id);
    const isAnswered = response.selected.size > 0 || response.value !== null;
    if (isAnswered) answered += 1;
    if (response.marked) marked += 1;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pal";
    btn.textContent = index + 1;
    if (response.marked) btn.classList.add("is-marked");
    else if (isAnswered) btn.classList.add("is-answered");
    else if (response.seen) btn.classList.add("is-seen");
    if (index === state.current) btn.classList.add("is-current");
    btn.disabled = Boolean(state.adaptive);
    btn.addEventListener("click", () => goTo(index));
    host.appendChild(btn);
  });

  const total = state.questions.length;
  $("progressSummary").innerHTML = state.adaptive
    ? `<div class="kv"><dt>Answered</dt><dd>${state.adaptive.answered}</dd></div>
       <div class="kv"><dt>Current level</dt><dd>${esc(state.adaptive.difficulty)}</dd></div>`
    : `<div class="kv"><dt>Answered</dt><dd>${answered} / ${total}</dd></div>
       <div class="kv"><dt>Marked</dt><dd>${marked}</dd></div>
       <div class="kv"><dt>Remaining</dt><dd>${total - answered}</dd></div>`;
}

async function submitTest(auto) {
  if (state.submitted) return;
  if (state.adaptive) return finishAdaptive();

  const unanswered = [...state.responses.values()].filter(
    (r) => r.selected.size === 0 && r.value === null
  ).length;
  if (!auto && unanswered > 0) {
    const ok = window.confirm(
      `${unanswered} question(s) are unattempted. Submit anyway?\n\n` +
        "Unattempted questions score zero, but carry no penalty either."
    );
    if (!ok) return;
  }

  state.submitted = true;
  stopClock();
  bankTime();

  const responses = [];
  state.responses.forEach((response, questionId) => {
    if (response.selected.size === 0 && response.value === null) return;
    const entry = { question_id: questionId, time_spent_seconds: Math.round(response.seconds) };
    if (response.value !== null) entry.value = response.value;
    else entry.selected = [...response.selected];
    if (response.marked) entry.marked_for_review = true;
    responses.push(entry);
  });

  const elapsed = state.paper.duration_minutes * 60 - Math.max(0, (state.deadline - Date.now()) / 1000);
  overlay(auto ? "Time is up. Grading…" : "Grading your paper…");
  const result = await call("/api/evaluate", {
    paper_id: state.paperId,
    submission: {
      paper_id: state.paperId,
      responses,
      total_time_spent_seconds: Math.round(Math.max(0, elapsed)),
    },
  });
  hideOverlay();
  if (!result.ok) { state.submitted = false; showError(result, null); return; }
  renderReport(result, auto);
}

/* ------------------------------------------------------------- adaptive test */

async function startAdaptive() {
  overlay("Starting your adaptive test…");
  const result = await call("/api/adaptive/start", buildRequest());
  hideOverlay();
  if (!result.ok) { showError(result, $("setupStatus")); return; }

  const session = result.session;
  state.paper = { duration_minutes: 0, test_title: "", maximum_marks: 0 };
  state.paperId = null;
  state.submitted = false;
  state.questions = [];
  state.responses = new Map();
  state.current = 0;
  state.deadline = null;
  state.adaptive = {
    sessionId: session.session_id,
    answered: 0,
    target: session.target,
    difficulty: session.current_difficulty,
    untilStable: session.until_stable,
    trail: [],
  };

  const notes = [];
  if (session.placeholder) {
    notes.push("Question text is placeholder content: no API key is configured.");
  }
  (result.advisories || []).forEach((a) => notes.push(esc(a)));
  banner(notes.length ? `<strong>Before you start</strong>${notes.join("<br>")}` : null, false);

  $("testTitle").textContent = `${$("exam").value} Adaptive Test`;
  $("testMeta").textContent = state.adaptive.untilStable
    ? `Difficulty adapts to every answer · runs until your level is clear (max ${session.target})`
    : `Difficulty adapts to every answer · ${session.target} questions`;
  $("coverageLine").textContent = "";
  $("paletteTitle").textContent = "Answered so far";
  $("btnSubmit").textContent = "End test & see report";
  $("timer").textContent = "--:--";
  $("adaptiveChip").hidden = false;
  updateAdaptiveChip();

  pushAdaptiveQuestion(result.question);
  show("test");
}

function updateAdaptiveChip() {
  const a = state.adaptive;
  if (!a) return;
  $("adaptiveChip").innerHTML = `Level<b>${esc(a.difficulty)}</b>`;
}

function pushAdaptiveQuestion(question) {
  if (!question) return;
  state.questions.push({ ...question, _section: question.section });
  state.responses.set(question.question_id, {
    selected: new Set(), value: null, seen: false, marked: false, seconds: 0,
  });
  state.current = state.questions.length - 1;
  state.lastFocusAt = Date.now();
  renderQuestion();
  renderPalette();
}

async function submitAdaptiveAnswer() {
  const a = state.adaptive;
  const q = state.questions[state.current];
  const response = state.responses.get(q.question_id);
  if (response.selected.size === 0 && response.value === null) {
    $("setupStatus").textContent = "";
    window.alert("Choose an answer first. An adaptive test needs a response to calibrate.");
    return;
  }
  bankTime();

  overlay("Checking and picking your next question…");
  const result = await call("/api/adaptive/answer", {
    session_id: a.sessionId,
    question_id: q.question_id,
    selected: [...response.selected],
    value: response.value,
    time_spent_seconds: Math.round(response.seconds),
  });
  hideOverlay();
  if (!result.ok) { showError(result, null); return; }

  a.answered = result.outcome.answered;
  a.difficulty = result.session.current_difficulty;
  a.trail.push(result.outcome);
  updateAdaptiveChip();

  if (result.question) {
    pushAdaptiveQuestion(result.question);
    renderPalette();
  } else {
    await finishAdaptive();
  }
}

async function finishAdaptive() {
  if (state.submitted) return;
  state.submitted = true;
  overlay("Grading and estimating your level…");
  const result = await call("/api/adaptive/finish", { session_id: state.adaptive.sessionId });
  hideOverlay();
  if (!result.ok) { state.submitted = false; showError(result, null); return; }
  renderReport(result, false, result.ability_estimate);
}

/* ------------------------------------------------------------------- report */

function accuracyBars(buckets) {
  if (!buckets || !buckets.length) return '<p class="muted">No data.</p>';
  return `<div class="barlist">${buckets
    .map((b) => {
      const value = b.accuracy_percentage;
      const cls = value === null ? "" : value >= 70 ? "is-high" : value >= 45 ? "is-mid" : "is-low";
      return `<div class="barrow">
        <span class="barrow-label" title="${esc(b.name)}">${esc(b.name)}</span>
        <span class="bartrack"><span class="barfill ${cls}" style="width:${value === null ? 0 : value}%"></span></span>
        <span class="barvalue">${pct(value, 0)} · ${b.correct}/${b.total_questions}</span>
      </div>`;
    })
    .join("")}</div>`;
}

function stackBars(buckets) {
  if (!buckets || !buckets.length) return '<p class="muted">No data.</p>';
  return `<div class="barlist">${buckets
    .map((b) => {
      const total = b.total_questions || 1;
      const w = (n) => `${((n / total) * 100).toFixed(1)}%`;
      return `<div class="barrow">
        <span class="barrow-label" title="${esc(b.name)}">${esc(b.name)}</span>
        <span class="stack">
          <span class="s-correct" style="width:${w(b.correct)}" title="${b.correct} correct"></span>
          <span class="s-incorrect" style="width:${w(b.incorrect)}" title="${b.incorrect} incorrect"></span>
          <span class="s-unattempted" style="width:${w(b.unattempted)}" title="${b.unattempted} unattempted"></span>
        </span>
        <span class="barvalue">${num(b.marks_awarded)}/${num(b.marks_possible)}</span>
      </div>`;
    })
    .join("")}</div>`;
}

const STACK_LEGEND = `<ul class="legend">
  <li><span class="dot dot-correct"></span> Correct</li>
  <li><span class="dot dot-incorrect"></span> Incorrect</li>
  <li><span class="dot dot-unattempted"></span> Unattempted</li>
</ul>`;

function bulletCard(title, items, emptyText) {
  const list = (items || []).length
    ? `<ul class="bullets">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`
    : `<p class="muted">${esc(emptyText)}</p>`;
  return `<section class="card"><h3>${esc(title)}</h3>${list}</section>`;
}

function tagClassFor(tag) {
  if (tag.startsWith("Low accuracy")) return "rtag-accuracy";
  if (tag.startsWith("Avoided")) return "rtag-avoided";
  return "rtag-time";
}

function weakAreaCard(weak) {
  if (!weak) return "";
  const areas = weak.weak_areas || [];
  const body = areas.length
    ? areas
        .map(
          (a) => `<div class="rec">
            <div class="rec-top"><span class="rec-topic">${esc(a.name)}</span></div>
            <div class="tagset">${a.reason_tags.map((t) => `<span class="rtag ${tagClassFor(t)}">${esc(t)}</span>`).join("")}</div>
            <div class="rec-reason">${esc(a.detail)}</div>
            <div class="rec-action">Suggested: <b>${esc(a.suggested_test_type)}</b> — ${esc(a.suggested_action)}</div>
          </div>`
        )
        .join("")
    : `<p class="muted">${esc(weak.message || "Nothing flagged yet.")}</p>`;
  return `<section class="card">
    <h3>Weak areas &amp; what to do</h3>
    ${body}
    <p class="small-note">${esc(weak.threshold_used || "")}</p>
  </section>`;
}

function readinessCard(readiness) {
  if (!readiness || !readiness.label) {
    return `<section class="card"><h3>Readiness</h3>
      <p class="muted">${esc((readiness && readiness.reasoning) || "Not enough data yet.")}</p>
      <p class="small-note">${esc((readiness && readiness.improve_confidence) || "")}</p></section>`;
  }
  const cls =
    readiness.label === "Exam-Ready" ? "is-ready" : readiness.label === "On Track" ? "is-track" : "is-work";
  return `<section class="card">
    <h3>Readiness estimate</h3>
    <p><span class="readiness-band ${cls}">${esc(readiness.label)}</span>
       <span class="conf">${esc(readiness.confidence)} confidence</span></p>
    <p>${esc(readiness.reasoning)}</p>
    ${readiness.improve_confidence ? `<p class="rec-action">${esc(readiness.improve_confidence)}</p>` : ""}
    <p class="small-note">${esc(readiness.caveat)}</p>
  </section>`;
}

function abilityCard(ability) {
  if (!ability) return "";
  return `<section class="card">
    <h3>Ability estimate by topic</h3>
    <p>Overall estimated level: <b>${esc(ability.overall_estimated_level)}</b> after
       ${ability.questions_answered} question(s)${ability.stopped_early ? ", stopped early once your level was clear" : ""}.</p>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>Topic</th><th>Level</th><th class="num">Correct</th><th>Confidence</th></tr></thead>
      <tbody>${(ability.per_topic || [])
        .map(
          (t) => `<tr><td>${esc(t.topic)}</td><td>${esc(t.estimated_level)}</td>
            <td class="num">${t.correct}/${t.attempted}</td><td>${esc(t.confidence)}</td></tr>`
        )
        .join("")}</tbody>
    </table></div>
    <p class="small-note">${esc(ability.caveat)}</p>
  </section>`;
}

function renderReport(payload, auto, ability) {
  const report = payload.report;
  const paper = payload.paper;
  const s = report.summary;
  const timing = report.time_utilisation || {};
  const scoreClass = s.score_percentage >= 60 ? "is-good" : s.score_percentage < 33 ? "is-bad" : "";
  const attempted = s.correct + s.incorrect + (s.partially_correct || 0);

  const answersById = {};
  ((paper && paper.sections) || []).forEach((section) =>
    (section.questions || []).forEach((q) => { answersById[q.question_id] = q; })
  );

  const review = (report.question_wise_results || [])
    .map((r) => {
      const q = answersById[r.question_id] || {};
      const cls =
        r.status === "Correct" ? "v-correct"
        : r.status === "Incorrect" ? "v-incorrect"
        : r.status === "Partially Correct" ? "v-partial" : "v-unattempted";
      const sol = q.solution;
      return `<div class="review-q">
        <div class="question-head" style="margin-bottom:8px;padding-bottom:8px">
          <span class="qnum">Q${r.number}</span>
          <span class="verdict ${cls}">${esc(r.status)}</span>
          <span class="tag">${esc(r.chapter)}</span>
          <span class="tag">${esc(r.difficulty)}</span>
          <span class="tag tag-marks">${num(r.marks_awarded)} / ${num(r.marks_possible)}</span>
        </div>
        <p class="qtext" style="font-size:14.5px">${esc(q.text || "")}</p>
        ${(q.options || [])
          .map(
            (o) => `<div class="ans">(${esc(o.key)}) ${esc(o.text)}${
              (r.correct_answer || "").includes(o.key) ? " &nbsp;<b>&larr; correct</b>" : ""
            }</div>`
          )
          .join("")}
        <p class="ans">Your answer: <b>${esc(r.your_answer || "not attempted")}</b> · Correct: <b>${esc(r.correct_answer)}</b>${
          r.time_spent_seconds ? ` · ${num(r.time_spent_seconds)}s` : ""
        }</p>
        ${
          sol
            ? `<div class="solution">
                <h5>Solution</h5>
                <p>${esc(sol.explanation || "")}</p>
                ${(sol.steps || []).length ? `<ol>${sol.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>` : ""}
                ${sol.formula_used ? `<p><strong>Formula:</strong> ${esc(sol.formula_used)}</p>` : ""}
                ${(sol.common_mistakes || []).map((m) => `<p class="mistake">Common mistake: ${esc(m)}</p>`).join("")}
                ${sol.time_saving_tip ? `<p class="tip">Tip: ${esc(sol.time_saving_tip)}</p>` : ""}
                ${sol.final_answer ? `<p><strong>Final answer:</strong> ${esc(sol.final_answer)}</p>` : ""}
              </div>`
            : ""
        }
      </div>`;
    })
    .join("");

  $("reportBody").innerHTML = `
    <div class="report-head">
      <div>
        <h2>${esc(report.test_title)}</h2>
        <p class="muted">${esc(report.exam)}${auto ? " · submitted automatically when time ran out" : ""} · test ${payload.attempt_count || ""} on record</p>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn btn-secondary" id="btnPrint" type="button">Print</button>
        <button class="btn btn-secondary" id="btnProgress2" type="button">Progress</button>
        <button class="btn btn-primary" id="btnNewTest" type="button">New test</button>
      </div>
    </div>

    <div class="tiles">
      <div class="tile"><div class="tile-label">Score</div>
        <div class="tile-value ${scoreClass}">${num(s.total_score)}<span style="font-size:16px;color:var(--text-muted)"> / ${num(s.maximum_marks)}</span></div>
        <div class="tile-sub">${pct(s.score_percentage)} of the paper</div></div>
      <div class="tile"><div class="tile-label">Accuracy</div>
        <div class="tile-value">${pct(s.accuracy_percentage, 0)}</div>
        <div class="tile-sub">of the ${attempted} you attempted</div></div>
      <div class="tile"><div class="tile-label">Attempted</div>
        <div class="tile-value">${attempted}<span style="font-size:16px;color:var(--text-muted)"> / ${s.total_questions}</span></div>
        <div class="tile-sub">${s.unattempted} left, worth ${num(s.marks_left_on_the_table)} marks</div></div>
      <div class="tile"><div class="tile-label">Lost to penalty</div>
        <div class="tile-value">${num(s.negative_marks_lost)}</div>
        <div class="tile-sub">marks deducted for wrong answers</div></div>
    </div>

    <section class="card" style="margin-bottom:16px">
      <h3>Personalised feedback</h3>
      <p>${esc(report.personalised_feedback)}</p>
      ${report.readiness && report.readiness.estimated_percentile_range
        ? `<p class="small-note">Relative estimate: ${esc(report.readiness.estimated_percentile_range)}. ${esc(report.readiness.disclaimer)}</p>`
        : ""}
    </section>

    ${ability ? abilityCard(ability) + '<div style="height:16px"></div>' : ""}

    <div class="grid-2">
      <section class="card"><h3>Subject-wise accuracy</h3>${accuracyBars(report.subject_performance)}</section>
      <section class="card"><h3>Difficulty-wise outcome</h3>${stackBars(report.difficulty_performance)}${STACK_LEGEND}</section>
    </div>
    <div class="grid-2" style="margin-top:16px">
      <section class="card"><h3>Chapter-wise accuracy</h3>${accuracyBars(report.chapter_performance)}</section>
      <section class="card"><h3>Section-wise outcome</h3>${stackBars(report.section_performance)}${STACK_LEGEND}</section>
    </div>

    <div class="grid-2" style="margin-top:16px">
      ${bulletCard("Strengths", report.strengths, "Nothing cleared the strength threshold in this attempt.")}
      ${bulletCard("Areas for improvement", report.areas_for_improvement, "No specific weakness stood out.")}
    </div>

    <div class="grid-2" style="margin-top:16px">
      ${weakAreaCard(payload.weak_areas)}
      ${readinessCard(payload.readiness_estimate)}
    </div>

    <div class="grid-2" style="margin-top:16px">
      ${
        timing.timing_data_available
          ? `<section class="card"><h3>Time utilisation</h3>
              <div class="kv"><dt>Used</dt><dd>${num(timing.used_minutes)} / ${num(timing.allotted_minutes)} min (${pct(timing.utilisation_percentage, 0)})</dd></div>
              <div class="kv"><dt>Per attempted question</dt><dd>${num(timing.average_seconds_per_attempted_question)}s</dd></div>
              <div class="kv"><dt>Fair budget</dt><dd>${num(timing.fair_seconds_per_question)}s</dd></div>
              ${(timing.slowest_questions || []).length
                ? `<h4 style="margin:14px 0 4px;font-size:12.5px">Slowest questions</h4>
                   <div class="table-wrap"><table class="data"><thead><tr><th>Q</th><th>Topic</th><th>Status</th><th class="num">Sec</th></tr></thead>
                   <tbody>${timing.slowest_questions.map((q) => `<tr><td>${esc(q.question_id)}</td><td>${esc(q.topic)}</td><td>${esc(q.status)}</td><td class="num">${num(q.seconds)}</td></tr>`).join("")}</tbody></table></div>`
                : ""}
            </section>`
          : `<section class="card"><h3>Time utilisation</h3><p class="muted">No timing data was recorded for this attempt.</p></section>`
      }
      ${
        (report.revision_plan || []).length
          ? `<section class="card"><h3>Revision plan</h3>${report.revision_plan
              .map((d) => `<div class="plan-day"><b>Day ${esc(d.day)}</b><div><strong>${esc(d.focus)}</strong><br>${esc(d.activity)}</div></div>`)
              .join("")}</section>`
          : bulletCard("Weak concepts", report.weak_concepts, "No topic-level gaps identified.")
      }
    </div>

    ${
      report.suggested_next_test
        ? `<section class="card" style="margin-top:16px"><h3>Suggested next test</h3>
            <p>${esc(report.suggested_next_test.rationale)}</p>
            <button class="btn btn-primary" id="btnApplyNext" type="button">Set this up</button></section>`
        : ""
    }

    <section class="card" style="margin-top:16px">
      <h3>Question-by-question review</h3>
      ${review || '<p class="muted">No questions to review.</p>'}
    </section>

    <section class="card" style="margin-top:16px">
      <h3>Important</h3>
      <ul class="bullets">${(report.disclaimers || []).map((d) => `<li>${esc(d)}</li>`).join("")}</ul>
    </section>`;

  $("btnPrint").addEventListener("click", () => window.print());
  $("btnNewTest").addEventListener("click", () => { banner(null); show("dash"); });
  $("btnProgress2").addEventListener("click", openProgress);
  const applyNext = $("btnApplyNext");
  if (applyNext) applyNext.addEventListener("click", () => applyNextTest(report.suggested_next_test.request));

  if (state.user) {
    state.user.attempt_count = payload.attempt_count || state.user.attempt_count;
    $("userLine").textContent = `${state.user.name} · ${state.user.attempt_count} test(s) completed`;
  }
  show("report");
}

async function applyNextTest(request) {
  const modeId = request.test_type || "Full Mock";
  if (request.exam && request.exam !== $("exam").value) {
    $("exam").value = request.exam;
    await onExamChange();
  }
  state.selectedSubjects = new Set(request.subjects || []);
  state.selectedChapters = new Set(request.chapters || []);
  state.selectedTopics = new Set(request.topics || []);
  openOptions(modeId);
  if (request.num_questions) $("numQuestions").value = request.num_questions;
  if (request.difficulty && request.difficulty !== "Mixed") $("difficulty").value = request.difficulty;
  $("setupStatus").textContent = "Loaded the suggested test. Adjust anything, then generate.";
}

/* ----------------------------------------------------------------- progress */

async function openProgress() {
  overlay("Loading your progress…");
  const [diag, hist] = await Promise.all([call("/api/diagnostics"), call("/api/history")]);
  hideOverlay();
  if (!diag.ok) { showError(diag, null); return; }

  const attempts = ((hist.ok && hist.history.attempts) || []).slice().reverse();
  const readiness = diag.readiness;
  const weak = diag.weak_areas;

  if (!attempts.length) {
    $("progressBody").innerHTML = `
      <div class="card empty">
        <h3>No tests yet</h3>
        <p>Take your first test and this page will fill with trends, weak areas and a readiness estimate.</p>
        <button class="btn btn-primary" id="btnGoDash" type="button" style="margin-top:14px">Choose a test</button>
      </div>`;
    $("btnGoDash").addEventListener("click", () => show("dash"));
    show("progress");
    return;
  }

  const maxPct = 100;
  const trend = attempts
    .slice(0, 12)
    .reverse()
    .map((a) => {
      const value = a.max_marks > 0 ? (100 * a.score) / a.max_marks : 0;
      const clamped = Math.max(0, Math.min(maxPct, value));
      const cls = clamped >= 70 ? "is-high" : clamped >= 50 ? "is-mid" : "is-low";
      return `<div class="trend-row">
        <span class="barrow-label">${esc(a.taken_on || a.exam || "test")}</span>
        <span class="bartrack"><span class="barfill ${cls}" style="width:${clamped.toFixed(1)}%"></span></span>
        <span class="barvalue">${value.toFixed(0)}% · ${num(a.score)}/${num(a.max_marks)}</span>
      </div>`;
    })
    .join("");

  $("progressBody").innerHTML = `
    <div class="report-head">
      <div><h2>Your progress</h2><p class="muted">${attempts.length} completed test(s) on record</p></div>
      <div style="display:flex;gap:10px">
        <button class="btn btn-ghost" id="btnClearHistory" type="button">Clear history</button>
        <button class="btn btn-primary" id="btnGoDash" type="button">New test</button>
      </div>
    </div>

    <div class="grid-2">
      ${readinessCard(readiness)}
      <section class="card"><h3>Score trend</h3><div class="trend-list">${trend}</div>
        <p class="small-note">Oldest at the top, newest at the bottom.</p></section>
    </div>

    <div style="margin-top:16px">${weakAreaCard(weak)}</div>

    ${
      (weak.needs_more_evidence || []).length
        ? `<section class="card" style="margin-top:16px"><h3>Not enough evidence yet</h3>
            <p class="muted">These look shaky but have been seen too few times to judge. Attempt more questions here before drawing a conclusion.</p>
            <ul class="bullets">${weak.needs_more_evidence.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></section>`
        : ""
    }`;

  $("btnGoDash").addEventListener("click", () => show("dash"));
  $("btnClearHistory").addEventListener("click", async () => {
    if (!window.confirm("Delete all your attempt history? This cannot be undone.")) return;
    await call("/api/history/clear", {});
    openProgress();
  });
  show("progress");
}

/* --------------------------------------------------------------- wiring up */

$("exam").addEventListener("change", onExamChange);
$("chapterSearch").addEventListener("input", renderChapters);
$("btnBackToModes").addEventListener("click", () => { banner(null); show("dash"); });
$("btnPreview").addEventListener("click", doPreview);
$("btnGenerate").addEventListener("click", doGenerate);
$("navDash").addEventListener("click", () => { banner(null); show("dash"); });
$("navProgress").addEventListener("click", openProgress);

$("btnPrev").addEventListener("click", () => goTo(state.current - 1));
$("btnNext").addEventListener("click", () => {
  if (state.adaptive) submitAdaptiveAnswer();
  else goTo(state.current + 1);
});
$("btnSubmit").addEventListener("click", () => submitTest(false));
$("btnClear").addEventListener("click", () => {
  const response = state.responses.get(state.questions[state.current].question_id);
  response.selected.clear();
  response.value = null;
  renderQuestion();
  renderPalette();
});
$("btnMark").addEventListener("click", () => {
  const response = state.responses.get(state.questions[state.current].question_id);
  response.marked = !response.marked;
  renderQuestion();
  renderPalette();
});

$("themeToggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme === "dark";
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  $("themeToggle").textContent = dark ? "Dark" : "Light";
});

document.addEventListener("keydown", (event) => {
  if ($("view-test").hidden || state.adaptive) return;
  if (event.target.matches("input, textarea, select")) return;
  if (event.key === "ArrowRight") goTo(state.current + 1);
  if (event.key === "ArrowLeft") goTo(state.current - 1);
});

window.addEventListener("beforeunload", (event) => {
  if (!$("view-test").hidden && !state.submitted) {
    event.preventDefault();
    event.returnValue = "";
  }
});

boot().catch((error) => {
  $("view-auth").hidden = false;
  $("loginError").textContent = `Could not reach the engine: ${error.message}`;
});
