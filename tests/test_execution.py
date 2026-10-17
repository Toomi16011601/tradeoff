"""Synthetic actual-engine regressions for the native execution boundary."""
from copy import deepcopy
import importlib
import json

import pytest

backtesting = pytest.importorskip('backtesting')
from backtesting import Backtest, Strategy
from tradeoff.adapters._shared import frame_from_rows


def tape(prices=None):
    prices = prices or [100] * 9
    return [dict(timestamp=f'2026-01-{i+1:02d}T00:00:00Z', symbol='SYNTH', open=p,
                 high=p+1, low=p-1, close=p, volume=100) for i, p in enumerate(prices)]


class RoundTrip(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) == 2:
            self.buy(size=4)
        if len(self.data) == 6:
            self.position.close()


def runner(cls=RoundTrip, **settings):
    module = importlib.import_module('tradeoff.execution')
    return module.make_backtesting_execution_runner(cls, engine_settings=settings)


def execute(cls=RoundTrip, rows=None, scenario=None, **settings):
    return runner(cls, **settings)(rows or tape(), {}, 7, scenario or {})


# Missing extraction, extra liquidation, or accidental projection accounting breaks this.
def test_zero_stress_is_native_equity_and_closed_trade_parity():
    rows = tape([100, 100, 102, 104, 105, 106, 108, 107, 110])
    native = Backtest(frame_from_rows(rows), RoundTrip, cash=10000, commission=.001,
                      spread=.002, finalize_trades=False).run()
    result = execute(rows=rows, commission=.001, spread=.002)
    assert [r['equity'] for r in result['equity']] == native['_equity_curve']['Equity'].tolist()
    assert [r['position'] for r in result['equity']] == [0, 0, 4, 4, 4, 4, 0, 0, 0]
    actual = result['trades'][0]
    expected = native['_trades'].iloc[0]
    assert actual == dict(entry_bar=int(expected.EntryBar), exit_bar=int(expected.ExitBar),
                          size=int(expected.Size), entry_price=expected.EntryPrice,
                          exit_price=expected.ExitPrice, pnl=expected.PnL, commission=expected.Commission)
    assert result['open_trades'] == []
    assert result['pending_orders'] == []
    assert result['engine_version'] == '0.6.6'
    assert result['initial_cash'] == 10000
    json.dumps(result, allow_nan=False)


# Due times must be extra bars beyond the native next-open, for entries and closes.
@pytest.mark.parametrize('delay,entry,exit', [(0, 2, 6), (1, 3, 7), (2, 4, 8)])
def test_precise_extra_bar_entry_and_manual_close(delay, entry, exit):
    result = execute(scenario={'delay_bars': delay})
    assert (result['trades'][0]['entry_bar'], result['trades'][0]['exit_bar']) == (entry, exit)


class RelativeEntries(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) in (2, 5):
            self.buy(size=.999)
        if len(self.data) in (3, 6):
            self.position.close()


# Native sizing and fee cash must feed later entries, not just change final PnL.
def test_native_commission_and_spread_feed_cash_and_later_sizing():
    zero = execute(RelativeEntries, cash=1000)
    stressed = execute(RelativeEntries, cash=1000, commission=.001, spread=.001,
                       scenario={'commission_bps': 200, 'spread_bps': 20})
    assert [t['size'] for t in zero['trades']] == [9, 9]
    assert [t['size'] for t in stressed['trades']] == [9, 9]
    assert stressed['effective_settings']['commission'] == pytest.approx(.021)
    assert stressed['effective_settings']['spread'] == pytest.approx(.003)
    assert stressed['equity'][-1]['equity'] < zero['equity'][-1]['equity']
    heavy = execute(RelativeEntries, cash=1000, scenario={'commission_bps': 900})
    assert [t['size'] for t in heavy['trades']] == [9, 7]


class PartialShort(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) == 2:
            self.sell(size=4)
        if len(self.data) == 5:
            self.trades[0].close(.5)


# Trade.close bypasses new_order, so delay must catch its direct insertion.
def test_partial_short_close_delayed_and_terminal_holdings_preserved():
    result = execute(PartialShort, scenario={'delay_bars': 1, 'commission_bps': 100})
    assert result['trades'][0]['size'] == -2
    assert result['trades'][0]['entry_bar'] == 3
    assert result['trades'][0]['exit_bar'] == 6
    assert result['open_trades'][0]['size'] == -2
    assert result['equity'][-1] == dict(timestamp='2026-01-09T00:00:00+00:00', position=-2, equity=9994)


class Bracket(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) == 2:
            self.buy(size=2, sl=95, tp=105)


# Protective orders must stay native, including same entry-bar reprocessing.
def test_delayed_entry_keeps_native_same_bar_protection():
    rows = tape()
    rows[3]['low'] = 90
    result = execute(Bracket, rows=rows, scenario={'delay_bars': 1})
    assert result['trades'][0]['entry_bar'] == 3
    assert result['trades'][0]['exit_bar'] == 3
    assert result['trades'][0]['exit_price'] == 95


