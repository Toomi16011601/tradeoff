"""One application boundary for Python, CLI and local MCP."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re

from ..privacy import reject_sensitive_data
from .contracts import (FeedbackError, ID_PATTERN, canonical_json, schema_for, utc_time,
                        validate_schema)
from .serialization import output_hash
from .store import FeedbackStore, _no_symlinks
from .recorder import Recorder
from .reconcile import reconcile
from .metrics import evaluate
from .comparison import compare, register_plan

_ID = {"type": "string", "pattern": ID_PATTERN}
_TIME = {"type": "string", "x-feedback": "time"}
_SEQ = {"type": "integer", "minimum": 0}


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


OPERATIONS = {
    "configure_price_source": ("Configure an explicit local single-instrument price CSV; no file scanning or network", _schema({
        "data_file": {"type":"string", "minLength":1, "maxLength":4096},
        "symbol": _ID, "currency": schema_for("mark")["properties"]["currency"], "source": _ID, "feed": _ID,
        "price_kind": schema_for("mark")["properties"]["price_kind"],
        **{name:{"type":"string", "minLength":1, "maxLength":256} for name in ("timestamp_column","price_column","available_at_column","timezone","session_close")},
        "replace": {"type":"boolean"}}, ["data_file","symbol","currency","source","feed","price_kind"])),
    "collect_outcomes": ("Collect matching matured outcome prices from the configured local CSV and refresh feedback; missing fees stay unknown", _schema({
        "as_of": _TIME, "output": {"type":"string", "maxLength":256}}, [])),
    "record_decision": ("Record a validated intent before the caller submits its order", _schema({"event_id": _ID, "decision": schema_for("decision")}, ["event_id", "decision"])),
    "bind_order": ("Bind one actual order ID to a recorded decision", _schema({"event_id": _ID, "binding": schema_for("order_binding")}, ["event_id", "binding"])),
    "import_evidence": ("Import normalized retrospective evidence, never prospective capture", _schema({"records": {"type": "array", "items": {"type": "object"}}}, ["records"])),
    "register_comparison": ("Record a comparison plan before its evaluation window", _schema({"event_id": _ID, "plan": schema_for("comparison_plan")}, ["event_id", "plan"])),
    "evaluate_decisions": ("Evaluate stored evidence with explicit unknown costs and exclusions", _schema({"as_of": _TIME, "as_of_seq": _SEQ}, ["as_of"])),
    "compare_versions": ("Compare declared observed episodes or explicitly modeled simulated accounts; does not declare a profitable winner", _schema({"plan_id": _ID, "as_of": _TIME, "as_of_seq": _SEQ}, ["plan_id", "as_of"])),
    "sync_paper_evidence": ("GET-only Alpaca paper sync using local credentials", _schema({"source_alias": _ID, "start": _TIME, "end": _TIME}, ["source_alias", "start", "end"])),
    "export_feedback": ("Write a fresh local offline report with pseudonymized evidence", _schema({"output": {"type": "string", "maxLength": 256}, "as_of": _TIME, "as_of_seq": _SEQ,
        "plan_id": _ID, "include_snapshots": {"type": "boolean"}}, ["output", "as_of"])),
}


def operation_definitions():
    return [{"operation": name, "description": desc, "input_schema": schema,
        "annotations": {"read_only_hint": name in {"evaluate_decisions", "compare_versions"},
            "destructive_hint": False, "idempotent_hint": name in {"record_decision", "bind_order", "register_comparison", "evaluate_decisions", "compare_versions", "configure_price_source", "collect_outcomes"},
            "open_world_hint": name == "sync_paper_evidence"}}
        for name, (desc, schema) in OPERATIONS.items()]


def _arguments(operation, args):
    canonical_json(args)
    try:
        reject_sensitive_data(args)
    except ValueError:
        raise FeedbackError("SENSITIVE_DATA", "Remove private fields and recognized sensitive data") from None
    if operation not in OPERATIONS:
        raise FeedbackError("UNKNOWN_OPERATION", "Unknown feedback operation")
    return validate_schema(args, OPERATIONS[operation][1])


class FeedbackApp:
    def __init__(self, project, *, clock=None, paper_reader_factory=None):
        self.project = Path(project).absolute()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.paper_reader_factory = paper_reader_factory

    def dispatch(self, operation, arguments):
        if operation not in OPERATIONS:
            raise FeedbackError("UNKNOWN_OPERATION", "Unknown feedback operation")
        return getattr(self, operation)(arguments)

    def record_decision(self, args):
        a = _arguments("record_decision", args)
        return {"status": "RECORDED", **Recorder(self.project, clock=self.clock).record_decision(a["decision"], event_id=a["event_id"])}

    def configure_price_source(self, args):
        # A local path is private configuration, not portable financial data.
        # Normalize its representation without weakening credential scanning.
        if isinstance(args, dict) and isinstance(args.get("data_file"), str) and Path(args["data_file"]).is_absolute():
            try:
                args = {**args, "data_file":os.path.relpath(args["data_file"], self.project)}
            except ValueError:
                raise FeedbackError("PRICE_PATH_VOLUME", "Select a CSV on the same filesystem volume as the project") from None
        a = _arguments("configure_price_source", args)
        from .outcomes import configure_source
        with FeedbackStore(self.project, clock=self.clock) as store, store.transaction():
            store.verify_chain()
            return configure_source(store, a)

    def collect_outcomes(self, args):
        a = _arguments("collect_outcomes", args)
        target = self._output(a["output"]) if "output" in a else None
        from .outcomes import collect
        with FeedbackStore(self.project, clock=self.clock) as store, store.transaction():
            before, after, collection, cutoff = collect(store, as_of=a.get("as_of"))
            previous = self._evaluate(before, cutoff)
            evaluation = self._evaluate(after, cutoff)
            available = lambda result: sum(d["outcome_status"] == "AVAILABLE" for d in result["decisions"])
            collection["newly_available_outcomes"] = available(evaluation) - available(previous)
            result = {"status":"COLLECTED", "collection":collection,
                      "feedback":self._report(after, evaluation, cutoff)}
        if target is not None:
            from .export import export_feedback
            try:
                result.update(export_feedback(after, evaluation, None, target), output=a["output"])
            except Exception as exc:
                code = exc.code if isinstance(exc, FeedbackError) else "INTERNAL_ERROR"
                raise FeedbackError("COLLECTED_EXPORT_FAILED",
                    "Outcome marks were saved; offline export failed (" + code +
                    "). Retry collection with a fresh writable output directory") from None
        return result

    def bind_order(self, args):
        a = _arguments("bind_order", args)
        return {"status": "BOUND", **Recorder(self.project, clock=self.clock).bind_order(a["binding"], event_id=a["event_id"])}

    def import_evidence(self, args):
        a = _arguments("import_evidence", args)
        return {"status": "IMPORTED", "receipts": Recorder(self.project, clock=self.clock).import_evidence(a["records"])}

    def register_comparison(self, args):
        a = _arguments("register_comparison", args)
        with FeedbackStore(self.project, clock=self.clock) as store:
            return {"status": "RECORDED", **register_plan(store, a["plan"], event_id=a["event_id"])}

    def _snapshot(self, args):
        with FeedbackStore(self.project) as store:
            return store.snapshot(as_of_seq=args.get("as_of_seq"))

    @staticmethod
    def _evaluate(snapshot, as_of):
        payloads = lambda kind: [e["payload"] for e in snapshot["events"] if e["kind"] == kind]
        return evaluate(reconcile(snapshot, as_of=as_of), marks=payloads("mark"), costs=payloads("cost"),
                        cost_scopes=payloads("cost_scope"), as_of=as_of)

    @staticmethod
    def _report(snapshot, evaluation, as_of, comparison=None):
        content = {"schema_version": "tradeoff.feedback-report.v1", "status": "EVALUATED",
            "environments": sorted({e["environment"] for e in snapshot["events"] if not e["kind"].startswith("_")}),
            "as_of": as_of, "evidence": {"as_of_seq": snapshot["as_of_seq"], "head_hash": snapshot["head_hash"]},
            "quality": evaluation["coverage"], "evaluation": evaluation, "comparison": comparison, "artifacts": {}}
        content["report_id"] = output_hash(content)[:24]
        return content

    def evaluate_decisions(self, args):
        a = _arguments("evaluate_decisions", args)
        snapshot = self._snapshot(a)
        return self._report(snapshot, self._evaluate(snapshot, a["as_of"]), a["as_of"])

    def compare_versions(self, args):
        a = _arguments("compare_versions", args)
        snapshot = self._snapshot(a)
        return compare(snapshot, self._evaluate(snapshot, a["as_of"]), plan_id=a["plan_id"], as_of=a["as_of"])

    def _output(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", value) or any(p in {"", ".", "..", ".tradeoff", ".git"} for p in value.split("/")):
            raise FeedbackError("UNSAFE_OUTPUT", "Choose a fresh workspace-relative feedback output directory")
        target = self.project / value
        _no_symlinks(target)
        if target.exists():
            raise FeedbackError("OUTPUT_EXISTS", "Choose a fresh feedback output directory")
        return target

    def export_feedback(self, args):
        a = _arguments("export_feedback", args)
        target = self._output(a["output"])
        snapshot = self._snapshot(a)
        evaluation = self._evaluate(snapshot, a["as_of"])
        comparison = compare(snapshot, evaluation, plan_id=a["plan_id"], as_of=a["as_of"]) if "plan_id" in a else None
        from .export import export_feedback
        result = export_feedback(snapshot, evaluation, comparison, target, include_snapshots=a.get("include_snapshots", False))
        return {"status": "EXPORTED", "output": a["output"], **result}

    def sync_paper_evidence(self, args):
        a = _arguments("sync_paper_evidence", args)
        if a["start"] >= a["end"]:
            raise FeedbackError("INVALID_INTERVAL", "Sync start must precede its end")
        from .alpaca import PaperReader, sync_paper
        with FeedbackStore(self.project, clock=self.clock) as store:
            if self.paper_reader_factory:
                reader = self.paper_reader_factory(store.fingerprint)
            else:
                key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
                if not key or not secret:
                    raise FeedbackError("BROKER_NOT_CONFIGURED", "Configure local Alpaca paper credentials before syncing")
                reader = PaperReader(key_id=key, secret_key=secret, fingerprint=store.fingerprint)
            return sync_paper(store, reader, source_alias=a["source_alias"], start=a["start"], end=a["end"])
