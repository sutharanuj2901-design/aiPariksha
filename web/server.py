"""Local web app, built on the standard library only.

No framework, no build step, no pip install — ``python -m aipariksha serve`` and
open the browser.

Two design decisions matter:

* **Generated papers stay server-side.** The browser receives the redacted
  student view, so correct answers never reach the client until submission.
  Grading looks the paper up by id.
* **Attempt history is persisted per account**, because weak-area detection and
  readiness estimation are only meaningful across several tests.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from collections import OrderedDict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from ..accounts import AccountStore, User
from ..config import Settings, load_settings
from ..engine import AIPariksha
from ..errors import AIParikshaError, ValidationError
from ..models.enums import TestType

STATIC_DIR = Path(__file__).resolve().parent / "static"

SESSION_COOKIE = "aip_session"

#: Cap on retained papers. This is a small local deployment, not a cluster; a
#: real one would put these in a database.
MAX_PAPERS = 96


class PaperStore:
    """Thread-safe, bounded store of generated papers (with answers)."""

    def __init__(self, limit: int = MAX_PAPERS) -> None:
        self._papers: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._limit = limit

    def put(self, paper: Mapping[str, Any]) -> None:
        paper_id = str(paper.get("paper_id") or "")
        if not paper_id:
            return
        with self._lock:
            self._papers[paper_id] = dict(paper)
            self._papers.move_to_end(paper_id)
            while len(self._papers) > self._limit:
                self._papers.popitem(last=False)

    def get(self, paper_id: str) -> dict[str, Any] | None:
        with self._lock:
            paper = self._papers.get(str(paper_id))
            if paper is not None:
                self._papers.move_to_end(str(paper_id))
            return paper


class Handler(BaseHTTPRequestHandler):
    server_version = "AIPariksha"
    engine: AIPariksha
    store: PaperStore
    accounts: AccountStore
    quiet: bool = True

    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------- routing

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlparse(self.path)
        path = route.path
        query = {k: v[0] for k, v in parse_qs(route.query).items()}

        if path in ("/", "/index.html"):
            self._send_static("index.html")
            return
        if path.startswith("/static/"):
            self._send_static(path[len("/static/") :])
            return

        handlers: Mapping[str, Callable[[], None]] = {
            "/api/config": lambda: self._send_json(
                {"ok": True, "engine": self.engine.settings.describe()}
            ),
            "/api/exams": lambda: self._send_json(self.engine.catalogue()),
            "/api/pattern": lambda: self._send_json(self.engine.pattern(query.get("exam", ""))),
            "/api/syllabus": lambda: self._send_json(
                self.engine.syllabus(query.get("exam", ""), query.get("subject") or None)
            ),
            "/api/auth/me": self._me,
            "/api/diagnostics": self._diagnostics,
            "/api/history": self._history,
        }
        action = handlers.get(path)
        if action is None:
            self._not_found(path)
            return
        action()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except ValueError as error:
            self._send_json(
                {"ok": False, "error": {"code": "invalid_json", "message": str(error)}}, 400
            )
            return

        routes: Mapping[str, Callable[[Mapping[str, Any]], None]] = {
            "/api/auth/register": self._register,
            "/api/auth/login": self._login,
            "/api/auth/logout": self._logout,
            "/api/profile": self._profile,
            "/api/preview": lambda body: self._send_json(self.engine.preview(body)),
            "/api/generate": self._generate,
            "/api/evaluate": self._evaluate,
            "/api/adaptive/start": self._adaptive_start,
            "/api/adaptive/answer": self._adaptive_answer,
            "/api/adaptive/finish": self._adaptive_finish,
            "/api/history/clear": self._clear_history,
        }
        action = routes.get(path)
        if action is None:
            self._not_found(path)
            return
        action(payload)

    # ---------------------------------------------------------------------- auth

    def _register(self, body: Mapping[str, Any]) -> None:
        try:
            user, token = self.accounts.register(
                body.get("name", ""),
                body.get("email", ""),
                body.get("password", ""),
                body.get("target_exam", ""),
            )
        except AIParikshaError as error:
            self._send_json(error.to_dict(), error.http_status)
            return
        self._send_json({"ok": True, "user": user.public()}, cookie=token)

    def _login(self, body: Mapping[str, Any]) -> None:
        try:
            user, token = self.accounts.login(body.get("email", ""), body.get("password", ""))
        except AIParikshaError as error:
            self._send_json(error.to_dict(), 401)
            return
        self._send_json({"ok": True, "user": user.public()}, cookie=token)

    def _logout(self, _body: Mapping[str, Any]) -> None:
        self.accounts.logout(self._token())
        self._send_json({"ok": True}, cookie="")

    def _me(self) -> None:
        user = self._user()
        if user is None:
            self._send_json({"ok": False, "error": {"code": "not_signed_in", "message": ""}}, 401)
            return
        self._send_json({"ok": True, "user": user.public()})

    def _profile(self, body: Mapping[str, Any]) -> None:
        user = self._require_user()
        if user is None:
            return
        self.accounts.set_target_exam(user, str(body.get("target_exam") or ""))
        self._send_json({"ok": True, "user": user.public()})

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 - a malformed cookie is just "no session"
            return None
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _user(self) -> User | None:
        return self.accounts.user_for_token(self._token())

    def _require_user(self) -> User | None:
        """Return the signed-in user, or emit a 401 and return None."""
        user = self._user()
        if user is None:
            self._send_json(
                {
                    "ok": False,
                    "error": {
                        "code": "not_signed_in",
                        "message": "Please sign in to continue.",
                    },
                },
                401,
            )
        return user

    # ----------------------------------------------------------------- generation

    def _generate(self, body: Mapping[str, Any]) -> None:
        user = self._require_user()
        if user is None:
            return

        payload = dict(body)
        payload.setdefault("student_history", self.accounts.history_payload(user))

        result = self.engine.generate(payload)
        if not result.get("ok"):
            self._send_json(result, 400)
            return

        paper = result["paper"]
        self.store.put(paper)
        student = self.engine.student_view(paper)
        self._send_json(
            {
                "ok": True,
                "paper": student["paper"],
                "paper_id": paper["paper_id"],
                "notes": result.get("notes", {}),
                "blueprint": paper.get("blueprint", {}),
                "request": paper.get("request", {}),
                "quality_report": paper.get("quality_report", {}),
                "disclaimers": paper.get("disclaimers", []),
            }
        )

    def _evaluate(self, body: Mapping[str, Any]) -> None:
        user = self._require_user()
        if user is None:
            return

        paper = self.store.get(str(body.get("paper_id") or ""))
        if paper is None:
            self._send_json(
                {
                    "ok": False,
                    "error": {
                        "code": "paper_not_found",
                        "message": (
                            "That paper is no longer held by the server. Generate a new one."
                        ),
                    },
                },
                404,
            )
            return

        result = self.engine.evaluate(
            {
                "paper": paper,
                "submission": body.get("submission") or {},
                "student_history": self.accounts.history_payload(user),
            }
        )
        if not result.get("ok"):
            self._send_json(result, 400)
            return

        self._finalise_attempt(user, result, paper)

    def _finalise_attempt(
        self, user: User, result: dict[str, Any], paper: Mapping[str, Any] | None
    ) -> None:
        """Persist the attempt, then attach the refreshed diagnostics."""
        entry = result.get("history_entry")
        if entry:
            self.accounts.record_attempt(user, entry)

        history = self.accounts.history_payload(user)
        diagnostics = self.engine.diagnostics({"student_history": history})
        if paper is not None:
            result["paper"] = paper
        result["weak_areas"] = diagnostics.get("weak_areas")
        result["readiness_estimate"] = diagnostics.get("readiness")
        result["attempt_count"] = len(history.get("attempts", []))
        self._send_json(result)

    # ------------------------------------------------------------------ adaptive

    def _adaptive_start(self, body: Mapping[str, Any]) -> None:
        user = self._require_user()
        if user is None:
            return
        payload = dict(body)
        payload.setdefault("student_history", self.accounts.history_payload(user))
        result = self.engine.adaptive_start(payload)
        self._send_json(result, 200 if result.get("ok") else 400)

    def _adaptive_answer(self, body: Mapping[str, Any]) -> None:
        if self._require_user() is None:
            return
        result = self.engine.adaptive_answer(body)
        self._send_json(result, 200 if result.get("ok") else 400)

    def _adaptive_finish(self, body: Mapping[str, Any]) -> None:
        user = self._require_user()
        if user is None:
            return
        result = self.engine.adaptive_finish(
            {**dict(body), "student_history": self.accounts.history_payload(user)}
        )
        if not result.get("ok"):
            self._send_json(result, 400)
            return
        self._finalise_attempt(user, result, result.get("paper"))

    # --------------------------------------------------------------- diagnostics

    def _diagnostics(self) -> None:
        user = self._require_user()
        if user is None:
            return
        self._send_json(
            self.engine.diagnostics({"student_history": self.accounts.history_payload(user)})
        )

    def _history(self) -> None:
        user = self._require_user()
        if user is None:
            return
        history = self.accounts.history_payload(user)
        self._send_json({"ok": True, "history": history, "user": user.public()})

    def _clear_history(self, _body: Mapping[str, Any]) -> None:
        user = self._require_user()
        if user is None:
            return
        self.accounts.clear_history(user)
        self._send_json({"ok": True, "user": user.public()})

    # ------------------------------------------------------------------ plumbing

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Malformed JSON body: {error}") from error
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object at the top level.")
        return data

    def _send_json(
        self, payload: Mapping[str, Any], status: int = 200, *, cookie: str | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            if cookie:
                self.send_header(
                    "Set-Cookie",
                    f"{SESSION_COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Strict",
                )
            else:
                self.send_header(
                    "Set-Cookie",
                    f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                )
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, path: str) -> None:
        self._send_json({"ok": False, "error": {"code": "not_found", "message": path}}, 404)

    def _send_static(self, relative: str) -> None:
        # Contain the path: no traversal outside the static directory.
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR)
        except ValueError:
            self._send_json({"ok": False, "error": {"code": "forbidden", "message": relative}}, 403)
            return
        if not target.is_file():
            self._not_found(relative)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith(("text/", "application/javascript")):
            content_type += "; charset=utf-8"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(fmt, *args)


def build_handler(
    engine: AIPariksha,
    *,
    accounts: AccountStore | None = None,
    quiet: bool = True,
) -> type[Handler]:
    """A handler class bound to one engine, store and account database."""
    return type(
        "BoundHandler",
        (Handler,),
        {
            "engine": engine,
            "store": PaperStore(),
            "accounts": accounts or AccountStore(),
            "quiet": quiet,
        },
    )


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    settings: Settings | None = None,
    open_browser: bool = True,
    verbose: bool = False,
) -> None:
    """Run the app until interrupted."""
    settings = settings or load_settings()
    engine = AIPariksha(settings)
    accounts = AccountStore()

    httpd = ThreadingHTTPServer((host, port), build_handler(engine, accounts=accounts, quiet=not verbose))
    url = f"http://{host}:{port}/"

    described = settings.describe()
    print(f"AIPariksha running at {url}")
    print(f"  provider: {described['provider']}   model: {described['model']}")
    if not described["api_key_configured"]:
        print(
            "  NOTE: no API key configured, so question text is placeholder.\n"
            "        Structure, marking, scoring and analytics are all real.\n"
            "        Set AIPARIKSHA_API_KEY for exam-quality questions."
        )
    print("  Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()
