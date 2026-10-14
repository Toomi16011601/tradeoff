"""Hand-calculated accounting oracles; no expected values use ledger helpers."""

from copy import deepcopy

import pytest


def tape(opens, closes=None):
    closes = closes or opens
    return [
        {"timestamp": f"2026-01-{i + 1:02d}T16:00:00+00:00", "symbol": "TEST",
         "open": op, "high": max(op, cl) + 1, "low": min(op, cl) - 1,
         "close": cl, "volume": 100}
        for i, (op, cl) in enumerate(zip(opens, closes))
    ]


def signals(rows, targets):
    return [{"timestamp": row["timestamp"], "target": target}
            for row, target in zip(rows, targets)]


def test_round_trip_uses_next_open_and_per_fill_costs():
    from backtest_witness.economics import project

    rows = tape([10, 20, 30, 40], [10, 25, 35, 45])
    result = project(rows, signals(rows, [1, 1, 0, 0]), initial_cash=1000,
                     fee_fixed=1, fee_bps=100, spread_bps=200, slippage_bps=100)
    assert [f["side"] for f in result["fills"]] == ["buy", "sell"]
    assert [f["timestamp"] for f in result["fills"]] == [rows[1]["timestamp"], rows[3]["timestamp"]]
    assert [f["fill_price"] for f in result["fills"]] == pytest.approx([20.4, 39.2])
    assert result["total_fees"] == pytest.approx(2.596)
    assert result["final_cash"] == pytest.approx(1016.204)
    assert result["final_quantity"] == 0
    assert result["final_equity"] == pytest.approx(1016.204)
    assert result["realized_pnl"] == pytest.approx(16.204)
    assert result["open_pnl"] == 0
    assert result["net_pnl"] == pytest.approx(16.204)
    assert result["return_pct"] == pytest.approx(1.6204)
    assert [x["equity"] for x in result["equity_curve"]] == pytest.approx(
        [1000, 1003.396, 1013.396, 1016.204])


def test_terminal_holding_marks_close_without_inventing_sale():
    from backtest_witness.economics import project

    rows = tape([10, 20, 30], [10, 25, 35])
    result = project(rows, signals(rows, [1, 1, 1]), initial_cash=100,
                     fee_fixed=1, fee_bps=100, spread_bps=200, slippage_bps=100)
    assert len(result["fills"]) == 1
    assert result["final_cash"] == pytest.approx(78.396)
    assert result["final_quantity"] == 1
    assert result["final_equity"] == pytest.approx(113.396)
    assert result["realized_pnl"] == 0
    assert result["open_pnl"] == pytest.approx(13.396)
    assert result["net_pnl"] == pytest.approx(13.396)


def test_rejected_buy_retries_persistent_target_when_affordable():
    from backtest_witness.economics import project

    rows = tape([10, 101, 99, 98])
    result = project(rows, signals(rows, [1, 1, 1, 1]), initial_cash=100,
                     fee_fixed=1, spread_bps=0, slippage_bps=0)
    assert len(result["rejected_orders"]) == 1
    assert result["rejected_orders"][0]["timestamp"] == rows[1]["timestamp"]
    assert result["fills"][0]["timestamp"] == rows[2]["timestamp"]
    assert result["final_cash"] == 0
    assert result["final_equity"] == 98
    assert result["open_pnl"] == -2


def test_risk_reducing_close_settles_fee_debt_instead_of_trapping_holding():
    from backtest_witness.economics import project

    rows = tape([10, 10, 2])
    result = project(rows, signals(rows, [1, 0, 0]), initial_cash=110,
                     fee_fixed=100, spread_bps=0, slippage_bps=0)
    assert result["final_cash"] == -98
    assert result["final_quantity"] == 0
    assert result["rejected_orders"] == []
    assert result["open_pnl"] == 0
    assert result["realized_pnl"] == -208
    assert result["risk_events"][-1]["nonpositive_equity"] is True


