"""An actual pinned public-code defect, an honest synthetic tape, and saved repair."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

import pytest

ROOT = Path(__file__).resolve().parents[1]


def demo_api():
    # Missing workflow should fail as an assertion before implementation exists.
    assert importlib.util.find_spec('tradeoff.future_demo') is not None, 'Public bug workflow is missing'
    return importlib.import_module('tradeoff.future_demo')


def invoke(*arguments, no_site=False):
    return subprocess.run([sys.executable, *(['-S'] if no_site else []), '-m', 'tradeoff', *arguments],
        cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
        capture_output=True, text=True)


def native_positions(rows, strategy):
    """Independent native observation: do not use Tradeoff's runner or projection."""
    import pandas as pd
    from backtesting import Backtest
    positions = [0] * len(rows)

    class Recording(strategy):
        def next(self):
            super().next()
            positions[len(self.data) - 1] = int(self.position.size)

    frame = pd.DataFrame([{key.title(): row[key] for key in ('open', 'high', 'low', 'close', 'volume')}
                          for row in rows], index=pd.to_datetime([row['timestamp'] for row in rows], utc=True).tz_localize(None))
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Some trades remain open.*')
        Backtest(frame, Recording, cash=100000, commission=.002, exclusive_orders=False,
                 hedging=False, finalize_trades=False).run()
    return positions


def test_public_bug_workflow_verifies_native_witness_and_same_fixture_active_repair(tmp_path, monkeypatch):
    pytest.importorskip('backtesting')
    api = demo_api()
    from tradeoff.cases.riskkit import PROVENANCE, _strategy, fixed_run, original_run
    from tradeoff.reproduce import InvarianceError, assert_future_invariance, load_fixture

    # Historical case pins must not masquerade as this run's installed versions.
    monkeypatch.setitem(PROVENANCE, 'tested_versions', {'pandas': 'historical-case-pin'})
    output = tmp_path / 'bug'
    report, folder = api.run_future_demo(output)
    saved = json.loads((folder / 'report.json').read_text())
    assert report['status'] == saved['status'] == 'FOUND'
    assert report['trace_kind'] == 'observed_position'
    assert 'synthetic' in report['headline'].lower()
    assert report['dataset']['row_count'] == 400
    assert 'synthetic' in report['provenance']['input'].lower()
    from importlib.metadata import version
    assert report['provenance']['tested_versions'] == {
        name: version(name) for name in ('backtesting', 'pandas', 'numpy')}
    assert 'bfill' in report['provenance']['fixed_patch']
    assert 'warmup' in report['provenance']['fixed_patch'].lower()
    witness = report['witness']
    assert witness['cutoff'] == '2024-01-02T20:00:00+00:00'
    assert witness['decision_timestamp'] == '2024-01-02T18:00:00+00:00'
    assert witness['before_decision']['target'] == 29
    assert witness['after_decision']['target'] == 31
    fixture_path = folder / 'reproducer.json'
    fixture_bytes = fixture_path.read_bytes()
    fixture = load_fixture(fixture_path)
    assert len(fixture['original_rows']) == len(fixture['mutated_rows']) == 400
    assert fixture['cutoff'] == witness['cutoff']
    for before, after in zip(fixture['original_rows'], fixture['mutated_rows']):
        assert before['timestamp'] == after['timestamp']
        assert before['available_at'] == after['available_at']
        if before['available_at'] <= fixture['cutoff']:
            assert before == after
    before = native_positions(fixture['original_rows'], _strategy(fixed=False))
    after = native_positions(fixture['mutated_rows'], _strategy(fixed=False))
    assert before[42] == 29 and after[42] == 31
    assert [row['target'] for row in report['baseline']['trace']] == before
    assert [row['target'] for row in witness['mutated_trace']] == after
    with pytest.raises(InvarianceError, match='29 became 31'):
        assert_future_invariance(original_run, fixture)
    assert_future_invariance(fixed_run, fixture)
    assert fixture_path.read_bytes() == fixture_bytes
    assert report['repair_replay']['status'] == 'PASS'
    assert report['repair_replay']['reason']
    assert report['repair_replay']['adapter'] == 'tradeoff.cases.riskkit:fixed_run'
    assert report['original_replay']['status'] == 'DEPENDENCY_REPRODUCED'
    assert report['repair_activity']['nonzero_bars'] == 95
    assert report['repair_activity']['status'] == 'PASS'
    fixed = json.loads((folder / 'fixed' / 'report.json').read_text())
    assert fixed['status'] == 'NO_DEPENDENCY_OBSERVED'
    assert any(row['target'] for row in fixed['baseline']['trace'][100:])
    assert report['workflow_status'] == 'VERIFIED'
    control = json.loads((folder / 'historical-control' / 'report.json').read_text())
    assert control['status'] == 'NO_DEPENDENCY_OBSERVED'
    assert control['dataset']['row_count'] == 2148
    assert 'historical' in control['headline'].lower() and 'GOOG' in control['headline']
    assert report['historical_control']['status'] == control['status']
    assert report['provenance']['source_sha256'] == 'c048814bd21cae26002958c9b769c52ecf89ce052c89a47b18476015b4700d9b'
    for name in ('riskkit_strategy.py', 'riskkit_sizing.py', 'riskkit_LICENSE'):
        assert (folder / 'source' / name).read_bytes() == (ROOT / 'src/tradeoff/cases/sources' / name).read_bytes()
    for relative in ('', 'fixed', 'historical-control'):
        report_folder = folder / relative
        exported = json.loads((report_folder / 'report.json').read_text())
        for entry in exported['provenance']['source_files'].values():
            source_path = report_folder / entry['path']
            assert source_path.is_file()
            assert source_path.resolve().is_relative_to(report_folder.resolve())
            assert hashlib.sha256(source_path.read_bytes()).hexdigest() == entry['sha256']
    assert (folder / 'index.html').is_file()
    assert (folder / 'test_future_invariance.py').is_file()


