"""Regression gaps found by isolated source mutation experiments."""
from copy import deepcopy

import pytest

from feedback_helpers import AFTER_HORIZON, episode_records, make_snapshot


def test_intervention_preserves_a_bar_available_exactly_at_cutoff():
    from tradeoff.mutations import mutate_future

    cutoff = "2026-01-05T14:30:00+00:00"
    rows = [
        {"timestamp": "2026-01-05T14:29:00+00:00", "available_at": "2026-01-05T14:31:00+00:00",
         "symbol": "SYNTH", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"timestamp": cutoff, "available_at": cutoff, "symbol": "SYNTH",
         "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"timestamp": "2026-01-05T14:31:00+00:00", "available_at": "2026-01-05T14:31:00+00:00",
         "symbol": "SYNTH", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
    ]
    original = deepcopy(rows)
    mutated, changes = mutate_future(rows, cutoff, "scale_up")
    assert rows == original
    assert mutated[1] == original[1]
    assert {change["index"] for change in changes} == {0, 2}


def test_one_oversized_history_record_is_rejected_even_in_an_unbounded_history():
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.serialization import output_json

    record = {f"field{i}": "x" * 4096 for i in range(300)}
    with pytest.raises(FeedbackError):
        output_json({"events": [record]})


def test_conflicting_duplicate_fill_id_excludes_an_otherwise_valid_episode(tmp_path):
    from tradeoff.feedback.reconcile import reconcile

    records = episode_records()
    conflict = deepcopy(next(record for record in records if record["kind"] == "fill"))
    conflict["event_id"] = "conflicting-entry-observation"
    conflict["payload"]["price"] = "999"
    records.append(conflict)
    result = reconcile(make_snapshot(tmp_path, records), as_of=AFTER_HORIZON)
    assert result["episodes"][0]["status"] == "UNATTRIBUTABLE"
    assert "FILL_ID_CONFLICT" in result["episodes"][0]["reasons"]
    assert result["coverage"]["attribution_complete"] is False