def test_pending_final_signal_does_not_trade_and_drawdown_uses_initial_equity():
    from backtest_witness.economics import project

    rows = tape([10, 10, 10], [10, 8, 10])
    pending = project(rows, signals(rows, [0, 0, 1]))
    assert pending["fills"] == []
    assert pending["final_quantity"] == 0
    result = project(rows, signals(rows, [1, 0, 0]), initial_cash=100,
                     fee_fixed=1, spread_bps=0, slippage_bps=0)
    assert result["net_pnl"] == -2
    assert result["realized_pnl"] == -2
    assert result["max_drawdown_pct"] == pytest.approx(3)


def test_lag_two_suppresses_first_two_fills_and_input_is_unchanged():
    from backtest_witness.economics import project

    rows = tape([10, 20, 30, 40])
    trace = signals(rows, [1, 0, 1, 0])
    before = deepcopy((rows, trace))
    result = project(rows, trace, initial_cash=100, fee_fixed=0,
                     spread_bps=0, slippage_bps=0, fill_lag_bars=2)
    assert [f["fill_price"] for f in result["fills"]] == [30, 40]
    assert result["net_pnl"] == 10
    assert (rows, trace) == before


@pytest.mark.parametrize("setting,value", [
    ("initial_cash", 0), ("initial_cash", float("inf")),
    ("fee_fixed", -1), ("fee_fixed", float("nan")),
    ("fee_bps", -1), ("spread_bps", -1), ("slippage_bps", -1),
    ("slippage_bps", 10000), ("fill_lag_bars", 0),
    ("fill_lag_bars", 1.5), ("fill_lag_bars", True),
    ("max_leverage", 0.99), ("max_leverage", True),
    ("max_leverage", float("inf")), ("short_borrow_bps_annual", -1),
    ("short_borrow_bps_annual", float("nan")),
])
def test_invalid_model_setting_is_rejected(setting, value):
    from backtest_witness.economics import project

    rows = tape([10, 20])
    with pytest.raises(ValueError):
        project(rows, signals(rows, [1, 1]), **{setting: value})


def test_invalid_trace_does_not_silently_change_accounting():
    from backtest_witness.economics import project

    rows = tape([10, 20])
    with pytest.raises(ValueError):
        project(rows, signals(rows, [True, 1]))
    with pytest.raises(ValueError):
        project(rows, signals(rows, [1]))


def test_compare_uses_original_prices_for_both_traces_and_literal_sensitivities():
    from backtest_witness.economics import compare_economics

    rows = tape([10, 20, 30, 40])
    result = compare_economics(rows, signals(rows, [1, 1, 0, 0]),
                               signals(rows, [0, 1, 1, 0]),
                               initial_cash=100, fee_fixed=1,
                               spread_bps=0, slippage_bps=0)
    assert result["original"]["net_pnl"] == 18
    assert result["intervention"]["net_pnl"] == 9
    assert result["delta"] == -9
    sensitivities = {item["name"]: item for item in result["sensitivity"]}
    assert sensitivities["cost_free"]["original"]["net_pnl"] == 20
    assert sensitivities["cost_free"]["intervention"]["net_pnl"] == 10
    assert sensitivities["doubled_costs"]["original"]["net_pnl"] == 16
    assert sensitivities["doubled_costs"]["intervention"]["net_pnl"] == 8
    assert sensitivities["extra_bar_delay"]["original"]["net_pnl"] == 9
    assert sensitivities["extra_bar_delay"]["intervention"]["net_pnl"] == -1
    assert result["benchmark"]["net_pnl"] == 19
    assert result["benchmark"]["final_quantity"] == 1


def test_absent_intervention_is_unpaired_through_every_sensitivity():
    from backtest_witness.economics import compare_economics

    rows = tape([10, 20])
    result = compare_economics(rows, signals(rows, [0, 0]))
    assert result["intervention"] is None
    assert result["delta"] is None
    assert all(item["intervention"] is None and item["delta"] is None
               for item in result["sensitivity"])


