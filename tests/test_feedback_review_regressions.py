"""Concrete independent-review reproductions, with literal expected outcomes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from feedback_helpers import (AFTER_HORIZON, START, END, decision, episode_records, make_snapshot)
from test_feedback_metrics import evaluate_records
from test_feedback_comparison import comparison_fixture


def test_missing_exit_commission_cannot_be_assumed_zero(tmp_path):
    records = [r for r in episode_records() if r["event_id"] != "fixture-10"]
    result = evaluate_records(tmp_path, records)["episodes"][0]
    assert result["observed_net"] is None
    assert result["modeled_net"] is None
    assert "COMMISSION_COST_UNKNOWN" in result["reasons"]


def test_modeled_nonapplicability_is_never_observed_zero(tmp_path):
    records = [r for r in episode_records() if r["kind"] != "cost"]
    scope = next(r["payload"] for r in records if r["kind"] == "cost_scope")
    scope["evidence_kind"] = "modeled"
    for component in scope["components"].values():
        component["applicable"] = False
    result = evaluate_records(tmp_path, records)["episodes"][0]
    assert result["observed_net"] is None
    assert result["modeled_net"] == "1"
    assert result["cost_coverage"] == "MODELED"


@pytest.mark.parametrize("partial_history", [False, True])
def test_older_history_does_not_poison_a_new_verified_baseline(tmp_path, partial_history):
    from tradeoff.feedback.reconcile import reconcile
    old = episode_records(suffix="-old")
    old = [r for r in old if r["kind"] != "inventory"]
    if partial_history:
        old = [r for r in old if not (r["kind"] == "fill" and r["payload"]["fill_id"] == "fill-exit-old")]
    def previous_day(value):
        if isinstance(value, dict):
            return {k: previous_day(v) for k,v in value.items()}
        if isinstance(value, list):
            return [previous_day(v) for v in value]
        return value.replace("2026-01-05", "2026-01-04") if isinstance(value,str) else value
    old = previous_day(old)
    result = reconcile(make_snapshot(tmp_path, old + episode_records()), as_of=AFTER_HORIZON)
    episodes = {e["episode_id"]: e for e in result["episodes"]}
    assert episodes["episode-long-old"]["status"] == "UNATTRIBUTABLE"
    assert episodes["episode-long"]["status"] == "ATTRIBUTABLE_CLOSED"


def test_generated_episode_context_contains_no_raw_broker_ids(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    records = episode_records()
    for r in records:
        if r["kind"] == "decision":
            r["payload"].pop("episode_id")
    make_snapshot(tmp_path, records)
    app = FeedbackApp(tmp_path)
    report = app.evaluate_decisions({"as_of": AFTER_HORIZON})
    eid = report["evaluation"]["episodes"][0]["episode_id"]
    assert "paper_a" not in eid and "fill-entry" not in eid
    app.export_feedback({"output": "feedback-output", "as_of": AFTER_HORIZON})
    for p in (tmp_path / "feedback-output").iterdir():
        assert "fill-entry" not in p.read_text()
        assert "paper_a" not in p.read_text()
    assert report["evaluation"]["decisions"][0]["episode_ids"] == [eid]


@pytest.mark.parametrize("field,value", [("event_id", "sk-proj-" + "SYNTHETIC" * 4),
    ("source_event_id", "/Users/SYNTHETIC/private/account")])
def test_direct_python_envelopes_cannot_store_or_echo_recognized_secrets(tmp_path, field, value):
    from tradeoff.feedback.recorder import Recorder
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    with FeedbackStore(tmp_path, create=True):
        pass
    recorder = Recorder(tmp_path)
    with pytest.raises(FeedbackError) as caught:
        if field == "event_id":
            recorder.record_decision(decision(), event_id=value)
        else:
            recorder.import_evidence([dict(event_id="e1", source_event_id=value, kind="decision", payload=decision())])
    assert value not in str(caught.value)
    with FeedbackStore(tmp_path) as store:
        assert not store.snapshot()["events"]


def test_late_economic_fee_invalidates_earlier_outcome(tmp_path):
    from tradeoff.feedback.alpaca import PaperReader, sync_paper
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.store import FeedbackStore
    from test_feedback_alpaca import PaperTransport
    make_snapshot(tmp_path, episode_records())
    fake = PaperTransport(activities=[{"id": "late-fee", "activity_type": "FEE", "date": "2026-01-05", "net_amount": "-0.25"}])
    with FeedbackStore(tmp_path) as store:
        reader = PaperReader(key_id="k", secret_key="s", fingerprint=store.fingerprint, transport=fake)
        sync_paper(store, reader, source_alias="paper_a", start="2026-01-06T00:00:00Z", end="2026-01-07T00:00:00Z")
        note = next(e["payload"] for e in store.snapshot()["events"] if e["kind"] == "source_note")
        assert note["metadata"]["economic_at"].startswith("2026-01-05")
    result = FeedbackApp(tmp_path).evaluate_decisions({"as_of": "2026-01-07T00:00:00Z"})
    episode = result["evaluation"]["episodes"][0]
    assert episode["observed_net"] is None
    assert "UNSUPPORTED_SOURCE_ACTIVITY" in episode["reasons"]


def test_comparison_does_not_pool_different_pair_environments(tmp_path):
    from tradeoff.feedback.comparison import compare
    snapshot, evaluation = comparison_fixture(tmp_path)
    episode_ids = set()
    for d in evaluation["decisions"]:
        if d["opportunity_id"] == "opportunity-2":
            d["environment"] = "simulated"
            episode_ids.update(d["episode_ids"])
    for e in evaluation["episodes"]:
        if e["episode_id"] in episode_ids:
            e["environment"] = "simulated"
    result = compare(snapshot, evaluation, plan_id="comparison-1", as_of=AFTER_HORIZON)
    assert result["status"] == "NOT_COMPARABLE"
    assert result["metrics"]["mean_delta_bps"] is None


def test_order_asset_class_cannot_disguise_unsupported_execution(tmp_path):
    from tradeoff.feedback.reconcile import reconcile
    records = episode_records()
    for r in records:
        if r["kind"] == "order":
            r["payload"]["asset_class"] = "crypto"
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert result["episodes"][0]["status"] == "UNATTRIBUTABLE"
    assert "ORDER_FILL_CONFLICT" in result["episodes"][0]["reasons"]


def test_missing_commission_excludes_a_pair_through_public_api(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    snapshot, _ = comparison_fixture(tmp_path / "original")
    records = [{k: e[k] for k in ("event_id", "kind", "payload", "origin", "environment", "source_event_id")}
        for e in snapshot["events"] if not (e["kind"] == "cost" and
            e["payload"].get("order_id") == "order-exit-v2-2")]
    make_snapshot(tmp_path / "incomplete", records)
    result = FeedbackApp(tmp_path / "incomplete").compare_versions({"plan_id": "comparison-1", "as_of": AFTER_HORIZON})
    assert result["matched_count"] == 1
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_malformed_economic_date_is_preserved_as_unallocated_activity(tmp_path):
    from tradeoff.feedback.alpaca import PaperReader, sync_paper
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.store import FeedbackStore
    from test_feedback_alpaca import PaperTransport
    make_snapshot(tmp_path, episode_records())
    fake = PaperTransport(activities=[{"id": "unknown-date", "activity_type": "FEE", "date": "unsupported-date", "net_amount": "-0.25"}])
    with FeedbackStore(tmp_path) as store:
        reader = PaperReader(key_id="k", secret_key="s", fingerprint=store.fingerprint, transport=fake)
        sync_paper(store, reader, source_alias="paper_a", start="2026-01-06T00:00:00Z", end="2026-01-07T00:00:00Z")
        assert any(e["kind"] == "source_note" for e in store.snapshot()["events"])
    result = FeedbackApp(tmp_path).evaluate_decisions({"as_of": "2026-01-07T00:00:00Z"})
    assert result["evaluation"]["episodes"][0]["observed_net"] is None
