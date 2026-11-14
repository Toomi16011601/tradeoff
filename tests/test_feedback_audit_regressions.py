"""Malformed imported evidence must not manufacture clean financial feedback."""
from copy import deepcopy

import pytest

from feedback_helpers import AFTER_HORIZON, episode_records, make_snapshot, mark
from tradeoff.feedback.api import FeedbackApp
from test_feedback_simulated_comparison import AS_OF, scenario


def report(project, records):
    make_snapshot(project, records)
    return FeedbackApp(project).evaluate_decisions({"as_of": AFTER_HORIZON})["evaluation"]


@pytest.mark.parametrize("damage", ["before-decision", "before-submission"])
def test_fill_with_impossible_decision_order_timing_has_no_attributed_net(tmp_path, damage):
    records = episode_records()
    entry = next(r["payload"] for r in records if r["kind"] == "fill")
    entry["occurred_at"] = ("2026-01-05T14:30:00.500000+00:00" if damage == "before-decision"
                            else "2026-01-05T14:30:01.500000+00:00")
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "UNATTRIBUTABLE"
    assert episode["observed_net"] is None
    assert "EXECUTION_TIME_CONFLICT" in episode["reasons"]


@pytest.mark.parametrize("damage", ["fills-exceed-intent", "order-exceeds-intent", "split-orders-exceed-intent"])
def test_execution_exceeding_recorded_intent_is_not_clean_attribution(tmp_path, damage):
    records = episode_records()
    intent = next(r["payload"] for r in records if r["kind"] == "decision")
    intent["quantity_delta"] = "0.01" if damage == "fills-exceed-intent" else "1"
    if damage == "split-orders-exceed-intent":
        entry = next(r["payload"] for r in records if r["kind"] == "order")
        entry["quantity"] = "0.75"
        extra = deepcopy(next(r for r in records if r["kind"] == "order"))
        extra.update(event_id="second-order")
        extra["payload"].update(order_id="second-entry", quantity="0.75", filled_quantity="0", status="new")
        records.extend([extra, dict(event_id="second-binding", kind="order_binding", environment="paper",
            payload=dict(decision_id="d1", source_alias="paper_a", order_id="second-entry"))])
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "UNATTRIBUTABLE"
    assert episode["observed_net"] is None
    assert "INTENT_QUANTITY_CONFLICT" in episode["reasons"]


@pytest.mark.parametrize("replacement_quantity", ["0.75", "1.25"])
def test_valid_replacement_and_partial_fills_preserve_original_intent(tmp_path, replacement_quantity):
    records = episode_records()
    entry = next(r["payload"] for r in records if r["kind"] == "order")
    entry.update(replaced_by_order_id="replacement-entry", status="replaced")
    replacement = deepcopy(next(r for r in records if r["kind"] == "order"))
    replacement.update(event_id="replacement-order")
    replacement["payload"].pop("replaced_by_order_id")
    replacement["payload"].update(order_id="replacement-entry", replaces_order_id="order-entry",
        quantity=replacement_quantity, filled_quantity="0", status="canceled")
    records.append(replacement)
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "ATTRIBUTABLE_CLOSED"
    assert episode["observed_net"] == "0.95"


def test_canceled_partial_order_can_retry_its_unfilled_remainder(tmp_path):
    records = episode_records()
    original = next(r["payload"] for r in records if r["kind"] == "order")
    original["source_updated_at"] = "2026-01-05T14:30:04+00:00"
    retry = deepcopy(next(r for r in records if r["kind"] == "order"))
    retry.update(event_id="retry-order")
    retry["payload"].update(order_id="retry-entry", quantity="0.75", filled_quantity="0", status="canceled",
        submitted_at="2026-01-05T14:30:05+00:00", source_updated_at="2026-01-05T14:30:06+00:00")
    records.extend([retry, dict(event_id="retry-binding", kind="order_binding", environment="paper",
        payload=dict(decision_id="d1", source_alias="paper_a", order_id="retry-entry"))])
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "ATTRIBUTABLE_CLOSED"
    assert episode["observed_net"] == "0.95"


@pytest.mark.parametrize("damage", ["environment", "binding-environment", "instrument", "ambiguous-binding"])
@pytest.mark.parametrize("explicit_child", [False, True])
def test_unfilled_replacement_ancestor_cannot_hide_conflicting_evidence(tmp_path, damage, explicit_child):
    records = episode_records()
    original = next(r for r in records if r["kind"] == "order")
    child = deepcopy(original)
    child.update(event_id="replacement-order", environment="paper")
    child["payload"].update(order_id="replacement-entry", replaces_order_id="order-entry")
    original["payload"].update(filled_quantity="0", status="replaced", replaced_by_order_id="replacement-entry")
    for record in records:
        p = record["payload"]
        if record["kind"] in {"fill", "cost"} and p.get("order_id") == "order-entry":
            p["order_id"] = "replacement-entry"
    records.append(child)
    if explicit_child:
        records.append(dict(event_id="child-binding", kind="order_binding", environment="paper",
            payload=dict(decision_id="d1", source_alias="paper_a", order_id="replacement-entry")))
    if damage == "environment":
        original["environment"] = "simulated"
    elif damage == "binding-environment":
        next(r for r in records if r["kind"] == "order_binding")["environment"] = "simulated"
    elif damage == "instrument":
        original["payload"]["currency"] = "EUR"
    else:
        other = deepcopy(next(r for r in records if r["kind"] == "decision"))
        other.update(event_id="other-intent")
        other["payload"].update(decision_id="d3", agent_version="v3")
        records.insert(1, other)
        records.insert(2, dict(event_id="conflicting-parent-binding", kind="order_binding", environment="paper",
            payload=dict(decision_id="d3", source_alias="paper_a", order_id="order-entry")))
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "UNATTRIBUTABLE"
    assert episode["observed_net"] is None