def test_derived_return_overflow_is_rejected_instead_of_emitting_nonfinite_json():
    from backtest_witness.economics import project

    rows = tape([1e-300, 1e-300, 1e308])
    rows[0]["low"] = rows[1]["low"] = 1e-300
    with pytest.raises(ValueError, match="finite"):
        project(rows, signals(rows, [1, 1, 1]), initial_cash=1e-300,
                fee_fixed=0, spread_bps=0, slippage_bps=0)


def test_multiple_round_trips_and_open_cost_basis_reconcile():
    from backtest_witness.economics import project

    rows = tape([10, 10, 20, 15, 25, 10], [10, 10, 20, 15, 25, 12])
    result = project(rows, signals(rows, [1, 0, 1, 0, 1, 1]), initial_cash=100,
                     fee_fixed=1, spread_bps=0, slippage_bps=0)
    # Buy 11, sell 19; buy 16, sell 24; buy 11, mark at 12.
    assert result["realized_pnl"] == 16
    assert result["open_pnl"] == 1
    assert result["final_cash"] == 105
    assert result["final_equity"] == 117
    assert result["net_pnl"] == 17
    assert result["total_fees"] == 5


def test_unknown_comparison_settings_are_rejected():
    from backtest_witness.economics import compare_economics

    rows = tape([10, 20])
    with pytest.raises(ValueError, match="unknown"):
        compare_economics(rows, signals(rows, [0, 0]), fee_typo=1)


@pytest.mark.parametrize("setting,value", [
    ("slippage_bps", 6000), ("fee_fixed", 1e308),
    ("fee_fixed", int(1e308)), ("short_borrow_bps_annual", int(1e308)),
])
def test_unrepresentable_doubled_cost_sensitivity_preserves_valid_main_projection(setting, value):
    import json
    from backtest_witness.economics import compare_economics

    rows = tape([10, 20, 30])
    result = compare_economics(rows, signals(rows, [1, 1, 1]), **{setting: value})
    stress = next(item for item in result["sensitivity"] if item["name"] == "doubled_costs")
    assert result["original"]["final_equity"] >= 0
    assert stress["original"] is None
    assert stress["intervention"] is None
    assert stress["delta"] is None
    assert stress["status"] == "UNAVAILABLE"
    assert stress["reason"]
    assert "unavailable" in result["explanation"].lower()
    json.dumps(result, allow_nan=False)
def test_unrepresentable_cash_precision_is_rejected_instead_of_false_reconciliation():
    from backtest_witness.economics import project
    import pytest
    rows = [dict(timestamp=f"2026-01-01T0{i}:00:00+00:00", symbol="SYN",
                 open=price, high=price, low=price, close=price, volume=100)
            for i, price in enumerate([10, 10, 11])]
    trace = [dict(timestamp=row["timestamp"], target=target)
             for row, target in zip(rows, [1, 0, 0])]
    with pytest.raises(ValueError, match="precision"):
        project(rows, trace, initial_cash=1e16, fee_fixed=0, fee_bps=0,
                spread_bps=0, slippage_bps=0)
@pytest.mark.parametrize("offset", ["Z", "+01:00"])
def test_equivalent_aware_source_and_trace_timestamps_are_accepted(offset):
    from datetime import datetime, timedelta, timezone
    from backtest_witness.demos import synthetic_rows
    from backtest_witness.economics import project, compare_economics
    rows = synthetic_rows(4)
    for row in rows:
        for key in ("timestamp", "available_at"):
            instant = datetime.fromisoformat(row[key])
            row[key] = (instant.isoformat().replace("+00:00", "Z") if offset == "Z"
                        else instant.astimezone(timezone(timedelta(hours=1))).isoformat())
    trace = [{"timestamp": row["timestamp"], "target": 0} for row in rows]
    assert project(rows, trace)["net_pnl"] == 0
    assert compare_economics(rows, trace)["original"]["net_pnl"] == 0


