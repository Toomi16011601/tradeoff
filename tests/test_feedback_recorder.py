import pytest

from feedback_helpers import (decision, order, fixed_clock, after_horizon_clock, AFTER_HORIZON,
                              feedback_project)


def test_late_and_imported_capture_cannot_be_prospective(feedback_project):
    from tradeoff.feedback.recorder import Recorder, classify_capture
    from tradeoff.feedback.store import FeedbackStore
    recorder = Recorder(feedback_project, clock=after_horizon_clock)
    recorder.record_decision(decision(), event_id="e1")
    recorder.import_evidence([dict(event_id="e2", kind="decision", payload=decision(decision_id="d2"), origin="captured")])
    with FeedbackStore(feedback_project) as store:
        events = store.snapshot()["events"]
    assert classify_capture(events[0], order(), as_of=AFTER_HORIZON, max_clock_skew_seconds=0)["classification"] == "LATE_CAPTURE"
    assert classify_capture(events[1], order(), as_of=AFTER_HORIZON, max_clock_skew_seconds=0)["classification"] == "IMPORTED"


def test_python_hook_records_then_binds_and_retries(feedback_project):
    from tradeoff.feedback.recorder import Recorder, classify_capture
    from tradeoff.feedback.store import FeedbackStore
    recorder = Recorder(feedback_project, clock=fixed_clock)
    receipt = recorder.record_decision(decision(), event_id="e1")
    # A caller's broker returns this explicit ID after recorder acknowledgement.
    binding = dict(decision_id="d1", source_alias="paper_a", order_id="order-entry")
    bound = recorder.bind_order(binding, event_id="b1")
    assert recorder.record_decision(decision(), event_id="e1") == receipt
    assert recorder.bind_order(binding, event_id="b1") == bound
    with FeedbackStore(feedback_project) as store:
        events = store.snapshot()["events"]
    assert len(events) == 2
    assert classify_capture(events[0], order(), as_of=AFTER_HORIZON, max_clock_skew_seconds=0)["classification"] == "PROSPECTIVE"


def test_conflicting_binding_and_decision_ids_refused(feedback_project):
    from tradeoff.feedback.recorder import Recorder
    from tradeoff.feedback.contracts import FeedbackError
    recorder = Recorder(feedback_project, clock=fixed_clock)
    recorder.record_decision(decision(), event_id="e1")
    recorder.record_decision(decision(decision_id="d2"), event_id="e2")
    recorder.bind_order(dict(decision_id="d1", source_alias="paper_a", order_id="order-entry"), event_id="b1")
    with pytest.raises(FeedbackError):
        recorder.bind_order(dict(decision_id="d2", source_alias="paper_a", order_id="order-entry"), event_id="b2")
    with pytest.raises(FeedbackError):
        recorder.record_decision(decision(quantity_delta="2"), event_id="another-id")


def test_missing_or_future_source_evidence_is_unverified(feedback_project):
    from tradeoff.feedback.recorder import Recorder, classify_capture
    from tradeoff.feedback.store import FeedbackStore
    recorder = Recorder(feedback_project, clock=fixed_clock)
    recorder.record_decision(decision(source_times=[dict(source="fixture", feed="fixture-feed",
        observed_at="2026-01-05T14:30:02Z", available_at="2026-01-05T14:30:02Z")]), event_id="e1")
    with FeedbackStore(feedback_project) as store:
        event = store.snapshot()["events"][0]
    result = classify_capture(event, order(), as_of=AFTER_HORIZON, max_clock_skew_seconds=0)
    assert result["classification"] == "CAPTURE_UNVERIFIED"
    assert "FUTURE_SOURCE" in result["reasons"]
