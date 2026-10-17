"""Real native runs retain required features and enforce declared side-input identity."""
import json
from pathlib import Path
import sys

import pytest

from backtest_witness.demos import synthetic_rows


def test_native_frame_retains_extra_columns_without_relabeling_source_times():
    pytest.importorskip('backtesting')
    from backtesting import Strategy
    from backtest_witness.execution import make_backtesting_execution_runner

    class UsesClock(Strategy):
        def init(self):
            assert self.data.Time[0] == '2024-01-01T09:00:00Z'
        def next(self):
            if len(self.data) == 3:
                self.buy(size=2)
            elif len(self.data) == 8:
                self.position.close()

    rows = synthetic_rows()
    for row in rows:
        row['Time'] = '2024-01-01T09:00:00Z'
    run = make_backtesting_execution_runner(UsesClock)
    result = run(rows, {}, 7, {})
    assert len(result['trades']) == 1
    assert result['trades'][0]['size'] == 2


def test_input_checks_happen_before_native_strategy_initialization(tmp_path, monkeypatch):
    pytest.importorskip('backtesting')
    from backtest_witness.execution import resolve_execution_runner
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'needs_state.py').write_text(
        'from pathlib import Path\nfrom backtesting import Strategy\nSPY_OK = None\n'
        'class NeedsState(Strategy):\n'
        '    def init(self):\n        Path("ran-init").write_text("bad")\n'
        '    def next(self):\n        if SPY_OK:\n            self.buy(size=1)\n')
    run = resolve_execution_runner('needs_state:NeedsState', integration={})
    with pytest.raises(ValueError, match='SPY_OK'):
        run.preflight(synthetic_rows())
    assert not (tmp_path / 'ran-init').exists()


def test_companion_input_change_refuses_replay_before_import(tmp_path, monkeypatch):
    from backtest_witness.execution import companion_manifest, resolve_execution_runner
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'spy.csv').write_text('Date,Close\n2024-01-01,100\n')
    manifest = companion_manifest(['spy.csv'])
    assert manifest[0]['path'] == 'spy.csv'
    assert len(manifest[0]['sha256']) == 64
    (tmp_path / 'spy.csv').write_text('Date,Close\n2024-01-01,999\n')
    (tmp_path / 'never_import.py').write_text(
        'from pathlib import Path\nPath("imported").touch()\ndef run(*args): return {}\n')
    with pytest.raises(ValueError, match='[Cc]ompanion'):
        resolve_execution_runner('never_import:run', engine='callback',
                                 integration={'companions': manifest})
    assert not (tmp_path / 'imported').exists()


def test_companion_manifest_rejects_outside_project_without_exporting_paths(tmp_path, monkeypatch):
    from backtest_witness.execution import companion_manifest
    project = tmp_path / 'project'
    project.mkdir()
    outside = tmp_path / 'private.csv'
    outside.write_text('private')
    monkeypatch.chdir(project)
    with pytest.raises(ValueError) as error:
        companion_manifest([str(outside)])
    assert str(tmp_path) not in str(error.value)


def test_callback_rechecks_companions_before_each_invocation(tmp_path, monkeypatch):
    from backtest_witness.execution import companion_manifest, resolve_execution_runner
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'side.csv').write_text('original')
    (tmp_path / 'guarded_callback.py').write_text(
        'from pathlib import Path\ndef run(*args):\n    Path("called").touch()\n    return {}\n')
    run = resolve_execution_runner('guarded_callback:run', engine='callback',
        integration={'companions': companion_manifest(['side.csv'])})
    (tmp_path / 'side.csv').write_text('changed')
    with pytest.raises(ValueError, match='[Cc]ompanion'):
        run(synthetic_rows(), {}, 7, {})
    assert not (tmp_path / 'called').exists()


