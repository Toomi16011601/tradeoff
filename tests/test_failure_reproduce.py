"""Portable policy-regression artifacts, repair overrides and tamper refusal."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_failure_lab import api as lab_api, bars, execution, scenario


def api():
    try:
        return importlib.import_module('backtest_witness.failure_reproduce')
    except ModuleNotFoundError:
        pytest.fail('failure reproducer public API is not implemented')


def exported(tmp_path, requirements=None):
    module = api()
    report = lab_api()(execution, bars(), scenarios=[scenario(200)], requirements=requirements)
    files = module.export_failure_reproducer(report, tmp_path, 'saved_strategy:run')
    fixture = module.load_failure_fixture(tmp_path / files['fixture'])
    return module, fixture, files


def test_saved_failure_and_config_repair_use_unchanged_hashed_fixture(tmp_path):
    module, fixture, files = exported(tmp_path)
    before = deepcopy(fixture)
    with pytest.raises(module.ResilienceError):
        module.assert_failure_resilience(execution, fixture)
    receipt = module.assert_failure_resilience(execution, fixture, config={'repair': True})
    assert receipt['status'] == 'PASS'
    assert receipt['config_overridden'] is True
    assert receipt['baseline']['metrics']['return_pct'] == pytest.approx(10)
    assert fixture == before
    assert files == {'fixture': 'failure-fixture.json', 'test': 'test_failure_resilience.py', 'receipt': 'failure-receipt.json'}
    saved_receipt = json.loads((tmp_path / files['receipt']).read_text())
    assert saved_receipt['runtime']['engine_version'] == '1'
    assert saved_receipt['fixture_hash'] == fixture['fixture_hash']


@pytest.mark.parametrize('field', ['rows', 'config', 'requirements', 'runner_spec', 'scenario', 'settings', 'runtime', 'observations'])
def test_tampered_content_is_rejected_before_runner_invocation(tmp_path, field):
    module, fixture, _ = exported(tmp_path)
    fixture[field] = {'tampered': True}
    with pytest.raises(ValueError, match='hash'):
        module.assert_failure_resilience(execution, fixture)


def test_engine_version_mismatch_refuses_even_when_repair_passes(tmp_path):
    module, fixture, _ = exported(tmp_path)
    def different(rows, config, seed, stress):
        result = execution(rows, {'repair': True}, seed, stress)
        result['engine_version'] = '2'
        return result
    with pytest.raises(ValueError, match='version'):
        module.assert_failure_resilience(different, fixture)


def test_runtime_version_declaration_mismatch_refuses_before_call(tmp_path):
    module, fixture, _ = exported(tmp_path)
    def wrong(*args):
        pytest.fail('declared mismatched runner should not be invoked')
    wrong.adapter_info = {'version': '2'}
    with pytest.raises(ValueError, match='version'):
        module.assert_failure_resilience(wrong, fixture)


def test_relative_replay_repeats_current_baseline_and_disallows_baseline_absolute_failure(tmp_path):
    module, fixture, _ = exported(tmp_path, {'max_return_drop_pct': 5})
    seen = []
    def repair(rows, config, seed, stress):
        seen.append(deepcopy(stress))
        result = execution(rows, {'repair': True}, seed, stress)
        for point in result['equity']: point['equity'] -= 5
        return result
    assert module.assert_failure_resilience(repair, fixture)['status'] == 'PASS'
    assert seen[:2] == [{'commission_bps': 0, 'spread_bps': 0, 'delay_bars': 0}] * 2
    assert seen[2:] == [fixture['scenario']] * 2
    def losing(rows, config, seed, stress):
        result = repair(rows, config, seed, stress)
        for point in result['equity']: point['equity'] -= 10
        return result
    with pytest.raises(module.ResilienceError, match='Baseline'):
        module.assert_failure_resilience(losing, fixture)


def test_replay_rejects_nonrepeatable_terminal_observations(tmp_path):
    module, fixture, _ = exported(tmp_path)
    counter = [0]
    def unstable(rows, config, seed, stress):
        result = execution(rows, {'repair': True}, seed, stress)
        counter[0] += 1
        result['warnings'] = [str(counter[0])]
        return result
    with pytest.raises(ValueError, match='repeat'):
        module.assert_failure_resilience(unstable, fixture)


def test_invalid_config_override_is_refused(tmp_path):
    module, fixture, _ = exported(tmp_path)
    with pytest.raises(ValueError):
        module.assert_failure_resilience(execution, fixture, config={'repair': object()})


def test_generated_pytest_original_failure_then_repaired_pass(tmp_path):
    module, fixture, files = exported(tmp_path)
    strategy = tmp_path / 'saved_strategy.py'
    source = Path(__file__).with_name('test_failure_lab.py').read_text()
    strategy.write_text(source + '\nrun = execution\n')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), str(Path(__file__).resolve().parents[1] / 'src')]))
    command = [sys.executable, '-m', 'pytest', str(tmp_path / files['test']), '-q']
    failure = subprocess.run(command, env=env, capture_output=True, text=True)
    assert failure.returncode == 1 and 'ResilienceError' in failure.stdout
    strategy.write_text(source + '\ndef run(rows, config, seed, scenario):\n    return execution(rows, {"repair": True}, seed, scenario)\n')
    repair = subprocess.run(command, env=env, capture_output=True, text=True)
    assert repair.returncode == 0, repair.stdout + repair.stderr
    assert module.load_failure_fixture(tmp_path / files['fixture']) == fixture


def test_export_refuses_nonfinding_report_and_invalid_reference(tmp_path):
    module = api()
    report = lab_api()(execution, bars(), scenarios=[scenario(5)])
    with pytest.raises(ValueError): module.export_failure_reproducer(report, tmp_path, 'saved_strategy:run')
    report = lab_api()(execution, bars(), scenarios=[scenario(200)])
    with pytest.raises(ValueError): module.export_failure_reproducer(report, tmp_path, 'not importable')


def test_actual_native_fixture_replay_repair_and_noop_guard(tmp_path):
    pytest.importorskip('backtesting')
    from backtest_witness.execution import resolve_execution_runner
    source = '''from backtesting import Strategy
class RoundTrip(Strategy):
    exit_after = 4
    enabled = True
    def init(self):
        pass
    def next(self):
        if self.enabled and len(self.data) == 2:
            self.buy(size=4)
        if len(self.data) == self.exit_after:
            self.position.close()
'''
    (tmp_path / 'native_repair.py').write_text(source)
    sys.path.insert(0, str(tmp_path))
    try:
        run = resolve_execution_runner('native_repair:RoundTrip', engine='backtesting', engine_settings={'cash': 1000})
        rows = bars()
        # An early 2-point gain fails entry+exit 200-bps native fees; a later
        # exit earns 10 points and passes those same fees with a real trade.
        from datetime import datetime, timedelta, timezone
        rows = [dict(timestamp=(datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat(),
                     symbol='SYN', open=p, high=p+1, low=p-1, close=p, volume=100)
                for i, p in enumerate([100, 100, 100, 101, 102, 105, 110, 110, 110])]
        report = lab_api()(run, rows, scenarios=[scenario(200)], requirements={'min_closed_trades': 1}, strategy_ref='native_repair:RoundTrip')
        assert report['status'] == 'FAILURE_FOUND'
        assert report['baseline']['metrics']['closed_trades'] == 1
        assert report['baseline']['metrics']['return_pct'] == pytest.approx(.8)
        module = api()
        files = module.export_failure_reproducer(report, tmp_path, 'native_repair:RoundTrip')
        fixture = module.load_failure_fixture(tmp_path / files['fixture'])
        with pytest.raises(module.ResilienceError): module.assert_failure_resilience(run, fixture)
        passed = module.assert_failure_resilience(run, fixture, config={'exit_after': 6})
        assert passed['stress']['metrics']['closed_trades'] == 1
        assert passed['stress']['metrics']['return_pct'] == pytest.approx(2.32)
        with pytest.raises(module.ResilienceError, match='Closed trades'):
            module.assert_failure_resilience(run, fixture, config={'enabled': False})
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), str(Path(__file__).resolve().parents[1] / 'src')]))
        command = [sys.executable, '-m', 'pytest', str(tmp_path / files['test']), '-q']
        original = subprocess.run(command, env=env, capture_output=True, text=True)
        assert original.returncode == 1 and 'ResilienceError' in original.stdout
        (tmp_path / 'native_repair.py').write_text(source.replace('exit_after = 4', 'exit_after = 6') + '\n# Repaired later close; no fixture bytes changed.\n')
        repaired = subprocess.run(command, env=env, capture_output=True, text=True)
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        assert module.load_failure_fixture(tmp_path / files['fixture']) == fixture
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop('native_repair', None)


def test_rehashed_invalid_settings_are_value_error_not_runtime_error(tmp_path):
    module, fixture, _ = exported(tmp_path)
    from backtest_witness.validation import canonical_hash
    fixture['settings'] = []
    fixture['content_hashes']['settings'] = canonical_hash([])
    fixture.pop('fixture_hash')
    fixture['fixture_hash'] = canonical_hash(fixture)
    with pytest.raises(ValueError, match='settings'):
        module.assert_failure_resilience(execution, fixture)


def test_relative_repair_compares_new_baseline_instead_of_saved_metrics(tmp_path):
    module, fixture, _ = exported(tmp_path, {'min_return_pct': None, 'max_return_drop_pct': 5})
    def better_baseline(rows, config, seed, stress):
        result = execution(rows, {'repair': True}, seed, stress)
        # Saved baseline returns 10%. Current baseline returns 20% and stress
        # still returns 10%; a saved-baseline comparison would falsely pass.
        if stress['commission_bps'] == 0:
            for point in result['equity']: point['equity'] += 10
        return result
    with pytest.raises(module.ResilienceError, match='drop'):
        module.assert_failure_resilience(better_baseline, fixture)


def test_repair_with_fabricated_closed_trade_is_invalid_not_scoped_pass(tmp_path):
    module, fixture, _ = exported(tmp_path, {'min_closed_trades': 1})
    def fabricated(rows, config, seed, stress):
        result = execution(rows, {'repair': True}, seed, stress)
        result['trades'] = [{}]
        return result
    with pytest.raises(ValueError, match='trade'):
        module.assert_failure_resilience(fabricated, fixture)


@pytest.mark.parametrize('changed_settings', [
    {'cash': 1000000}, {'cash': 1000, 'commission': .001},
    {'cash': 1000, 'spread': .001}, {'cash': 1000, 'margin': .5},
    {'cash': 1000, 'trade_on_close': True}, {'cash': 1000, 'exclusive_orders': True},
])
def test_native_repair_cannot_change_saved_engine_settings_before_execution(tmp_path, changed_settings):
    pytest.importorskip('backtesting')
    from backtesting import Strategy
    from backtest_witness.execution import make_backtesting_execution_runner
    calls = []

    class RoundTrip(Strategy):
        def init(self):
            pass
        def next(self):
            calls.append(len(self.data))
            if len(self.data) == 2:
                self.buy(size=4)
            if len(self.data) == 3:
                self.position.close()

    original = make_backtesting_execution_runner(RoundTrip, engine_settings={'cash': 1000})
    report = lab_api()(original, bars(), scenarios=[scenario(200)],
                       requirements={'min_return_pct': None, 'max_return_drop_pct': .1,
                                     'min_closed_trades': 1})
    assert report['status'] == 'FAILURE_FOUND'
    module = api()
    module.export_failure_reproducer(report, tmp_path, 'saved_strategy:RoundTrip')
    fixture = module.load_failure_fixture(tmp_path / 'failure-fixture.json')
    altered = make_backtesting_execution_runner(RoundTrip, engine_settings=changed_settings)
    calls.clear()
    with pytest.raises(ValueError, match='runner_spec'):
        module.assert_failure_resilience(altered, fixture)
    assert calls == []


@pytest.mark.parametrize('declare_spec', [False, True])
@pytest.mark.parametrize('change_on', ['both', 'baseline', 'stress'])
def test_callback_repair_cannot_dilute_saved_policy_by_changing_initial_cash(tmp_path, declare_spec, change_on):
    module, fixture, _ = exported(tmp_path, {'min_return_pct': None, 'max_return_drop_pct': 5})
    def recapitalized(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        if change_on == 'both' or (change_on == 'baseline') == (stress['commission_bps'] == 0):
            result['initial_cash'] = 1000000
            result['effective_settings']['cash'] = 1000000
            for point in result['equity']:
                point['equity'] += 999900
        return result
    if declare_spec:
        recapitalized.runner_spec = deepcopy(execution.runner_spec)
    with pytest.raises(ValueError, match='initial_cash'):
        module.assert_failure_resilience(recapitalized, fixture)


@pytest.mark.parametrize('declare_spec', [False, True])
def test_callback_config_repair_can_update_metadata_with_saved_cash(tmp_path, declare_spec):
    module, fixture, _ = exported(tmp_path)
    before = deepcopy(fixture)
    def repaired(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        result['effective_settings']['strategy_source_hash'] = 'repaired-source'
        return result
    if declare_spec:
        repaired.runner_spec = deepcopy(execution.runner_spec)
    receipt = module.assert_failure_resilience(repaired, fixture, config={'repair': True})
    assert receipt['status'] == 'PASS'
    assert receipt['baseline']['result']['initial_cash'] == 100
    assert receipt['stress']['result']['initial_cash'] == 100
    assert fixture == before
