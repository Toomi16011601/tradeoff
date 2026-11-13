"""Hand-checked modeled account comparisons; synthetic one-stock evidence only."""
from copy import deepcopy
from decimal import Decimal

import pytest

from tradeoff.feedback.contracts import COMPONENTS
from tradeoff.feedback.metrics import evaluate
from tradeoff.feedback.reconcile import reconcile

INITIAL = "2026-01-05T14:30:00+00:00"
MIDDLE = "2026-01-06T14:30:00+00:00"
TERMINAL = "2026-01-07T14:30:00+00:00"
AS_OF = "2026-02-01T00:00:00+00:00"
FILL_AT = "2026-01-05T14:31:00+00:00"


def scenario():
    """Buy five at ten plus one dollar; hold through twelve then eight."""
    records = []

    def add(kind, payload, *, environment="simulated"):
        records.append(dict(kind=kind, payload=payload, environment=environment,
            event_id=f"event-{len(records)}", seq=len(records)+1, origin="imported",
            recorded_at=AS_OF, event_hash=f"{len(records):064x}"))

    references = [dict(price=price, price_kind="close", source="fixture", feed="daily",
        observed_at=at, available_at=at, max_age_seconds=0)
        for at, price in [(INITIAL, "10"), (MIDDLE, "12")]]
    for alias, version in [("baseline-source", "v1"), ("candidate-source", "v2")]:
        common = dict(source_alias=alias, symbol="SYNTH", currency="USD", asset_class="us_equity")
        prior = "2026-01-05T14:00:00+00:00"
        add("inventory", {**common, "quantity":"0", "observed_at":prior,
            "capture_started_at":prior, "capture_completed_at":prior, "open_order_ids":[],
            "origin":"synthetic_fixture"})
        add("source_note", dict(source_alias=alias, note_id=f"{version}-clock",
            code="HISTORICAL_TIMESTAMPS_UNVERIFIED", interval_start=prior,
            interval_end=TERMINAL, symbol="SYNTH"))
        for i, (at, horizon) in enumerate([(INITIAL, MIDDLE), (MIDDLE, TERMINAL)]):
            buy = version == "v1" and i == 0
            add("decision", dict(decision_id=f"{version}-d{i}", agent_id="agent", agent_version=version,
                opportunity_id=f"session-{i}", symbol="SYNTH", asset_class="us_equity", currency="USD",
                action="buy" if buy else "hold", quantity_delta="5" if buy else "0", decision_at=at,
                horizon_end=horizon, input_hash=("a" if version == "v1" else "b")*64,
                episode_id=f"{version}-episode", reference=deepcopy(references[i])))
        if version == "v1":
            add("order_binding", dict(decision_id="v1-d0", source_alias=alias, order_id="buy"))
            add("order", {**common, "order_id":"buy", "side":"buy", "quantity":"5",
                "filled_quantity":"5", "status":"filled", "submitted_at":INITIAL,
                "source_updated_at":FILL_AT})
            add("fill", {**common, "fill_id":"fill-buy", "order_id":"buy", "quantity_delta":"5",
                "price":"10", "occurred_at":FILL_AT})
            add("cost", dict(cost_id="commission", source_alias=alias, component="commission",
                amount="1", currency="USD", evidence_kind="modeled", fill_id="fill-buy", applies_at=FILL_AT))
            add("cost_scope", dict(episode_id="v1-episode", evidence_kind="modeled", components={
                component:dict(applicable=component == "commission", evidence_ref="declared-costs")
                for component in COMPONENTS}))
    for at, price in [(MIDDLE, "12"), (TERMINAL, "8")]:
        add("mark", dict(mark_id="mark-"+at[:10], symbol="SYNTH", currency="USD", price=price,
            price_kind="close", source="fixture", feed="daily", observed_at=at, available_at=at))
    simulation = dict(baseline_source_alias="baseline-source", candidate_source_alias="candidate-source",
        initial_cash="100", currency="USD", symbol="SYNTH", asset_class="us_equity", valuation_source="fixture",
        valuation_feed="daily", price_kind="close", initial_at=INITIAL, terminal_at=TERMINAL,
        expected_decisions=2, cost_model_id="fee-model-1", execution_policy_id="fill-price-includes-shortfall",
        timestamp_policy="declared_historical_ordering", acknowledge_assumptions=True)
    plan = dict(plan_id="modeled-plan", baseline_version="v1", candidate_version="v2", window_start=INITIAL,
        window_end=TERMINAL, metric="simulated_account_return_bps", horizon_policy="decision_at_declared_end",
        reference_policy="exact_reference", cost_policy="complete_modeled", match_policy="same_market_calendar",
        minimum_pairs=1, simulation=simulation)
    plan_event = dict(kind="comparison_plan", payload=plan, event_hash="f"*64, recorded_at=AS_OF,
        origin="imported", environment="simulated", event_id="plan", seq=len(records)+1)
    records.append(plan_event)
    snapshot = dict(events=records, as_of_seq=len(records), head_hash="e"*64, sync_state={}, source_state={},
        project_id="synthetic-project", schema_version="tradeoff.feedback-snapshot.v1")
    return snapshot, plan_event


