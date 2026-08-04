"""The web layer: routes, and the guarantee that answers stay server-side."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from aipariksha.config import Settings
from aipariksha.engine import AIPariksha
from aipariksha.web.server import STATIC_DIR, Handler, PaperStore

OFFLINE = Settings(api_key="", provider="offline", batch_size=10)


@pytest.fixture(scope="module")
def base_url():
    """A real server on a real socket, torn down afterwards."""
    handler = type(
        "TestHandler",
        (Handler,),
        {"engine": AIPariksha(OFFLINE), "store": PaperStore(), "quiet": True},
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def get(base, path):
    with urllib.request.urlopen(f"{base}{path}", timeout=15) as response:
        return response.status, response.read(), response.headers


def post(base, path, payload):
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


# ------------------------------------------------------------------- static


def test_static_assets_exist():
    for name in ("index.html", "styles.css", "app.js"):
        assert (STATIC_DIR / name).is_file(), name


def test_index_and_assets_are_served(base_url):
    status, body, headers = get(base_url, "/")
    assert status == 200
    assert b"AIPariksha" in body
    assert headers["Content-Type"].startswith("text/html")

    for path, marker in [("/static/styles.css", b"--series-1"), ("/static/app.js", b"buildRequest")]:
        status, body, _ = get(base_url, path)
        assert status == 200
        assert marker in body


def test_path_traversal_is_refused(base_url):
    for attempt in ("/static/../../config.py", "/static/..%2f..%2fengine.py"):
        try:
            status, body, _ = get(base_url, attempt)
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        assert status in (403, 404), attempt
        assert b"api_key" not in body


# ---------------------------------------------------------------------- api


def test_catalogue_and_syllabus_endpoints(base_url):
    status, body, _ = get(base_url, "/api/exams")
    assert status == 200
    data = json.loads(body)
    assert data["ok"] and len(data["exams"]) == 18

    status, body, _ = get(base_url, "/api/syllabus?exam=NEET%20UG&subject=Physics")
    data = json.loads(body)
    assert data["ok"]
    assert any(c["chapter"] == "Kinematics" for c in data["subjects"][0]["chapters"])

    status, body, _ = get(base_url, "/api/pattern?exam=SSC%20CGL")
    data = json.loads(body)
    assert data["ok"] and data["pattern"]["total_questions"] == 100


def test_unknown_exam_returns_an_envelope(base_url):
    status, body, _ = get(base_url, "/api/pattern?exam=Nonsense")
    assert json.loads(body)["ok"] is False


def test_preview_endpoint(base_url):
    status, data = post(base_url, "/api/preview", {"exam": "JEE Main", "seed": 1})
    assert status == 200 and data["ok"]
    assert data["blueprint"]["total_questions"] == 75


def test_clarification_is_returned_as_json_not_a_500(base_url):
    status, data = post(base_url, "/api/preview", {"exam": "NEET UG", "test_type": "Chapter Wise"})
    assert status == 200
    assert data["ok"] is False
    assert data["error"]["code"] == "clarification_needed"
    assert data["error"]["questions"]


def test_malformed_body_is_handled(base_url):
    request = urllib.request.Request(
        f"{base_url}/api/preview", data=b"{not json", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, data = response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        status, data = error.code, json.loads(error.read())
    assert status == 400
    assert data["error"]["code"] == "invalid_json"


def test_unknown_route_404s(base_url):
    for path in ("/api/nope", "/nope"):
        try:
            status, body, _ = get(base_url, path)
        except urllib.error.HTTPError as error:
            status = error.code
        assert status == 404, path


# ------------------------------------------- the integrity property that matters


def test_generate_never_leaks_answers_to_the_browser(base_url):
    status, data = post(base_url, "/api/generate", {"exam": "SSC CGL", "num_questions": 8, "seed": 1})
    assert status == 200 and data["ok"]

    # Substring checks on the whole payload would false-positive on the request
    # echo ("solutions": "Detailed" is a *setting*, not an answer), so assert on
    # the actual question objects.
    leaky = {"correct_answer", "correct_keys", "correct_value", "solution"}
    for section in data["paper"]["sections"]:
        for question in section["questions"]:
            assert not (leaky & question.keys()), question.keys() & leaky
            assert question["options"], "the student still needs the options"
            for option in question["options"]:
                assert set(option) <= {"key", "text", "text_hi"}

    assert "answer_key" not in data["paper"]
    assert data.get("answer_key") is None
    assert data["paper_id"]


def test_full_attempt_flow_through_http(base_url):
    """Generate, answer blind, submit by paper_id, get a graded report."""
    status, generated = post(
        base_url, "/api/generate", {"exam": "SSC CHSL", "num_questions": 12, "seed": 4}
    )
    assert generated["ok"]
    paper_id = generated["paper_id"]

    # The client cannot know the answers, so it guesses "A" everywhere.
    responses = [
        {"question_id": q["question_id"], "selected": "A", "time_spent_seconds": 20}
        for s in generated["paper"]["sections"]
        for q in s["questions"]
    ]
    status, result = post(
        base_url,
        "/api/evaluate",
        {"paper_id": paper_id, "submission": {"responses": responses}},
    )
    assert status == 200 and result["ok"], result
    report = result["report"]
    assert report["summary"]["total_questions"] == 12
    assert report["summary"]["unattempted"] == 0
    assert report["readiness"]["band"]
    # Answers and solutions are available now, for the review screen.
    assert "correct_answer" in result["paper"]["sections"][0]["questions"][0]
    assert report["question_wise_results"][0]["correct_answer"]


def test_evaluating_an_unknown_paper_id_is_a_clean_404(base_url):
    status, data = post(
        base_url, "/api/evaluate", {"paper_id": "does-not-exist", "submission": {"responses": []}}
    )
    assert status == 404
    assert data["error"]["code"] == "paper_not_found"


def test_store_evicts_oldest_beyond_its_limit():
    store = PaperStore(limit=2)
    for index in range(3):
        store.put({"paper_id": f"p{index}"})
    assert store.get("p0") is None
    assert store.get("p1") is not None
    assert store.get("p2") is not None
