import copy
import pytest


def tape():
    return [
        {"timestamp": f"2026-01-01T0{i}:00:00+00:00", "symbol": "SYN", "open": 10, "high": 12, "low": 8, "close": 11, "volume": 100, "extra": {"nested": [1]}}
        for i in range(4)
    ]


def test_validation_defaults_availability_without_mutating_input():
    from backtest_witness.validation import validate_rows
    rows = tape()
    validated = validate_rows(rows)
    assert validated[0]["available_at"] == rows[0]["timestamp"]
    validated[0]["extra"]["nested"].append(2)
    assert rows[0]["extra"]["nested"] == [1]
    assert "available_at" not in rows[0]


@pytest.mark.parametrize("field,value", [("timestamp", "2026-01-01T00:00:00"), ("available_at", "2025-01-01T00:00:00Z"), ("high", 9), ("low", 13), ("close", 0), ("open", float("inf")), ("volume", -1), ("close", True)])
def test_invalid_market_data_has_descriptive_error(field, value):
    from backtest_witness.validation import validate_rows
    rows = tape()
    rows[0][field] = value
    with pytest.raises(ValueError, match=field):
        validate_rows(rows)


def test_data_rejects_nonchronological_or_multiple_symbols():
    from backtest_witness.validation import validate_rows
    rows = tape()
    rows[1]["timestamp"] = rows[0]["timestamp"]
    with pytest.raises(ValueError, match="timestamp"):
        validate_rows(rows)
    rows = tape()
    rows[1]["symbol"] = "OTHER"
    with pytest.raises(ValueError, match="symbol"):
        validate_rows(rows)


@pytest.mark.parametrize("target", [True, "1", None, float("nan"), float("inf"), float("-inf"), 10 ** 400])
def test_targets_reject_nonnumeric_or_unrepresentable_units(target):
    from backtest_witness.validation import validate_trace
    rows = tape()
    trace = [{"timestamp": row["timestamp"], "target": 0} for row in rows]
    trace[0]["target"] = target
    with pytest.raises(ValueError, match="target"):
        validate_trace(trace, rows)


def test_trace_accepts_signed_fractional_targets_and_canonicalizes_integral_values():
    from backtest_witness.validation import validate_trace
    rows = tape()
    trace = [{"timestamp": row["timestamp"], "target": target}
             for row, target in zip(rows, [-2.5, 3.0, -0.0, 7])]
    actual = validate_trace(trace, rows)
    assert [entry["target"] for entry in actual] == [-2.5, 3, 0, 7]
    assert [type(entry["target"]) for entry in actual] == [float, int, int, int]
    assert type(trace[1]["target"]) is float
    assert trace[2]["target"] == -0.0


def test_normalize_target_preserves_large_representable_native_integer_without_float_rounding():
    from backtest_witness.validation import normalize_target
    value = 2 ** 53 + 1
    assert normalize_target(value) == value
    assert type(normalize_target(value)) is int


def test_config_rejects_non_json_and_nan():
    from backtest_witness.validation import validate_config
    for invalid in ({"x": object()}, {"x": float("nan")}, []):
        with pytest.raises(ValueError, match="config"):
            validate_config(invalid)


def test_cyclic_json_inputs_raise_descriptive_value_error():
    from backtest_witness.validation import validate_config, validate_rows
    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(ValueError, match="config"):
        validate_config(cycle)
    rows = tape()
    rows[0]["extra"] = cycle
    with pytest.raises(ValueError, match="rows"):
        validate_rows(rows)


def test_arbitrary_size_integers_remain_valid_json_configuration():
    from backtest_witness.validation import validate_config
    large = 10 ** 400
    assert validate_config({"identifier": large}) == {"identifier": large}


def test_timestamp_order_uses_instants_across_different_offsets():
    from backtest_witness.validation import validate_rows
    rows = tape()[:2]
    rows[0]["timestamp"] = "2026-01-01T10:00:00+10:00"
    rows[1]["timestamp"] = "2026-01-01T01:00:00+00:00"
    assert len(validate_rows(rows)) == 2


def test_timestamps_normalize_to_utc_for_portable_callback_comparisons():
    from backtest_witness.validation import validate_rows
    rows = tape()[:1]
    rows[0]["timestamp"] = "2026-01-01T10:00:00+10:00"
    rows[0]["available_at"] = "2026-01-01T02:00:00+01:00"
    normalized = validate_rows(rows)
    assert normalized[0]["timestamp"] == "2026-01-01T00:00:00+00:00"
    assert normalized[0]["available_at"] == "2026-01-01T01:00:00+00:00"
    assert normalized[0]["available_at"] > normalized[0]["timestamp"]
    assert rows[0]["timestamp"] == "2026-01-01T10:00:00+10:00"
def test_trace_alignment_uses_instants_and_returns_canonical_utc_copy():
    from backtest_witness.validation import validate_trace
    rows = tape()[:1]
    trace = [{"timestamp": "2026-01-01T01:00:00+01:00", "target": 0}]
    assert validate_trace(trace, rows)[0]["timestamp"] == rows[0]["timestamp"]
    assert trace[0]["timestamp"] == "2026-01-01T01:00:00+01:00"
    trace[0]["timestamp"] = "2026-01-01T02:00:00+01:00"
    with pytest.raises(ValueError, match="timestamp"):
        validate_trace(trace, rows)
