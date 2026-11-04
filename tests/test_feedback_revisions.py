"""The running workflow must improve evidence without rewriting old outcomes."""
import hashlib

from feedback_helpers import (AFTER_HORIZON, START, complete_cost_scope, episode_records, make_snapshot)


def test_explicit_scope_revision_resolves_borrow_without_rewriting_old_result(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import canonical_json
    records = episode_records(short=True)
    old_scope = records[11]["payload"]
    snapshot = make_snapshot(tmp_path, records)
    old_seq = snapshot["as_of_seq"]
    app = FeedbackApp(tmp_path)
    assert app.evaluate_decisions({"as_of": AFTER_HORIZON})["evaluation"]["episodes"][0]["observed_net"] is None
    scope = complete_cost_scope("episode-short", short=True, borrow="0")
    scope["supersedes_scope_hash"] = hashlib.sha256(canonical_json(old_scope).encode()).hexdigest()
    app.import_evidence({"records": [dict(event_id="scope-revision", kind="cost_scope", payload=scope),
        dict(event_id="observed-borrow", kind="cost", payload=dict(cost_id="observed-borrow", source_alias="paper_a",
            component="borrow", amount="0", currency="USD", evidence_kind="observed", applies_at=START, episode_id="episode-short"))]})
    assert app.evaluate_decisions({"as_of": AFTER_HORIZON})["evaluation"]["episodes"][0]["observed_net"] == "0.48"
    assert app.evaluate_decisions({"as_of": AFTER_HORIZON, "as_of_seq": old_seq})["evaluation"]["episodes"][0]["observed_net"] is None


def test_reused_episode_context_is_not_double_attributed(tmp_path):
    from tradeoff.feedback.reconcile import reconcile
    records = episode_records() + episode_records(alias="paper_b", suffix="-b")
    for record in records:
        if record["kind"] == "decision":
            record["payload"]["episode_id"] = "same-context"
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert all(ep["status"] == "UNATTRIBUTABLE" for ep in result["episodes"])
    assert all("EPISODE_ID_CONFLICT" in ep["reasons"] for ep in result["episodes"])