def test_long_increase_and_partial_close_allocate_average_basis_and_fees():
    from backtest_witness.economics import project

    rows = tape([90, 100, 120, 130], [90, 100, 120, 140])
    result = project(rows, signals(rows, [2, 3, 1, 1]), fee_fixed=2,
                     fee_bps=100, spread_bps=0, slippage_bps=0)
    # Two at 100 cost 204; one at 120 costs 123.2. Selling two at 130
    # pays 4.6, leaving one unit with average entry basis 327.2 / 3.
    assert [fill["signed_quantity"] for fill in result["fills"]] == [2, 1, -2]
    assert [fill["quantity"] for fill in result["fills"]] == [2, 1, 2]
    assert [fill["target_quantity"] for fill in result["fills"]] == [2, 3, 1]
    assert result["final_cash"] == pytest.approx(928.2)
    assert result["final_quantity"] == 1
    assert result["realized_pnl"] == pytest.approx(37.2666666666667)
    assert result["open_pnl"] == pytest.approx(30.9333333333333)
    assert result["net_pnl"] == pytest.approx(68.2)
    assert result["total_fees"] == pytest.approx(11.8)


def test_short_add_and_partial_cover_allocate_average_proceeds_and_fees():
    from backtest_witness.economics import project

    rows = tape([110, 100, 80, 70], [110, 100, 80, 60])
    result = project(rows, signals(rows, [-2, -3, -1, -1]), fee_fixed=2,
                     fee_bps=100, spread_bps=0, slippage_bps=0)
    # Opening net proceeds are 196 and 77.2; cover two costs 143.4.
    assert [fill["signed_quantity"] for fill in result["fills"]] == [-2, -1, 2]
    assert [fill["side"] for fill in result["fills"]] == ["sell", "sell", "buy"]
    assert result["final_cash"] == pytest.approx(1129.8)
    assert result["final_quantity"] == -1
    assert result["realized_pnl"] == pytest.approx(38.7333333333333)
    assert result["open_pnl"] == pytest.approx(31.0666666666667)
    assert result["net_pnl"] == pytest.approx(69.8)
    assert result["total_fees"] == pytest.approx(10.2)


@pytest.mark.parametrize("targets,opens,closes,cash,realized,open_pnl,net,fees", [
    ([2, -1, -1], [90, 100, 110], [90, 100, 90],
     1120.7, 12.4666666666667, 18.2333333333333, 30.7, 9.3),
    ([-2, 1, 1], [110, 100, 90], [110, 100, 110],
     921.3, 12.8666666666667, 18.4333333333333, 31.3, 8.7),
])
def test_reversal_is_one_delta_fill_and_splits_fixed_and_notional_fee(
        targets, opens, closes, cash, realized, open_pnl, net, fees):
    from backtest_witness.economics import project

    rows = tape(opens, closes)
    result = project(rows, signals(rows, targets), fee_fixed=2, fee_bps=100,
                     spread_bps=0, slippage_bps=0)
    assert len(result["fills"]) == 2
    assert result["fills"][-1]["quantity"] == 3
    assert result["final_cash"] == pytest.approx(cash)
    assert result["realized_pnl"] == pytest.approx(realized)
    assert result["open_pnl"] == pytest.approx(open_pnl)
    assert result["net_pnl"] == pytest.approx(net)
    assert result["total_fees"] == pytest.approx(fees)


def test_fractional_hold_marks_only_held_quantity_and_does_not_repeat_fees():
    from backtest_witness.economics import project

    rows = tape([90, 100, 110], [90, 100, 120])
    result = project(rows, signals(rows, [0.25, 0.25, 0.25]), fee_fixed=1,
                     fee_bps=100, spread_bps=0, slippage_bps=0)
    assert len(result["fills"]) == 1
    assert result["fills"][0]["notional"] == 25
    assert result["final_cash"] == pytest.approx(973.75)
    assert result["final_quantity"] == 0.25
    assert result["open_pnl"] == pytest.approx(3.75)
    assert result["realized_pnl"] == 0
    assert result["net_pnl"] == pytest.approx(3.75)


@pytest.mark.parametrize("target", [2, -2])
def test_exposure_cap_rejects_whole_target_including_short_sale_proceeds(target):
    from backtest_witness.economics import project

    rows = tape([100, 100, 100])
    result = project(rows, signals(rows, [target, target, target]),
                     initial_cash=100, fee_fixed=0, spread_bps=0, slippage_bps=0)
    assert result["final_quantity"] == 0
    assert result["final_cash"] == 100
    assert result["fills"] == []
    assert len(result["rejected_orders"]) == 2
    assert all(order["target_quantity"] == target for order in result["rejected_orders"])


