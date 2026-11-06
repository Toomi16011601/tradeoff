"""Read-only, bounded evidence diagnostics; never run a strategy or broker."""
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .api import FeedbackApp
from .contracts import FeedbackError, utc_time
from .store import FeedbackStore


def check(name, status, message, next_step=""):
    return dict(id=name, status=status, message=message, next_step=next_step)


def diagnose(project, *, as_of=None):
    """Inspect a consistent local snapshot without initializing or changing it.

    Counts deliberately omit strategy payloads, broker identifiers and paths.
    Captured records alone cannot establish that a real agent hook is installed.
    """
    when = utc_time(as_of if as_of is not None else datetime.now(timezone.utc))
    result = dict(schema_version="tradeoff.doctor.v1", status="NEEDS_ATTENTION",
                  agent_hook="NOT_VERIFIED", evidence_status="UNKNOWN", as_of=when,
                  checks=[], counts={})
    checks = result["checks"]
    try:
        with FeedbackStore(Path(project), readonly=True) as store:
            snapshot = store.snapshot()
            project_id = store.metadata["project_id"]
        evaluation = FeedbackApp._evaluate(snapshot, when)
    except Exception as exc:
        missing = isinstance(exc, FeedbackError) and exc.code == "PROJECT_NOT_INITIALIZED"
        wal = isinstance(exc, FeedbackError) and exc.code == "READ_ONLY_STORAGE_MODE"
        result["status"] = "SETUP_REQUIRED" if missing else "BLOCKED"
        checks.append(check("storage", "FAIL", "No initialized feedback project." if missing else "WAL or unsupported SQLite mode requires a separate consistent snapshot." if wal else "Evidence could not be safely verified.",
                            "Run tradeoff connect --project ." if missing else "Keep the source unchanged. Use a separately created consistent SQLite backup in default DELETE journal mode before diagnostics." if wal else "Keep the evidence unchanged; inspect its integrity and workspace path before retrying."))
        return result
    checks.append(check("storage", "PASS", "Read-only snapshot and hash chain verified."))
    from .onboarding import probe, read_connection
    try:
        connection = read_connection(Path(project).absolute(), project_id=project_id)
        if connection is None:
            result["setup_status"] = "REQUIRED"
            checks.append(check("connection", "WARN", "No generated connection bundle.", "Run tradeoff connect --project ."))
        elif connection["project"] != str(Path(project).absolute()):
            result["setup_status"] = "BLOCKED"
            checks.append(check("connection", "FAIL", "Connection paths refer to a different workspace.", "Rerun tradeoff connect --project . after moving the workspace."))
        else:
            checks.append(check("connection", "PASS", "Generated configuration is unchanged; client registration is not verified."))
            installed = probe(connection["python"])
            ok = installed["status"] == "PASS"
            result["setup_status"] = "READY" if ok else "BLOCKED"
            checks.append(check("interpreter", "PASS" if ok else "FAIL", "Installed Python and pinned MCP SDK verified." if ok else "Configured Python or MCP installation is unavailable.",
                                "" if ok else "Repair the installation or rerun connect --python with the correct environment executable."))
    except Exception:
        result["setup_status"] = "BLOCKED"
        checks.append(check("connection", "FAIL", "Connection bundle is edited, unsafe or incomplete.", "Preserve your changes, move the connection folder aside, then rerun tradeoff connect --project ."))
    events = snapshot["events"]
    decisions, episodes = evaluation["decisions"], evaluation["episodes"]
    trades = {d["decision_id"] for d in decisions if d["action"] in {"buy", "sell"}}
    bindings = [e["payload"] for e in events if e["kind"] == "order_binding" and e["payload"]["decision_id"] in trades]
    bound = {b["decision_id"] for b in bindings}
    orders = {}
    fill_records = {}
    for event in events:
        payload = event["payload"]
        if event["kind"] == "order" and payload.get("source_updated_at", payload["submitted_at"]) <= when:
            key = (payload["source_alias"], payload["order_id"])
            old = orders.get(key)
            if old is None or payload.get("source_updated_at", payload["submitted_at"]) >= old.get("source_updated_at", old["submitted_at"]):
                orders[key] = payload
        elif event["kind"] == "fill" and payload["occurred_at"] <= when:
            fill_records[(payload["source_alias"], payload["fill_id"])] = payload
    filled = defaultdict(lambda: Decimal("0"))
    for fill in fill_records.values():
        filled[(fill["source_alias"], fill["order_id"])] += abs(Decimal(fill["quantity_delta"]))
    missing_bindings = len(trades - bound)
    missing_orders = sum((b["source_alias"], b["order_id"]) not in orders for b in bindings)
    missing_fills = sum(Decimal(order["filled_quantity"]) > filled[key] for key, order in orders.items())
    pending = sum(d["outcome_status"] == "PENDING" for d in decisions)
    missing_outcomes = sum(d["outcome_status"] == "UNAVAILABLE" for d in decisions)
    missing_costs = sum(e["cost_coverage"] != "COMPLETE_OBSERVED" for e in episodes)
    result["counts"] = dict(events=snapshot["as_of_seq"], decisions=len(decisions),
        fills=evaluation["coverage"]["fill_count"], episodes=len(episodes),
        missing_bindings=missing_bindings, missing_orders=missing_orders,
        orders_missing_fills=missing_fills,
        pending_outcomes=pending, missing_outcomes=missing_outcomes,
        incomplete_cost_episodes=missing_costs,
        complete_observed_net_episodes=evaluation["coverage"]["complete_observed_net_episodes"])
    checks.append(check("decisions", "PASS" if decisions else "WARN", f"{len(decisions)} decisions in the evaluated snapshot.",
                        "" if decisions else "Give your coding agent the generated AGENT_SETUP.md prompt; test its real callback with a fake broker."))
    checks.append(check("agent_hook", "WARN", "A real agent hook is not verified by setup or stored records.",
                        "Review the integration diff and run a fake-broker test: record intent before submission, then bind the returned order ID."))
    checks.append(check("bindings", "WARN" if missing_bindings else "PASS" if trades else "WAIT",
                        f"{missing_bindings} trade intents have no explicit binding.",
                        "Bind the actual returned order ID after submission; do not infer matches from time or symbol." if missing_bindings else ""))
    checks.append(check("order_evidence", "WARN" if missing_orders else "PASS" if bindings else "WAIT",
                        f"{missing_orders} bindings have no corresponding order evidence.",
                        "Import normalized order/fill records or explicitly run the read-only Alpaca paper sync." if missing_orders else ""))
    checks.append(check("fills", "WARN" if missing_fills else "PASS" if orders else "WAIT",
                        f"{missing_fills} orders report a filled quantity greater than their recorded fills.",
                        "Collect the missing execution activities; an order status alone cannot supply fill prices or fees." if missing_fills else ""))
    inventory_ok = evaluation["coverage"]["inventory_resolved"]
    checks.append(check("inventory", "PASS" if inventory_ok else "WARN" if episodes else "WAIT",
                        "Opening inventory resolved." if inventory_ok else "Opening inventory cannot yet be established for all episodes.",
                        "Capture inventory before future episodes; never invent a historical zero balance." if episodes and not inventory_ok else ""))
    checks.append(check("costs", "WARN" if missing_costs else "PASS" if episodes else "WAIT",
                        f"{missing_costs} episodes lack complete observed costs and applicability evidence.",
                        "Collect applicable fees and cost-scope evidence; keep modeled costs labeled and never assume missing fees are zero." if missing_costs else ""))
    checks.append(check("outcomes", "WARN" if missing_outcomes else "WAIT" if pending or not decisions else "PASS",
                        f"{missing_outcomes} matured decisions lack a matching horizon mark; {pending} are still waiting.",
                        "Configure a matching local price source and run tradeoff feedback collect, or import marks with the declared feed, price kind and horizon tolerance." if missing_outcomes else "Wait until declared horizons mature; no open market is needed to inspect stored evidence." if pending else ""))
    excluded = evaluation["coverage"]["excluded_episodes"]
    checks.append(check("attribution", "WARN" if excluded else "PASS" if episodes else "WAIT",
                        f"{excluded} episodes excluded from attribution.",
                        "Inspect the report's Data quality view; resolve mixed ownership, external inventory or conflicting evidence." if excluded else ""))
    evidence_checks = {"decisions", "bindings", "order_evidence", "fills", "inventory", "costs", "outcomes", "attribution"}
    result["evidence_status"] = "NO_DECISIONS" if not decisions else "GAPS" if any(c["status"] == "WARN" and c["id"] in evidence_checks for c in checks) else "WAITING" if pending else "AVAILABLE"
    if any(c["status"] == "FAIL" for c in checks):
        result["status"] = "BLOCKED"
    elif result["setup_status"] == "READY" and result["evidence_status"] in {"WAITING", "AVAILABLE"}:
        result["status"] = "EVIDENCE_" + result["evidence_status"]
    return result