def test_demo_command_success_is_verified_workflow_not_audit_exit_one(tmp_path):
    pytest.importorskip('backtesting')
    demo_api()
    command = invoke('demo-bug', '--output', str(tmp_path / 'bug'), '--json')
    assert command.returncode == 0, command.stderr
    summary = json.loads(command.stdout)
    assert summary['status'] == 'VERIFIED'
    assert summary['original_status'] == 'FOUND'
    assert summary['repair_replay']['status'] == 'PASS'
    assert summary['repair_activity']['status'] == 'PASS'
    assert summary['historical_control']['status'] == 'NO_DEPENDENCY_OBSERVED'
    assert 'synthetic' in summary['input'].lower()
    assert Path(summary['artifacts']['fixture']).is_file()


def test_occupied_output_fails_before_optional_imports_and_preserves_user_file(tmp_path):
    demo_api()
    output = tmp_path / 'occupied'
    output.mkdir()
    keep = output / 'keep.txt'
    keep.write_text('user content')
    command = invoke('demo-bug', '--output', str(output), '--json', no_site=True)
    assert command.returncode == 2
    summary = json.loads(command.stdout)
    assert summary['phase'] == 'output'
    assert 'new or empty' in summary['error']['message']
    assert keep.read_text() == 'user content'


def test_missing_optional_engine_is_actionable_and_writes_nothing(tmp_path):
    demo_api()
    output = tmp_path / 'bug'
    command = invoke('demo-bug', '--output', str(output), '--json', no_site=True)
    assert command.returncode == 2
    summary = json.loads(command.stdout)
    assert summary['phase'] == 'settings'
    assert "pip install '.[audit]'" in summary['error']['message']
    assert "git+https://github.com/Toomi16011601/tradeoff.git" in summary['error']['message']
    assert not output.exists()


def test_future_demo_and_legacy_alias_import_without_optional_packages():
    demo_api()
    command = subprocess.run([sys.executable, '-S', '-c', '''import sys
import tradeoff.future_demo as current
import backtest_witness.future_demo as old
assert current is old
assert not any(name in sys.modules for name in ('backtesting','pandas','numpy'))
'''], cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True)
    assert command.returncode == 0, command.stderr


def test_invariant_but_inactive_repair_cannot_verify_workflow(tmp_path):
    pytest.importorskip('backtesting')
    api = demo_api()
    from tradeoff.cases.riskkit import rows
    # The shorter existing fixture demonstrates why same-fixture PASS alone is insufficient.
    report, _ = api.run_future_demo(tmp_path / 'short', rows=rows(),
        input_description='Synthetic 160-bar public-case tape; inactive repaired strategy')
    assert report['status'] == 'FOUND'
    assert report['repair_replay']['status'] == 'PASS'
    assert report['repair_activity']['nonzero_bars'] == 0
    assert report['repair_activity']['status'] == 'FAILED'
    assert report['workflow_status'] == 'INCOMPLETE'


def test_supplied_historical_input_without_witness_is_not_verified(tmp_path):
    pytest.importorskip('backtesting')
    api = demo_api()
    from tradeoff.historical_demo import historical_rows
    report, folder = api.run_future_demo(tmp_path / 'history', rows=historical_rows(),
        input_description='Historical GOOG daily sample from Backtesting.py 0.6.6')
    assert report['status'] == 'NO_DEPENDENCY_OBSERVED'
    assert report['workflow_status'] == 'INCOMPLETE'
    assert report['repair_replay']['status'] == 'MISSING'
    assert report['repair_replay']['reason']
    assert not (folder / 'reproducer.json').exists()