def payload(snapshot, kind, index=0):
    return [e["payload"] for e in snapshot["events"] if e["kind"] == kind][index]


def run(snapshot, plan_event, *, as_of=AS_OF):
    from tradeoff.feedback.simulated_comparison import compare_simulated
    items = lambda kind: [e["payload"] for e in snapshot["events"] if e["kind"] == kind]
    evaluation = evaluate(reconcile(snapshot, as_of=as_of), marks=items("mark"), costs=items("cost"),
        cost_scopes=items("cost_scope"), as_of=as_of)
    return compare_simulated(snapshot, evaluation, plan_event, as_of)


def test_account_return_includes_holds_and_terminal_open_stock():
    snapshot, plan_event = scenario()
    before = deepcopy(snapshot)
    result = run(snapshot, plan_event)
    assert result["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert result["schema_version"] == "tradeoff.simulated-account-comparison.v1"
    assert result["capture_class"] == "RETROSPECTIVE_PLAN"
    assert result["matched_count"] == 2
    assert result["population_counts"] == {"v1":2, "v2":2}
    assert result["accounts"]["baseline"]["final_cash"] == "49"
    assert result["accounts"]["baseline"]["final_shares"] == "5"
    assert result["accounts"]["baseline"]["terminal_equity"] == "89"
    assert result["accounts"]["baseline"]["net_pnl"] == "-11"
    assert result["accounts"]["baseline"]["net_return_pct"] == "-11"
    assert result["accounts"]["baseline"]["explicit_fees"] == "1"
    assert result["accounts"]["baseline"]["filled_notional"] == "50"
    assert result["accounts"]["baseline"]["turnover"] == "0.5"
    assert result["accounts"]["baseline"]["fill_count"] == 1
    assert result["accounts"]["baseline"]["hold_count"] == 1
    assert result["accounts"]["candidate"]["hold_count"] == 2
    assert result["metrics"] == {"baseline_return_bps":"-1100", "candidate_return_bps":"0", "delta_return_bps":"1100"}
    assert [row["baseline_equity"] for row in result["timeline"]] == ["100", "109", "89"]
    assert [row["candidate_equity"] for row in result["timeline"]] == ["100", "100", "100"]
    assert Decimal(result["accounts"]["baseline"]["max_drawdown_bps"]) == pytest.approx(Decimal("1834.86238532110091743119266055"))
    assert len(result["market_path_hash"]) == 64
    assert result["warnings"] and not result["exclusions"]
    assert snapshot == before
    assert result["pairs"] == []


def test_active_cost_correction_is_charged_once():
    snapshot, plan_event = scenario()
    correction = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "cost"))
    correction["event_id"] = "correction-event"
    correction["payload"].update(cost_id="corrected", corrects_cost_id="commission", amount="2")
    snapshot["events"].append(correction)
    result = run(snapshot, plan_event)
    assert result["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert result["accounts"]["baseline"]["explicit_fees"] == "2"
    assert result["accounts"]["baseline"]["terminal_equity"] == "88"


def test_repeated_identical_fill_is_not_double_counted():
    snapshot, plan_event = scenario()
    duplicate = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "fill"))
    duplicate["event_id"] = "duplicate-import"
    snapshot["events"].append(duplicate)
    result = run(snapshot, plan_event)
    assert result["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert result["accounts"]["baseline"]["fill_count"] == 1
    assert result["accounts"]["baseline"]["terminal_equity"] == "89"


def test_changed_account_hashes_preserve_common_market_hash():
    snapshot, plan_event = scenario()
    result = run(snapshot, plan_event)
    payload(snapshot, "decision", 2)["input_hash"] = "c"*64
    changed = run(snapshot, plan_event)
    assert changed["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert changed["market_path_hash"] == result["market_path_hash"]


@pytest.mark.parametrize("damage", [
    "missing-calendar", "duplicate-calendar", "wrong-horizon", "wrong-reference", "future-reference",
    "missing-mark", "conflicting-mark", "late-mark", "wrong-feed", "mixed-environment", "mark-environment",
    "nonzero-inventory", "initial-open-order", "unknown-activity", "unbound-fill", "wrong-filled-total",
    "conflicting-fill", "missing-charge", "unknown-scope", "non-modeled-cost", "scope-conflict",
    "unlinked-cost", "order-cost", "duplicate-charge", "cost-cycle", "cost-branch", "wrong-currency",
    "multi-instrument", "overspend", "short", "extra-owner", "inventory-conflict", "missing-inventory",
    "missing-decision-order", "outside-window-fill", "fill-before-decision", "late-inventory", "future-cost",
])
def test_incomplete_or_ambiguous_account_has_no_return(damage):
    snapshot, plan_event = scenario()
    events = snapshot["events"]
    if damage == "missing-calendar":
        events.remove(next(e for e in events if e["kind"] == "decision" and e["payload"]["decision_id"] == "v2-d1"))
    elif damage == "duplicate-calendar":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "decision"))
        duplicate["payload"]["decision_id"] = "another-decision"
        events.append(duplicate)
    elif damage == "wrong-horizon": payload(snapshot, "decision")["horizon_end"] = "2026-01-06T14:31:00+00:00"
    elif damage == "wrong-reference": payload(snapshot, "decision", 2)["reference"]["price"] = "11"
    elif damage == "future-reference":
        for e in events:
            if e["kind"] == "decision" and e["payload"]["decision_at"] == INITIAL:
                e["payload"]["reference"]["available_at"] = MIDDLE
    elif damage == "missing-mark": events.remove(next(e for e in events if e["kind"] == "mark"))
    elif damage == "conflicting-mark":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "mark"))
        duplicate["payload"].update(mark_id="conflicting", price="13")
        events.append(duplicate)
    elif damage == "late-mark": payload(snapshot, "mark")["available_at"] = "2026-03-01T00:00:00+00:00"
    elif damage == "wrong-feed": payload(snapshot, "mark")["feed"] = "other"
    elif damage in {"mixed-environment", "mark-environment"}:
        next(e for e in events if e["kind"] == ("mark" if damage == "mark-environment" else "cost"))["environment"] = "paper"
    elif damage == "nonzero-inventory": payload(snapshot, "inventory")["quantity"] = "1"
    elif damage == "initial-open-order": payload(snapshot, "inventory")["open_order_ids"] = ["unknown"]
    elif damage == "unknown-activity": payload(snapshot, "source_note")["code"] = "SPLIT_OR_CASH_ACTIVITY"
    elif damage == "unbound-fill": events.remove(next(e for e in events if e["kind"] == "order_binding"))
    elif damage == "wrong-filled-total": payload(snapshot, "order")["filled_quantity"] = "4"
    elif damage == "conflicting-fill":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "fill"))
        duplicate["payload"]["price"] = "11"
        events.append(duplicate)
    elif damage == "missing-charge": events.remove(next(e for e in events if e["kind"] == "cost"))
    elif damage == "unknown-scope": payload(snapshot, "cost_scope")["components"]["commission"]["applicable"] = None
    elif damage == "non-modeled-cost": payload(snapshot, "cost")["evidence_kind"] = "observed"
    elif damage == "scope-conflict":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "cost_scope"))
        duplicate["payload"]["components"]["venue"]["applicable"] = True
        events.append(duplicate)
    elif damage == "unlinked-cost": payload(snapshot, "cost")["fill_id"] = "nonexistent"
    elif damage == "order-cost": payload(snapshot, "cost").pop("fill_id"); payload(snapshot, "cost")["order_id"] = "buy"
    elif damage == "duplicate-charge":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "cost"))
        duplicate["payload"]["cost_id"] = "duplicate-commission"
        events.append(duplicate)
    elif damage == "cost-cycle": payload(snapshot, "cost")["corrects_cost_id"] = "commission"
    elif damage == "cost-branch":
        for i in range(2):
            duplicate = deepcopy(next(e for e in events if e["kind"] == "cost"))
            duplicate["payload"].update(cost_id=f"correction-{i}", corrects_cost_id="commission")
            events.append(duplicate)
    elif damage == "wrong-currency": payload(snapshot, "cost")["currency"] = "GBP"
    elif damage == "multi-instrument": payload(snapshot, "fill")["symbol"] = "OTHER"
    elif damage == "overspend": payload(snapshot, "fill")["price"] = "25"
    elif damage == "short":
        payload(snapshot, "fill")["quantity_delta"] = "-5"
        payload(snapshot, "order")["side"] = "sell"
        payload(snapshot, "decision").update(action="sell", quantity_delta="-5")
    elif damage == "extra-owner":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "decision"))
        duplicate["payload"].update(decision_id="unknown-owner", agent_id="other-agent")
        events.append(duplicate)
    elif damage == "inventory-conflict":
        duplicate = deepcopy(next(e for e in events if e["kind"] == "inventory"))
        duplicate["payload"].update(quantity="4", observed_at=MIDDLE, capture_started_at=MIDDLE, capture_completed_at=MIDDLE)
        events.append(duplicate)
    elif damage == "missing-inventory": events.remove(next(e for e in events if e["kind"] == "inventory"))
    elif damage == "missing-decision-order":
        payload(snapshot, "decision", 2).update(action="buy", quantity_delta="1")
    elif damage == "outside-window-fill": payload(snapshot, "fill")["occurred_at"] = "2026-01-08T00:00:00+00:00"
    elif damage == "fill-before-decision": payload(snapshot, "fill")["occurred_at"] = "2026-01-05T14:29:00+00:00"
    elif damage == "late-inventory": payload(snapshot, "inventory")["capture_completed_at"] = FILL_AT
    elif damage == "future-cost": payload(snapshot, "cost")["applies_at"] = "2026-03-01T00:00:00+00:00"
    result = run(snapshot, plan_event)
    assert result["status"] in {"NOT_COMPARABLE", "INSUFFICIENT_EVIDENCE"}, damage
    assert result["exclusions"], damage
    assert result["accounts"] == {}, damage
    assert all(value is None for value in result["metrics"].values()), damage
    assert result["timeline"] == [], damage


