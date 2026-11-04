"""One-command local setup and read-only doctor command boundaries."""
from pathlib import Path

from .cli import _Once
from .contracts import FeedbackError, canonical_json


def add_connection_commands(sub):
    for name, help_text in (("connect", "Prepare local agent feedback and test the installed Python/MCP connection"),
                            ("doctor", "Inspect local setup and missing feedback evidence without changing it")):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--project", action=_Once, default=".")
        parser.add_argument("--json", action="store_true")
        if name == "connect":
            parser.add_argument("--python", action=_Once, help="Installed tool environment's Python executable; defaults to this interpreter")
            parser.add_argument("--environment", action=_Once, choices=["paper", "simulated", "live_import"], default=None)
        else:
            parser.add_argument("--as-of", action=_Once, help="Aware ISO evaluation timestamp; defaults to now")
        parser.set_defaults(handler=_handle_connection)


def _handle_connection(args):
    try:
        if args.command == "connect":
            from .onboarding import connect
            result = connect(args.project, python=args.python, environment=args.environment)
            code = 0 if result["status"] == "SETUP_READY" else 2
        else:
            from .diagnostics import diagnose
            result = diagnose(args.project, as_of=args.as_of)
            code = 0 if result["status"] in {"EVIDENCE_AVAILABLE", "EVIDENCE_WAITING"} else 1
    except FeedbackError as exc:
        result = {"status": "ERROR", "error": {"code": exc.code, "message": exc.message}}
        code = 2
    except Exception:
        result = {"status": "ERROR", "error": {"code": "SETUP_FAILED", "message": "Local setup or diagnostics failed; no raw project details are included"}}
        code = 2
    if args.json or result["status"] == "ERROR":
        print(canonical_json(result))
    else:
        print(result["status"])
        print("Real agent hook: " + result.get("agent_hook", "NOT_VERIFIED"))
        if "self_test" in result:
            print("Isolated self-test: " + result["self_test"]["status"] + " (" + result["self_test"]["code"] + ")")
        if "instructions" in result:
            print("Open setup instructions: " + str(Path(args.project).absolute() / result["instructions"]))
        if "evidence_status" in result:
            print("Evidence: " + result["evidence_status"])
        for check in result.get("checks", []):
            print(f"[{check['status']}] {check['id']}: {check['message']}")
            if check["next_step"]:
                print("  Next: " + check["next_step"])
        if "next_step" in result:
            print("Next: " + result["next_step"])
    return code
