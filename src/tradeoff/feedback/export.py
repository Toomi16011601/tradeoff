"""Fresh offline artifacts; allowlisted records and local stable pseudonyms."""
from copy import deepcopy
import hashlib
import hmac
from pathlib import Path
import shutil
import tempfile

from ..privacy import reject_sensitive_data
from .contracts import FeedbackError, canonical_json, validate_payload
from .store import _no_symlinks

_ID_KEYS = {"source_alias", "order_id", "fill_id", "client_order_id", "replaces_order_id", "replaced_by_order_id",
            "parent_order_id", "cost_id", "corrects_cost_id"}
_LIST_IDS = {"order_ids", "fill_ids", "open_order_ids"}


def _only(item, keys):
    return {k: deepcopy(item[k]) for k in keys.split() if k in item}


def _public_evaluation(evaluation):
    result = _only(evaluation, "as_of coverage")
    result["episodes"] = [_only(e, "episode_id source_alias symbol currency environment direction agent_id agent_version decision_ids order_ids fill_ids opening_at closing_at entry_quantity closing_quantity unfilled_quantity terminal_quantity reasons status gross_cashflow observed_net modeled_net entry_notional cost_coverage") for e in evaluation["episodes"]]
    result["decisions"] = [_only(d, "decision_id agent_id agent_version opportunity_id symbol action environment decision_at horizon_end input_hash reference episode_ids capture intended_quantity filled_quantity cancellation_count decision_to_submission_seconds decision_to_first_fill_seconds outcome_status horizon_mark_id horizon_price_change execution_price_difference execution_difference_label realized_decision_pnl") for d in evaluation["decisions"]]
    result["findings"] = [_only(f, "code episode_id decision_id action") for f in evaluation["findings"]]
    result["groups"] = [_only(g, "agent_id agent_version decision_count available_outcomes turnover_notional exposure exposure_unit horizon_price_changes") for g in evaluation.get("groups", [])]
    return result


def export_feedback(snapshot, evaluation, comparison, output_dir, *, include_snapshots=False):
    from .api import FeedbackApp
    from ..report.feedback_renderer import render_feedback_report
    target = Path(output_dir).absolute()
    _no_symlinks(target)
    if target.exists():
        raise FeedbackError("OUTPUT_EXISTS", "Choose a fresh feedback output directory")
    key = snapshot["project_id"].encode()

    def pseudo(value):
        return "ref-" + hmac.new(key, str(value).encode(), hashlib.sha256).hexdigest()[:20]

    def scrub(value, field=None):
        if isinstance(value, dict):
            return {k: scrub(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [pseudo(v) if field in _LIST_IDS else scrub(v) for v in value]
        return pseudo(value) if field in _ID_KEYS and value is not None else value

    events = []
    for event in snapshot["events"]:
        if event["kind"].startswith("_"):
            continue
        payload = validate_payload(event["kind"], event["payload"])
        if event["kind"] == "decision":
            payload.pop("reason", None)
            if not include_snapshots:
                payload.pop("input_snapshot", None)
        events.append({"kind": event["kind"], "seq": event["seq"], "event_hash": event["event_hash"],
            "recorded_at": event["recorded_at"], "origin": event["origin"], "environment": event["environment"],
            "payload": scrub(payload)})
    public = scrub(_public_evaluation(evaluation))
    report = FeedbackApp._report(snapshot, public, evaluation["as_of"], scrub(comparison) if comparison else None)
    report["artifacts"] = {"report": "feedback-report.json", "evidence": "feedback-evidence.json", "receipt": "feedback-receipt.json"}
    evidence = {"schema_version": "tradeoff.feedback-export.v1", "as_of_seq": snapshot["as_of_seq"],
        "head_hash": snapshot["head_hash"], "events": events, "snapshot_content_included": include_snapshots,
        "scope": "Allowlisted normalized evidence with project-local pseudonyms; proprietary decisions may remain"}
    try:
        reject_sensitive_data(report)
        reject_sensitive_data(evidence)
        blobs = {"feedback-report.json": canonical_json(report) + "\n", "feedback-evidence.json": canonical_json(evidence) + "\n"}
        blobs["index.html"] = render_feedback_report(report)
        receipt = {"schema_version": "tradeoff.feedback-receipt.v1", "report_id": report["report_id"],
            "as_of_seq": snapshot["as_of_seq"], "head_hash": snapshot["head_hash"],
            "files": {name: hashlib.sha256(data.encode()).hexdigest() for name, data in blobs.items()},
            "scope": "Byte-integrity receipt, not a signature or source-authenticity attestation"}
        blobs["feedback-receipt.json"] = canonical_json(receipt) + "\n"
    except ValueError:
        raise FeedbackError("UNSAFE_EXPORT", "Feedback export contains invalid or recognized sensitive data") from None
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".feedback-export-", dir=target.parent))
    try:
        for name, data in blobs.items():
            path = staging / name
            path.write_text(data, encoding="utf-8")
            path.chmod(0o600)
        staging.rename(target)
    except OSError:
        raise FeedbackError("EXPORT_FAILED", "Feedback export could not be written to a fresh directory") from None
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"report_id": report["report_id"], "report": "feedback-report.json", "interface": "index.html",
            "evidence": "feedback-evidence.json", "receipt": "feedback-receipt.json"}
