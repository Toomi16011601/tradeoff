"""Conservative attribution from explicit bindings and verified inventory."""
from collections import defaultdict
from decimal import Decimal, localcontext
import hashlib

from .contracts import canonical_json, decimal_text, utc_time


def _baseline_info(alias, symbol, first_fill_at, fills, kinds, *, last_fill_at=None):
    observations = [e["payload"] for e in kinds["inventory"] if e["payload"]["source_alias"] == alias
                    and e["payload"]["symbol"] == symbol]
    initial = [p for p in observations if p["observed_at"] <= first_fill_at]
    baseline = max(initial, key=lambda p: p["observed_at"], default=None)
    reasons = set()
    if baseline is None:
        reasons.add("OPENING_INVENTORY_UNKNOWN")
    elif Decimal(baseline["quantity"]) != 0:
        reasons.add("EXTERNAL_INVENTORY")
    if baseline:
        if baseline["capture_completed_at"] >= first_fill_at:
            reasons.add("INVENTORY_WINDOW_CONFLICT")
        for inv in observations:
            if inv["observed_at"] < baseline["observed_at"] or inv["observed_at"] > (last_fill_at or first_fill_at):
                continue
            expected = Decimal(baseline["quantity"]) + sum((Decimal(f["quantity_delta"]) for f in fills if
                baseline["observed_at"] < f["occurred_at"] <= inv["observed_at"]), Decimal("0"))
            if expected != Decimal(inv["quantity"]):
                reasons.add("INVENTORY_SNAPSHOT_CONFLICT")
            if any(inv["capture_started_at"] <= f["occurred_at"] <= inv["capture_completed_at"] for f in fills):
                reasons.add("INVENTORY_WINDOW_CONFLICT")
    return baseline, reasons


def reconcile(snapshot, *, as_of):
    with localcontext() as context:
        context.prec = 128
        return _reconcile(snapshot, as_of=utc_time(as_of))


