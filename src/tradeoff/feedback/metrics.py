"""Exact descriptive outcomes; missing evidence never becomes zero profit."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, localcontext
import hashlib

from .contracts import COMPONENTS, canonical_json, decimal_text, utc_time, validate_payload
from .recorder import classify_capture


def execution_difference(fill, decision_reference):
    """Positive means worse price than the named reference, including movement."""
    if not decision_reference:
        return None
    with localcontext() as ctx:
        ctx.prec = 128
        direction = Decimal("1") if Decimal(fill["quantity_delta"]) > 0 else Decimal("-1")
        return decimal_text(direction * (Decimal(fill["price"]) - Decimal(decision_reference["price"])))


def _active_costs(costs, as_of):
    unique, invalid = {}, False
    for c in costs:
        if c["applies_at"] > as_of:
            continue
        key = (c["source_alias"], c["cost_id"])
        if key in unique and unique[key] != c:
            invalid = True
        unique[key] = c
    replaced, branches = set(), set()
    for key, c in unique.items():
        old_id = c.get("corrects_cost_id")
        if old_id:
            old_key = (c["source_alias"], old_id)
            old = unique.get(old_key)
            link = tuple(k for k in ("fill_id", "order_id", "episode_id") if k in c)
            if old_key in branches or old is None or old_key == key or any(old.get(k) != c.get(k) for k in ("component", "currency", *link)):
                invalid = True
            branches.add(old_key)
            replaced.add(old_key)
    # Cyclic revisions cannot yield an eligible observed charge set.
    for key in unique:
        visited, node = set(), key
        while node in unique and unique[node].get("corrects_cost_id"):
            if node in visited:
                invalid = True
                break
            visited.add(node)
            node = (node[0], unique[node]["corrects_cost_id"])
    active = [c for k, c in unique.items() if k not in replaced]
    def target(c):
        return tuple(c.get(k) for k in ("source_alias", "component", "currency", "fill_id", "order_id", "episode_id"))
    actual_targets = {target(c) for c in active if c["evidence_kind"] == "observed"}
    return [c for c in active if c["evidence_kind"] == "observed" or target(c) not in actual_targets], invalid


def _episode_costs(episode, episodes, costs, scope):
    components = defaultdict(list)
    coverage = defaultdict(lambda: defaultdict(set))
    needed_fills = set(episode["fill_ids"])
    reasons = []
    for c in costs:
        if c["source_alias"] != episode["source_alias"]:
            continue
        amount, covered = None, set()
        if c.get("episode_id") == episode["episode_id"]:
            amount = Decimal(c["amount"])
            covered = needed_fills
        elif "fill_id" in c and c["fill_id"] in episode["fill_ids"]:
            amount = Decimal(c["amount"])
            covered = {c["fill_id"]}
        elif "order_id" in c and c["order_id"] in episode["order_ids"]:
            involved = [ep for ep in episodes if ep["source_alias"] == c["source_alias"] and c["order_id"] in ep["order_ids"]]
            if any(ep["status"] != "ATTRIBUTABLE_CLOSED" for ep in involved):
                reasons.append("UNSUPPORTED_COST_ALLOCATION")
                continue
            all_fills = sorted([f for ep in involved for f in ep["fills"] if f["order_id"] == c["order_id"]],
                               key=lambda f: (f["occurred_at"], f["fill_id"]))
            total = sum((abs(Decimal(f["quantity_delta"]) * Decimal(f["price"])) for f in all_fills), Decimal("0"))
            allocated, shares = Decimal("0"), []
            for i, f in enumerate(all_fills):
                value = Decimal(c["amount"]) - allocated if i == len(all_fills) - 1 else Decimal(c["amount"]) * abs(Decimal(f["quantity_delta"]) * Decimal(f["price"])) / total
                shares.append((f["fill_id"], value))
                allocated += value
            amount = sum((value for fid, value in shares if fid in episode["fill_ids"]), Decimal("0"))
            covered = {f["fill_id"] for f in episode["fills"] if f["order_id"] == c["order_id"]}
        if amount is not None:
            if c["currency"] != episode["currency"]:
                reasons.append("COST_CURRENCY_CONFLICT")
            else:
                components[c["component"]].append((c["evidence_kind"], amount))
                coverage[c["component"]][c["evidence_kind"]].update(covered)
    observed, modeled = Decimal("0"), Decimal("0")
    observed_ok = bool(scope and scope["evidence_kind"] == "observed")
    modeled_ok = bool(scope)
    for name in COMPONENTS:
        applicability = scope.get("components", {}).get(name, {}).get("applicable") if scope else None
        charges = components[name]
        if applicability is False:
            if any(amount != 0 for _, amount in charges):
                reasons.append("COST_SCOPE_CONFLICT")
            continue
        if applicability is None or not charges:
            reasons.append(name.upper() + "_COST_UNKNOWN")
            observed_ok = modeled_ok = False
            continue
        actual_coverage = coverage[name]["observed"]
        combined_coverage = actual_coverage | coverage[name]["modeled"]
        if actual_coverage != needed_fills:
            observed_ok = False
        if combined_coverage != needed_fills:
            observed_ok = modeled_ok = False
            reasons.append(name.upper() + "_COST_UNKNOWN")
        if scope.get("evidence_kind") != "observed" or any(kind != "observed" for kind, _ in charges):
            observed_ok = False
            reasons.append(name.upper() + "_COST_MODELED")
        observed += sum((amount for kind, amount in charges if kind == "observed"), Decimal("0"))
        modeled += sum((amount for _, amount in charges), Decimal("0"))
    if scope and scope["evidence_kind"] == "modeled":
        reasons.append("COST_SCOPE_MODELED")
    if any(r in reasons for r in ("UNSUPPORTED_COST_ALLOCATION", "COST_CURRENCY_CONFLICT", "COST_SCOPE_CONFLICT")):
        observed_ok = modeled_ok = False
    return observed if observed_ok else None, modeled if modeled_ok else None, sorted(set(reasons))


def evaluate(reconciled, *, marks, costs, cost_scopes, as_of):
    marks = [validate_payload("mark", item) for item in marks]
    costs = [validate_payload("cost", item) for item in costs]
    cost_scopes = [validate_payload("cost_scope", item) for item in cost_scopes]
    with localcontext() as context:
        context.prec = 128
        return _evaluate(reconciled, marks=marks, costs=costs, cost_scopes=cost_scopes, as_of=utc_time(as_of))


def _evaluate(reconciled, *, marks, costs, cost_scopes, as_of):
    costs, cost_conflict = _active_costs(costs, as_of)
    scope_by_episode, scope_conflict = {}, set()
    for scope in cost_scopes:
        eid = scope["episode_id"]
        old = scope_by_episode.get(eid)
        predecessor = scope.get("supersedes_scope_hash")
        if predecessor:
            if old is None or hashlib.sha256(canonical_json(old).encode()).hexdigest() != predecessor:
                scope_conflict.add(eid)
        elif old is not None and old != scope:
            scope_conflict.add(eid)
        scope_by_episode[eid] = scope
    episodes, findings = [], []
    for ep in reconciled["episodes"]:
        valid = ep["status"] == "ATTRIBUTABLE_CLOSED"
        entry_positive = ep["direction"] == "long"
        gross = -sum((Decimal(f["quantity_delta"]) * Decimal(f["price"]) for f in ep["fills"]), Decimal("0")) if valid else None
        entry_notional = sum((abs(Decimal(f["quantity_delta"]) * Decimal(f["price"])) for f in ep["fills"] if
                             (Decimal(f["quantity_delta"]) > 0) == entry_positive), Decimal("0"))
        observed, modeled, reasons = _episode_costs(ep, reconciled["episodes"], costs, scope_by_episode.get(ep["episode_id"]))
        reasons = sorted(set([*ep["reasons"], *reasons]))
        if cost_conflict or ep["episode_id"] in scope_conflict:
            reasons.append("COST_REVISION_CONFLICT")
            observed = modeled = None
        row = {k: v for k, v in ep.items() if k != "fills"}
        row.update(gross_cashflow=decimal_text(gross) if gross is not None else None,
            observed_net=decimal_text(gross - observed) if valid and observed is not None else None,
            modeled_net=decimal_text(gross - modeled) if valid and modeled is not None and observed is None else None,
            entry_notional=decimal_text(entry_notional), reasons=reasons,
            cost_coverage="COMPLETE_OBSERVED" if observed is not None else "MODELED" if modeled is not None else "INCOMPLETE")
        episodes.append(row)
        for reason in reasons:
            findings.append({"code": reason, "episode_id": ep["episode_id"],
                "action": "Inspect linked evidence and collect missing observations before comparing versions"})
    decision_results = []
    for item in reconciled["decisions"]:
        event, orders = item["event"], item["orders"]
        d = event["payload"]
        earliest = min(orders, key=lambda o: o["submitted_at"], default=None)
        capture = classify_capture(event, earliest, as_of=as_of, max_clock_skew_seconds=0)
        ref = d["reference"]
        eligible = [m for m in marks if m["symbol"] == d["symbol"] and m["currency"] == d["currency"] and
            all(m[k] == ref[k] for k in ("price_kind", "source", "feed")) and
            d["decision_at"] <= m["observed_at"] <= d["horizon_end"] and m["available_at"] <= as_of and
            0 <= (datetime.fromisoformat(d["horizon_end"]) - datetime.fromisoformat(m["observed_at"])).total_seconds() <= ref["max_age_seconds"]]
        horizon_mark = max(eligible, key=lambda m: (m["observed_at"], m["mark_id"]), default=None)
        outcome = "PENDING" if as_of < d["horizon_end"] else "AVAILABLE" if horizon_mark else "UNAVAILABLE"
        keyset = {(o["source_alias"], o["order_id"]) for o in orders}
        fills = [f for ep in reconciled["episodes"] for f in ep["fills"] if (f["source_alias"], f["order_id"]) in keyset]
        first_fill = min(fills, key=lambda f: f["occurred_at"], default=None)
        ref_eligible = (ref["available_at"] <= d["decision_at"] and ref["observed_at"] <= d["decision_at"] and
            (datetime.fromisoformat(d["decision_at"]) - datetime.fromisoformat(ref["observed_at"])).total_seconds() <= ref["max_age_seconds"])
        row = {"decision_id": d["decision_id"], "agent_id": d["agent_id"], "agent_version": d["agent_version"],
            "opportunity_id": d["opportunity_id"], "symbol": d["symbol"], "action": d["action"], "environment": event["environment"],
            "decision_at": d["decision_at"], "horizon_end": d["horizon_end"], "input_hash": d["input_hash"], "reference": ref,
            "episode_ids": item["episode_ids"], "capture": capture, "intended_quantity": d["quantity_delta"],
            "filled_quantity": decimal_text(sum((Decimal(f["quantity_delta"]) for f in fills), Decimal("0"))),
            "cancellation_count": sum(o["status"] in {"canceled", "expired", "rejected"} for o in orders),
            "decision_to_submission_seconds": str((datetime.fromisoformat(earliest["submitted_at"]) - datetime.fromisoformat(d["decision_at"])).total_seconds()) if earliest else None,
            "decision_to_first_fill_seconds": str((datetime.fromisoformat(first_fill["occurred_at"]) - datetime.fromisoformat(d["decision_at"])).total_seconds()) if first_fill else None,
            "outcome_status": outcome, "horizon_mark_id": horizon_mark["mark_id"] if horizon_mark and outcome == "AVAILABLE" else None,
            "horizon_price_change": decimal_text(Decimal(horizon_mark["price"]) - Decimal(ref["price"])) if outcome == "AVAILABLE" else None,
            "execution_price_difference": execution_difference(first_fill, ref) if first_fill and ref_eligible else None,
            "execution_difference_label": "Price difference including market movement; not causal impact",
            "realized_decision_pnl": None}
        decision_results.append(row)
        if d["action"] in {"buy", "sell"} and not orders:
            findings.append({"code": "BINDING_MISSING", "decision_id": d["decision_id"], "action": "Bind the actual order ID to this recorded decision"})
    groups = []
    for owner in sorted({(d["agent_id"], d["agent_version"]) for d in decision_results}):
        owned = [d for d in decision_results if (d["agent_id"], d["agent_version"]) == owner]
        eps = [ep for ep in reconciled["episodes"] if (ep["agent_id"], ep["agent_version"]) == owner]
        positions, exposure = defaultdict(lambda: Decimal("0")), []
        for f in sorted([f for ep in eps for f in ep["fills"]], key=lambda f: (f["occurred_at"], f["fill_id"])):
            stream = (f["source_alias"], f["symbol"])
            positions[stream] += Decimal(f["quantity_delta"])
            exposure.append({"at": f["occurred_at"], "source_alias": f["source_alias"],
                             "symbol": f["symbol"], "quantity": decimal_text(positions[stream])})
        groups.append({"agent_id": owner[0], "agent_version": owner[1], "decision_count": len(owned),
            "available_outcomes": sum(d["outcome_status"] == "AVAILABLE" for d in owned),
            "turnover_notional": decimal_text(sum((abs(Decimal(f["quantity_delta"]) * Decimal(f["price"])) for ep in eps for f in ep["fills"]), Decimal("0"))),
            "exposure": exposure, "exposure_unit": "signed shares per recorded inventory stream; not portfolio risk",
            "horizon_price_changes": [d["horizon_price_change"] for d in owned if d["horizon_price_change"] is not None]})
    return {"as_of": as_of, "episodes": episodes, "decisions": decision_results, "findings": findings,
        "groups": groups, "coverage": {**reconciled["coverage"], "complete_observed_net_episodes": sum(ep["observed_net"] is not None for ep in episodes),
            "pending_decisions": sum(d["outcome_status"] == "PENDING" for d in decision_results)}}
