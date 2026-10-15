"""Run the checkout example through the real optional native engine and replay."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def example():
    try:
        return importlib.import_module('examples.agent_integration')
    except ModuleNotFoundError:
        pytest.fail('The runnable agent integration example is missing')


def native():
    pytest.importorskip('backtesting')
    pytest.importorskip('pandas')


def invoke(module, *arguments):
    return subprocess.run([sys.executable, '-m', module, *arguments], cwd=ROOT,
        env={**os.environ, 'PYTHONPATH': os.pathsep.join((str(ROOT / 'src'), str(ROOT)))},
        capture_output=True, text=True)


def test_agent_decides_from_a_visible_prefix_and_current_position():
    example()
    from examples.agent_integration.agent import decide

    assert decide((100, 100), 0) == 'hold'
    assert decide((100, 100, 101), 0) == 'buy'
    assert decide((100, 100, 101), 30) == 'hold'
    assert decide((110, 108, 106), 30) == 'close'
    assert decide((110, 108, 106), 0) == 'hold'
    assert decide((100, 100, 100), 0) == 'hold'


def test_strategy_calls_agent_with_only_current_native_history(monkeypatch):
    native()
    module = example()
    from examples.agent_integration import strategy
    from backtest_witness.execution import make_backtesting_execution_runner

    observed = []
    real_decide = strategy.decide

    def observe(history, position, *, lookback):
        observed.append((history, position))
        return real_decide(history, position, lookback=lookback)

    monkeypatch.setattr(strategy, 'decide', observe)
    rows = module.synthetic_rows()
    result = make_backtesting_execution_runner(strategy.AgentStrategy)(rows, {}, 7, {})
    prices = tuple(row['close'] for row in rows)
    assert observed
    assert observed[0] == ((100.0, 100.0), 0)
    assert all(history == prices[:len(history)] for history, _ in observed)
    assert result['engine'] == 'backtesting'
    assert result['engine_version'] == '0.6.6'
    assert len(result['trades']) == 1
    trade = result['trades'][0]
    assert (trade['entry_bar'], trade['exit_bar'], trade['size']) == (3, 10, 30)
    assert (trade['entry_price'], trade['exit_price'], trade['pnl']) == (101, 106, 150)


def test_pending_delayed_orders_do_not_duplicate_agent_entries_or_closes():
    native()
    module = example()
    from examples.agent_integration.strategy import AgentStrategy
    from backtest_witness.execution import make_backtesting_execution_runner

    result = make_backtesting_execution_runner(AgentStrategy)(
        module.synthetic_rows(), {}, 7, {'delay_bars': 2})
    assert len(result['trades']) == 1
    assert result['trades'][0]['size'] == 30
    assert (result['trades'][0]['entry_bar'], result['trades'][0]['exit_bar']) == (5, 12)
    assert result['open_trades'] == []
    assert result['pending_orders'] == []


@pytest.mark.parametrize('invalid', ['BUY', None])
def test_invalid_agent_action_is_reported_as_unavailable(tmp_path, monkeypatch, invalid):
    native()
    module = example()
    from examples.agent_integration import strategy

    monkeypatch.setattr(strategy, 'decide', lambda *args, **kwargs: invalid)
    report = module.run_example(tmp_path / 'output')
    assert report['status'] == 'INCONCLUSIVE'
    assert report['baseline']['status'] == 'UNAVAILABLE'
    assert 'Agent must return buy, close or hold' in report['baseline']['reason']
    assert report['baseline']['metrics'] is None
    assert report['failure'] is None


def test_default_agent_example_finds_a_native_policy_failure(tmp_path):
    native()
    report = example().run_example(tmp_path / 'output')
    assert report['status'] == 'FAILURE_FOUND'
    assert report['baseline']['metrics']['closed_trades'] == 1
    assert report['baseline']['metrics']['return_pct'] == pytest.approx(1.5)
    assert report['requirements']['min_return_pct'] is None
    assert report['requirements']['min_closed_trades'] == 1
    assert report['requirements']['max_return_drop_pct'] == 0.5
    assert report['coverage']['complete']
    assert len(report['scenarios']) == 12
    assert report['failure']['metrics']['closed_trades'] >= 1
    assert report['baseline']['metrics']['return_pct'] - report['failure']['metrics']['return_pct'] > 0.5
    assert report['failure']['result']['engine'] == 'backtesting'


def test_json_command_exports_real_artifacts_and_failure_exit(tmp_path):
    native()
    example()
    output = tmp_path / 'output'
    command = invoke('examples.agent_integration', '--output', str(output), '--json')
    assert command.returncode == 1, command.stderr
    summary = json.loads(command.stdout)
    report = json.loads((output / 'report.json').read_text())
    assert summary['status'] == report['status'] == 'FAILURE_FOUND'
    assert summary['baseline_metrics'] == report['baseline']['metrics']
    assert summary['stress_metrics'] == report['failure']['metrics']
    assert summary['failed_scenario'] == report['failure']['scenario']
    assert set(summary['artifacts']) == {'json', 'html', 'fixture', 'test', 'receipt'}
    assert all(Path(path).is_file() for path in summary['artifacts'].values())
    assert summary['requirements'] == report['requirements']
    assert summary['coverage'] == report['coverage']


def test_saved_agent_fixture_replays_in_cli_and_generated_pytest(tmp_path):
    native()
    module = example()
    output = tmp_path / 'output'
    module.run_example(output)
    fixture_path = output / 'failure-fixture.json'
    fixture_text = fixture_path.read_text()
    fixture = json.loads(fixture_text)
    assert fixture['strategy_ref'] == 'examples.agent_integration.strategy:AgentStrategy'
    assert str(ROOT) not in fixture_text
    original_rows = module.synthetic_rows()
    assert len(fixture['rows']) == len(original_rows) == 17
    for saved, original in zip(fixture['rows'], original_rows):
        assert original.items() <= saved.items()
        assert saved['available_at'] == saved['timestamp']
    replay = invoke('backtest_witness', 'replay-failure', str(fixture_path))
    assert replay.returncode == 1, replay.stderr
    assert 'FAILURE REPRODUCED' in replay.stdout
    generated = invoke('pytest', '-q', str(output / 'test_failure_resilience.py'))
    assert generated.returncode == 1, generated.stdout + generated.stderr
    assert 'ResilienceError' in generated.stdout
    assert '1 failed' in generated.stdout
    assert 'ImportError' not in generated.stdout
    assert fixture_path.read_text() == fixture_text


def test_config_override_can_replay_a_smaller_active_agent_without_changing_fixture(tmp_path):
    native()
    module = example()
    from backtest_witness.execution import resolve_execution_runner
    from backtest_witness.failure_reproduce import assert_failure_resilience, load_failure_fixture

    output = tmp_path / 'output'
    module.run_example(output)
    fixture_path = output / 'failure-fixture.json'
    before = fixture_path.read_bytes()
    fixture = load_failure_fixture(fixture_path)
    runner = resolve_execution_runner(fixture['strategy_ref'], **fixture['runner_spec'])
    repaired = assert_failure_resilience(runner, fixture, config={'units': 1, 'lookback': 3})
    assert repaired['status'] == 'PASS'
    assert repaired['config_overridden']
    assert repaired['baseline']['metrics']['closed_trades'] == 1
    assert fixture_path.read_bytes() == before


def test_nonempty_output_is_rejected_before_strategy_execution(tmp_path, monkeypatch):
    native()
    module = example()
    from examples.agent_integration.strategy import AgentStrategy

    output = tmp_path / 'output'
    output.mkdir()
    kept = output / 'keep.txt'
    kept.write_text('previous evidence')

    def must_not_run(self):
        pytest.fail('Agent executed before output directory validation')

    monkeypatch.setattr(AgentStrategy, 'init', must_not_run)
    with pytest.raises(ValueError, match='new or empty directory'):
        module.run_example(output)
    assert list(output.iterdir()) == [kept]
    assert kept.read_text() == 'previous evidence'
    command = invoke('examples.agent_integration', '--output', str(output), '--json')
    assert command.returncode == 2
    assert json.loads(command.stdout)['status'] == 'ERROR'
    assert list(output.iterdir()) == [kept]
    assert kept.read_text() == 'previous evidence'
