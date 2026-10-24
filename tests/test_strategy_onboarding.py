"""Script inspection and baseline metric comparison for new integrations."""
import json
from pathlib import Path

import pytest


def test_inspect_script_finds_import_time_run_without_executing_source(tmp_path):
    from tradeoff.strategy_onboarding import inspect_script

    marker = tmp_path / 'executed'
    source = tmp_path / 'strategy.py'
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
        "from backtesting import Backtest, Strategy\n"
        "class Strat(Strategy):\n    def init(self): pass\n    def next(self): pass\n"
        "bt = Backtest(data, Strat)\nstats = bt.run()\nbt.plot()\n"
    )
    result = inspect_script(source)

    assert marker.exists() is False
    assert result['status'] == 'INSPECTED'
    assert result['strategy_classes'] == [{'name': 'Strat', 'line': 4}]
    assert [(item['call'], item['line']) for item in result['import_time_calls']] == [
        ('Backtest', 7), ('run', 8), ('plot', 9)]
    assert result['recognized_import_time_calls_present'] is True
    assert 'bounded' in result['scope'].lower()
    assert str(source) not in json.dumps(result)


def test_inspect_script_keeps_main_guard_separate_from_import_time_calls(tmp_path):
    from tradeoff.strategy_onboarding import inspect_script

    source = tmp_path / 'strategy.py'
    source.write_text(
        "from backtesting import Backtest, Strategy\n"
        "class Safe(Strategy):\n    pass\n"
        "if __name__ == '__main__':\n"
        "    bt = Backtest(data, Safe)\n    bt.run()\n"
    )
    result = inspect_script(source)

    assert result['strategy_classes'] == [{'name': 'Safe', 'line': 2}]
    assert result['import_time_calls'] == []
    assert [item['call'] for item in result['main_guard_calls']] == ['Backtest', 'run']
    assert result['recognized_import_time_calls_present'] is False
    assert 'not a safety' in result['scope'].lower()


def test_inspect_script_finds_backtesting_lib_strategy_mixin_bases(tmp_path):
    from tradeoff.strategy_onboarding import inspect_script

    source = tmp_path / 'library_example.py'
    source.write_text(
        "from backtesting.lib import SignalStrategy, TrailingStrategy\n"
        "class SmaCross(SignalStrategy, TrailingStrategy):\n    pass\n"
    )
    result = inspect_script(source)
    assert result['strategy_classes'] == [{'name': 'SmaCross', 'line': 2}]
    assert 'known Backtesting.py Strategy bases' in result['scope']


def test_inspect_script_rejects_invalid_source_without_echoing_it(tmp_path):
    from tradeoff.strategy_onboarding import inspect_script

    secret = 'SECRET_ACCOUNT_12345'
    source = tmp_path / 'strategy.py'
    source.write_text(f"def broken(: # {secret}\n")
    with pytest.raises(ValueError, match='valid Python syntax') as exc:
        inspect_script(source)
    assert secret not in str(exc.value)


def report():
    return {
        'schema_version': 'backtest-witness.failure-lab.v1',
        'runner_spec': {'engine': 'backtesting', 'engine_settings': {
            'cash': 10000, 'commission': 0, 'spread': 0, 'margin': 1,
            'trade_on_close': False, 'exclusive_orders': False}},
        'dataset': {'input_hash': 'a' * 64},
        'baseline': {'status': 'PASS', 'metrics': {
            'return_pct': 4.067, 'max_drawdown_pct': 5.154,
            'closed_trades': 572, 'final_equity': 10406.7,
            'net_profit': 406.7}},
    }


def test_check_baseline_accepts_native_backtesting_stats_and_discloses_context_limit():
    from tradeoff.strategy_onboarding import compare_baseline

    expected = {'Return [%]': 4.067, 'Max. Drawdown [%]': -5.154,
                '# Trades': 572, 'Equity Final [$]': 10406.7}
    result = compare_baseline(report(), expected)

    assert result['status'] == 'METRICS_MATCH_CONTEXT_UNVERIFIED'
    assert result['checked_metrics'] == ['return_pct', 'max_drawdown_pct', 'closed_trades', 'final_equity']
    assert result['context']['dataset'] == 'UNVERIFIED'
    assert result['context']['engine_settings'] == 'UNVERIFIED'
    assert 'not prove' in result['scope'].lower()


