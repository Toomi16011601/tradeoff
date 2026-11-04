"""Account-free synthetic agent feedback through the public application API."""
from datetime import datetime
import hashlib
from pathlib import Path

from .api import FeedbackApp
from .contracts import canonical_json
from .store import FeedbackStore

START = "2026-01-05T14:30:00+00:00"
END = "2026-01-05T16:00:00+00:00"


def _intent(case, phase, version, qty, price, opportunity):
    at = "2026-01-05T14:30:01+00:00" if phase == "entry" else "2026-01-05T14:31:00+00:00"
    quote_at = START if phase == "entry" else "2026-01-05T14:30:59+00:00"
    return {"decision_id": f"{case}-{phase}", "agent_id": "synthetic-agent", "agent_version": version,
        "opportunity_id": opportunity, "symbol": "SYNTH", "asset_class": "us_equity", "currency": "USD",
        "action": "sell" if qty.startswith("-") else "buy", "quantity_delta": qty, "decision_at": at,
        "horizon_end": "2026-01-05T15:30:00+00:00", "episode_id": "episode-" + case,
        "input_hash": hashlib.sha256(b"synthetic-shared-observation").hexdigest(),
        "reference": {"price": price, "price_kind": "mid", "observed_at": quote_at, "available_at": quote_at,
            "source": "synthetic_demo", "feed": "synthetic-feed", "max_age_seconds": 60}}


def _episode(app, *, case, version="v1", short=False, mixed=False, exit_price="12", opportunity="demo-opportunity"):
    alias = "synthetic-" + case
    entry_qty, exit_qty = ("-0.25", "0.25") if short else ("0.5", "-0.5")
    entry_price = "20" if short else "10"
    records = [{"event_id": case + "-inventory", "kind": "inventory", "payload": {
        "source_alias": alias, "symbol": "SYNTH", "asset_class": "us_equity", "currency": "USD", "quantity": "0",
        "observed_at": START, "capture_started_at": START, "capture_completed_at": START, "open_order_ids": [], "origin": "synthetic_fixture"}, "environment": "simulated"}]
    for phase, qty, price in (("entry", entry_qty, entry_price), ("exit", exit_qty, exit_price)):
        version_for_decision = "v2" if mixed and phase == "exit" else version
        d = _intent(case, phase, version_for_decision, qty, entry_price if phase == "entry" else exit_price,
                    opportunity if phase == "entry" else opportunity + "-close")
        if phase == "entry" and not short:
            d["quantity_delta"] = "1.25"
        app.clock = lambda at=d["decision_at"]: datetime.fromisoformat(at)
        app.record_decision({"event_id": case + "-decision-" + phase, "decision": d})
        oid, fid = case + "-order-" + phase, case + "-fill-" + phase
        app.bind_order({"event_id": case + "-binding-" + phase, "binding": {
            "decision_id": d["decision_id"], "source_alias": alias, "order_id": oid}})
        submitted = "2026-01-05T14:30:02+00:00" if phase == "entry" else "2026-01-05T14:31:01+00:00"
        filled = "2026-01-05T14:30:03+00:00" if phase == "entry" else "2026-01-05T14:31:02+00:00"
        records.extend([
            {"event_id": oid, "kind": "order", "payload": {"source_alias": alias, "order_id": oid, "symbol": "SYNTH",
                "asset_class": "us_equity", "currency": "USD", "side": d["action"], "quantity": abs_text(d["quantity_delta"]),
                "filled_quantity": abs_text(qty), "status": "canceled" if phase == "entry" and not short else "filled",
                "submitted_at": submitted}, "environment": "simulated"},
            {"event_id": fid, "kind": "fill", "payload": {"source_alias": alias, "fill_id": fid, "order_id": oid,
                "symbol": "SYNTH", "asset_class": "us_equity", "currency": "USD", "quantity_delta": qty,
                "price": price, "occurred_at": filled}, "environment": "simulated"},
            {"event_id": case + "-fee-" + phase, "kind": "cost", "payload": {"cost_id": case + "-fee-" + phase,
                "source_alias": alias, "component": "commission", "amount": "0.02" if phase == "entry" else "0" if short else "0.03",
                "currency": "USD", "evidence_kind": "observed", "applies_at": filled, "order_id": oid}, "environment": "simulated"}])
    components = {c: {"applicable": True, "evidence_ref": "synthetic-explicit-cost-contract"}
                  for c in ("commission", "transaction", "venue", "regulatory")}
    components.update(borrow={"applicable": None if short else False, "evidence_ref": "synthetic-contract"},
                      financing={"applicable": False, "evidence_ref": "synthetic-fully-funded"})
    records.append({"event_id": case + "-scope", "kind": "cost_scope", "payload": {
        "episode_id": "episode-" + case, "components": components, "evidence_kind": "observed"}, "environment": "simulated"})
    for component in ("transaction", "venue", "regulatory"):
        records.append({"event_id": case + "-" + component, "kind": "cost", "payload": {
            "cost_id": case + "-" + component, "source_alias": alias, "component": component,
            "amount": "0", "currency": "USD", "evidence_kind": "observed", "applies_at": START,
            "episode_id": "episode-" + case}, "environment": "simulated"})
    app.clock = lambda: datetime.fromisoformat(END)
    app.import_evidence({"records": records})


def abs_text(qty):
    return qty.lstrip("-")


def run_feedback_demo(output_dir):
    output = Path(output_dir).absolute()
    # The demo has its own project; it never attaches to a user's trading workspace.
    if output.exists() or output.is_symlink():
        from .contracts import FeedbackError
        raise FeedbackError("OUTPUT_EXISTS", "Choose a fresh synthetic demo output directory")
    output.mkdir(parents=True, mode=0o700)
    with FeedbackStore(output, create=True, environment="simulated"):
        pass
    app = FeedbackApp(output, clock=lambda: datetime.fromisoformat("2026-01-05T14:00:00+00:00"))
    app.register_comparison({"event_id": "demo-plan", "plan": {"plan_id": "demo-comparison", "baseline_version": "v1",
        "candidate_version": "v2", "window_start": START, "window_end": END, "metric": "episode_net_return_bps",
        "horizon_policy": "decision_at_declared_end", "reference_policy": "exact_reference",
        "cost_policy": "complete_observed", "match_policy": "exact_opportunity", "minimum_pairs": 2}})
    _episode(app, case="long", opportunity="paired-1")
    _episode(app, case="baseline-2", exit_price="11.06", opportunity="paired-2")
    _episode(app, case="candidate-1", version="v2", exit_price="11.9", opportunity="paired-1")
    _episode(app, case="candidate-2", version="v2", exit_price="11", opportunity="paired-2")
    _episode(app, case="short", short=True, exit_price="18", opportunity="unmatched-short")
    _episode(app, case="mixed", mixed=True, opportunity="mixed-ownership")
    app.import_evidence({"records": [{"event_id": "demo-mark", "kind": "mark", "environment": "simulated", "payload": {
        "mark_id": "synthetic-horizon", "symbol": "SYNTH", "currency": "USD", "price": "12", "price_kind": "mid",
        "source": "synthetic_demo", "feed": "synthetic-feed", "observed_at": "2026-01-05T15:30:00+00:00",
        "available_at": "2026-01-05T15:30:00+00:00"}}]})
    result = app.export_feedback({"output": "report", "as_of": END, "plan_id": "demo-comparison"})
    return {"status": "DEMO_COMPLETED", "data": "SYNTHETIC", "report_id": result["report_id"],
        "report": "report/" + result["report"], "interface": "report/" + result["interface"],
        "interpretation": "Synthetic workflow demonstration; does not establish better trading"}
