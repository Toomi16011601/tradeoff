"""Exercise the developer-facing native failure lab workflows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args, cwd=ROOT):
    return subprocess.run([sys.executable, '-m', 'tradeoff', *args],
        cwd=cwd, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
        capture_output=True, text=True)


def test_cli_exposes_native_failure_lab_and_separate_replay():
    result = invoke('--help')
    assert result.returncode == 0
    assert 'lab-cases' in result.stdout
    assert 'replay-failure' in result.stdout
    assert 'init-requirements' in result.stdout


def test_init_requirements_writes_explicit_relative_policy_without_default_profit_floor(tmp_path):
    destination = tmp_path / 'requirements.json'
    result = invoke('init-requirements', '--max-return-drop-pct', '2',
                    '--min-closed-trades', '1', '--output', str(destination), '--json')
    assert result.returncode == 0, result.stderr
    assert json.loads(destination.read_text()) == {
        'min_return_pct': None, 'max_drawdown_pct': None,
        'max_return_drop_pct': 2, 'min_closed_trades': 1,
    }
    assert json.loads(result.stdout)['requirements'] == str(destination)


def test_init_requirements_requires_a_meaningful_threshold_and_preserves_existing_file(tmp_path):
    destination = tmp_path / 'requirements.json'
    blank = invoke('init-requirements', '--output', str(destination), '--json')
    assert blank.returncode == 2
    assert json.loads(blank.stdout)['status'] == 'ERROR'
    assert not destination.exists()

    destination.write_text('{"personal": "keep me"}')
    occupied = invoke('init-requirements', '--max-return-drop-pct', '2',
                      '--output', str(destination), '--json')
    assert occupied.returncode == 2
    assert destination.read_text() == '{"personal": "keep me"}'


def test_init_requirements_validates_numeric_threshold_before_writing(tmp_path):
    destination = tmp_path / 'requirements.json'
    result = invoke('init-requirements', '--max-return-drop-pct', '-1',
                    '--output', str(destination), '--json')
    assert result.returncode == 2
    assert json.loads(result.stdout)['phase'] == 'requirements'
    assert not destination.exists()


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
    result = invoke('lab', '--adapter', 'tradeoff.cases.coinglass:fixed_execution',
                    '--engine', 'callback', '--data', str(ROOT / 'src/tradeoff/cases/sources/coinglass_rows.json'),
                    '--requirements', str(requirements), '--output', str(output), '--json')
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)['status'] == 'FAILURE_FOUND'
    report = json.loads((output / 'report.json').read_text())
    assert report['baseline']['metrics']['closed_trades'] == 1
    assert report['coverage']['complete']
    assert (output / 'failure-fixture.json').exists()


def test_native_lab_summary_exposes_coverage_and_unbounded_deterioration(tmp_path):
    pytest.importorskip('backtesting')
    output = tmp_path / 'lab'
    result = invoke('lab', '--adapter', 'tradeoff.cases.coinglass:fixed_execution',
                    '--engine', 'callback', '--data', str(ROOT / 'src/tradeoff/cases/sources/coinglass_rows.json'),
                    '--output', str(output), '--json')
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary['status'] == 'NO_FAILURE_OBSERVED'
    assert summary['coverage'] == {'completed': 12, 'total': 12, 'complete': True}
    assert summary['requirements']['max_return_drop_pct'] is None
    assert 'substantial deterioration can still pass' in summary['interpretation']


def test_inconclusive_summary_does_not_claim_complete_scenario_coverage_is_incomplete(tmp_path, capsys):
    from tradeoff.failure_cli import _announce

    report = {'status': 'INCONCLUSIVE', 'report_id': 'example',
              'headline': 'Final repeated verification changed',
              'requirements': {'max_return_drop_pct': 2},
              'coverage': {'completed': 1, 'total': 1, 'complete': True}}
    _announce(report, tmp_path, as_json=True)
    summary = json.loads(capsys.readouterr().out)
    assert summary['coverage'] == {'completed': 1, 'total': 1, 'complete': True}
    assert summary['interpretation'] == 'Evidence is inconclusive; inspect the report reason and coverage.'


def test_native_lab_explains_baseline_failed_without_stress_coverage(tmp_path):
    pytest.importorskip('backtesting')
    requirements = tmp_path / 'requirements.json'
    requirements.write_text(json.dumps({'min_return_pct': 1000}))
    output = tmp_path / 'lab'
    result = invoke('lab', '--adapter', 'tradeoff.cases.coinglass:fixed_execution',
                    '--engine', 'callback', '--data', str(ROOT / 'src/tradeoff/cases/sources/coinglass_rows.json'),
                    '--requirements', str(requirements), '--output', str(output))
    assert result.returncode == 1, result.stderr
    assert 'Coverage: 0/12' in result.stdout
    assert 'Stress scenarios were not run' in result.stdout
