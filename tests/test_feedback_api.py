import json

import pytest

from feedback_helpers import (AFTER_HORIZON, decision, episode_records, feedback_project, fixed_clock,
                              make_snapshot, mark)


def test_shared_api_imports_and_evaluates_without_optional_packages(feedback_project):
    from tradeoff.feedback.api import FeedbackApp
    app = FeedbackApp(feedback_project, clock=fixed_clock)
    records = episode_records()
    records.append(dict(event_id="mark", kind="mark", payload=mark()))
    app.import_evidence({"records": records})
    report = app.evaluate_decisions({"as_of": AFTER_HORIZON})
    assert report["evaluation"]["episodes"][0]["observed_net"] == "0.95"
    assert report["evaluation"]["decisions"][0]["capture"]["classification"] == "IMPORTED"
    assert report == app.dispatch("evaluate_decisions", {"as_of": AFTER_HORIZON})
    assert str(feedback_project) not in json.dumps(report)


def test_api_retry_and_safe_argument_validation(feedback_project):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError
    app = FeedbackApp(feedback_project, clock=fixed_clock)
    args = {"event_id": "e1", "decision": decision()}
    assert app.dispatch("record_decision", args) == app.dispatch("record_decision", args)
    for operation, bad in [("record_decision", {**args, "api_key": "SYNTHETIC_SECRET"}),
        ("evaluate_decisions", {"as_of": AFTER_HORIZON, "as_of_seq": True}),
        ("sync_paper_evidence", {"source_alias": "paper_a", "start": "bad", "end": AFTER_HORIZON})]:
        with pytest.raises(FeedbackError) as caught:
            app.dispatch(operation, bad)
        assert "SYNTHETIC_SECRET" not in str(caught.value)


def test_api_export_paths_do_not_escape_workspace(feedback_project):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError
    for output in ("../escape", "/tmp/escape", ".tradeoff/feedback", "a/../../escape"):
        with pytest.raises(FeedbackError):
            FeedbackApp(feedback_project).export_feedback({"output": output, "as_of": AFTER_HORIZON})