class CancelTail(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) == 2:
            self.buy(size=2)
        if len(self.data) == 3:
            assert len(self.orders) == 1
            self.orders[0].cancel()
        if len(self.data) == 8:
            self.buy(size=3)


# Filtering broker processing must preserve visibility/cancellation and tail orders.
def test_cancelled_orders_and_pending_tail_are_visible():
    result = execute(CancelTail, scenario={'delay_bars': 2})
    assert result['trades'] == result['open_trades'] == []
    assert [r['position'] for r in result['equity']] == [0] * 9
    assert result['pending_orders'][0]['size'] == 3
    assert result['pending_orders'][0]['created_bar'] == 7
    assert result['pending_orders'][0]['due_bar'] == 10


class Limit(Strategy):
    def init(self):
        pass
    def next(self):
        self.buy(size=1, limit=99)


class InitOrder(Strategy):
    def init(self):
        self.buy(size=1)
    def next(self):
        pass


@pytest.mark.parametrize('cls,settings,message', [
    (Limit, {}, 'stop/limit'), (RoundTrip, {'trade_on_close': True}, 'trade_on_close'),
    (InitOrder, {}, 'init')])
def test_unsupported_delayed_semantics_refused(cls, settings, message):
    with pytest.raises(ValueError, match=message):
        execute(cls, scenario={'delay_bars': 1}, **settings)


def test_delay_private_hook_version_gate(monkeypatch):
    module = importlib.import_module('tradeoff.execution')
    monkeypatch.setattr(module, 'engine_version', lambda name: '0.6.7')
    with pytest.raises(ValueError, match='0.6.6'):
        execute(scenario={'delay_bars': 1})


def test_repeated_runs_preserve_rows_and_preparation():
    rows = tape()
    original = deepcopy(rows)
    def prepare(frame):
        frame['Signal'] = 1
        return frame
    module = importlib.import_module('tradeoff.execution')
    run = module.make_backtesting_execution_runner(RoundTrip, prepare=prepare)
    assert run(rows, {}, 7, {'delay_bars': 1}) == run(rows, {}, 7, {'delay_bars': 1})
    assert rows == original
    def corrupt(frame):
        frame.loc[frame.index[0], 'Open'] = 1
        return frame
    bad = module.make_backtesting_execution_runner(RoundTrip, prepare=corrupt)
    with pytest.raises(ValueError, match='OHLCV'):
        bad(rows, {}, 7, {})


def callback(rows, config, seed, scenario):
    return {'seed': seed, 'scenario': scenario}


def test_resolver_strategy_and_explicit_four_argument_callback():
    module = importlib.import_module('tradeoff.execution')
    run = module.resolve_execution_runner('test_execution:RoundTrip')
    assert run.runner_spec['engine'] == 'backtesting'
    assert run.adapter_info['version'] == '0.6.6'
    run = module.resolve_execution_runner('test_execution:callback', engine='callback')
    assert run([], {}, 9, {'delay_bars': 1}) == {'seed': 9, 'scenario': {'delay_bars': 1}}
    assert run.runner_spec == {'engine': 'callback', 'engine_settings': {}}


@pytest.mark.parametrize('scenario', [{'delay_bars': True}, {'delay_bars': 1.1},
                                      {'commission_bps': -1}, {'spread_bps': float('nan')},
                                      {'other': 1}])
def test_invalid_scenarios_refused(scenario):
    with pytest.raises(ValueError):
        execute(scenario=scenario)


class Exclusive(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) in (2, 3, 6):
            self.buy(size=2 if len(self.data) != 3 else 3)


def test_exclusive_rules_cancel_immature_orders_and_delay_replacement_close():
    result = execute(Exclusive, exclusive_orders=True, scenario={'delay_bars': 2})
    assert [(t['entry_bar'], t['exit_bar'], t['size']) for t in result['trades']] == [(5, 8, 3)]
    assert [(t['entry_bar'], t['size']) for t in result['open_trades']] == [(8, 2)]


def test_active_native_protection_remains_pending_during_delayed_manual_close():
    class ProtectedClose(Bracket):
        def next(self):
            super().next()
            if len(self.data) == 8:
                self.position.close()
    result = execute(ProtectedClose, scenario={'delay_bars': 2})
    assert result['open_trades'][0]['size'] == 2
    protective = [order for order in result['pending_orders'] if order['is_contingent']]
    manual = [order for order in result['pending_orders'] if not order['is_contingent']]
    assert len(protective) == 2
    assert [(o['stop'], o['limit']) for o in protective] == [(95, None), (None, 105)]
    assert manual[0]['due_bar'] == 10


def test_short_spread_and_commission_use_native_equity_not_sale_proceeds():
    result = execute(PartialShort, rows=tape([100, 100, 100, 100, 100, 100, 90, 90, 90]),
                     cash=1000, scenario={'delay_bars': 1, 'spread_bps': 100, 'commission_bps': 100})
    assert result['trades'][0]['entry_price'] == 99
    assert result['trades'][0]['exit_price'] == 90
    assert result['equity'][-1]['equity'] == pytest.approx(1030.24)