@pytest.mark.parametrize("kind", ["inventory", "order", "order_binding", "cost", "cost_scope"])
def test_simulated_evidence_cannot_complete_observed_paper_net(tmp_path, kind):
    records = episode_records()
    for record in records:
        if record["kind"] == kind:
            record["environment"] = "simulated"
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["observed_net"] is None
    assert episode["modeled_net"] is None
    assert "ENVIRONMENT_CONFLICT" in episode["reasons"]


def test_inventory_for_another_instrument_cannot_establish_opening_shares(tmp_path):
    records = episode_records()
    records[0]["payload"].update(currency="EUR", asset_class="crypto")
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "UNATTRIBUTABLE"
    assert episode["observed_net"] is None
    assert "INVENTORY_INSTRUMENT_CONFLICT" in episode["reasons"]


def test_filled_order_with_only_partial_execution_evidence_cannot_realize_net(tmp_path):
    records = episode_records()
    next(r["payload"] for r in records if r["kind"] == "order")["status"] = "filled"
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "UNATTRIBUTABLE"
    assert episode["observed_net"] is None
    assert "FILLED_ORDER_QUANTITY_CONFLICT" in episode["reasons"]


@pytest.mark.parametrize("kind", ["order", "fill"])
@pytest.mark.parametrize("foreign_first", [False, True])
def test_duplicate_execution_payloads_cannot_hide_conflicting_environments(tmp_path, kind, foreign_first):
    records = episode_records()
    extra = deepcopy(next(r for r in records if r["kind"] == kind))
    extra.update(event_id="foreign-duplicate", environment="simulated")
    records.insert(0, extra) if foreign_first else records.append(extra)
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["status"] == "UNATTRIBUTABLE"
    assert episode["observed_net"] is None
    assert "ENVIRONMENT_CONFLICT" in episode["reasons"]


def test_cost_correction_cannot_hide_a_change_of_recording_environment(tmp_path):
    records = episode_records()
    original = next(r for r in records if r["kind"] == "cost")
    correction = deepcopy(original)
    original["environment"] = "simulated"
    correction.update(event_id="paper-cost-correction", environment="paper")
    correction["payload"].update(cost_id="corrected-entry", corrects_cost_id="cost-entry")
    records.append(correction)
    episode = report(tmp_path, records)["episodes"][0]
    assert episode["observed_net"] is None
    assert "ENVIRONMENT_CONFLICT" in episode["reasons"]


@pytest.mark.parametrize("same_id", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_horizon_prices_remain_unknown_regardless_of_import_order(tmp_path, same_id, reverse):
    marks = [mark(mark_id="first", price="12"), mark(mark_id="first" if same_id else "second", price="99")]
    if reverse:
        marks.reverse()
    records = episode_records() + [dict(event_id=f"mark-{i}", kind="mark", payload=item, environment="paper")
                                   for i, item in enumerate(marks)]
    evaluation = report(tmp_path, records)
    decision = evaluation["decisions"][0]
    assert decision["outcome_status"] == "UNAVAILABLE"
    assert decision["horizon_mark_id"] is None
    assert decision["horizon_price_change"] is None
    assert any(f["code"] == "MARK_OBSERVATION_CONFLICT" for f in evaluation["findings"])


def test_simulated_horizon_mark_cannot_complete_a_paper_outcome(tmp_path):
    records = episode_records() + [dict(event_id="mark", kind="mark", payload=mark(), environment="simulated")]
    evaluation = report(tmp_path, records)
    assert evaluation["decisions"][0]["outcome_status"] == "UNAVAILABLE"
    assert any(f["code"] == "ENVIRONMENT_CONFLICT" for f in evaluation["findings"])


@pytest.mark.parametrize("kind", ["order", "mark", "cost", "inventory", "fill", "source_note"])
def test_future_evidence_cannot_change_a_historical_simulated_comparison(tmp_path, kind):
    snapshot, _ = scenario()
    records = [{k: deepcopy(e[k]) for k in ("event_id", "kind", "payload", "environment")}
               for e in snapshot["events"]]
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(tmp_path, create=True, environment="simulated"):
        pass
    app = FeedbackApp(tmp_path)
    app.import_evidence({"records": records})
    arguments = dict(plan_id="modeled-plan", as_of=AS_OF)
    original = app.compare_versions(arguments)
    assert original["status"] == "MODELED_ACCOUNT_COMPARISON"
    future = deepcopy(next(r for r in records if r["kind"] == kind))
    future["event_id"] = "future-update"
    later = "2026-03-01T00:00:00+00:00"
    changes = {
        "order": dict(source_updated_at=later, filled_quantity="0", status="new"),
        "mark": dict(mark_id="future-mark", available_at=later, price="99"),
        "cost": dict(cost_id="future-charge", applies_at=later),
        "inventory": dict(observed_at=later, capture_started_at=later, capture_completed_at=later, currency="EUR"),
        "fill": dict(fill_id="future-fill", occurred_at=later),
        "source_note": dict(note_id="future-note", interval_start=later, interval_end="2026-03-02T00:00:00+00:00"),
    }
    future["payload"].update(changes[kind])
    if kind in {"cost", "source_note"}:
        future["environment"] = "paper"
    app.import_evidence({"records": [future]})
    assert app.compare_versions(arguments) == original
