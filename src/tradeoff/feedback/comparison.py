"""Predeclared version comparisons; descriptive evidence, never a winner."""
from collections import defaultdict
from decimal import Decimal, localcontext

from .contracts import FeedbackError, canonical_json, decimal_text, utc_time, validate_payload


def register_plan(store, payload, *, event_id):
    p = validate_payload("comparison_plan", payload)
    if p["baseline_version"] == p["candidate_version"]:
        raise FeedbackError("INVALID_PLAN", "Choose two different declared versions")
    with store.transaction():
        plans = [e for e in store.snapshot()["events"] if e["kind"] == "comparison_plan"]
        if any(e["payload"]["plan_id"] == p["plan_id"] and e["event_id"] != event_id for e in plans):
            raise FeedbackError("PLAN_CONFLICT", "Plan revisions require a new plan ID")
        if "supersedes_plan_id" in p and not any(e["payload"]["plan_id"] == p["supersedes_plan_id"] for e in plans):
            raise FeedbackError("PLAN_NOT_FOUND", "The preceding plan revision was not found")
        return store.append(event_id, "comparison_plan", p, environment=store.metadata.get("recording_environment", "paper"))


def compare(snapshot, evaluation, *, plan_id, as_of):
    with localcontext() as context:
        context.prec = 128
        return _compare(snapshot, evaluation, plan_id=plan_id, as_of=utc_time(as_of))


def _compare(snapshot, evaluation, *, plan_id, as_of):
    plans = [e for e in snapshot["events"] if e["kind"] == "comparison_plan" and e["payload"]["plan_id"] == plan_id]
    if len(plans) != 1:
        raise FeedbackError("PLAN_NOT_FOUND", "One unambiguous recorded comparison plan is required")
    event, = plans
    p = event["payload"]
    baseline_version, candidate_version = p["baseline_version"], p["candidate_version"]
    capture_class = "PROSPECTIVE_PLAN" if event["recorded_at"] < p["window_start"] and event["origin"] == "captured" else "RETROSPECTIVE_PLAN"
    episodes = {ep["episode_id"]: ep for ep in evaluation["episodes"]}
    all_decisions = evaluation["decisions"]
    opening = {}
    for ep in episodes.values():
        related = [d for d in all_decisions if ep["episode_id"] in d["episode_ids"]]
        opening[ep["episode_id"]] = min(related, key=lambda d: (d["decision_at"], d["decision_id"]), default={}).get("decision_id")
    candidates, exclusions, population = defaultdict(lambda: defaultdict(list)), [], defaultdict(int)
    for d in all_decisions:
        version = d["agent_version"]
        if version not in {baseline_version, candidate_version}:
            continue
        population[version] += 1
        reason = None
        ep = episodes.get(d["episode_ids"][0]) if len(d["episode_ids"]) == 1 else None
        if not p["window_start"] <= d["decision_at"] < p["window_end"]:
            reason = "OUTSIDE_WINDOW"
        elif d["action"] in {"hold", "skip"}:
            reason = "HOLD_OR_SKIP"
        elif ep is None:
            reason = "UNFILLED_OR_AMBIGUOUS"
        elif opening[ep["episode_id"]] != d["decision_id"]:
            reason = "NON_OPENING_DECISION"
        elif ep["status"] != "ATTRIBUTABLE_CLOSED" or ep["observed_net"] is None or Decimal(ep["entry_notional"]) <= 0:
            reason = "OUTCOME_OR_COST_INELIGIBLE"
        elif ep["closing_at"] > as_of or d["horizon_end"] > as_of:
            reason = "IMMATURE"
        if reason:
            exclusions.append({"decision_id": d["decision_id"], "version": version, "opportunity_id": d["opportunity_id"], "reason": reason})
        else:
            candidates[d["opportunity_id"]][version].append((d, ep))
    pairs, b_values, c_values = [], [], []
    incompatible = False
    for opportunity, by_version in sorted(candidates.items()):
        base, cand = by_version[baseline_version], by_version[candidate_version]
        if len(base) != 1 or len(cand) != 1:
            exclusions.append({"opportunity_id": opportunity, "reason": "MISSING_OR_DUPLICATE_PAIR"})
            continue
        (bd, be), (cd, ce) = base[0], cand[0]
        match = (bd["symbol"] == cd["symbol"] and bd["input_hash"] == cd["input_hash"] and
            bd["decision_at"] == cd["decision_at"] and bd["horizon_end"] == cd["horizon_end"] and
            canonical_json(bd["reference"]) == canonical_json(cd["reference"]) and
            bd["environment"] == cd["environment"] and be["environment"] == ce["environment"] and
            be["currency"] == ce["currency"] and bd["capture"]["classification"] == cd["capture"]["classification"])
        if not match:
            incompatible = True
            exclusions.append({"opportunity_id": opportunity, "reason": "INCOMPATIBLE_REFERENCE_ENVIRONMENT_OR_CAPTURE"})
            continue
        b = Decimal(be["observed_net"]) / Decimal(be["entry_notional"]) * 10000
        c = Decimal(ce["observed_net"]) / Decimal(ce["entry_notional"]) * 10000
        b_values.append(b)
        c_values.append(c)
        pairs.append({"opportunity_id": opportunity, "baseline_decision": bd["decision_id"],
                      "candidate_decision": cd["decision_id"], "delta_bps": decimal_text(c - b),
                      "capture_class": bd["capture"]["classification"], "environment": bd["environment"]})
    count = len(pairs)
    if len({(pair["environment"], pair["capture_class"]) for pair in pairs}) > 1:
        exclusions.extend({"opportunity_id": pair["opportunity_id"], "reason": "MIXED_COMPARISON_COHORT"} for pair in pairs)
        incompatible = True
        pairs, b_values, c_values, count = [], [], [], 0
    metrics = {"baseline_mean_bps": decimal_text(sum(b_values) / count) if count else None,
               "candidate_mean_bps": decimal_text(sum(c_values) / count) if count else None,
               "mean_delta_bps": decimal_text(sum((c-b for b,c in zip(b_values,c_values)), Decimal("0")) / count) if count else None}
    return {"schema_version": "tradeoff.feedback-comparison.v1", "status": "DESCRIPTIVE_COMPARISON" if count >= p["minimum_pairs"] else "NOT_COMPARABLE" if incompatible else "INSUFFICIENT_EVIDENCE",
        "plan_id": plan_id, "plan_revision": event["event_hash"], "capture_class": capture_class,
        "matched_count": count, "minimum_pairs": p["minimum_pairs"], "exclusions": exclusions,
        "population_counts": dict(population), "metrics": metrics, "pairs": pairs,
        "scope": "Eligible both-traded opening-decision subset; episode net return on entry notional. Descriptive, not account return or causal improvement. All other decisions appear in exclusions."}
