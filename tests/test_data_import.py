"""Import real-world-shaped bars without silently guessing market semantics."""
import csv
import json

import pytest


def importer():
    # Import inside each test so a missing feature produces a behavioral failure.
    from backtest_witness.data import load_data, inspect_data
    return load_data, inspect_data


def write_csv(tmp_path, headers, rows):
    path = tmp_path / "bars.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def test_date_ohlcv_csv_needs_explicit_symbol_and_market_close(tmp_path):
    # Break caught: uppercase provider OHLCV columns or date-only labels rejected.
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Date", "Open", "High", "Low", "Close", "Volume"],
                     [["2025-01-03", 100, 103, 99, 102, 50],
                      ["2025-07-03", 102, 105, 101, 104, 55]])
    rows = load_data(path, symbol="SYN", timezone="America/New_York", session_close="16:00")
    assert rows[0]["timestamp"] == "2025-01-03T21:00:00+00:00"
    assert rows[1]["timestamp"] == "2025-07-03T20:00:00+00:00"
    assert rows[0]["available_at"] == rows[0]["timestamp"]
    assert rows[0]["Date"] == "2025-01-03"
    assert rows[0]["symbol"] == "SYN"
    assert rows[0]["open"] == 100.0


def test_open_labeled_csv_shifts_instant_and_preserves_strategy_time(tmp_path):
    # Break caught: passing an open label as a close, or dropping companion Time.
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Datetime", "Open", "High", "Low", "Close", "Volume", "signal"],
                     [["2025-01-01 05:00:00+00:00", 10, 12, 9, 11, 0, 2]])
    rows = load_data(path, symbol="SYN", timestamp_kind="open", bar_duration="1h",
                     column_map={"Time": "Datetime"})
    assert rows[0]["timestamp"] == "2025-01-01T06:00:00+00:00"
    assert rows[0]["available_at"] == "2025-01-01T06:00:00+00:00"
    assert rows[0]["Time"] == "2025-01-01 05:00:00+00:00"
    assert rows[0]["Datetime"] == rows[0]["Time"]
    assert rows[0]["signal"] == 2


def test_naive_timestamp_requires_timezone_not_machine_timezone(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["time", "open", "high", "low", "close", "volume"],
                     [["2025-01-01 05:00:00", 10, 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="SYN")
    assert caught.value.code == "TIMEZONE_REQUIRED"
    rows = load_data(path, symbol="SYN", timezone="Europe/London")
    assert rows[0]["timestamp"] == "2025-01-01T05:00:00+00:00"


@pytest.mark.parametrize("options,code", [
    ({}, "SYMBOL_REQUIRED"),
    ({"symbol": "SYN"}, "SESSION_CLOSE_REQUIRED"),
    ({"symbol": "SYN", "session_close": "16:00"}, "TIMEZONE_REQUIRED"),
])
def test_date_import_never_guesses_missing_inputs(tmp_path, options, code):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Date", "Open", "High", "Low", "Close", "Volume"],
                     [["2025-01-03", 100, 103, 99, 102, 50]])
    with pytest.raises(ValueError) as caught:
        load_data(path, **options)
    assert caught.value.code == code


def test_normalized_csv_remains_compatible_and_keeps_extras(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume", "note", "enabled"],
                     [["2025-01-01T00:00:00Z", "SYN", 10, 12, 9, 11, 0, "ordinary", "true"]])
    rows = load_data(path)
    assert rows[0]["timestamp"] == "2025-01-01T00:00:00+00:00"
    assert rows[0]["note"] == "ordinary"
    assert rows[0]["enabled"] is True


@pytest.mark.parametrize("wrapped", [False, True])
def test_normalized_json_keeps_legacy_nested_features(tmp_path, wrapped):
    load_data, _ = importer()
    row = {"timestamp": "2025-01-01T00:00:00Z", "symbol": "SYN", "open": 10, "high": 12,
           "low": 9, "close": 11, "volume": 0, "features": {"nested": [1, True]}}
    path = tmp_path / "bars.json"
    path.write_text(json.dumps({"rows": [row]} if wrapped else [row]))
    assert load_data(path)[0]["features"] == {"nested": [1, True]}


@pytest.mark.parametrize("headers,code", [
    (["Date", "Open", "open", "High", "Low", "Close", "Volume"], "DUPLICATE_COLUMNS"),
    (["Date", "Time", "Open", "High", "Low", "Close", "Volume"], "AMBIGUOUS_TIMESTAMP"),
    (["Date", "Open", "High", "Low", "Close"], "MISSING_COLUMNS"),
])
def test_ambiguous_or_missing_headers_are_actionable(tmp_path, headers, code):
    load_data, _ = importer()
    path = write_csv(tmp_path, headers, [["x"] * len(headers)])
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="SYN")
    assert caught.value.code == code


def test_timestamp_column_can_resolve_multiple_time_columns(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Datetime", "Time", "Open", "High", "Low", "Close", "Volume"],
                     [["2025-01-01T00:00:00Z", "unchanged", 10, 12, 9, 11, 0]])
    rows = load_data(path, symbol="SYN", timestamp_column="Datetime")
    assert rows[0]["timestamp"] == "2025-01-01T00:00:00+00:00"
    assert rows[0]["Time"] == "unchanged"


