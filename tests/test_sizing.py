"""Independent sizing examples, including side-correct stops and lot boundaries."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest


def rows(prices=(100, 50, 25, 100)):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(days=i)).isoformat(), "symbol": "SYN",
             "open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 100} for i, price in enumerate(prices)]


def test_fixed_notional_sizes_long_short_and_flat_at_current_available_close():
    from backtest_witness.sizing import size_by_notional
    data = rows()
    directions = [1, -1, 0, -1]
    before = deepcopy((data, directions))
    assert size_by_notional(data, directions, notional=250) == [2.5, -5, 0, -2.5]
    assert (data, directions) == before


def test_notional_lots_round_down_toward_zero_at_exact_decimal_boundaries():
    from backtest_witness.sizing import size_by_notional
    assert size_by_notional(rows(), [1, -1, 0, -1], notional=279, lot_size=1) == [2, -5, 0, -2]
    assert size_by_notional(rows((100, 100)), [1, -1], notional=30, lot_size=0.1) == [0.3, -0.3]


def test_risk_sizing_uses_static_equity_stop_distance_and_notional_cap():
    from backtest_witness.sizing import size_by_risk
    # 1% of 10,000 = 100 risk units. Long stop distance 10 => 10 units,
    # short distance 5 => 20, then exposure cap 750 => 7.5 long / 15 short.
    assert size_by_risk(rows(), [1, -1, 0, 1], [90, 55, None, 60],
                        equity=10000, risk_fraction=0.01, max_notional=750) == [7.5, -15, 0, 2.5]


def test_risk_sizing_rounds_whole_lots_toward_zero_for_shorts():
    from backtest_witness.sizing import size_by_risk
    assert size_by_risk(rows(), [1, -1, 0, 1], [91, 59, None, 91],
                        equity=10000, risk_fraction=0.01, max_notional=750, lot_size=2) == [6, -10, 0, 6]


@pytest.mark.parametrize("fn", ["size_by_notional", "size_by_risk"])
def test_sizing_rejects_unavailable_current_close_for_nonzero_direction(fn):
    import backtest_witness.sizing as sizing
    data = rows()
    data[0]["available_at"] = data[1]["timestamp"]
    kwargs = {"notional": 100} if fn == "size_by_notional" else {
        "equity": 1000, "risk_fraction": 0.01, "max_notional": 100}
    positional = ([1, -1, 0, 1],) if fn == "size_by_notional" else ([1, -1, 0, 1], [90, 60, None, 90])
    with pytest.raises(ValueError, match="available"):
        getattr(sizing, fn)(data, *positional, **kwargs)


def test_unavailable_close_is_not_consumed_for_flat_direction():
    from backtest_witness.sizing import size_by_risk
    data = rows()
    data[0]["available_at"] = data[1]["timestamp"]
    assert size_by_risk(data, [0, 0, 0, 0], [None] * 4,
                        equity=1000, risk_fraction=0.01, max_notional=100) == [0, 0, 0, 0]


@pytest.mark.parametrize("stop", [float("nan"), float("inf"), "100", True])
def test_flat_sizing_allows_null_stops_but_rejects_other_invalid_stop_values(stop):
    from backtest_witness.sizing import size_by_risk
    with pytest.raises(ValueError, match="stop"):
        size_by_risk(rows(), [0, 0, 0, 0], [stop, None, None, None],
                     equity=1000, risk_fraction=0.01, max_notional=100)


@pytest.mark.parametrize("directions", [[True, 0, 0, 0], [2, 0, 0, 0], [0.5, 0, 0, 0], ["1", 0, 0, 0], [1, 0], [float("nan"), 0, 0, 0]])
def test_sizing_rejects_invalid_or_misaligned_directions(directions):
    from backtest_witness.sizing import size_by_notional
    with pytest.raises(ValueError, match="direction"):
        size_by_notional(rows(), directions, notional=100)


@pytest.mark.parametrize("stops", [[100, 60, None, 90], [110, 60, None, 90], [90, 50, None, 90], [90, 40, None, 90], [None, 60, None, 90], [True, 60, None, 90], [float("inf"), 60, None, 90], [90]])
def test_risk_sizing_rejects_stops_on_wrong_side_or_invalid_values(stops):
    from backtest_witness.sizing import size_by_risk
    with pytest.raises(ValueError, match="stop"):
        size_by_risk(rows(), [1, -1, 0, 1], stops, equity=1000, risk_fraction=0.01, max_notional=100)


@pytest.mark.parametrize("kwargs", [
    {"notional": 0}, {"notional": -1}, {"notional": float("inf")}, {"notional": True},
    {"notional": 100, "lot_size": 0}, {"notional": 100, "lot_size": float("nan")},
])
def test_notional_sizing_rejects_invalid_parameters(kwargs):
    from backtest_witness.sizing import size_by_notional
    with pytest.raises(ValueError, match="notional|lot_size"):
        size_by_notional(rows(), [1, 0, 0, 0], **kwargs)


@pytest.mark.parametrize("override", [
    {"equity": 0}, {"equity": float("inf")}, {"risk_fraction": 0},
    {"risk_fraction": 1.1}, {"risk_fraction": True}, {"max_notional": 0},
    {"max_notional": float("nan")}, {"lot_size": -1},
])
def test_risk_sizing_rejects_invalid_static_parameters(override):
    from backtest_witness.sizing import size_by_risk
    params = {"equity": 1000, "risk_fraction": 0.01, "max_notional": 100, **override}
    with pytest.raises(ValueError, match="equity|risk_fraction|max_notional|lot_size"):
        size_by_risk(rows(), [1, -1, 0, 1], [90, 60, None, 90], **params)


def test_sizing_supports_numeric_numpy_directions_without_changing_their_dtype():
    np = pytest.importorskip("numpy")
    from backtest_witness.sizing import size_by_notional
    signals = np.array([1, -1, 0, 1], dtype=np.int64)
    assert size_by_notional(rows(), signals, notional=250) == [2.5, -5, 0, 2.5]
    assert signals.dtype == np.dtype("int64")
