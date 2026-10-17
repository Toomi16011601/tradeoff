"""Behavioral failure-search policy tests with deterministic execution callbacks."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import pytest


def api():
    try:
        module = importlib.import_module('tradeoff.failure_lab')
    except ModuleNotFoundError:
        pytest.fail('failure lab public API is not implemented')
    return module.run_failure_lab


def bars():
    return [dict(timestamp=(datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat(),
                 symbol='SYN', open=100, high=102, low=99, close=101, volume=100) for i in range(4)]


def execution(rows, config, seed, scenario):
    loss = (scenario['commission_bps'] + scenario['spread_bps']) / 10 + scenario['delay_bars'] * 2
    final = 110 - loss if not config.get('repair') else 110
    result = dict(engine='synthetic', engine_version='1', initial_cash=100,
                  effective_settings={'cash': 100}, scenario=deepcopy(scenario), timing='next open', warnings=[],
                  equity=[dict(timestamp=row['timestamp'], position=1 if i else 0,
                               equity=100 + (final - 100) * i / 3) for i, row in enumerate(rows)],
                  trades=[dict(entry_bar=1, exit_bar=3, size=1, entry_price=100, exit_price=110,
                               pnl=final-100, commission=loss)], open_trades=[], pending_orders=[])
    return result

execution.runner_spec = dict(engine='callback', engine_settings={})
execution.adapter_info = dict(version='1')


def scenario(commission=0, spread=0, delay=0, name='stress'):
    return dict(name=name, commission_bps=commission, spread_bps=spread, delay_bars=delay)


def test_policy_failure_reduced_without_dropping_history_and_four_final_calls():
    calls = []
    def run(rows, config, seed, stress):
        calls.append((deepcopy(rows), deepcopy(config), seed, deepcopy(stress)))
        return execution(rows, config, seed, stress)
    report = api()(run, bars(), {'tag': 'same'}, scenarios=[scenario(200, 25, 2), scenario(25), scenario(100)], max_calls=40)
    assert report['status'] == 'FAILURE_FOUND'
    assert report['failure']['scenario'] == dict(commission_bps=100, spread_bps=0, delay_bars=2)
    assert len(report['failure']['differences']) == 3
    assert all(len(rows) == 4 and config == {'tag': 'same'} and seed == 7 for rows, config, seed, _ in calls)
    assert [s for _, _, _, s in calls[-4:]] == [dict(commission_bps=0, spread_bps=0, delay_bars=0)] * 2 + [report['failure']['scenario']] * 2
    assert report['coverage']['runs'] == len(calls) <= 40
    assert report['failure']['reduction']['complete'] is True


def test_baseline_absolute_failure_is_not_a_stress_finding():
    report = api()(execution, bars(), scenarios=[scenario(200)], requirements={'min_return_pct': 20})
    assert report['status'] == 'BASELINE_FAILED'
    assert report['failure'] is None
    assert report['baseline']['status'] == 'FAIL'
    assert report['scenarios'][0]['status'] == 'NOT_RUN'
    assert report['coverage']['runs'] == 2


def test_relative_drop_uses_losing_baseline_and_minimum_trade_guard():
    def losing(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        for point in result['equity']:
            point['equity'] -= 20
        return result
    report = api()(losing, bars(), scenarios=[scenario(50)], requirements={'min_return_pct': None, 'max_return_drop_pct': 4, 'min_closed_trades': 1})
    assert report['baseline']['metrics']['return_pct'] == pytest.approx(-10)
    assert report['status'] == 'FAILURE_FOUND'
    assert any('drop' in v.lower() for v in report['failure']['violations'])
    empty = lambda rows, config, seed, s: dict(execution(rows, config, seed, s), trades=[])
    assert api()(empty, bars(), scenarios=[scenario(50)], requirements={'min_closed_trades': 1})['status'] == 'BASELINE_FAILED'


def test_default_suite_has_separate_costs_delay_and_combination():
    report = api()(execution, bars(), requirements={'min_return_pct': None})
    stresses = [entry['scenario'] for entry in report['scenarios']]
    assert len(stresses) == 12
    assert dict(commission_bps=200, spread_bps=0, delay_bars=0) in stresses
    assert dict(commission_bps=0, spread_bps=25, delay_bars=0) in stresses
    assert dict(commission_bps=0, spread_bps=0, delay_bars=2) in stresses
    assert dict(commission_bps=25, spread_bps=10, delay_bars=1) in stresses
    assert report['status'] == 'NO_FAILURE_OBSERVED'
    assert report['coverage']['complete'] is True


def test_budget_omissions_are_visible_and_inconclusive():
    report = api()(execution, bars(), scenarios=[scenario(5), scenario(10)], max_calls=8)
    assert report['status'] == 'INCONCLUSIVE'
    assert report['coverage']['runs'] <= 8
    assert report['coverage']['complete'] is False
    assert any(entry['status'] == 'NOT_RUN' for entry in report['scenarios'])


def test_failure_remains_available_with_unsupported_other_scenario():
    from tradeoff.privacy import ExecutionUnavailable
    def unsupported(rows, config, seed, stress):
        if stress['delay_bars']:
            raise ExecutionUnavailable('unsupported stop entry delay')
        return execution(rows, config, seed, stress)
    report = api()(unsupported, bars(), scenarios=[scenario(delay=1), scenario(200)])
    assert report['status'] == 'FAILURE_FOUND'
    assert report['scenarios'][0]['status'] == 'UNAVAILABLE'
    assert 'unsupported stop' in report['scenarios'][0]['reason']
    assert report['coverage']['complete'] is False


def test_full_observation_repeatability_includes_pending_orders():
    counter = [0]
    def unstable(rows, config, seed, stress):
        counter[0] += 1
        result = execution(rows, config, seed, stress)
        result['pending_orders'] = [dict(size=counter[0], limit=None, stop=None, sl=None, tp=None,
                                         is_contingent=False, parent_entry_bar=None, created_bar=3, due_bar=4)]
        return result
    report = api()(unstable, bars(), scenarios=[scenario(200)])
    assert report['status'] == 'INCONCLUSIVE'
    assert 'repeat' in report['baseline']['reason'].lower()
    assert report['failure'] is None


@pytest.mark.parametrize('fault', ['nan', 'short', 'timestamp', 'negative_cash', 'bad_position'])
def test_invalid_observation_is_unavailable(fault):
    def invalid(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        if fault == 'nan': result['equity'][0]['equity'] = float('nan')
        if fault == 'short': result['equity'].pop()
        if fault == 'timestamp': result['equity'][0]['timestamp'] = rows[1]['timestamp']
        if fault == 'negative_cash': result['initial_cash'] = -1
        if fault == 'bad_position': result['equity'][0]['position'] = True
        return result
    report = api()(invalid, bars(), scenarios=[scenario(5)])
    assert report['status'] == 'INCONCLUSIVE'
    assert report['baseline']['status'] == 'UNAVAILABLE'


def test_drawdown_accounts_for_initial_cash_before_first_bar():
    def depressed(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        for point in result['equity']: point['equity'] = 80
        return result
    report = api()(depressed, bars(), scenarios=[], requirements={'min_return_pct': None, 'max_drawdown_pct': 19})
    assert report['baseline']['metrics']['max_drawdown_pct'] == pytest.approx(20)
    assert report['status'] == 'BASELINE_FAILED'


def test_each_call_gets_independent_config_and_rows():
    rows, config = bars(), {'nested': {'value': 1}}
    def mutating(tape, options, seed, stress):
        original = deepcopy(tape)
        assert options['nested']['value'] == 1 and tape[0]['close'] == 101
        options['nested']['value'] = 999
        tape[0]['close'] = 999
        return execution(original, {}, seed, stress)
    report = api()(mutating, rows, config, scenarios=[scenario(5)])
    assert report['status'] == 'NO_FAILURE_OBSERVED'
    assert config['nested']['value'] == 1 and rows[0]['close'] == 101


@pytest.mark.parametrize('kwargs', [{'requirements': {'min_closed_trades': True}}, {'requirements': {'max_return_drop_pct': -1}}, {'scenarios': [scenario(delay=1.5)]}, {'max_calls': True}, {'seed': True}])
def test_invalid_policy_or_search_settings_fail_before_execution(kwargs):
    with pytest.raises(ValueError): api()(execution, bars(), **kwargs)


def test_stress_cannot_change_engine_version_or_initial_cash():
    def changed(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        if stress['commission_bps']: result['initial_cash'] = 200
        return result
    report = api()(changed, bars(), scenarios=[scenario(200)])
    assert report['status'] == 'INCONCLUSIVE'
    assert report['scenarios'][0]['status'] == 'UNAVAILABLE'
    assert 'initial_cash' in report['scenarios'][0]['reason']


def test_reduction_budget_can_find_failure_without_claiming_complete_reduction():
    report = api()(execution, bars(), scenarios=[scenario(200, 25, 2)], max_calls=8)
    assert report['status'] == 'FAILURE_FOUND'
    assert report['coverage']['runs'] == 8
    assert report['failure']['reduction']['complete'] is False
    assert report['failure']['scenario'] == dict(commission_bps=200, spread_bps=25, delay_bars=2)


def test_final_cross_phase_change_refuses_finding():
    count = [0]
    def changing(rows, config, seed, stress):
        count[0] += 1
        result = execution(rows, config, seed, stress)
        if count[0] >= 5: result['warnings'] = ['late hidden state']
        return result
    report = api()(changing, bars(), scenarios=[scenario(200)], max_calls=8)
    assert report['status'] == 'INCONCLUSIVE'
    assert report['failure'] is None
    assert report['coverage']['runs'] == 8


@pytest.mark.parametrize('fault', ['closed_missing', 'closed_zero_size', 'closed_boolean_size', 'closed_negative_price',
                                  'closed_missing_commission', 'closed_float_bar', 'closed_future_bar', 'closed_reversed_bars',
                                  'open_missing', 'pending_missing', 'pending_boolean_bar', 'pending_early_due', 'warning_object'])
def test_malformed_native_records_cannot_satisfy_trade_guard(fault):
    def malformed(rows, config, seed, stress):
        result = execution(rows, {'repair': True}, seed, stress)
        if not stress['commission_bps']:
            return result
        trade = result['trades'][0]
        if fault == 'closed_missing': result['trades'] = [{}]
        if fault == 'closed_zero_size': trade['size'] = 0
        if fault == 'closed_boolean_size': trade['size'] = True
        if fault == 'closed_negative_price': trade['exit_price'] = -1
        if fault == 'closed_missing_commission': trade.pop('commission')
        if fault == 'closed_float_bar': trade['entry_bar'] = 1.0
        if fault == 'closed_future_bar': trade['exit_bar'] = 4
        if fault == 'closed_reversed_bars': trade['exit_bar'] = 0
        if fault == 'open_missing': result['open_trades'] = [{}]
        if fault == 'pending_missing': result['pending_orders'] = [{}]
        if fault in ('pending_boolean_bar', 'pending_early_due'):
            result['pending_orders'] = [dict(size=1, limit=None, stop=None, sl=None, tp=None,
                                             is_contingent=False, parent_entry_bar=None,
                                             created_bar=True if fault == 'pending_boolean_bar' else 2, due_bar=1)]
        if fault == 'warning_object': result['warnings'] = [{}]
        return result
    report = api()(malformed, bars(), scenarios=[scenario(200)], requirements={'min_closed_trades': 1})
    assert report['status'] == 'INCONCLUSIVE'
    assert report['scenarios'][0]['status'] == 'UNAVAILABLE'
    assert report['failure'] is None


def test_valid_open_holdings_and_future_pending_bars_allow_negative_equity():
    def insolvent(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        result['equity'][-1].update(position=-2, equity=-5)
        result['open_trades'] = [dict(entry_bar=1, size=-2, entry_price=100, pnl=-105, sl=None, tp=95)]
        result['pending_orders'] = [dict(size=2, limit=None, stop=None, sl=None, tp=None,
                                         is_contingent=True, parent_entry_bar=1, created_bar=3, due_bar=6)]
        return result
    report = api()(insolvent, bars(), scenarios=[], requirements={'min_return_pct': None})
    assert report['status'] == 'NO_FAILURE_OBSERVED'
    assert report['baseline']['metrics']['max_drawdown_pct'] > 100


@pytest.mark.parametrize('entry', [None, [], 0, 'stress'])
def test_invalid_scenario_entry_is_rejected_before_any_execution(entry):
    calls = []
    def tracked(rows, config, seed, stress):
        calls.append(stress)
        return execution(rows, config, seed, stress)
    with pytest.raises(ValueError):
        api()(tracked, bars(), scenarios=[entry])
    assert calls == []


def test_equivalent_position_numbers_have_same_exported_representation():
    import json
    def typed(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        for point in result['equity']:
            point['position'] = 1.0 if stress['commission_bps'] else 1
        return result
    report = api()(typed, bars(), scenarios=[scenario(200)])
    assert report['status'] == 'FAILURE_FOUND'
    for difference in report['failure']['differences']:
        assert json.dumps(difference['before_position']) == json.dumps(difference['after_position'])


def test_position_canonicalization_retains_exact_large_integers_and_fractional_units():
    def quantities(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        for point, quantity in zip(result['equity'], [0, 9007199254740993, .125, -.125]):
            point['position'] = quantity
        return result
    report = api()(quantities, bars(), scenarios=[])
    assert [point['position'] for point in report['baseline']['result']['equity']] == [0, 9007199254740993, .125, -.125]
    assert type(report['baseline']['result']['equity'][1]['position']) is int