def test_execution_integration_survives_saved_fixture_replay(tmp_path, monkeypatch):
    pytest.importorskip('backtesting')
    from backtest_witness.execution import companion_manifest, resolve_execution_runner
    from backtest_witness.failure_lab import run_failure_lab
    from backtest_witness.failure_reproduce import (export_failure_reproducer, load_failure_fixture,
        assert_failure_resilience, ResilienceError)

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'policy.csv').write_text('enabled\ntrue\n')
    integration = {'companions': companion_manifest(['policy.csv']),
                   'required_columns': ['Time']}
    rows = synthetic_rows()
    for row in rows:
        row['Time'] = row['timestamp']
    run = resolve_execution_runner('examples.agent_integration.strategy:AgentStrategy', integration=integration)
    report = run_failure_lab(run, rows, scenarios=[{'commission_bps': 100}],
        requirements={'min_return_pct': None, 'max_return_drop_pct': .01, 'min_closed_trades': 1},
        strategy_ref='examples.agent_integration.strategy:AgentStrategy')
    assert report['status'] == 'FAILURE_FOUND'
    export_failure_reproducer(report, tmp_path / 'output', report['strategy_ref'])
    fixture = load_failure_fixture(tmp_path / 'output' / 'failure-fixture.json')
    assert fixture['runner_spec']['integration']['companions'] == integration['companions']
    recreated = resolve_execution_runner(fixture['strategy_ref'], **fixture['runner_spec'])
    with pytest.raises(ResilienceError):
        assert_failure_resilience(recreated, fixture)


def test_prepared_columns_are_checked_after_preparation():
    pytest.importorskip('backtesting')
    from backtesting import Strategy
    from backtest_witness.execution import make_backtesting_execution_runner

    class PreparedFeature(Strategy):
        def init(self):
            pass
        def next(self):
            if self.data.Feature[-1] > 0 and len(self.data) == 3:
                self.buy(size=1)

    def prepare(frame):
        frame['Feature'] = 1
        return frame

    run = make_backtesting_execution_runner(PreparedFeature, prepare=prepare, integration={})
    assert run(synthetic_rows(), {}, 7, {})['open_trades'][0]['size'] == 1


@pytest.mark.parametrize('commission', [.1, .2, [1, .1]])
def test_invalid_native_baseline_commission_is_rejected_at_configuration(commission):
    from backtest_witness.execution import make_backtesting_execution_runner
    with pytest.raises(ValueError, match='commission'):
        make_backtesting_execution_runner(object, engine_settings={'commission': commission})


def test_python_repair_callable_cannot_drop_saved_companion_contract(tmp_path, monkeypatch):
    from backtest_witness.execution import companion_manifest
    from backtest_witness.failure_lab import run_failure_lab
    from backtest_witness.failure_reproduce import (export_failure_reproducer,
        load_failure_fixture, assert_failure_resilience)
    from test_failure_lab import bars, execution
    monkeypatch.chdir(tmp_path)
    side = tmp_path / 'side.csv'
    side.write_text('original')
    def original(rows, config, seed, scenario):
        return execution(rows, config, seed, scenario)
    original.runner_spec = {'engine': 'callback', 'engine_settings': {},
                           'integration': {'companions': companion_manifest(['side.csv'])}}
    report = run_failure_lab(original, bars(), scenarios=[{'commission_bps': 200}],
                             strategy_ref='saved_strategy:run')
    export_failure_reproducer(report, tmp_path / 'output', report['strategy_ref'])
    fixture = load_failure_fixture(tmp_path / 'output' / 'failure-fixture.json')
    side.write_text('changed')
    def repair(*args):
        pytest.fail('Saved companion changes must block arbitrary repair code before it runs')
    with pytest.raises(ValueError, match='[Cc]ompanion'):
        assert_failure_resilience(repair, fixture, config={'repair': True})


def test_cli_companion_change_has_an_actionable_message_before_strategy_import(tmp_path, monkeypatch, capsys):
    from backtest_witness.cli import main
    from backtest_witness.execution import companion_manifest
    from backtest_witness.failure_lab import run_failure_lab
    from backtest_witness.failure_reproduce import export_failure_reproducer
    from test_failure_lab import bars, execution
    monkeypatch.chdir(tmp_path)
    side = tmp_path / 'companion.csv'
    side.write_text('original')
    def run(rows, config, seed, scenario):
        return execution(rows, config, seed, scenario)
    run.runner_spec = {'engine': 'callback', 'engine_settings': {},
                      'integration': {'companions': companion_manifest(['companion.csv'])}}
    report = run_failure_lab(run, bars(), scenarios=[{'commission_bps': 200}],
                             strategy_ref='companion_strategy:run')
    export_failure_reproducer(report, tmp_path / 'output', report['strategy_ref'])
    (tmp_path / 'companion_strategy.py').write_text(
        'from pathlib import Path\nPath("imported").touch()\ndef run(*args): return {}\n')
    side.write_text('changed')
    assert main(['replay-failure', str(tmp_path / 'output' / 'failure-fixture.json')]) == 2
    error = capsys.readouterr().err
    assert 'Companion' in error and 'restore' in error
    assert not (tmp_path / 'imported').exists()