def test_explicit_leverage_allows_funded_fractional_exposure():
    from backtest_witness.economics import project

    rows = tape([100, 100])
    result = project(rows, signals(rows, [1.5, 1.5]), initial_cash=100,
                     fee_fixed=0, spread_bps=0, slippage_bps=0, max_leverage=1.5)
    assert result["final_quantity"] == 1.5
    assert result["final_cash"] == -50
    assert result["equity_curve"][-1]["leverage"] == 1.5
    assert result["risk_events"] == []


def test_insolvent_short_cover_is_allowed_and_no_forced_exit_is_invented():
    from backtest_witness.economics import project

    rows = tape([100, 100, 300], [100, 300, 300])
    result = project(rows, signals(rows, [-1, 0, 0]), initial_cash=100,
                     fee_fixed=0, spread_bps=0, slippage_bps=0)
    assert [fill["signed_quantity"] for fill in result["fills"]] == [-1, 1]
    assert result["final_cash"] == -100
    assert result["final_quantity"] == 0
    assert result["realized_pnl"] == -200
    assert result["open_pnl"] == 0
    assert result["rejected_orders"] == []
    assert result["risk_events"][0]["timestamp"] == rows[1]["timestamp"]
    assert result["risk_events"][0]["nonpositive_equity"] is True
    assert result["equity_curve"][1]["leverage"] is None
    held = project(rows, signals(rows, [-1, -1, -1]), initial_cash=100,
                   fee_fixed=0, spread_bps=0, slippage_bps=0)
    assert len(held["fills"]) == 1
    assert held["final_quantity"] == -1
    assert held["open_pnl"] == -200


def test_market_move_records_cap_breach_without_liquidating():
    from backtest_witness.economics import project

    rows = tape([100, 100, 150])
    result = project(rows, signals(rows, [-1, -1, -1]), initial_cash=100,
                     fee_fixed=0, spread_bps=0, slippage_bps=0)
    assert result["final_quantity"] == -1
    assert result["final_equity"] == 50
    assert result["risk_events"][-1]["leverage_cap_breached"] is True
    assert result["equity_curve"][-1]["gross_exposure"] == 150
    assert result["equity_curve"][-1]["leverage"] == 3


def test_short_borrow_uses_elapsed_year_previous_quantity_and_previous_close():
    from backtest_witness.economics import project, compare_economics

    rows = tape([100, 100, 80, 60])
    for row, timestamp in zip(rows, ["2024-12-31T00:00:00+00:00",
                                    "2025-01-01T00:00:00+00:00",
                                    "2026-01-01T00:00:00+00:00",
                                    "2026-07-02T12:00:00+00:00"]):
        row["timestamp"] = timestamp
    trace = signals(rows, [-2, -1, 0, 0])
    result = project(rows, trace, fee_fixed=0, spread_bps=0, slippage_bps=0,
                     short_borrow_bps_annual=1000)
    # Charge two prior shorts at 100 for 365 days, then one at 80 for
    # 182.5 days. The first entry bar carries no prior short holding.
    assert [charge["amount"] for charge in result["borrow_charges"]] == [20, 4]
    assert [charge["reference_price"] for charge in result["borrow_charges"]] == [100, 80]
    assert [charge["quantity"] for charge in result["borrow_charges"]] == [2, 1]
    assert result["total_borrow_cost"] == 24
    assert result["final_cash"] == 1036
    assert result["realized_pnl"] == 36
    assert result["open_pnl"] == 0
    compared = compare_economics(rows, trace, fee_fixed=0, spread_bps=0,
                                slippage_bps=0, short_borrow_bps_annual=1000)
    sensitivity = {item["name"]: item for item in compared["sensitivity"]}
    assert sensitivity["cost_free"]["original"]["net_pnl"] == 60
    assert sensitivity["doubled_costs"]["original"]["net_pnl"] == 12
    assert sensitivity["doubled_costs"]["settings"]["max_leverage"] == 1


