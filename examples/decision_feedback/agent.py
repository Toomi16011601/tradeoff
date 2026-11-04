"""Explicit retrospective projection of native closed trades for a parity check.

Engine trade aggregates are not broker order/fill logs. IDs and reconstructed
decision/binding records here are synthetic normalization scaffolding. This
does not validate prospective timing or observed net costs. The native input,
including terminal holdings and pending orders, is never changed or liquidated.
"""
from datetime import datetime, timedelta
import hashlib

from tradeoff.feedback.api import FeedbackApp
from tradeoff.feedback.store import FeedbackStore


def import_native_closed_trades(project, *, rows, native):
    with FeedbackStore(project, create=True, environment="simulated"):
        pass
    records = []
    for i, trade in enumerate(native["trades"]):
        alias, episode = f"native-trade-{i}", f"native-episode-{i}"
        qty = str(trade["size"])
        entry = datetime.fromisoformat(rows[trade["entry_bar"]]["timestamp"])
        exit_time = datetime.fromisoformat(rows[trade["exit_bar"]]["timestamp"])
        before = (entry - timedelta(seconds=1)).isoformat()
        common = {"source_alias": alias, "symbol": "GOOG", "asset_class": "us_equity", "currency": "USD"}
        items = [("inventory", {**common, "quantity": "0", "observed_at": before,
            "capture_started_at": before, "capture_completed_at": before, "open_order_ids": [], "origin": "imported"})]
        for phase, amount, price, at in (("entry", qty, str(trade["entry_price"]), entry),
            ("exit", str(-trade["size"]), str(trade["exit_price"]), exit_time)):
            did, oid, fid = f"native-{i}-{phase}-decision", f"native-{i}-{phase}-order", f"native-{i}-{phase}-fill"
            side = "sell" if amount.startswith("-") else "buy"
            intent = {"decision_id": did, "agent_id": "riskkit-public-example", "agent_version": "upstream-pinned",
                "opportunity_id": f"native-{i}-{phase}", "symbol": "GOOG", "asset_class": "us_equity", "currency": "USD",
                "action": side, "quantity_delta": amount, "decision_at": at.isoformat(),
                "horizon_end": (at + timedelta(days=1)).isoformat(), "input_hash": hashlib.sha256(b"retrospective-native-trade-aggregate").hexdigest(),
                "episode_id": episode, "reference": {"price": price, "price_kind": "trade", "observed_at": at.isoformat(),
                    "available_at": at.isoformat(), "source": "native-trade-aggregate", "feed": "daily-ordering-labels", "max_age_seconds": 86400}}
            items.extend([("decision", intent), ("order_binding", {"decision_id": did, "source_alias": alias, "order_id": oid}),
                ("order", {**common, "order_id": oid, "side": side, "quantity": amount.lstrip("-"),
                    "filled_quantity": amount.lstrip("-"), "status": "filled", "submitted_at": at.isoformat()}),
                ("fill", {**common, "fill_id": fid, "order_id": oid, "quantity_delta": amount, "price": price, "occurred_at": at.isoformat()})])
        items.append(("source_note", {"source_alias": alias, "note_id": f"native-float-{i}", "code": "NUMERIC_SOURCE_FLOAT",
            "interval_start": before, "interval_end": (exit_time + timedelta(days=1)).isoformat(), "symbol": "GOOG",
            "metadata": {"activity_type": "reconstructed-native-closed-trade"}}))
        records.extend({"event_id": f"native-{i}-event-{j}", "kind": kind, "payload": payload, "environment": "simulated"}
                       for j, (kind, payload) in enumerate(items))
    FeedbackApp(project).import_evidence({"records": records})
    return {"status": "RETROSPECTIVE", "closed_native_trades": len(native["trades"]),
        "open_native_trades": len(native["open_trades"]), "pending_native_orders": len(native["pending_orders"]),
        "limitations": "Closed-trade gross parity only. Native float text, reconstructed IDs, daily ordering labels; no prospective timing or complete net-cost evidence. Open holdings and pending orders remain in the unchanged native input."}