def _reconcile(snapshot, *, as_of):
    kinds = defaultdict(list)
    for event in snapshot["events"]:
        p = event["payload"]
        event_time = next((p[k] for k in ("occurred_at", "source_updated_at", "submitted_at", "observed_at", "decision_at") if k in p), None)
        if event_time is None or event_time <= as_of:
            kinds[event["kind"]].append(event)
    decisions, duplicate_decisions = {}, set()
    for e in kinds["decision"]:
        key = e["payload"]["decision_id"]
        if key in decisions:
            duplicate_decisions.add(key)
        decisions[key] = e
    bindings, conflicting_bindings = {}, set()
    for e in kinds["order_binding"]:
        p = e["payload"]
        key = (p["source_alias"], p["order_id"])
        if key in bindings and bindings[key] != p["decision_id"]:
            conflicting_bindings.add(key)
        bindings[key] = p["decision_id"]
    orders = {}
    for e in kinds["order"]:
        p = e["payload"]
        key = (p["source_alias"], p["order_id"])
        old = orders.get(key)
        if old is None or (p.get("source_updated_at", p["submitted_at"]), e["seq"]) >= (old.get("source_updated_at", old["submitted_at"]), old["seq"]):
            orders[key] = {**p, "seq": e["seq"], "environment": e["environment"]}
    # A replacement is attributable only with corroborating IDs on both orders.
    for _ in range(len(orders)):
        changed = False
        for key, p in orders.items():
            parent = (key[0], p.get("replaces_order_id"))
            if key not in bindings and parent in bindings and parent in orders and orders[parent].get("replaced_by_order_id") == key[1]:
                bindings[key], changed = bindings[parent], True
        if not changed:
            break
    grouped, seen, bad_fills = defaultdict(list), {}, set()
    for e in kinds["fill"]:
        p = e["payload"]
        key = (p["source_alias"], p["fill_id"])
        if key in seen:
            if seen[key] != p:
                bad_fills.add(key)
            continue
        seen[key] = p
        grouped[(p["source_alias"], p["symbol"])].append({**p, "environment": e["environment"]})
    order_totals = defaultdict(lambda: Decimal("0"))
    for fills in grouped.values():
        for f in fills:
            order_totals[(f["source_alias"], f["order_id"])] += abs(Decimal(f["quantity_delta"]))
    episodes, excluded = [], []
    for (alias, symbol), fills in sorted(grouped.items()):
        fills.sort(key=lambda f: (f["occurred_at"], f["fill_id"]))
        position = Decimal("0")
        current, owners, reasons = [], set(), set()
        for i, f in enumerate(fills):
            if not current:
                baseline, reasons = _baseline_info(alias, symbol, f["occurred_at"], fills, kinds)
                position = Decimal(baseline["quantity"]) if baseline else Decimal("0")
                if baseline and any((alias, oid) not in bindings for oid in baseline["open_order_ids"]):
                    reasons.add("OPEN_ORDER_UNRESOLVED")
            key = (alias, f["order_id"])
            order = orders.get(key)
            owner_event = decisions.get(bindings.get(key))
            if not order:
                reasons.add("ORDER_MISSING")
            if not owner_event or key in conflicting_bindings:
                reasons.add("UNBOUND_FILL")
            else:
                d = owner_event["payload"]
                owners.add((d["agent_id"], d["agent_version"]))
                if d["decision_id"] in duplicate_decisions:
                    reasons.add("DECISION_ID_CONFLICT")
                if d["action"] in {"hold", "skip"} or (d["quantity_delta"].startswith("-") != f["quantity_delta"].startswith("-")):
                    reasons.add("INTENT_FILL_CONFLICT")
                if d["symbol"] != symbol or d["currency"] != f["currency"] or d["asset_class"] != f["asset_class"]:
                    reasons.add("INSTRUMENT_CONFLICT")
            if (alias, f["fill_id"]) in bad_fills:
                reasons.add("FILL_ID_CONFLICT")
            if f["asset_class"] != "us_equity" or f["currency"] != "USD":
                reasons.add("UNSUPPORTED_INSTRUMENT")
            if order:
                if order.get("parent_order_id"):
                    reasons.add("UNSUPPORTED_CHILD_ORDER")
                if order["currency"] != f["currency"] or order["asset_class"] != f["asset_class"] or order["symbol"] != symbol or ((order["side"] == "sell") != f["quantity_delta"].startswith("-")):
                    reasons.add("ORDER_FILL_CONFLICT")
                if Decimal(order["filled_quantity"]) != order_totals[key]:
                    reasons.add("FILL_QUANTITY_CONFLICT")
                for link, back in (("replaces_order_id", "replaced_by_order_id"), ("replaced_by_order_id", "replaces_order_id")):
                    if link in order:
                        other = orders.get((alias, order[link]))
                        if not other or other.get(back) != order["order_id"]:
                            reasons.add("REPLACEMENT_UNRESOLVED")
            after = position + Decimal(f["quantity_delta"])
            if position and after and (position > 0) != (after > 0):
                reasons.add("WITHIN_FILL_REVERSAL")
            current.append(f)
            position = after
            reset_after = i + 1 < len(fills) and any(e["payload"]["source_alias"] == alias and
                e["payload"]["symbol"] == symbol and Decimal(e["payload"]["quantity"]) == 0 and
                f["occurred_at"] < e["payload"]["observed_at"] and
                e["payload"]["capture_completed_at"] < fills[i+1]["occurred_at"] for e in kinds["inventory"])
            if position == 0 or i == len(fills) - 1 or reset_after:
                if reset_after and position != 0:
                    reasons.add("INVENTORY_BASELINE_RESET")
                _, interval_reasons = _baseline_info(alias, symbol, current[0]["occurred_at"], fills, kinds,
                                                      last_fill_at=current[-1]["occurred_at"])
                reasons.update(interval_reasons)
                for note_event in kinds["source_note"]:
                    note = note_event["payload"]
                    if (note["source_alias"] == alias and note.get("symbol", symbol) == symbol and
                        note["code"] != "NUMERIC_SOURCE_FLOAT" and note["interval_start"] <= current[-1]["occurred_at"] and
                        note["interval_end"] >= current[0]["occurred_at"]):
                        reasons.add("UNSUPPORTED_SOURCE_ACTIVITY")
                bound = [decisions[bindings[(alias, x["order_id"])]] for x in current
                         if bindings.get((alias, x["order_id"])) in decisions]
                owner_ids = sorted({e["payload"]["decision_id"] for e in bound})
                contexts = {e["payload"]["episode_id"] for e in bound if "episode_id" in e["payload"]}
                if len(owners) > 1:
                    reasons.add("MIXED_VERSION")
                if len(contexts) > 1:
                    reasons.add("EPISODE_CONTEXT_CONFLICT")
                if len({x["environment"] for x in current}) > 1 or any(e["environment"] != current[0]["environment"] for e in bound):
                    reasons.add("ENVIRONMENT_CONFLICT")
                entry_positive = Decimal(current[0]["quantity_delta"]) > 0
                involved = {x["order_id"] for x in current}
                unfilled = sum((max(Decimal("0"), Decimal(orders[(alias, oid)]["quantity"]) - Decimal(orders[(alias, oid)]["filled_quantity"]))
                                for oid in involved if (alias, oid) in orders), Decimal("0"))
                episode = {"episode_id": sorted(contexts)[0] if contexts else "episode-" + hashlib.sha256(canonical_json([alias, current[0]["fill_id"]]).encode()).hexdigest()[:24],
                    "source_alias": alias, "symbol": symbol, "currency": current[0]["currency"],
                    "environment": current[0]["environment"], "direction": "long" if entry_positive else "short",
                    "agent_id": next(iter(owners))[0] if len(owners) == 1 else None,
                    "agent_version": next(iter(owners))[1] if len(owners) == 1 else None,
                    "decision_ids": owner_ids, "order_ids": sorted(involved), "fill_ids": [x["fill_id"] for x in current],
                    "fills": current, "opening_at": current[0]["occurred_at"], "closing_at": current[-1]["occurred_at"] if position == 0 else None,
                    "entry_quantity": decimal_text(sum((abs(Decimal(x["quantity_delta"])) for x in current if
                        (Decimal(x["quantity_delta"]) > 0) == entry_positive), Decimal("0"))),
                    "closing_quantity": decimal_text(sum((abs(Decimal(x["quantity_delta"])) for x in current if
                        (Decimal(x["quantity_delta"]) > 0) != entry_positive), Decimal("0"))),
                    "unfilled_quantity": decimal_text(unfilled), "terminal_quantity": decimal_text(position),
                    "reasons": sorted(reasons), "status": "UNATTRIBUTABLE" if reasons else "ATTRIBUTABLE_CLOSED" if position == 0 else "OPEN"}
                episodes.append(episode)
                if reasons:
                    excluded.append({"episode_id": episode["episode_id"], "reasons": sorted(reasons)})
                current, owners, reasons = [], set(), set()
    context_counts = defaultdict(int)
    for episode in episodes:
        context_counts[episode["episode_id"]] += 1
    for episode in episodes:
        if context_counts[episode["episode_id"]] > 1:
            episode["status"] = "UNATTRIBUTABLE"
            episode["reasons"] = sorted(set([*episode["reasons"], "EPISODE_ID_CONFLICT"]))
            excluded.append({"episode_id": episode["episode_id"], "reasons": episode["reasons"]})
    decision_rows = []
    for did, e in sorted(decisions.items()):
        bound_orders = [orders[k] for k, v in bindings.items() if v == did and k in orders]
        decision_rows.append({"event": e, "orders": bound_orders,
            "episode_ids": [ep["episode_id"] for ep in episodes if did in ep["decision_ids"]]})
    aliases = {k[0] for k in grouped}
    coverage = {"fetch_complete": bool(aliases) and all(snapshot["sync_state"].get(a, {}).get("fetch_complete") is True for a in aliases),
        "inventory_resolved": bool(episodes) and not any(any(r in ep["reasons"] for r in ("OPENING_INVENTORY_UNKNOWN", "EXTERNAL_INVENTORY", "INVENTORY_WINDOW_CONFLICT", "INVENTORY_SNAPSHOT_CONFLICT")) for ep in episodes),
        "bindings_complete": not any("UNBOUND_FILL" in e["reasons"] for e in episodes),
        "attribution_complete": bool(episodes) and all(e["status"] == "ATTRIBUTABLE_CLOSED" for e in episodes),
        "decision_count": len(decisions), "fill_count": len(seen), "excluded_episodes": len(excluded)}
    return {"as_of_seq": snapshot["as_of_seq"], "evidence_hash": snapshot["head_hash"],
            "decisions": decision_rows, "orders": list(orders.values()), "episodes": episodes, "excluded": excluded, "coverage": coverage}
