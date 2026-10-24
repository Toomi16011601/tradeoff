"""The installed CLI can prove and replay a native failure on public history."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def invoke(*arguments):
    return subprocess.run([sys.executable, '-m', 'tradeoff', *arguments],
        cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
        capture_output=True, text=True)


def test_historical_demo_matches_native_baseline_and_replays_failure(tmp_path):
    pytest.importorskip('backtesting')
    from backtesting import Backtest
    from backtesting.test import GOOG
    from tradeoff.historical_strategy import SmaCross

    output = tmp_path / 'history'
    command = invoke('demo-history', '--output', str(output), '--json')
    assert command.returncode == 1, command.stderr
    summary = json.loads(command.stdout)
    report = json.loads((output / 'report.json').read_text())
    assert summary['status'] == report['status'] == 'FAILURE_FOUND'
    assert summary['coverage']['completed'] == summary['coverage']['total'] == 12
    assert summary['coverage']['complete'] is True
    assert report['dataset']['row_count'] == len(GOOG) == 2148
    assert report['requirements']['min_return_pct'] is None
    assert report['requirements']['max_return_drop_pct'] == 2
    assert report['requirements']['min_closed_trades'] == 1
    assert report['baseline']['result']['engine_version'] == '0.6.6'
    assert report['baseline']['metrics']['return_pct'] == pytest.approx(656.4599, abs=.001)
    assert report['baseline']['metrics']['closed_trades'] == 46
    assert len(report['baseline']['result']['open_trades']) == 1
    assert report['failure']['scenario'] == {'commission_bps': 5, 'spread_bps': 0,
                                             'delay_bars': 0}
    assert report['failure']['metrics']['return_pct'] == pytest.approx(626.2069, abs=.001)

    with pytest.warns(UserWarning, match='Some trades remain open'):
        native = Backtest(GOOG, SmaCross, cash=10000, commission=0, spread=0,
                          margin=1, trade_on_close=False, exclusive_orders=False,
                          hedging=False, finalize_trades=False).run()
    assert report['baseline']['metrics']['final_equity'] == pytest.approx(native['Equity Final [$]'])
    assert report['baseline']['metrics']['closed_trades'] == native['# Trades']
    assert report['failure']['metrics']['return_pct'] < report['baseline']['metrics']['return_pct'] - 2

    fixture = output / 'failure-fixture.json'
    assert (output / 'index.html').is_file()
    assert (output / 'test_failure_resilience.py').is_file()
    assert fixture.is_file()
    assert len(json.loads(fixture.read_text())['rows']) == len(GOOG)
    replay = invoke('replay-failure', str(fixture))
    assert replay.returncode == 1, replay.stderr
    assert 'FAILURE REPRODUCED' in replay.stdout


def test_historical_demo_preserves_occupied_output(tmp_path):
    output = tmp_path / 'history'
    output.mkdir()
    existing = output / 'keep.txt'
    existing.write_text('existing user data')
    command = invoke('demo-history', '--output', str(output), '--json')
    assert command.returncode == 2
    assert json.loads(command.stdout)['phase'] == 'output'
    assert existing.read_text() == 'existing user data'


def test_plain_historical_demo_names_the_saved_stress(tmp_path):
    pytest.importorskip('backtesting')
    output = tmp_path / 'history'
    command = invoke('demo-history', '--output', str(output))
    assert command.returncode == 1, command.stderr
    assert 'Coverage: 12/12' in command.stdout
    assert 'Failing stress: +5 bps commission' in command.stdout
    assert (output / 'index.html').is_file()


def test_historical_demo_explains_missing_optional_engine_before_writing(tmp_path):
    output = tmp_path / 'history'
    command = subprocess.run([sys.executable, '-S', '-m', 'tradeoff', 'demo-history',
                              '--output', str(output), '--json'], cwd=ROOT,
        env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
        capture_output=True, text=True)
    assert command.returncode == 2
    summary = json.loads(command.stdout)
    assert summary['phase'] == 'settings'
    assert "pip install '.[lab]'" in summary['error']['message']
    assert not output.exists()