def test_immature_window_is_insufficient_and_has_no_partial_return():
    snapshot, plan_event = scenario()
    result = run(snapshot, plan_event, as_of=MIDDLE)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["accounts"] == {}
    assert result["timeline"] == []


def test_unrelated_account_cost_conflict_does_not_poison_selected_accounts():
    snapshot, plan_event = scenario()
    unrelated = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "cost"))
    unrelated["payload"].update(source_alias="unrelated-account", corrects_cost_id="missing-unrelated-cost")
    snapshot["events"].append(unrelated)
    result = run(snapshot, plan_event)
    assert result["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert result["accounts"]["baseline"]["terminal_equity"] == "89"


def test_valid_scope_revision_retains_complete_modeled_coverage():
    import hashlib
    from tradeoff.feedback.contracts import canonical_json
    snapshot, plan_event = scenario()
    old = payload(snapshot, "cost_scope")
    revision = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "cost_scope"))
    revision["payload"]["supersedes_scope_hash"] = hashlib.sha256(canonical_json(old).encode()).hexdigest()
    snapshot["events"].append(revision)
    result = run(snapshot, plan_event)
    assert result["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert result["accounts"]["baseline"]["explicit_fees"] == "1"


def test_zero_applicable_charge_is_evidence_and_is_not_missing():
    snapshot, plan_event = scenario()
    payload(snapshot, "cost")["amount"] = "0"
    result = run(snapshot, plan_event)
    assert result["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert result["accounts"]["baseline"]["terminal_equity"] == "90"


@pytest.mark.parametrize("damage", ["orphan-binding", "filled-order-incomplete", "conflicting-old-order-identity"])
def test_inconsistent_order_history_is_not_a_complete_simulated_account(damage):
    snapshot, plan_event = scenario()
    if damage == "orphan-binding":
        extra = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "order_binding"))
        extra["payload"].update(order_id="never-imported", decision_id="v2-d0", source_alias="candidate-source")
        snapshot["events"].append(extra)
    elif damage == "filled-order-incomplete":
        payload(snapshot, "order")["quantity"] = "6"
    else:
        extra = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "order"))
        extra["payload"]["submitted_at"] = "2026-01-05T14:30:30+00:00"
        extra["payload"]["source_updated_at"] = "2026-01-05T14:30:45+00:00"
        snapshot["events"].append(extra)
    result = run(snapshot, plan_event)
    assert result["status"] == "NOT_COMPARABLE"
    assert result["accounts"] == {}
    assert result["exclusions"]


