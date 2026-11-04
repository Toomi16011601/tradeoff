"""Explicit agent hooks; receipts are assigned before the caller submits orders."""
from datetime import datetime, timedelta

from .contracts import FeedbackError, decimal_text, utc_time, validate_payload
from .store import FeedbackStore


class Recorder:
    def __init__(self, project, *, clock=None):
        self.project, self.clock = project, clock

    def record_decision(self, payload, *, event_id):
        payload = validate_payload("decision", payload)
        with FeedbackStore(self.project, clock=self.clock) as store, store.transaction():
            events = store.snapshot()["events"]
            for event in events:
                if event["kind"] == "decision" and event["payload"]["decision_id"] == payload["decision_id"] and event["event_id"] != event_id:
                    raise FeedbackError("DECISION_CONFLICT", "Use one stable event ID per decision")
            return store.append(event_id, "decision", payload, environment=store.metadata.get("recording_environment", "paper"))

    def bind_order(self, payload, *, event_id):
        payload = validate_payload("order_binding", payload)
        with FeedbackStore(self.project, clock=self.clock) as store, store.transaction():
            events = store.snapshot()["events"]
            if not any(e["kind"] == "decision" and e["payload"]["decision_id"] == payload["decision_id"] for e in events):
                raise FeedbackError("DECISION_NOT_FOUND", "Record the decision before binding its order")
            for e in events:
                p = e["payload"]
                if e["kind"] == "order_binding" and (p["source_alias"], p["order_id"]) == (payload["source_alias"], payload["order_id"]):
                    if p != payload:
                        raise FeedbackError("BINDING_CONFLICT", "An order can belong to only one explicit decision")
            return store.append(event_id, "order_binding", payload, environment=store.metadata.get("recording_environment", "paper"))

    def import_evidence(self, records):
        if not isinstance(records, list):
            raise FeedbackError("INVALID_BATCH", "Evidence import requires a list of records")
        with FeedbackStore(self.project, clock=self.clock) as store:
            return store.append_batch([{**record, "origin": "imported"} for record in records])


def classify_capture(decision_event, bound_order, *, as_of, max_clock_skew_seconds):
    if isinstance(max_clock_skew_seconds, bool) or not isinstance(max_clock_skew_seconds, int) or not 0 <= max_clock_skew_seconds <= 300:
        raise FeedbackError("INVALID_CLOCK_POLICY", "Clock tolerance must be explicit and bounded")
    p = decision_event["payload"]
    parse = datetime.fromisoformat
    receipt, decision_at = parse(decision_event["recorded_at"]), parse(p["decision_at"])
    skew = timedelta(seconds=max_clock_skew_seconds)
    reasons = []
    if decision_event["origin"] == "imported":
        classification = "IMPORTED"
    elif receipt >= parse(p["horizon_end"]):
        classification = "LATE_CAPTURE"
    elif bound_order and receipt > parse(bound_order["submitted_at"]) + skew:
        classification = "LATE_CAPTURE"
    else:
        ref = p["reference"]
        sources = [ref, *p.get("source_times", [])]
        if any(parse(s["available_at"]) > decision_at + skew or parse(s["observed_at"]) > decision_at + skew for s in sources):
            reasons.append("FUTURE_SOURCE")
        if (decision_at - parse(ref["observed_at"])).total_seconds() > ref["max_age_seconds"]:
            reasons.append("STALE_REFERENCE")
        if decision_at > receipt + skew or receipt > parse(utc_time(as_of)):
            reasons.append("CLOCK_UNVERIFIED")
        if p["action"] in {"buy", "sell"} and bound_order is None:
            reasons.append("ORDER_TIME_UNKNOWN")
        classification = "CAPTURE_UNVERIFIED" if reasons else "PROSPECTIVE"
    return {"classification": classification, "reasons": reasons,
            "capture_lag_seconds": str((receipt - decision_at).total_seconds()),
            "clock_skew_seconds": max_clock_skew_seconds,
            "clock_assumption": "Local receipt ordering; not authenticated future-data attestation"}
