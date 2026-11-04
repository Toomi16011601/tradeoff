import json

from feedback_helpers import AFTER_HORIZON


def test_complete_demo_runs_without_broker_or_model(tmp_path):
    from tradeoff.feedback.demo import run_feedback_demo
    result = run_feedback_demo(tmp_path / "demo")
    assert result["status"] == "DEMO_COMPLETED"
    report = json.loads((tmp_path / "demo" / result["report"]).read_text())
    long = next(e for e in report["evaluation"]["episodes"] if e["episode_id"] == "episode-long")
    assert (long["gross_cashflow"], long["observed_net"]) == ("1", "0.95")
    short = next(e for e in report["evaluation"]["episodes"] if e["episode_id"] == "episode-short")
    assert short["observed_net"] is None
    assert "BORROW_COST_UNKNOWN" in short["reasons"]
    assert any(e["status"] == "UNATTRIBUTABLE" for e in report["evaluation"]["episodes"])
    assert report["comparison"]["metrics"]["mean_delta_bps"] == "-80"
    assert report["environments"] == ["simulated"]
    assert "SYNTHETIC" in (tmp_path / "demo" / result["interface"]).read_text()


def test_recorder_respects_project_environment(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.recorder import Recorder
    from feedback_helpers import decision, fixed_clock
    with FeedbackStore(tmp_path, create=True, environment="simulated"):
        pass
    Recorder(tmp_path, clock=fixed_clock).record_decision(decision(), event_id="d1")
    with FeedbackStore(tmp_path) as store:
        assert store.snapshot()["events"][0]["environment"] == "simulated"
