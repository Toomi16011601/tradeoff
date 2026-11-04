from copy import deepcopy
from datetime import datetime

import pytest

from feedback_helpers import (START, AFTER_HORIZON, decision, plan, episode_records, make_snapshot, mark)


def comparison_fixture(tmp_path, *, late_plan=False):
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.comparison import register_plan
    from tradeoff.feedback.reconcile import reconcile
    from tradeoff.feedback.metrics import evaluate
    with FeedbackStore(tmp_path, create=True, clock=lambda: datetime.fromisoformat(
        "2026-01-05T15:00:00+00:00" if late_plan else "2026-01-05T14:00:00+00:00")) as store:
        register_plan(store, plan(), event_id="plan-1")
    records = []
    for version in ("v1", "v2"):
        for i in (1, 2):
            suffix = f"-{version}-{i}"
            items = episode_records(alias=f"source-{version}-{i}", version=version, suffix=suffix)
            # Two literal paired long outcomes: baseline .95/.48, candidate .90/.45 on notional 5.
            exit_price = {("v1", 1): "12", ("v1", 2): "11.06", ("v2", 1): "11.9", ("v2", 2): "11"}[(version, i)]
            items[1]["payload"]["opportunity_id"] = f"opportunity-{i}"
            items[2]["payload"]["opportunity_id"] = f"close-{i}"
            items[8]["payload"]["price"] = exit_price
            records.extend(items)
    snap = make_snapshot(tmp_path, records)
    rec = reconcile(snap, as_of=AFTER_HORIZON)
    result = evaluate(rec, marks=[mark()], costs=[e["payload"] for e in snap["events"] if e["kind"] == "cost"],
        cost_scopes=[e["payload"] for e in snap["events"] if e["kind"] == "cost_scope"], as_of=AFTER_HORIZON)
    return snap, result


def test_paired_delta_and_subset_disclosure(tmp_path):
    from tradeoff.feedback.comparison import compare
    snap, evaluation = comparison_fixture(tmp_path)
    result = compare(snap, evaluation, plan_id="comparison-1", as_of=AFTER_HORIZON)
    assert result["status"] == "DESCRIPTIVE_COMPARISON"
    assert result["matched_count"] == 2
    assert result["metrics"]["mean_delta_bps"] == "-80"
    assert result["metrics"]["baseline_mean_bps"] == "1430"
    assert result["metrics"]["candidate_mean_bps"] == "1350"
    assert "both-traded" in result["scope"]
    assert "winner" not in result
    assert result["capture_class"] == "PROSPECTIVE_PLAN"


def test_late_or_changed_plan_is_retrospective(tmp_path):
    from tradeoff.feedback.comparison import compare, register_plan
    from tradeoff.feedback.store import FeedbackStore
    snap, evaluation = comparison_fixture(tmp_path)
    with FeedbackStore(tmp_path, clock=lambda: datetime.fromisoformat(AFTER_HORIZON)) as store:
        register_plan(store, plan(plan_id="revision-2", supersedes_plan_id="comparison-1"), event_id="plan-2")
        snap = store.snapshot()
    result = compare(snap, evaluation, plan_id="revision-2", as_of=AFTER_HORIZON)
    assert result["capture_class"] == "RETROSPECTIVE_PLAN"


@pytest.mark.parametrize("change", ["candidate-absent", "all-skipped", "feed", "cost", "imported", "different-period"])
def test_incompatible_or_untraded_opportunities_are_not_a_winner(tmp_path, change):
    from tradeoff.feedback.comparison import compare
    snap, evaluation = comparison_fixture(tmp_path)
    for d in evaluation["decisions"]:
        if d["agent_version"] == "v2":
            if change == "feed":
                d["reference"]["feed"] = "other"
            elif change == "all-skipped":
                d["action"], d["episode_ids"] = "skip", []
            elif change == "imported":
                d["capture"]["classification"] = "IMPORTED"
            elif change == "different-period":
                d["decision_at"] = "2026-01-06T14:30:01+00:00"
    if change == "candidate-absent":
        evaluation["decisions"] = [d for d in evaluation["decisions"] if d["agent_version"] != "v2"]
    if change == "cost":
        for e in evaluation["episodes"]:
            if e["agent_version"] == "v2":
                e["observed_net"] = None
    result = compare(snap, evaluation, plan_id="comparison-1", as_of=AFTER_HORIZON)
    assert result["status"] in {"INSUFFICIENT_EVIDENCE", "NOT_COMPARABLE"}
    assert result["matched_count"] == 0
    assert result["exclusions"]
