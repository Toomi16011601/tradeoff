"""New-user CLI checks use real projects, files and native execution."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_failure_lab import bars

ROOT = Path(__file__).resolve().parents[1]


def invoke(folder, *args):
    return subprocess.run([sys.executable, '-m', 'tradeoff', *map(str, args)],
        cwd=folder, env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT / 'src'), str(folder)])},
        capture_output=True, text=True)


def input_file(folder):
    data = folder / 'bars.json'
    data.write_text(json.dumps(bars()))
    return data


def importing_project(folder):
    (folder / 'danger.py').write_text(
        'from pathlib import Path\n'
        'Path("imported.txt").write_text("import ran")\n'
        'class Failure(RuntimeError): code = "SYNTHETIC_PRIVATE_CODE"\n'
        'raise Failure("SYNTHETIC_PRIVATE_IMPORT_DETAIL")\n')


def test_nonempty_output_is_rejected_before_strategy_import(tmp_path):
    # Late output validation used to spend all native runs before refusing the directory.
    importing_project(tmp_path)
    data = input_file(tmp_path)
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'keep.txt').write_text('keep')
    result = invoke(tmp_path, 'lab', '--adapter', 'danger:Strategy', '--data', data,
                    '--output', output, '--json')
    assert result.returncode == 2
    assert not (tmp_path / 'imported.txt').exists()
    summary = json.loads(result.stdout)
    assert summary['status'] == 'ERROR'
    assert summary['phase'] == 'output'
    assert (output / 'keep.txt').read_text() == 'keep'


@pytest.mark.parametrize('kind', ['requirements', 'scenarios'])
def test_invalid_policy_inputs_are_rejected_before_import(tmp_path, kind):
    importing_project(tmp_path)
    data = input_file(tmp_path)
    invalid = tmp_path / f'{kind}.json'
    invalid.write_text(json.dumps({'min_closed_trades': -1} if kind == 'requirements'
                                  else [{'delay_bars': -1}]))
    result = invoke(tmp_path, 'lab', '--adapter', 'danger:Strategy', '--data', data,
                    f'--{kind}', invalid, '--output', tmp_path / 'output', '--json')
    assert result.returncode == 2
    assert not (tmp_path / 'imported.txt').exists()
    assert json.loads(result.stdout)['phase'] == kind
    assert not (tmp_path / 'output').exists()


def test_raw_csv_flags_preserve_features_and_reach_native_engine(tmp_path):
    pytest.importorskip('backtesting')
    data = tmp_path / 'bars.csv'
    with data.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'model score'])
        for day in (2, 3, 6, 7, 8, 9):
            writer.writerow([f'2025-01-{day:02}', 100, 101, 99, 100, 1000, day])
    (tmp_path / 'strategy.py').write_text('from backtesting import Strategy\n'
        'class Existing(Strategy):\n'
        '    def init(self): pass\n'
        '    def next(self): self.observed = self.data.Feature[-1]\n')
    scenarios = tmp_path / 'scenarios.json'
    scenarios.write_text('[{"delay_bars":1}]')
    output = tmp_path / 'output'
    result = invoke(tmp_path, 'lab', '--adapter', 'strategy:Existing', '--data', data,
        '--symbol', 'AAPL', '--timezone', 'America/New_York', '--session-close', '16:00',
        '--column-map', '{"Feature":"model score"}', '--require-column', 'Feature',
        '--scenarios', scenarios, '--output', output, '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    report = json.loads((output / 'report.json').read_text())
    assert report['baseline']['result']['equity'][0]['timestamp'] == '2025-01-02T21:00:00+00:00'
    assert 'Feature' in summary['input_checks']['required_columns']
    assert 'strategy_source' in report['provenance']
    assert summary['input_checks']['data_warnings']


def test_json_input_error_is_structured_and_keeps_private_path_out(tmp_path):
    data = tmp_path / 'bad.json'
    data.write_text('{"private-person@example.invalid":')
    result = invoke(tmp_path, 'lab', '--adapter', 'not_imported:Strategy', '--data', data,
                    '--output', tmp_path / 'output', '--json')
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary['status'] == 'ERROR'
    assert summary['error']['code'] == 'INVALID_JSON'
    assert summary['phase'] == 'data'
    assert 'private-person' not in result.stdout + result.stderr
    assert 'Traceback' not in result.stdout + result.stderr
    assert not (tmp_path / 'output').exists()


def test_json_argument_error_still_returns_machine_readable_response(tmp_path):
    result = invoke(tmp_path, 'lab', '--adapter', 'missing:Strategy', '--engine', 'unknown', '--json')
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary['status'] == 'ERROR'
    assert summary['phase'] == 'arguments'
    assert summary['error']['code'] == 'INVALID_ARGUMENTS'


def test_private_callback_diagnostics_are_opt_in_and_separate_from_reports(tmp_path):
    data = input_file(tmp_path)
    (tmp_path / 'broken.py').write_text('def run(*args):\n'
        '    try: raise KeyError("SYNTHETIC_PRIVATE_COLUMN_DETAIL")\n'
        '    except KeyError as exc: raise RuntimeError("SYNTHETIC_PRIVATE_STRATEGY_DETAIL") from exc\n')
    output = tmp_path / 'output'
    private = tmp_path / 'local-debug.txt'
    result = invoke(tmp_path, 'lab', '--adapter', 'broken:run', '--engine', 'callback',
        '--data', data, '--output', output, '--json', '--diagnostics', private)
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary['status'] == 'INCONCLUSIVE'
    assert 'diagnostics' in summary['hint']
    assert 'SYNTHETIC_PRIVATE_COLUMN_DETAIL' in private.read_text()
    assert 'SYNTHETIC_PRIVATE_STRATEGY_DETAIL' in private.read_text()
    for path in output.iterdir():
        if path.is_file():
            assert 'SYNTHETIC_PRIVATE' not in path.read_text()
    assert 'SYNTHETIC_PRIVATE' not in result.stdout + result.stderr


@pytest.mark.parametrize('location', ['same', 'nested'])
def test_diagnostics_inside_output_is_rejected_before_import(tmp_path, location):
    importing_project(tmp_path)
    output = tmp_path / 'output'
    private = output if location == 'same' else output / 'debug.txt'
    result = invoke(tmp_path, 'lab', '--adapter', 'danger:Strategy', '--data', input_file(tmp_path),
                    '--output', output, '--diagnostics', private, '--json')
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary['error']['code'] == 'DIAGNOSTICS_LOCATION'
    assert not (tmp_path / 'imported.txt').exists()
    assert not output.exists()


def test_arbitrary_import_error_is_redacted_but_local_diagnostics_retains_it(tmp_path):
    importing_project(tmp_path)
    private = tmp_path / 'private.txt'
    result = invoke(tmp_path, 'lab', '--adapter', 'danger:Strategy', '--data', input_file(tmp_path),
                    '--output', tmp_path / 'output', '--diagnostics', private, '--json')
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary['phase'] == 'strategy_import'
    assert summary['error']['code'] == 'EXECUTION_ERROR'
    assert 'SYNTHETIC_PRIVATE_IMPORT_DETAIL' not in result.stdout + result.stderr
    assert 'SYNTHETIC_PRIVATE_IMPORT_DETAIL' in private.read_text()


@pytest.mark.parametrize('engine', ['backtesting', 'callback'])
def test_unsupported_engine_setting_is_actionable_before_strategy_import(tmp_path, engine):
    # Native option validation must not wait until after arbitrary project imports.
    importing_project(tmp_path)
    result = invoke(tmp_path, 'lab', '--adapter', 'danger:Strategy', '--engine', engine,
                    '--engine-settings', '{"finalize_trades":true}', '--data', input_file(tmp_path),
                    '--output', tmp_path / 'output', '--json')
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary['phase'] == 'settings'
    assert 'finalize_trades' in summary['error']['message']
    assert not (tmp_path / 'imported.txt').exists()
    assert not (tmp_path / 'output').exists()


def test_reproduce_import_valueerror_cannot_echo_arbitrary_private_text(tmp_path):
    # Dispatch must not mistake an unmarked strategy-import error for trusted input validation.
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer
    from test_audit import future_last
    from test_validation import tape

    report = audit(future_last, tape(), min_history=1)
    fixture_folder = tmp_path / 'saved'
    export_reproducer(report, fixture_folder, 'danger:run')
    (tmp_path / 'danger.py').write_text('raise ValueError("SYNTHETIC_PRIVATE_IMPORT_DETAIL")\n')
    result = invoke(tmp_path, 'reproduce', fixture_folder / 'reproducer.json')
    assert result.returncode == 2
    assert 'SYNTHETIC_PRIVATE_IMPORT_DETAIL' not in result.stdout + result.stderr


@pytest.mark.parametrize('command', ['reproduce', 'replay-failure'])
def test_replay_diagnostics_cannot_enter_saved_portable_artifacts(tmp_path, command):
    # Replays have a fixture directory rather than --output, but need the same boundary.
    saved = tmp_path / 'saved'
    saved.mkdir()
    fixture = saved / 'fixture.json'
    fixture.write_text('{}')
    private = saved / 'private-debug.txt'
    result = invoke(tmp_path, command, fixture, '--diagnostics', private)
    assert result.returncode == 2
    assert 'outside' in result.stderr
    assert not private.exists()
