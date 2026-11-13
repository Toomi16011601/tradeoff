"""Feedback CLI: local setup and offline reports, no web server."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from .contracts import FeedbackError, MAX_BYTES, parse_json, utc_time
from .serialization import output_chunks, output_json


class _Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        seen = getattr(namespace, "_feedback_seen", set())
        if self.dest in seen:
            raise FeedbackError("DUPLICATE_ARGUMENT", "Specify each feedback value option only once")
        namespace._feedback_seen = seen | {self.dest}
        setattr(namespace, self.dest, values)


def add_feedback_commands(sub):
    parser = sub.add_parser("feedback", help="Record agent decisions and inspect execution feedback locally")
    commands = parser.add_subparsers(dest="feedback_command", required=True)
    for name in ("init", "record", "bind-order", "import", "plan", "evaluate", "compare", "report", "sync-alpaca-paper", "demo", "mcp", "price-source", "collect"):
        p = commands.add_parser(name)
        p.add_argument("--project", action=_Once, default=".", help="Your trading workspace; feedback stays under its .tradeoff folder")
        p.add_argument("--json", action="store_true", help="Emit structured results")
        p.set_defaults(handler=_handle)
        if name == "init":
            p.add_argument("--environment", action=_Once, choices=["paper", "simulated", "live_import"], default=None)
        if name in {"record", "bind-order", "import", "plan"}:
            p.add_argument("--input", action=_Once, required=True, help="JSON arguments file, or - for standard input")
        if name in {"evaluate", "compare", "report", "collect"}:
            p.add_argument("--as-of", action=_Once, help="Aware ISO timestamp; defaults to now")
        if name in {"evaluate", "compare", "report"}:
            p.add_argument("--as-of-seq", action=_Once, type=int)
        if name == "price-source":
            for option in ("data", "symbol", "currency", "source", "feed", "price-kind"):
                p.add_argument("--" + option, action=_Once, required=True)
            for option in ("timestamp-column", "price-column", "available-at-column", "timezone", "session-close"):
                p.add_argument("--" + option, action=_Once)
            p.add_argument("--replace", action="store_true", help="Explicitly replace existing price-source settings; evidence is preserved")
        if name == "collect":
            p.add_argument("--output", action=_Once, help="Optional fresh offline-report directory")
        if name in {"compare", "report"}:
            p.add_argument("--plan-id", action=_Once, required=name == "compare")
        if name in {"report", "demo"}:
            p.add_argument("--output", action=_Once, default="feedback-output-demo" if name == "demo" else "feedback-output")
        if name == "report":
            p.add_argument("--include-snapshots", action="store_true", help="Explicitly include secret-scanned input snapshots")
        if name == "sync-alpaca-paper":
            p.add_argument("--source-alias", action=_Once, required=True)
            p.add_argument("--start", action=_Once, required=True)
            p.add_argument("--end", action=_Once, required=True)


def _handle(args):
    try:
        result = _run(args)
        if args.feedback_command == "mcp":
            return 0
        if args.json:
            sys.stdout.writelines(output_chunks(result))
            sys.stdout.write("\n")
        else:
            print(result["status"])
            if "collection" in result:
                counts = {name:sum(d["outcome_status"] == name for d in result["feedback"]["evaluation"]["decisions"])
                          for name in ("AVAILABLE", "PENDING", "UNAVAILABLE")}
                print(f"Outcomes: {counts['AVAILABLE']} available, {counts['PENDING']} waiting, {counts['UNAVAILABLE']} unresolved; {result['collection']['new_marks']} new price marks.")
            if "interface" in result:
                print("Open report file: " + str(Path(args.project).absolute() / result.get("output", "") / result["interface"]))
            elif args.feedback_command in {"evaluate", "compare"}:
                sys.stdout.writelines(output_chunks(result))
                sys.stdout.write("\n")
            elif args.feedback_command == "init":
                print("Feedback stays on this device. Connect a Python hook or local MCP tool; see docs/feedback-integration.md.")
            elif args.feedback_command == "price-source":
                print("Next: In the project folder selected with --project, run:")
                print("  tradeoff feedback collect --project . --output feedback-output")
                print("Choose a fresh report directory if feedback-output already exists.")
        return 1 if result.get("status") == "PARTIAL_SYNC" else 0
    except FeedbackError as exc:
        result = {"status": "ERROR", "error": {"code": exc.code, "message": exc.message}}
    except Exception:
        result = {"status": "ERROR", "error": {"code": "INTERNAL_ERROR", "message": "Feedback operation failed"}}
    print(output_json(result))
    return 2


def _run(args):
    from .api import FeedbackApp
    from .store import FeedbackStore
    name = args.feedback_command
    if name == "init":
        with FeedbackStore(Path(args.project), create=True, environment=args.environment):
            return {"status": "INITIALIZED", "storage": ".tradeoff/feedback", "network": "None during initialization"}
    if name == "mcp":
        from .mcp import serve
        serve(Path(args.project))
        return {}
    app = FeedbackApp(Path(args.project))
    if name == "price-source":
        payload = {key:getattr(args, key) for key in ("symbol", "currency", "source", "feed", "price_kind")}
        payload.update(data_file=args.data, replace=args.replace)
        payload.update({key:getattr(args,key) for key in ("timestamp_column","price_column","available_at_column","timezone","session_close") if getattr(args,key) is not None})
        return app.dispatch("configure_price_source", payload)
    if name == "collect":
        payload = {key:getattr(args,key) for key in ("as_of","output") if getattr(args,key) is not None}
        return app.dispatch("collect_outcomes", payload)
    if name == "demo":
        target = app._output(args.output)
        from .demo import run_feedback_demo
        return {**run_feedback_demo(target), "output": args.output}
    mapping = {"record": "record_decision", "bind-order": "bind_order", "import": "import_evidence", "plan": "register_comparison",
        "evaluate": "evaluate_decisions", "compare": "compare_versions", "report": "export_feedback", "sync-alpaca-paper": "sync_paper_evidence"}
    if name in {"record", "bind-order", "import", "plan"}:
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        else:
            with Path(args.input).open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        payload = parse_json(raw)
    elif name == "sync-alpaca-paper":
        payload = {"source_alias": args.source_alias, "start": args.start, "end": args.end}
    else:
        payload = {"as_of": args.as_of or utc_time(datetime.now(timezone.utc))}
        if args.as_of_seq is not None:
            payload["as_of_seq"] = args.as_of_seq
        if getattr(args, "plan_id", None):
            payload["plan_id"] = args.plan_id
        if name == "report":
            payload.update(output=args.output, include_snapshots=args.include_snapshots)
    return app.dispatch(mapping[name], payload)
