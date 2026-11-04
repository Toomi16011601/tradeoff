"""Hook for TradingAgents propagate()'s five-tier rating or REVIEW result.

Contract checked at TauricResearch/TradingAgents commit
c4544913a14ed3df5f1ed7b9e8483270ce20682a (Apache-2.0).
This independent example copies no upstream implementation. The caller owns
the explicit action, size and horizon; a rating is never an order.
"""
from copy import deepcopy

from tradeoff.feedback.contracts import FeedbackError


def record_tradingagents_decision(recorder, *, decision, rating, event_id):
    if rating not in {"Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"}:
        raise FeedbackError("UNSUPPORTED_RATING", "Use a documented TradingAgents rating")
    if rating == "REVIEW" and decision.get("action") in {"buy", "sell"}:
        raise FeedbackError("REVIEW_REQUIRED", "A REVIEW rating must remain a hold or skip until the caller resolves it")
    intent = deepcopy(decision)
    intent["prediction"] = {"label": rating, "horizon_end": intent["horizon_end"]}
    return recorder.record_decision(intent, event_id=event_id)
