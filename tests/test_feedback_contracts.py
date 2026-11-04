"""Reject malformed money/evidence without echoing private input."""
import json
from decimal import Decimal

import pytest

from feedback_helpers import decision, order, fill, inventory, cost, mark, plan


def test_exact_adjacent_quantities_and_zero():
    from tradeoff.feedback.contracts import normalize_decimal
    assert normalize_decimal("9007199254740993.25") == "9007199254740993.25"
    assert normalize_decimal("9007199254740994.25") == "9007199254740994.25"
    assert normalize_decimal("-0.000") == "0"
    assert normalize_decimal(Decimal("10.00")) == "10"


@pytest.mark.parametrize("value", [True, False, 1.2, "NaN", "Infinity", "1e40", "1e-19", "garbage"])
def test_unsafe_decimals_refused(value):
    from tradeoff.feedback.contracts import normalize_decimal, FeedbackError
    with pytest.raises(FeedbackError):
        normalize_decimal(value)


@pytest.mark.parametrize("kind,helper", [("decision", decision), ("order", order), ("fill", fill),
    ("inventory", inventory), ("cost", cost), ("mark", mark), ("comparison_plan", plan)])
def test_valid_payloads_are_copied_and_schema_required_fields_are_enforced(kind, helper):
    from tradeoff.feedback.contracts import validate_payload, schema_for, FeedbackError
    payload = helper()
    before = json.dumps(payload, sort_keys=True)
    assert validate_payload(kind, payload) == payload
    assert json.dumps(payload, sort_keys=True) == before
    for key in schema_for(kind)["required"]:
        with pytest.raises(FeedbackError):
            validate_payload(kind, {k: v for k, v in payload.items() if k != key})


@pytest.mark.parametrize("changes", [{"quantity_delta": "-1"}, {"action": "hold"},
    {"decision_at": "2026-01-05T14:30:00"}, {"horizon_end": "2025-01-01T00:00:00Z"},
    {"api_key": "SYNTHETIC_SECRET_SENTINEL"}, {"reason": "/Users/private-person/data"},
    {"prediction": {"label": "up", "horizon_end": "2026-01-05T15:30:00Z", "confidence": "1.1"}}])
def test_invalid_payloads_have_safe_errors(changes):
    from tradeoff.feedback.contracts import validate_payload, FeedbackError
    with pytest.raises(FeedbackError) as caught:
        validate_payload("decision", decision(**changes))
    assert "SYNTHETIC_SECRET_SENTINEL" not in str(caught.value)
    assert "private-person" not in str(caught.value)


def test_nested_and_duplicate_json_limits():
    from tradeoff.feedback.contracts import parse_json, canonical_json, FeedbackError
    for raw in ['{"a":1,"a":2}', 'NaN', '[' * 40 + '0' + ']' * 40, '"' + 'a' * (1024*1024) + '"']:
        with pytest.raises(FeedbackError):
            parse_json(raw)
    cycle = []
    cycle.append(cycle)
    with pytest.raises(FeedbackError):
        canonical_json(cycle)


def test_snapshot_content_requires_matching_hash():
    from tradeoff.feedback.contracts import validate_payload, FeedbackError
    with pytest.raises(FeedbackError):
        validate_payload("decision", decision(input_snapshot={"close": "10"}))
