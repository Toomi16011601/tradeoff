"""Bounded modeled account ledgers on one common historical market calendar.

This deliberately separate comparison never changes observed episode eligibility.
Declared policies and hashes are research receipts, not source attestations.
"""
from collections import defaultdict
from decimal import Decimal, localcontext
import hashlib

from .contracts import COMPONENTS, canonical_json, decimal_text, utc_time
from .metrics import _active_costs

_ALLOWED_NOTES = {"NUMERIC_SOURCE_FLOAT", "HISTORICAL_TIMESTAMPS_UNVERIFIED"}
_RECHECKED_COST_REASONS = {"COST_SCOPE_MODELED", "COST_SCOPE_CONFLICT", "COST_CURRENCY_CONFLICT",
    "UNSUPPORTED_COST_ALLOCATION", "COST_REVISION_CONFLICT",
    *[name.upper()+suffix for name in COMPONENTS for suffix in ("_COST_MODELED", "_COST_UNKNOWN")]}
_SCOPE = ("Whole simulated accounts on the complete declared common market calendar, including holds and "
          "marked open holdings. All costs and execution are modeled under caller-declared assumptions. "
          "Retrospective descriptive research; not observed account returns, causal improvement or a winner.")


def compare_simulated(snapshot, evaluation, plan_event, as_of):
    """Reconstruct a complete paired one-stock cash ledger, or report its gaps."""
    with localcontext() as context:
        context.prec = 128
        return _compare(snapshot, evaluation, plan_event, utc_time(as_of))


