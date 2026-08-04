"""Command line interface — JSON in, JSON out.

    python -m aipariksha exams
    python -m aipariksha syllabus "NEET UG" --subject Physics
    python -m aipariksha preview examples/request_neet_full_mock.json
    python -m aipariksha generate examples/request_neet_full_mock.json -o paper.json
    python -m aipariksha generate paper.json --print --student
    python -m aipariksha evaluate paper.json examples/submission_sample.json --print

Every command writes a JSON envelope to stdout (or ``-o``) and exits non-zero on
a failure envelope, so it composes with shell pipelines and CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import formatting
from .config import load_settings
from .engine import AIPariksha
from .errors import AIParikshaError


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    settings = load_settings(
        provider=args.provider,
        model=args.model,
        batch_size=args.batch_size,
    )
    engine = AIPariksha(settings)

    # serve() blocks until interrupted and prints its own banner; there is no
    # envelope worth emitting afterwards.
    if args.command == "serve":
        from .web.server import serve as run_server

        run_server(
            args.host,
            args.port,
            settings=settings,
            open_browser=not args.no_browser,
            verbose=args.verbose,
        )
        return 0

    try:
        result, text = _dispatch(engine, args)
    except AIParikshaError as error:
        result, text = error.to_dict(), None
    except FileNotFoundError as error:
        result, text = {"ok": False, "error": {"code": "file_not_found", "message": str(error)}}, None
    except json.JSONDecodeError as error:
        result, text = (
            {"ok": False, "error": {"code": "invalid_json", "message": f"Malformed JSON input: {error}"}},
            None,
        )

    if text is not None and getattr(args, "print_text", False):
        _emit(text, args.output)
    else:
        _emit(json.dumps(result, indent=2, ensure_ascii=False), args.output)

    return 0 if result.get("ok") else 1


# ----------------------------------------------------------------------- parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aipariksha",
        description="AIPariksha - AI-first examination paper generation and evaluation.",
    )
    # Shared flags live on a parent parser so they are accepted both before and
    # after the subcommand. "generate req.json -o out.json" is what people
    # actually type, and a top-level-only option would reject it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", help="Override the provider (anthropic | offline).")
    common.add_argument("--model", help="Override the model id.")
    common.add_argument("--batch-size", type=int, help="Questions requested per provider call.")
    common.add_argument(
        "-o", "--output", type=Path, help="Write output to a file instead of stdout."
    )
    for action in common._actions:
        parser._add_action(action)

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("exams", parents=[common], help="List every registered exam.")

    syllabus = sub.add_parser(
        "syllabus", parents=[common], help="Show subjects, chapters and topics for an exam."
    )
    syllabus.add_argument("exam")
    syllabus.add_argument("--subject", help="Restrict to one subject.")

    pattern = sub.add_parser(
        "pattern", parents=[common], help="Show the official pattern for an exam."
    )
    pattern.add_argument("exam")

    preview = sub.add_parser(
        "preview", parents=[common],
        help="Blueprint a paper without calling a provider (free, instant).",
    )
    preview.add_argument("request", type=Path, help="Path to a request JSON file, or - for stdin.")

    generate = sub.add_parser("generate", parents=[common], help="Generate a paper.")
    generate.add_argument("request", type=Path, help="Path to a request JSON file, or - for stdin.")
    generate.add_argument(
        "--print", dest="print_text", action="store_true", help="Print a formatted paper instead of JSON."
    )
    generate.add_argument(
        "--student", action="store_true", help="With --print, hide answers and solutions."
    )

    evaluate = sub.add_parser(
        "evaluate", parents=[common], help="Grade a submission against a generated paper."
    )
    evaluate.add_argument("paper", type=Path, help="Paper JSON produced by 'generate'.")
    evaluate.add_argument("submission", type=Path, help="Submission JSON, or - for stdin.")
    evaluate.add_argument("--history", type=Path, help="Optional student history JSON.")
    evaluate.add_argument(
        "--print", dest="print_text", action="store_true", help="Print a formatted report instead of JSON."
    )

    render = sub.add_parser(
        "render", parents=[common], help="Format an existing paper or report JSON as text."
    )
    render.add_argument("file", type=Path)
    render.add_argument("--student", action="store_true", help="Hide answers and solutions.")

    serve = sub.add_parser("serve", parents=[common], help="Launch the web UI.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-browser", action="store_true", help="Do not open a browser.")
    serve.add_argument("--verbose", action="store_true", help="Log every HTTP request.")

    return parser


# --------------------------------------------------------------------- dispatch


def _dispatch(engine: AIPariksha, args: argparse.Namespace) -> tuple[dict[str, Any], str | None]:
    command = args.command

    if command == "exams":
        return engine.catalogue(), None

    if command == "pattern":
        return engine.pattern(args.exam), None

    if command == "syllabus":
        return engine.syllabus(args.exam, args.subject), None

    if command == "preview":
        return engine.preview(_read_json(args.request)), None

    if command == "generate":
        result = engine.generate(_read_json(args.request))
        if not result.get("ok"):
            return result, None
        paper = result["paper"]
        reveal = not args.student
        text = formatting.render_paper(
            paper if reveal else engine.student_view(paper)["paper"],
            include_solutions=reveal,
            include_key=reveal,
        )
        return result, text

    if command == "evaluate":
        payload: dict[str, Any] = {
            "paper": _unwrap_paper(_read_json(args.paper)),
            "submission": _read_json(args.submission),
        }
        if args.history:
            payload["student_history"] = _read_json(args.history)
        result = engine.evaluate(payload)
        if not result.get("ok"):
            return result, None
        return result, formatting.render_report(result["report"])

    if command == "render":
        data = _read_json(args.file)
        if "report" in data or "summary" in data:
            report = data.get("report", data)
            return {"ok": True}, formatting.render_report(report)
        paper = _unwrap_paper(data)
        if args.student:
            paper = engine.student_view(paper)["paper"]
        return {"ok": True}, formatting.render_paper(
            paper, include_solutions=not args.student, include_key=not args.student
        )

    return {"ok": False, "error": {"code": "unknown_command", "message": command}}, None


# ---------------------------------------------------------------------- helpers


def _read_json(path: Path) -> dict[str, Any]:
    if str(path) == "-":
        return json.loads(sys.stdin.read())
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise AIParikshaError(f"{path}: expected a JSON object at the top level.")
    return data


def _unwrap_paper(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept either a bare paper or the full ``generate`` envelope."""
    if "paper" in data and isinstance(data["paper"], Mapping):
        return data["paper"]
    return data


def _emit(text: str, output: Path | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"Written to {output}", file=sys.stderr)
    else:
        # Windows consoles default to a codepage that cannot encode Devanagari.
        try:
            print(text)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
            sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