def test_zero_stress_open_holdings_match_native_marks_without_liquidation():
    result = execute(Bracket)
    assert result['trades'] == []
    assert result['open_trades'][0]['size'] == 2
    assert result['equity'][-1]['position'] == 2
    assert any('remain open' in warning for warning in result['warnings'])


def test_fixed_native_commission_is_retained_with_additional_relative_costs():
    result = execute(commission=[2, .001], scenario={'commission_bps': 10})
    assert result['effective_settings']['commission'] == [2, .002]
    assert result['trades'][0]['commission'] == pytest.approx(5.6)
    assert result['equity'][-1]['equity'] == pytest.approx(9994.4)


def test_callback_resolver_copies_runtime_metadata():
    callback.adapter_info = {'engine': 'backtesting', 'version': '0.6.6'}
    module = importlib.import_module('tradeoff.execution')
    run = module.resolve_execution_runner('test_execution:callback', engine='callback')
    assert run.adapter_info == callback.adapter_info
    run.adapter_info['version'] = 'other'
    assert callback.adapter_info['version'] == '0.6.6'


@pytest.mark.parametrize('delay', [0, 1])
def test_unverified_engine_version_refused_even_for_control(monkeypatch, delay):
    module = importlib.import_module('tradeoff.execution')
    monkeypatch.setattr(module, 'engine_version', lambda name: '0.6.7')
    with pytest.raises(ValueError, match='0.6.6'):
        execute(scenario={'delay_bars': delay})


def test_delayed_fills_use_due_bar_open_without_rewriting_tape():
    rows = tape([100, 100, 101, 103, 107, 109, 111, 113, 117])
    original = deepcopy(rows)
    result = execute(rows=rows, scenario={'delay_bars': 2})
    assert result['trades'][0]['entry_price'] == 107
    assert result['trades'][0]['exit_price'] == 117
    assert result['trades'][0]['pnl'] == 40
    assert rows == original


def test_protective_stop_fires_before_immature_manual_close():
    class CloseProtected(Bracket):
        def next(self):
            super().next()
            if len(self.data) == 5:
                self.position.close()
    rows = tape()
    rows[5]['open'] = 90
    rows[5]['low'] = 89
    rows[5]['close'] = 90
    result = execute(CloseProtected, rows=rows, scenario={'delay_bars': 2})
    assert result['trades'][0]['entry_bar'] == 4
    assert result['trades'][0]['exit_bar'] == 5
    assert result['trades'][0]['exit_price'] == 90
    assert result['open_trades'] == result['pending_orders'] == []


def test_ordering_rejected_delay_does_not_patch_other_native_backtests():
    with pytest.raises(ValueError, match='stop/limit'):
        execute(Limit, scenario={'delay_bars': 1})
    native = Backtest(frame_from_rows(tape()), RoundTrip).run()
    assert native['_trades'].iloc[0].EntryBar == 2


def test_open_native_pnl_does_not_invent_commission_allocation():
    result = execute(PartialShort, commission=[2, .001], scenario={'delay_bars': 1})
    assert 'commission' not in result['open_trades'][0]
    assert result['open_trades'][0]['pnl'] == 0
    assert any('Open-trade P&L excludes entry fees' in warning for warning in result['warnings'])


class InsolventMultipleTrades(Strategy):
    def init(self):
        pass
    def next(self):
        if len(self.data) in (2, 3):
            self.buy(size=4)


@pytest.mark.parametrize('delay,crash_bar', [(0, 4), (1, 5)])
def test_insolvency_halt_preserves_native_residual_position_and_frozen_suffix(delay, crash_bar):
    rows = tape([100] * crash_bar + [10] * (9 - crash_bar))
    result = execute(InsolventMultipleTrades, rows=rows, cash=100, margin=.1,
                     scenario={'delay_bars': delay})
    # Native 0.6.6 closes one trade while iterating a mutating trade list,
    # retains the second holding, and freezes its equity curve at zero.
    assert [r['position'] for r in result['equity'][crash_bar:]] == [4] * (9 - crash_bar)
    assert [r['equity'] for r in result['equity'][crash_bar:]] == [0] * (9 - crash_bar)
    assert [(t['size'], t['exit_bar']) for t in result['trades']] == [(4, crash_bar)]
    assert [t['size'] for t in result['open_trades']] == [4]
    assert any('halted' in warning for warning in result['warnings'])
    assert result == execute(InsolventMultipleTrades, rows=rows, cash=100, margin=.1,
                             scenario={'delay_bars': delay})
    if delay == 0:
        native = Backtest(frame_from_rows(rows), InsolventMultipleTrades, cash=100, margin=.1).run()
        assert native['_strategy']._broker.position.size == 4
        assert [r['equity'] for r in result['equity']] == native['_equity_curve']['Equity'].tolist()