def _compare(snapshot, evaluation, plan_event, as_of):
    plan, events = plan_event["payload"], snapshot["events"]
    sim = plan["simulation"]
    versions = (plan["baseline_version"], plan["candidate_version"])
    aliases = (sim["baseline_source_alias"], sim["candidate_source_alias"])
    owner_alias = dict(zip(versions, aliases))
    start, end = sim["initial_at"], sim["terminal_at"]
    initial = Decimal(sim["initial_cash"])
    exclusions, warnings, severities = [], set(), []
    result = {"schema_version":"tradeoff.simulated-account-comparison.v1", "status":"INSUFFICIENT_EVIDENCE",
        "plan_id":plan["plan_id"], "plan_revision":plan_event["event_hash"],
        "capture_class":"RETROSPECTIVE_PLAN", "environment":"simulated", "evidence_kind":"modeled",
        "matched_count":0, "minimum_pairs":plan["minimum_pairs"], "population_counts":{},
        "metrics":{"baseline_return_bps":None, "candidate_return_bps":None, "delta_return_bps":None},
        "accounts":{}, "timeline":[], "pairs":[], "market_path_hash":None,
        "cost_model_id":sim["cost_model_id"], "execution_policy_id":sim["execution_policy_id"],
        "timestamp_policy":sim["timestamp_policy"], "warnings":[], "exclusions":exclusions, "scope":_SCOPE}

    def reject(reason, *, missing=False, **context):
        item = {"reason":reason, **context}
        if item not in exclusions:
            exclusions.append(item)
        severities.append(not missing)

    def finish():
        result["warnings"] = sorted(warnings)
        if exclusions:
            result["status"] = "NOT_COMPARABLE" if any(severities) else "INSUFFICIENT_EVIDENCE"
        return result

    if plan_event["environment"] != "simulated":
        reject("SIMULATED_ENVIRONMENT_REQUIRED")
    if as_of < end:
        reject("IMMATURE_ACCOUNT_WINDOW", missing=True)
        return finish()
    # The supported model is explicitly fully funded, flat-start, USD equity.
    if (sim["currency"] != "USD" or sim["asset_class"] != "us_equity" or initial <= 0 or
            aliases[0] == aliases[1] or versions[0] == versions[1]):
        reject("UNSUPPORTED_ACCOUNT_MODEL")
        return finish()
    if not sim["acknowledge_assumptions"] or sim["timestamp_policy"] != "declared_historical_ordering":
        reject("SIMULATION_ASSUMPTIONS_REQUIRED")
        return finish()

    by_version = defaultdict(list)
    decision_events, decisions, duplicate_ids = [], {}, set()
    for event in events:
        if event["kind"] != "decision":
            continue
        decision = event["payload"]
        if decision["agent_version"] not in versions or not start <= decision["decision_at"] < end:
            continue
        decision_events.append(event)
        by_version[decision["agent_version"]].append(decision)
        if decision["decision_id"] in decisions:
            duplicate_ids.add(decision["decision_id"])
        decisions[decision["decision_id"]] = decision
    result["population_counts"] = {version:len(by_version[version]) for version in versions}
    for did in sorted(duplicate_ids):
        reject("DECISION_ID_CONFLICT", decision_id=did)
    for version in versions:
        group = by_version[version]
        group.sort(key=lambda d:(d["decision_at"], d["opportunity_id"], d["decision_id"]))
        if len(group) != sim["expected_decisions"]:
            reject("INCOMPLETE_OR_DUPLICATE_CALENDAR", missing=len(group) < sim["expected_decisions"], version=version)
        if len({d["agent_id"] for d in group}) > 1:
            reject("MIXED_ACCOUNT_OWNER", version=version)
        if len({d["opportunity_id"] for d in group}) != len(group) or len({d["decision_at"] for d in group}) != len(group):
            reject("DUPLICATE_CALENDAR_OPPORTUNITY", version=version)
        if group and (group[0]["decision_at"] != start or group[-1]["horizon_end"] != end or
                any(a["horizon_end"] != b["decision_at"] for a, b in zip(group, group[1:]))):
            reject("BROKEN_ACCOUNT_CALENDAR", version=version)
        for d in group:
            if any(d[k] != sim[k] for k in ("symbol", "currency", "asset_class")):
                reject("INSTRUMENT_CONFLICT", decision_id=d["decision_id"])
            ref = d["reference"]
            if Decimal(ref["price"]) <= 0:
                reject("NONPOSITIVE_DECISION_REFERENCE", decision_id=d["decision_id"])
            if any(ref[k] != sim[s] for k, s in (("source","valuation_source"), ("feed","valuation_feed"), ("price_kind","price_kind"))):
                reject("REFERENCE_FEED_CONFLICT", decision_id=d["decision_id"])
            if (ref["observed_at"] != d["decision_at"] or ref["available_at"] > d["decision_at"] or
                    any(s["observed_at"] > d["decision_at"] or s["available_at"] > d["decision_at"] for s in d.get("source_times", []))):
                reject("UNAVAILABLE_OR_STALE_DECISION_REFERENCE", decision_id=d["decision_id"])
    baseline, candidate = (by_version[v] for v in versions)
    if not exclusions:
        for bd, cd in zip(baseline, candidate):
            if (any(bd[k] != cd[k] for k in ("opportunity_id", "decision_at", "horizon_end", "symbol", "currency", "asset_class")) or
                    canonical_json(bd["reference"]) != canonical_json(cd["reference"])):
                reject("INCOMPATIBLE_MARKET_CALENDAR_OR_REFERENCE", opportunity_id=bd["opportunity_id"])
    if exclusions:
        return finish()
    if len(baseline) < plan["minimum_pairs"]:
        reject("MINIMUM_CALENDAR_COUNT_NOT_REACHED", missing=True)
        return finish()

    dids = set(decisions)
    selected_event_ids = {id(event) for event in decision_events}
    episode_ids = {d["episode_id"] for d in decisions.values() if "episode_id" in d}
    selected_episodes = [ep for ep in evaluation["episodes"] if ep["source_alias"] in aliases]
    episode_ids.update(ep["episode_id"] for ep in selected_episodes)
    kinds = defaultdict(list)
    for event in events:
        kind, p = event["kind"], event["payload"]
        economic_at = next((p[k] for k in ("occurred_at", "source_updated_at", "submitted_at", "observed_at", "applies_at") if k in p), None)
        if kind == "mark":
            economic_at = max(p["observed_at"], p["available_at"])
        if economic_at is not None and economic_at > as_of:
            continue
        if kind == "source_note" and (p["interval_start"] > end or p["interval_end"] < start):
            continue
        related = (id(event) in selected_event_ids if kind == "decision" else
            p.get("source_alias") in aliases or
            (kind == "order_binding" and p["decision_id"] in dids) or
            (kind == "cost_scope" and p["episode_id"] in episode_ids) or
            (kind == "mark" and p["symbol"] == sim["symbol"] and p["currency"] == sim["currency"] and
             p["source"] == sim["valuation_source"] and p["feed"] == sim["valuation_feed"] and p["price_kind"] == sim["price_kind"]))
        if not related:
            continue
        if event["environment"] != "simulated":
            reject("MIXED_EVIDENCE_ENVIRONMENT", kind=kind)
        kinds[kind].append(event)
    for event in kinds["source_note"]:
        note = event["payload"]
        if note["interval_start"] <= end and note["interval_end"] >= start:
            if note["code"] in _ALLOWED_NOTES:
                warnings.add(note["code"])
            else:
                reject("UNSUPPORTED_SOURCE_ACTIVITY", source_alias=note["source_alias"])
    # Only the declared historical-clock limitation is relaxed here. The native
    # episode statuses, attribution reasons and observed net values stay intact.
    for ep in selected_episodes:
        for reason in ep["reasons"]:
            if reason != "UNSUPPORTED_SOURCE_ACTIVITY" and reason not in _RECHECKED_COST_REASONS:
                reject(reason, source_alias=ep["source_alias"])
        if ep["environment"] != "simulated" or ep["agent_version"] != versions[aliases.index(ep["source_alias"])]:
            reject("EPISODE_ACCOUNT_OWNER_CONFLICT", source_alias=ep["source_alias"])

    def same_instrument(item):
        return all(item[k] == sim[k] for k in ("symbol", "currency", "asset_class"))

    inventories = defaultdict(list)
    for event in kinds["inventory"]:
        p = event["payload"]
        if not same_instrument(p):
            reject("INVENTORY_INSTRUMENT_CONFLICT", source_alias=p["source_alias"])
        inventories[p["source_alias"]].append(p)
    for alias in aliases:
        initial_inventories = [p for p in inventories[alias] if p["observed_at"] <= start]
        inv = max(initial_inventories, key=lambda p:p["observed_at"], default=None)
        if inv is None:
            reject("OPENING_INVENTORY_UNKNOWN", missing=True, source_alias=alias)
        elif Decimal(inv["quantity"]) != 0 or inv["open_order_ids"] or inv["capture_completed_at"] > start:
            reject("INITIAL_ACCOUNT_NOT_FLAT_AND_SETTLED", source_alias=alias)
        if initial_inventories and any(Decimal(p["quantity"]) != 0 or p["open_order_ids"] for p in initial_inventories):
            reject("AMBIGUOUS_INITIAL_INVENTORY", source_alias=alias)

    bindings, orders, fills = {}, {}, {}
    for event in kinds["order_binding"]:
        p = event["payload"]
        key = (p["source_alias"], p["order_id"])
        d = decisions.get(p["decision_id"])
        if d is None or owner_alias[d["agent_version"]] != p["source_alias"]:
            reject("BINDING_ACCOUNT_OWNER_CONFLICT", source_alias=p["source_alias"])
        if key in bindings and bindings[key] != p["decision_id"]:
            reject("BINDING_CONFLICT", source_alias=p["source_alias"])
        bindings[key] = p["decision_id"]
    for event in kinds["order"]:
        p = event["payload"]
        key = (p["source_alias"], p["order_id"])
        if not same_instrument(p):
            reject("ORDER_INSTRUMENT_CONFLICT", source_alias=p["source_alias"])
        if any(k in p for k in ("parent_order_id", "replaces_order_id", "replaced_by_order_id")):
            reject("UNSUPPORTED_ORDER_STRUCTURE", source_alias=p["source_alias"])
        if key in orders and any(orders[key][1].get(field) != p.get(field) for field in
                ("symbol", "asset_class", "currency", "side", "quantity", "submitted_at",
                 "parent_order_id", "replaces_order_id", "replaced_by_order_id")):
            reject("ORDER_IDENTITY_CONFLICT", source_alias=p["source_alias"])
        rank = (p.get("source_updated_at", p["submitted_at"]), event["seq"])
        if key not in orders or rank >= orders[key][0]:
            orders[key] = (rank, p)
    orders = {k:p for k, (_, p) in orders.items()}
    for key in bindings:
        if key not in orders:
            reject("BOUND_ORDER_EVIDENCE_MISSING", source_alias=key[0])
    totals = defaultdict(lambda:Decimal("0"))
    for event in kinds["fill"]:
        p = event["payload"]
        key = (p["source_alias"], p["fill_id"])
        if key in fills:
            if fills[key] != p:
                reject("FILL_ID_CONFLICT", source_alias=p["source_alias"])
            continue
        fills[key] = p
        order_key = (p["source_alias"], p["order_id"])
        order, d = orders.get(order_key), decisions.get(bindings.get(order_key))
        if not same_instrument(p):
            reject("FILL_INSTRUMENT_CONFLICT", source_alias=p["source_alias"])
        if order is None or d is None:
            reject("UNBOUND_OR_MISSING_ORDER_FILL", source_alias=p["source_alias"])
        elif (d["action"] in {"hold", "skip"} or (Decimal(p["quantity_delta"]) > 0) != (d["action"] == "buy") or
                (Decimal(p["quantity_delta"]) > 0) != (order["side"] == "buy")):
            reject("INTENT_ORDER_FILL_CONFLICT", source_alias=p["source_alias"])
        elif not d["decision_at"] <= order["submitted_at"] <= p["occurred_at"] <= d["horizon_end"]:
            reject("FILL_OUTSIDE_DECLARED_DECISION_INTERVAL", source_alias=p["source_alias"])
        if not start <= p["occurred_at"] <= end:
            reject("FILL_OUTSIDE_ACCOUNT_WINDOW", source_alias=p["source_alias"])
        totals[order_key] += abs(Decimal(p["quantity_delta"]))
    for key, order in orders.items():
        if key not in bindings:
            reject("UNBOUND_ACCOUNT_ORDER", source_alias=key[0])
        if order["status"] == "filled" and Decimal(order["quantity"]) != Decimal(order["filled_quantity"]):
            reject("FILLED_ORDER_QUANTITY_CONFLICT", source_alias=key[0])
        if Decimal(order["filled_quantity"]) != totals[key]:
            reject("FILL_QUANTITY_CONFLICT", source_alias=key[0])
        if not start <= order["submitted_at"] <= end:
            reject("ORDER_OUTSIDE_ACCOUNT_WINDOW", source_alias=key[0])
    for d in decisions.values():
        bound = [orders[key] for key, did in bindings.items() if did == d["decision_id"] and key in orders]
        submitted = sum((Decimal(order["quantity"]) for order in bound), Decimal("0"))
        if bound and (d["action"] in {"hold", "skip"} or submitted > abs(Decimal(d["quantity_delta"])) or
                any((order["side"] == "buy") != (d["action"] == "buy") for order in bound)):
            reject("INTENT_ORDER_QUANTITY_OR_SIDE_CONFLICT", decision_id=d["decision_id"])
        if d["action"] in {"buy", "sell"} and not bound:
            reject("DECISION_ORDER_EVIDENCE_MISSING", missing=True, decision_id=d["decision_id"])
    for alias in aliases:
        account_fills = [p for (a, _), p in fills.items() if a == alias]
        for inv in inventories[alias]:
            if start <= inv["observed_at"] <= end:
                expected = sum((Decimal(p["quantity_delta"]) for p in account_fills if p["occurred_at"] <= inv["observed_at"]), Decimal("0"))
                if expected != Decimal(inv["quantity"]):
                    reject("INVENTORY_SNAPSHOT_CONFLICT", source_alias=alias)
                if any(inv["capture_started_at"] <= p["occurred_at"] <= inv["capture_completed_at"] for p in account_fills):
                    reject("INVENTORY_WINDOW_CONFLICT", source_alias=alias)

    # Account charges are fill-linked only. There is no order/episode allocation
    # or extra slippage debit: modeled fill prices already include execution.
    costs, conflict = _active_costs([e["payload"] for e in kinds["cost"]], as_of)
    if conflict:
        reject("COST_REVISION_CONFLICT")
    scopes, scope_conflicts = _resolve_scopes([e["payload"] for e in kinds["cost_scope"]])
    for eid in scope_conflicts:
        reject("COST_SCOPE_REVISION_CONFLICT", episode_id=eid)
    fill_episodes = defaultdict(set)
    for ep in selected_episodes:
        for fid in ep["fill_ids"]:
            fill_episodes[(ep["source_alias"], fid)].add(ep["episode_id"])
    charges = defaultdict(list)
    for cost in costs:
        key = (cost["source_alias"], cost.get("fill_id"))
        if "fill_id" not in cost or key not in fills:
            reject("UNSUPPORTED_OR_UNLINKED_ACCOUNT_COST", source_alias=cost["source_alias"])
            continue
        if cost["currency"] != sim["currency"] or cost["evidence_kind"] != "modeled":
            reject("COST_CURRENCY_OR_EVIDENCE_CONFLICT", source_alias=cost["source_alias"])
        if not fills[key]["occurred_at"] <= cost["applies_at"] <= end:
            reject("COST_OUTSIDE_ACCOUNT_INTERVAL", source_alias=cost["source_alias"])
        charges[(key, cost["component"])].append(cost)
    for key in fills:
        eids = fill_episodes[key]
        scope = scopes.get(next(iter(eids))) if len(eids) == 1 else None
        if scope is None or scope["evidence_kind"] != "modeled":
            reject("COMPLETE_MODELED_COST_SCOPE_REQUIRED", missing=scope is None, source_alias=key[0])
            continue
        for component in COMPONENTS:
            applicability = scope["components"][component]["applicable"]
            items = charges[(key, component)]
            if applicability is None or (applicability and not items):
                reject("MODELED_COST_COVERAGE_MISSING", missing=True, source_alias=key[0], component=component)
            if len(items) > 1:
                reject("DUPLICATE_ACTIVE_COMPONENT_CHARGE", source_alias=key[0], component=component)
            if applicability is False and any(Decimal(c["amount"]) != 0 for c in items):
                reject("COST_SCOPE_CONFLICT", source_alias=key[0], component=component)
    if exclusions:
        return finish()

    times = [start, *[d["horizon_end"] for d in baseline]]
    prices = {start:Decimal(baseline[0]["reference"]["price"])}
    by_time = defaultdict(list)
    for event in kinds["mark"]:
        mark = event["payload"]
        if mark["observed_at"] in times:
            by_time[mark["observed_at"]].append(mark)
    for at in times:
        matches = by_time[at]
        values = {Decimal(m["price"]) for m in matches}
        if len(values) > 1 or (at == start and values and values != {prices[start]}):
            reject("CONFLICTING_MARKET_VALUATION", at=at)
        usable = [m for m in matches if m["available_at"] <= as_of]
        if at != start:
            if not usable:
                reject("EXACT_AVAILABLE_VALUATION_MISSING", missing=True, at=at)
            else:
                prices[at] = Decimal(usable[0]["price"])
    for decision in baseline:
        if decision["decision_at"] in prices and Decimal(decision["reference"]["price"]) != prices[decision["decision_at"]]:
            reject("REFERENCE_MARKET_PATH_CONFLICT", decision_id=decision["decision_id"])
    if exclusions:
        return finish()

    paths = {}
    for label, version, alias in zip(("baseline", "candidate"), versions, aliases):
        account_fills = [p for (a, _), p in fills.items() if a == alias]
        account_costs = [c for c in costs if c["source_alias"] == alias]
        ledger = [(f["occurred_at"], 0, f["fill_id"], -Decimal(f["quantity_delta"])*Decimal(f["price"]), Decimal(f["quantity_delta"])) for f in account_fills]
        ledger += [(c["applies_at"], 1, c["cost_id"], -Decimal(c["amount"]), Decimal("0")) for c in account_costs]
        ledger.sort(key=lambda row:row[:3])
        cash, quantity, index = initial, Decimal("0"), 0
        path, peak, drawdown = [], initial, Decimal("0")
        for at in times:
            while index < len(ledger) and ledger[index][0] <= at:
                _, _, _, cash_delta, quantity_delta = ledger[index]
                cash += cash_delta
                quantity += quantity_delta
                if cash < 0 or quantity < 0:
                    reject("UNFUNDED_OR_SHORT_ACCOUNT_PATH", source_alias=alias)
                index += 1
            equity = cash + quantity*prices[at]
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak-equity)/peak*10000)
            path.append({"cash":decimal_text(cash), "shares":decimal_text(quantity), "equity":decimal_text(equity)})
        notional = sum((abs(Decimal(f["quantity_delta"])*Decimal(f["price"])) for f in account_fills), Decimal("0"))
        fees = sum((Decimal(c["amount"]) for c in account_costs), Decimal("0"))
        pnl = Decimal(path[-1]["equity"])-initial
        paths[label] = path
        result["accounts"][label] = {"initial_cash":decimal_text(initial), "final_cash":decimal_text(cash),
            "final_shares":decimal_text(quantity), "terminal_equity":path[-1]["equity"], "net_pnl":decimal_text(pnl),
            "net_return_pct":decimal_text(pnl/initial*100), "net_return_bps":decimal_text(pnl/initial*10000),
            "max_drawdown_bps":decimal_text(drawdown), "filled_notional":decimal_text(notional),
            "turnover":decimal_text(notional/initial), "explicit_fees":decimal_text(fees), "fill_count":len(account_fills),
            "decision_count":len(by_version[version]), "hold_count":sum(d["action"] in {"hold", "skip"} for d in by_version[version])}
    if exclusions:
        result["accounts"] = {}
        return finish()
    timeline = [{"at":at, "price":decimal_text(prices[at]), **{
        label+"_"+field:paths[label][i][field] for label in ("baseline", "candidate") for field in ("cash", "shares", "equity")}}
        for i, at in enumerate(times)]
    b, c = (Decimal(result["accounts"][label]["net_return_bps"]) for label in ("baseline", "candidate"))
    result.update(status="MODELED_ACCOUNT_COMPARISON", matched_count=len(baseline), timeline=timeline,
        metrics={"baseline_return_bps":decimal_text(b), "candidate_return_bps":decimal_text(c), "delta_return_bps":decimal_text(c-b)},
        market_path_hash=_market_hash(sim, baseline, timeline))
    warnings.add("MODELED_EXECUTION_AND_COST_ASSUMPTIONS")
    return finish()


def _resolve_scopes(items):
    scopes, conflicts = {}, set()
    for scope in items:
        eid = scope["episode_id"]
        old = scopes.get(eid)
        predecessor = scope.get("supersedes_scope_hash")
        if predecessor:
            if old is None or hashlib.sha256(canonical_json(old).encode()).hexdigest() != predecessor:
                conflicts.add(eid)
        elif old is not None and old != scope:
            conflicts.add(eid)
        scopes[eid] = scope
    return scopes, conflicts


def _market_hash(sim, decisions, timeline):
    """Hash bounded rows incrementally; aggregate history is not an input record."""
    digest = hashlib.sha256()
    identity = {k:sim[k] for k in ("symbol", "currency", "asset_class", "valuation_source", "valuation_feed", "price_kind")}
    digest.update((canonical_json(identity)+"\n").encode())
    for decision in decisions:
        row = {k:decision[k] for k in ("opportunity_id", "decision_at", "horizon_end", "reference")}
        digest.update((canonical_json(row)+"\n").encode())
    for point in timeline:
        digest.update((canonical_json({k:point[k] for k in ("at", "price")})+"\n").encode())
    return digest.hexdigest()