@pytest.mark.parametrize("duration", [None, "0h", "-1h", "1month", "nan", "1.5h"])
def test_open_labels_require_positive_unambiguous_fixed_duration(tmp_path, duration):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Timestamp", "Open", "High", "Low", "Close", "Volume"],
                     [["2025-01-01T00:00:00Z", 10, 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="SYN", timestamp_kind="open", bar_duration=duration)
    assert caught.value.code == "BAR_DURATION_REQUIRED"


@pytest.mark.parametrize("label", ["2025-03-09 02:30:00", "2025-11-02 01:30:00"])
def test_nonexistent_and_ambiguous_local_times_need_aware_input(tmp_path, label):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Timestamp", "Open", "High", "Low", "Close", "Volume"],
                     [[label, 10, 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="SYN", timezone="America/New_York")
    assert caught.value.code == "AMBIGUOUS_LOCAL_TIME"


def test_custom_column_map_retains_extra_feature_but_cannot_replace_prices(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Date", "Open", "High", "Low", "Close", "Volume", "factor"],
                     [["2025-01-01T00:00:00Z", 10, 12, 9, 11, 0, 3]])
    rows = load_data(path, symbol="SYN", column_map={"SPY_OK": "factor"})
    assert rows[0]["SPY_OK"] == 3
    assert rows[0]["factor"] == 3
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="SYN", column_map={"close": "factor"})
    assert caught.value.code == "COLUMN_MAP_CONFLICT"


def test_explicit_symbol_cannot_silently_override_embedded_symbol(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
                     [["2025-01-01T00:00:00Z", "ORIGINAL", 10, 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="OVERRIDE")
    assert caught.value.code == "SYMBOL_CONFLICT"


def test_bad_number_error_does_not_echo_private_cell_or_path(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
                     [["2025-01-01T00:00:00Z", "SYN", "private-cell-sentinel", 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path)
    assert caught.value.code == "NONNUMERIC_OHLCV"
    assert "private-cell-sentinel" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.columns == ["open"]


def test_sensitive_extra_values_cannot_enter_portable_rows(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume", "email"],
                     [["2025-01-01T00:00:00Z", "SYN", 10, 12, 9, 11, 0, "owner@example.com"]])
    with pytest.raises(ValueError, match="sensitive"):
        load_data(path)


def test_inspection_warns_on_unavailable_volume_and_observed_gaps_without_filling(tmp_path):
    load_data, inspect_data = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
                     [["2025-01-01T00:00:00Z", "SYN", 10, 12, 9, 11, 0],
                      ["2025-01-01T01:00:00Z", "SYN", 10, 12, 9, 11, 0],
                      ["2025-01-01T04:00:00Z", "SYN", 10, 12, 9, 11, 0]])
    rows = load_data(path)
    warnings = inspect_data(rows)
    assert {warning["code"] for warning in warnings} == {"ZERO_VOLUME", "IRREGULAR_INTERVALS"}
    assert all(set(warning) == {"code", "message", "columns"} for warning in warnings)
    assert len(rows) == 3
    assert rows[-1]["timestamp"] == "2025-01-01T04:00:00+00:00"


def test_normal_regular_nonzero_volume_has_no_data_warning(tmp_path):
    load_data, inspect_data = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
                     [["2025-01-01T00:00:00Z", "SYN", 10, 12, 9, 11, 1],
                      ["2025-01-01T01:00:00Z", "SYN", 10, 12, 9, 11, 2]])
    assert inspect_data(load_data(path)) == []


def test_uppercase_timestamp_source_is_retained_for_strategy_features(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Timestamp", "Open", "High", "Low", "Close", "Volume"],
                     [["2025-01-01T00:00:00Z", 10, 12, 9, 11, 0]])
    row = load_data(path, symbol="SYN", timestamp_kind="open", bar_duration="15m")[0]
    assert row["Timestamp"] == "2025-01-01T00:00:00Z"
    assert row["timestamp"] == "2025-01-01T00:15:00+00:00"


@pytest.mark.parametrize("label", ["20250103", "2025-W01-5"])
def test_nonextended_date_forms_cannot_bypass_session_close_requirement(tmp_path, label):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["Date", "Open", "High", "Low", "Close", "Volume"],
                     [[label, 10, 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path, symbol="SYN", timezone="UTC")
    assert caught.value.code == "INVALID_TIMESTAMP"


def test_timezone_conversion_overflow_is_a_safe_import_error(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
                     [["0001-01-01T00:00:00+23:00", "SYN", 10, 12, 9, 11, 0]])
    with pytest.raises(ValueError) as caught:
        load_data(path)
    assert caught.value.code == "INVALID_TIMESTAMP"


def test_numeric_custom_fields_can_be_mapped_without_standard_headers(tmp_path):
    load_data, _ = importer()
    path = write_csv(tmp_path, ["observation", "o", "h", "l", "c", "v"],
                     [["2025-01-01T00:00:00Z", 10, 12, 9, 11, 3]])
    row = load_data(path, symbol="SYN", timestamp_column="observation", column_map={
        "open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})[0]
    assert row["close"] == 11.0
    assert row["volume"] == 3.0
    assert row["observation"] == "2025-01-01T00:00:00Z"
