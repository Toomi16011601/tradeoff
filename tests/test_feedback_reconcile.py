from copy import deepcopy

import pytest

from feedback_helpers import (AFTER_HORIZON, partial_cancel_snapshot, mixed_version_snapshot,
                              episode_records, make_snapshot)


def test_partial_cancel_preserves_fills_and_unfilled_quantity(partial_cancel_snapshot):
    from tradeoff.feedback.reconcile import reconcile
    result = reconcile(partial_cancel_snapshot, as_of=AFTER_HORIZON)
    episode = result["episodes"][0]
    assert episode["status"] == "ATTRIBUTABLE_CLOSED"
    assert (episode["entry_quantity"], episode["closing_quantity"], episode["unfilled_quantity"]) == ("0.5", "0.5", "0.75")
    assert len(episode["fill_ids"]) == 2


def test_mixed_versions_have_no_attributed_winner(mixed_version_snapshot):
    from tradeoff.feedback.reconcile import reconcile
    result = reconcile(mixed_version_snapshot, as_of=AFTER_HORIZON)
    assert result["episodes"][0]["status"] == "UNATTRIBUTABLE"
    assert "MIXED_VERSION" in result["episodes"][0]["reasons"]


@pytest.mark.parametrize("change,reason", [("no-inventory", "OPENING_INVENTORY_UNKNOWN"),
    ("carried", "EXTERNAL_INVENTORY"), ("unbound", "UNBOUND_FILL"),
    ("child", "UNSUPPORTED_CHILD_ORDER"), ("replacement", "REPLACEMENT_UNRESOLVED"),
    ("quantity", "FILL_QUANTITY_CONFLICT"), ("snapshot-window", "INVENTORY_WINDOW_CONFLICT")])
def test_ambiguous_evidence_is_visible_but_not_attributed(tmp_path, change, reason):
    from tradeoff.feedback.reconcile import reconcile
    records = episode_records()
    if change == "no-inventory":
        records = [r for r in records if r["kind"] != "inventory"]
    elif change == "carried":
        records[0]["payload"]["quantity"] = "1"
    elif change == "unbound":
        records = [r for r in records if not (r["kind"] == "order_binding" and r["payload"]["order_id"] == "order-exit")]
    elif change == "child":
        records[5]["payload"]["parent_order_id"] = "external-parent"
    elif change == "replacement":
        records[5]["payload"]["replaced_by_order_id"] = "missing"
    elif change == "quantity":
        records[5]["payload"]["filled_quantity"] = "0.4"
    else:
        records[0]["payload"]["capture_completed_at"] = "2026-01-05T14:30:04+00:00"
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert result["episodes"][0]["status"] == "UNATTRIBUTABLE"
    assert reason in result["episodes"][0]["reasons"]
    assert not result["coverage"]["attribution_complete"]


def test_open_inventory_is_pending_not_realized(tmp_path):
    from tradeoff.feedback.reconcile import reconcile
    records = [r for r in episode_records() if not (r["kind"] == "fill" and r["payload"]["fill_id"] == "fill-exit")]
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert result["episodes"][0]["status"] != "ATTRIBUTABLE_CLOSED"


def test_fill_ingestion_order_does_not_change_broker_event_order(tmp_path):
    from tradeoff.feedback.reconcile import reconcile
    records = episode_records()
    records[7], records[8] = records[8], records[7]
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert result["episodes"][0]["status"] == "ATTRIBUTABLE_CLOSED"
    assert result["episodes"][0]["fill_ids"] == ["fill-entry", "fill-exit"]


@pytest.mark.parametrize("change,reason", [("reversal", "WITHIN_FILL_REVERSAL"),
    ("currency", "UNSUPPORTED_INSTRUMENT"), ("snapshot", "INVENTORY_SNAPSHOT_CONFLICT")])
def test_reversals_fx_and_conflicting_snapshots_stay_excluded(tmp_path, change, reason):
    from tradeoff.feedback.reconcile import reconcile
    records = episode_records()
    if change == "reversal":
        records[6]["payload"].update(quantity="1", filled_quantity="1")
        records[8]["payload"]["quantity_delta"] = "-1"
    elif change == "currency":
        records[7]["payload"]["currency"] = "EUR"
    else:
        new = deepcopy(records[0])
        new["event_id"] = "conflicting-inventory"
        new["payload"]["quantity"] = "1"
        records.append(new)
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert reason in result["episodes"][0]["reasons"]
    assert result["episodes"][0]["status"] == "UNATTRIBUTABLE"


def test_partial_fetch_is_separate_from_attribution(partial_cancel_snapshot):
    from tradeoff.feedback.reconcile import reconcile
    partial_cancel_snapshot["sync_state"] = {"paper_a": {"fetch_complete": False}}
    result = reconcile(partial_cancel_snapshot, as_of=AFTER_HORIZON)
    assert not result["coverage"]["fetch_complete"]
    assert result["coverage"]["attribution_complete"]