def test_open_short_marks_market_without_hypothetical_exit_or_borrow_after_end():
    from backtest_witness.economics import project

    rows = tape([110, 100, 90], [110, 100, 80])
    result = project(rows, signals(rows, [-0.5, -0.5, -0.5]), fee_fixed=1,
                     spread_bps=0, slippage_bps=0, short_borrow_bps_annual=3650)
    # One day at 36.5% annually on prior 0.5 * 100 costs 0.05.
    assert len(result["fills"]) == 1
    assert result["total_borrow_cost"] == pytest.approx(0.05)
    assert result["realized_pnl"] == pytest.approx(-0.05)
    assert result["open_pnl"] == 9
    assert result["net_pnl"] == pytest.approx(8.95)


@pytest.mark.parametrize("target,slippage", [(-1, 9999), (-0.25, 0)])
def test_fill_underflow_is_rejected_instead_of_creating_zero_value_trade(target, slippage):
    from backtest_witness.economics import project

    rows = [{"timestamp": f"2026-01-0{index + 1}T00:00:00+00:00", "symbol": "TEST",
             "open": 5e-324, "high": 5e-324, "low": 5e-324,
             "close": 5e-324, "volume": 1} for index in range(2)]
    with pytest.raises(ValueError, match="precision"):
        project(rows, signals(rows, [target, target]), fee_fixed=0, spread_bps=0,
                slippage_bps=slippage)


def test_paired_delta_overflow_is_rejected_even_when_both_ledgers_are_finite():
    from backtest_witness.economics import project, compare_economics

    rows = tape([1e307, 1e307, 1e308])
    short, long = signals(rows, [-1, -1, -1]), signals(rows, [1, 1, 1])
    settings = {"initial_cash": 1e307, "fee_fixed": 0,
                "spread_bps": 0, "slippage_bps": 0}
    assert project(rows, short, **settings)["net_pnl"] == pytest.approx(-9e307)
    assert project(rows, long, **settings)["net_pnl"] == pytest.approx(9e307)
    with pytest.raises(ValueError, match="finite"):
        compare_economics(rows, short, long, **settings)


@pytest.mark.parametrize("direction", [-1, 1])
def test_derived_reversal_quantity_overflow_is_a_descriptive_value_error(direction):
    from backtest_witness.economics import project

    rows = [{"timestamp": f"2026-01-0{index + 1}T00:00:00+00:00", "symbol": "TEST",
             "open": 1e-300, "high": 1e-300, "low": 1e-300,
             "close": 1e-300, "volume": 1} for index in range(3)]
    trace = signals(rows, [direction * 1e308, direction * -1e308, 0])
    with pytest.raises(ValueError, match="quantity.*finite"):
        project(rows, trace, initial_cash=1e9, fee_fixed=0,
                spread_bps=0, slippage_bps=0)


def test_finite_target_price_product_overflow_is_checked_before_balance_conversion():
    from backtest_witness.economics import project

    rows = tape([10, 10])
    with pytest.raises(ValueError, match="finite"):
        project(rows, signals(rows, [1e308, 1e308]), fee_fixed=0,
                spread_bps=0, slippage_bps=0)


@pytest.mark.parametrize("reduce", [False, True])
def test_held_position_price_product_overflow_is_a_value_error_at_close_or_rebalance(reduce):
    from backtest_witness.economics import project

    rows = [{"timestamp": f"2026-01-0{index + 1}T00:00:00+00:00", "symbol": "TEST",
             "open": price, "high": price, "low": price,
             "close": price, "volume": 1}
            for index, price in enumerate([1e-300, 1e-300, 10])]
    units = int(1e308)
    trace = signals(rows, [units, units - 1 if reduce else units, 0])
    with pytest.raises(ValueError, match="finite"):
        project(rows, trace, initial_cash=1e9, fee_fixed=0,
                spread_bps=0, slippage_bps=0)