def test_check_baseline_detects_metric_difference_and_checks_declared_context():
    from tradeoff.strategy_onboarding import compare_baseline

    expected = {'return_pct': 1.23, 'closed_trades': 572,
                'dataset_hash': 'a' * 64,
                'engine_settings': report()['runner_spec']['engine_settings']}
    result = compare_baseline(report(), expected)

    assert result['status'] == 'MISMATCH'
    assert result['context'] == {'dataset': 'MATCH', 'engine_settings': 'MATCH'}
    assert result['metrics']['return_pct']['match'] is False
    assert result['metrics']['closed_trades']['match'] is True


def test_check_baseline_partial_metrics_never_report_full_match_even_with_matching_context():
    from tradeoff.strategy_onboarding import compare_baseline

    expected = {'closed_trades': 572, 'dataset_hash': 'a' * 64,
                'engine_settings': report()['runner_spec']['engine_settings']}
    result = compare_baseline(report(), expected)
    assert result['status'] == 'PARTIAL_MATCH'
    assert result['checked_metrics'] == ['closed_trades']
    assert result['unchecked_metrics'] == ['return_pct', 'max_drawdown_pct', 'final_equity']
    assert result['context'] == {'dataset': 'MATCH', 'engine_settings': 'MATCH'}


def test_check_baseline_full_match_requires_all_four_metrics_and_both_context_fields():
    from tradeoff.strategy_onboarding import compare_baseline

    expected = {'return_pct': 4.067, 'max_drawdown_pct': 5.154,
                'closed_trades': 572, 'final_equity': 10406.7,
                'dataset_hash': 'a' * 64,
                'engine_settings': report()['runner_spec']['engine_settings']}
    result = compare_baseline(report(), expected)
    assert result['status'] == 'MATCH'
    assert result['unchecked_metrics'] == []


def test_check_baseline_accepts_partial_metrics_but_refuses_context_mismatch():
    from tradeoff.strategy_onboarding import compare_baseline

    expected = {'closed_trades': 572, 'dataset_hash': 'b' * 64}
    result = compare_baseline(report(), expected)
    assert result['status'] == 'MISMATCH'
    assert result['context']['dataset'] == 'MISMATCH'
    assert result['unchecked_metrics'] == ['return_pct', 'max_drawdown_pct', 'final_equity']


@pytest.mark.parametrize('expected', [
    {}, {'return_pct': True}, {'return_pct': float('nan')},
    {'closed_trades': 1.5}, {'unknown': 3},
    {'Return [%]': 1, 'return_pct': 1},
])
def test_check_baseline_rejects_ambiguous_or_invalid_expected_metrics(expected):
    from tradeoff.strategy_onboarding import compare_baseline
    with pytest.raises(ValueError):
        compare_baseline(report(), expected)


def test_check_baseline_requires_completed_native_baseline():
    from tradeoff.strategy_onboarding import compare_baseline
    saved = report()
    saved['baseline']['metrics'] = None
    with pytest.raises(ValueError, match='completed native baseline'):
        compare_baseline(saved, {'return_pct': 4.067})


def test_cli_inspect_and_check_baseline_are_machine_readable(tmp_path, capsys):
    from tradeoff.cli import main

    script = tmp_path / 'script.py'
    script.write_text('from backtesting import Strategy\nclass Strat(Strategy):\n    pass\n')
    assert main(['inspect-script', str(script), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['strategy_classes'][0]['name'] == 'Strat'

    saved = tmp_path / 'report.json'
    expected = tmp_path / 'expected.json'
    saved.write_text(json.dumps(report()))
    expected.write_text(json.dumps({'Return [%]': 4.067, '# Trades': 572}))
    assert main(['check-baseline', str(saved), '--expected', str(expected), '--json']) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['status'] == 'PARTIAL_MATCH'
    assert summary['checked_metrics'] == ['return_pct', 'closed_trades']

    assert main(['check-baseline', str(saved), '--expected', str(expected)]) == 0
    text_output = capsys.readouterr().out
    assert 'PARTIAL_MATCH' in text_output
    assert 'Unchecked metrics: max_drawdown_pct, final_equity' in text_output

    expected.write_text(json.dumps({'Return [%]': 1.0}))
    assert main(['check-baseline', str(saved), '--expected', str(expected), '--json']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'MISMATCH'
