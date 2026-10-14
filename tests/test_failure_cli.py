"""Exercise the developer-facing native failure lab workflows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args, cwd=ROOT):
    return subprocess.run([sys.executable, '-m', 'backtest_witness', *args],
        cwd=cwd, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
        capture_output=True, text=True)


def test_cli_exposes_native_failure_lab_and_separate_replay():
    result = invoke('--help')
    assert result.returncode == 0
    assert 'lab-cases' in result.stdout
    assert 'replay-failure' in result.stdout


def test_failure_lab_rejects_unsupported_engine_without_output(tmp_path):
    destination = tmp_path / 'output'
    result = invoke('lab', '--adapter', 'examples.backtrader_demo:DemoStrategy',
                    '--engine', 'backtrader', '--data', 'missing.json', '--output', str(destination))
    assert result.returncode == 2
    assert not destination.exists()


def test_replay_help_explains_adapter_and_config_overrides():
    result = invoke('replay-failure', '--help')
    assert result.returncode == 0
    assert '--adapter' in result.stdout and '--config' in result.stdout


def test_native_casebook_and_replay_report_policy_failure_exit_codes(tmp_path):
    pytest.importorskip('backtesting')
    scenarios = tmp_path / 'scenarios.json'
    scenarios.write_text(json.dumps([{'commission_bps': 25}, {'delay_bars': 1}]))
    output = tmp_path / 'casebook'
    result = invoke('lab-cases', '--case', 'coinglass', '--variant', 'fixed',
                    '--scenarios', str(scenarios), '--output', str(output), '--json')
    assert result.returncode == 1, result.stderr
    summary = json.loads(result.stdout)
    assert summary['cases'][0]['status'] == 'FAILURE_FOUND'
    fixture = output / 'coinglass-fixed' / 'failure-fixture.json'
    assert fixture.exists()
    replay = invoke('replay-failure', str(fixture))
    assert replay.returncode == 1, replay.stderr
    assert 'FAILURE REPRODUCED' in replay.stdout
    assert (output / 'coinglass-fixed' / 'test_failure_resilience.py').exists()


def test_native_lab_honors_policy_and_writes_replayable_artifacts(tmp_path):
    pytest.importorskip('backtesting')
    requirements = tmp_path / 'requirements.json'
    requirements.write_text(json.dumps({'min_return_pct': None, 'max_return_drop_pct': 0.05,
                                       'min_closed_trades': 1}))
    output = tmp_path / 'lab'
    result = invoke('lab', '--adapter', 'backtest_witness.cases.coinglass:fixed_execution',
                    '--engine', 'callback', '--data', str(ROOT / 'src/backtest_witness/cases/sources/coinglass_rows.json'),
                    '--requirements', str(requirements), '--output', str(output), '--json')
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)['status'] == 'FAILURE_FOUND'
    report = json.loads((output / 'report.json').read_text())
    assert report['baseline']['metrics']['closed_trades'] == 1
    assert report['coverage']['complete']
    assert (output / 'failure-fixture.json').exists()