def test_changed_terminal_price_changes_market_receipt():
    snapshot, plan_event = scenario()
    before = run(snapshot, plan_event)
    payload(snapshot, "mark", 1)["price"] = "9"
    after = run(snapshot, plan_event)
    assert after["status"] == "MODELED_ACCOUNT_COMPARISON"
    assert after["market_path_hash"] != before["market_path_hash"]
    assert after["accounts"]["baseline"]["terminal_equity"] == "94"


@pytest.mark.parametrize("damage", ["nonpositive-reference", "order-exceeds-intent", "hold-submits-order"])
def test_recorded_intent_must_support_the_modeled_order(damage):
    snapshot, plan_event = scenario()
    if damage == "nonpositive-reference":
        for event in snapshot["events"]:
            if event["kind"] == "decision" and event["payload"]["decision_at"] == INITIAL:
                event["payload"]["reference"]["price"] = "0"
    elif damage == "order-exceeds-intent":
        payload(snapshot, "decision")["quantity_delta"] = "4"
    else:
        extra = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "order"))
        extra["payload"].update(order_id="hold-order", source_alias="candidate-source", quantity="1", filled_quantity="0", status="open")
        snapshot["events"].append(extra)
        binding = deepcopy(next(e for e in snapshot["events"] if e["kind"] == "order_binding"))
        binding["payload"].update(decision_id="v2-d0", source_alias="candidate-source", order_id="hold-order")
        snapshot["events"].append(binding)
    result = run(snapshot, plan_event)
    assert result["status"] == "NOT_COMPARABLE"
    assert result["accounts"] == {}
    assert result["exclusions"]
