from copy import deepcopy

from feedback_helpers import (AFTER_HORIZON, episode_records, make_snapshot, complete_cost_scope, cost, mark)


def evaluate_records(tmp_path, records, *, marks=None, as_of=AFTER_HORIZON):
    from tradeoff.feedback.reconcile import reconcile
    from tradeoff.feedback.metrics import evaluate
    snapshot = make_snapshot(tmp_path, records)
    return evaluate(reconcile(snapshot, as_of=as_of), marks=marks or [],
        costs=[e["payload"] for e in snapshot["events"] if e["kind"] == "cost"],
        cost_scopes=[e["payload"] for e in snapshot["events"] if e["kind"] == "cost_scope"], as_of=as_of)


def test_partial_cancel_gross_and_net_are_exact(tmp_path):
    result = evaluate_records(tmp_path, episode_records(), marks=[mark()])
    episode = result["episodes"][0]
    assert (episode["gross_cashflow"], episode["observed_net"], episode["entry_notional"]) == ("1", "0.95", "5")
    assert result["decisions"][0]["horizon_price_change"] == "2"


def test_short_net_unknown_until_explicit_borrow_observation(tmp_path):
    records = episode_records(short=True)
    unknown = evaluate_records(tmp_path / "unknown", records)
    episode = unknown["episodes"][0]
    assert episode["gross_cashflow"] == "0.5"
    assert episode["observed_net"] is None
    assert "BORROW_COST_UNKNOWN" in episode["reasons"]
    records[11]["payload"] = complete_cost_scope("episode-short", short=True, borrow="0")
    records.append(dict(event_id="borrow-zero", kind="cost", payload=dict(cost_id="borrow-zero", source_alias="paper_a",
        component="borrow", amount="0", currency="USD", evidence_kind="observed", applies_at=AFTER_HORIZON,
        episode_id="episode-short")))
    known = evaluate_records(tmp_path / "known", records)
    assert known["episodes"][0]["observed_net"] == "0.48"


def test_cost_revision_changes_new_result_not_old_export_value(tmp_path):
    records = episode_records()
    old = evaluate_records(tmp_path / "old", records)
    corrected = cost(cost_id="fee-correction", amount="0.12", corrects_cost_id="cost-entry")
    records.append(dict(event_id="fee-correction", kind="cost", payload=corrected))
    new = evaluate_records(tmp_path / "new", records)
    assert old["episodes"][0]["observed_net"] == "0.95"
    assert new["episodes"][0]["observed_net"] == "0.85"


def test_mixed_version_profit_and_modeled_fee_are_not_observed(tmp_path):
    records = episode_records(mixed=True)
    assert evaluate_records(tmp_path / "mixed", records)["episodes"][0]["observed_net"] is None
    records = episode_records()
    records[9]["payload"]["evidence_kind"] = "modeled"
    result = evaluate_records(tmp_path / "modeled", records)["episodes"][0]
    assert result["observed_net"] is None
    assert result["modeled_net"] == "0.95"


def test_horizon_marks_must_be_mature_compatible_and_available(tmp_path):
    records = episode_records()
    early = evaluate_records(tmp_path / "early", records, marks=[mark()], as_of="2026-01-05T15:00:00Z")
    assert early["decisions"][0]["outcome_status"] == "PENDING"
    for i, bad in enumerate([mark(feed="other"), mark(observed_at="2026-01-05T15:28:00Z"),
        mark(available_at="2026-01-06T00:00:00Z")]):
        unavailable = evaluate_records(tmp_path / str(i), records, marks=[bad])
        assert unavailable["decisions"][0]["outcome_status"] == "UNAVAILABLE"


def test_large_quantities_do_not_collapse_to_the_same_profit(tmp_path):
    results = []
    for i, quantity in enumerate(["9007199254740993.25", "9007199254740994.25"]):
        records = episode_records()
        for r in records:
            p = r["payload"]
            if r["kind"] in {"decision", "fill"}:
                p["quantity_delta"] = ("-" if p["quantity_delta"].startswith("-") else "") + quantity
            if r["kind"] == "order":
                p.update(quantity=quantity, filled_quantity=quantity)
            if r["kind"] == "fill":
                p["price"] = "1" if p["fill_id"] == "fill-entry" else "2"
            if r["kind"] == "cost":
                p["amount"] = "0"
        results.append(evaluate_records(tmp_path / str(i), records)["episodes"][0]["observed_net"])
    assert results == ["9007199254740993.25", "9007199254740994.25"]


def test_execution_difference_is_signed_price_diagnostic():
    from tradeoff.feedback.metrics import execution_difference
    from feedback_helpers import fill, decision
    assert execution_difference(fill(price="10.1"), decision()["reference"]) == "0.1"
    assert execution_difference(fill(price="9.9", quantity_delta="-0.5"), decision()["reference"]) == "0.1"


def test_exposure_does_not_add_shares_across_inventory_streams(tmp_path):
    records = episode_records() + episode_records(alias="paper_b", suffix="-b")
    result = evaluate_records(tmp_path, records)
    opened = [p for p in result["groups"][0]["exposure"] if p["at"] == "2026-01-05T14:30:03+00:00"]
    assert [p["quantity"] for p in opened] == ["0.5", "0.5"]
    assert {p["source_alias"] for p in opened} == {"paper_a", "paper_b"}


def test_modeled_estimate_does_not_override_observed_component(tmp_path):
    records = episode_records()
    records.append(dict(event_id="estimate", kind="cost", payload=cost(cost_id="estimate", amount="99", evidence_kind="modeled")))
    result = evaluate_records(tmp_path, records)
    assert result["episodes"][0]["observed_net"] == "0.95"
