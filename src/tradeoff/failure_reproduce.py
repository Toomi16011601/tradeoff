"""Portable, content-bound execution failures and scoped repair assertions."""
from copy import deepcopy
from .privacy import callback_error, reject_sensitive_data
import json
from pathlib import Path
import platform
import re

from . import __version__
from .failure_lab import (SCHEMA_VERSION as LAB_SCHEMA, ZERO_SCENARIO, execution_metrics,
                          requirement_violations, validate_execution_result,
                          validate_requirements, validate_runner_spec, validate_scenario)
from .validation import canonical_hash, validate_config, validate_rows

FIXTURE_SCHEMA = 'backtest-witness.failure-fixture.v1'
_HASH_FIELDS = ('rows', 'config', 'seed', 'settings', 'runner_spec', 'baseline', 'scenario',
                'requirements', 'runtime', 'observations')


class ResilienceError(AssertionError):
    """Repeated comparable executions breach the saved requirements."""


def _reference(value):
    reject_sensitive_data(value)
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', value) is None:
        raise ValueError('strategy_ref must be an importable module:callable reference')
    return value


def _validated_fixture(value):
    data = validate_config(value)
    if data.get('schema_version') != FIXTURE_SCHEMA:
        raise ValueError('Unsupported failure fixture schema')
    claimed = data.pop('fixture_hash', None)
    if claimed != canonical_hash(data):
        raise ValueError('Fixture hash mismatch: failure fixture content changed')
    data['fixture_hash'] = claimed
    hashes = data.get('content_hashes')
    if not isinstance(hashes, dict):
        raise ValueError('Fixture content hashes are missing')
    for field in _HASH_FIELDS:
        if field not in data or hashes.get(field) != canonical_hash(data[field]):
            raise ValueError(f'Fixture content hash mismatch for {field}')
    _reference(data.get('strategy_ref'))
    rows = validate_rows(data['rows'])
    validate_config(data['config'])
    validate_runner_spec(data['runner_spec'])
    requirements = validate_requirements(data['requirements'])
    if not isinstance(data['settings'], dict):
        raise ValueError('Fixture settings must be a JSON object')
    settings = validate_config(data['settings'])
    if type(data['seed']) is not int or type(settings.get('seed')) is not int or settings.get('seed') != data['seed']:
        raise ValueError('Fixture seed must be an integer matching saved settings')
    if validate_scenario(data['baseline']) != ZERO_SCENARIO:
        raise ValueError('Fixture baseline must have zero additional stress')
    stress = validate_scenario(data['scenario'])
    runtime = validate_config(data['runtime'])
    if not isinstance(runtime.get('engine'), str) or not isinstance(runtime.get('engine_version'), str):
        raise ValueError('Fixture runtime must record engine and engine_version')
    observations = validate_config(data['observations'])
    baseline = validate_execution_result(observations.get('baseline'), rows, ZERO_SCENARIO)
    stressed = validate_execution_result(observations.get('stress'), rows, stress)
    _comparable(baseline, stressed)
    for result in (baseline, stressed):
        _runtime_matches(result, runtime)
    baseline_metrics = execution_metrics(baseline)
    if requirement_violations(baseline_metrics, requirements):
        raise ValueError('Fixture baseline already breaches absolute requirements')
    if not requirement_violations(execution_metrics(stressed), requirements, baseline_metrics):
        raise ValueError('Fixture must record an observed stress policy failure')
    return data


def _runtime_matches(result, runtime):
    if result['engine'] != runtime['engine'] or result['engine_version'] != runtime['engine_version']:
        raise ValueError(f"Engine/version mismatch: fixture {runtime['engine']} {runtime['engine_version']}, current {result['engine']} {result['engine_version']}; comparison refused")


def _comparable(baseline, stress):
    for field in ('engine', 'engine_version', 'initial_cash'):
        if baseline[field] != stress[field]:
            raise ValueError(f'Baseline/stress {field} mismatch; comparison refused')


def load_failure_fixture(path):
    """Read a fixture without importing its strategy or optional engine."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Cannot read failure fixture: {exc}') from exc
    return _validated_fixture(raw)


def assert_failure_resilience(run, fixture, *, config=None):
    """Repeat current baseline and stress, then apply the unchanged policy.

    Saved observations describe the defect; repairs need not reproduce those
    hashes. Overrides are explicit JSON configuration and never alter the saved
    hashes. The saved runner specification and starting cash preserve the same
    engine environment; strategy source and configuration repairs remain allowed.
    Relative deterioration always uses this runner's current baseline.
    """
    data = _validated_fixture(fixture)
    if not callable(run):
        raise ValueError('run must be callable')
    options = validate_config(data['config'] if config is None else config)
    saved_spec = validate_runner_spec(data['runner_spec'])
    saved_inputs = saved_spec.get('integration')
    if saved_inputs is not None:
        from .execution import _check_companions, validate_integration
        saved_inputs = validate_integration(saved_inputs)
        _check_companions(saved_inputs)
    current_spec = validate_runner_spec(getattr(run, 'runner_spec',
                                               {'engine': 'callback', 'engine_settings': {}}))
    if current_spec != saved_spec:
        raise ValueError('Execution runner_spec differs from saved simulation; comparison refused before execution')
    runtime = data['runtime']
    declared = getattr(run, 'adapter_info', {})
    if isinstance(declared, dict) and declared.get('version') is not None and declared['version'] != runtime['engine_version']:
        raise ValueError('Declared runner engine version mismatch; comparison refused before execution')
    rows = validate_rows(data['rows'])

    def repeated(stress, saved):
        results = []
        try:
            for _ in range(2):
                if saved_inputs is not None:
                    _check_companions(saved_inputs)
                try:
                    output = run(deepcopy(rows), deepcopy(options), data['seed'], deepcopy(stress))
                except Exception as exc:
                    raise ValueError('Failure replay: ' + callback_error(exc)) from None
                result = validate_execution_result(output, rows, stress)
                _runtime_matches(result, runtime)
                if result['initial_cash'] != saved['initial_cash']:
                    raise ValueError('Execution initial_cash differs from saved simulation; comparison refused')
                results.append(result)
        except Exception as exc:
            raise ValueError(f'Failure replay is not comparable: {type(exc).__name__}: {exc}') from None
        if results[0] != results[1]:
            raise ValueError('Execution observations are not repeatable on identical failure replay inputs')
        return results[0]

    baseline = repeated(ZERO_SCENARIO, data['observations']['baseline'])
    stress = repeated(data['scenario'], data['observations']['stress'])
    _comparable(baseline, stress)
    base_metrics, stress_metrics = execution_metrics(baseline), execution_metrics(stress)
    base_errors = requirement_violations(base_metrics, data['requirements'])
    stress_errors = requirement_violations(stress_metrics, data['requirements'], base_metrics)
    if base_errors:
        raise ResilienceError('Baseline requirements failed: ' + '; '.join(base_errors))
    if stress_errors:
        raise ResilienceError('Stress requirements failed: ' + '; '.join(stress_errors))
    return {'status': 'PASS', 'baseline': {'result': baseline, 'metrics': base_metrics, 'violations': []},
            'stress': {'result': stress, 'metrics': stress_metrics, 'violations': []},
            'config_overridden': config is not None, 'config_hash': canonical_hash(options),
            'runtime': {'engine': baseline['engine'], 'engine_version': baseline['engine_version']},
            'fixture_hash': data['fixture_hash']}


def export_failure_reproducer(report, output_dir, strategy_ref):
    """Write the full tape, policy, observations, receipt and executable pytest."""
    reject_sensitive_data(report)
    reference = _reference(strategy_ref)
    if report.get('schema_version') != LAB_SCHEMA or report.get('status') != 'FAILURE_FOUND' or not report.get('failure'):
        raise ValueError('A FAILURE_FOUND report with verified native observations is required')
    failure, baseline = report['failure'], report['baseline']
    runtime = {'python_version': platform.python_version(), 'python_implementation': platform.python_implementation(),
               'backtest_witness_version': __version__, 'engine': baseline['result']['engine'],
               'engine_version': baseline['result']['engine_version']}
    fixture = {'schema_version': FIXTURE_SCHEMA, 'strategy_ref': reference,
               'rows': validate_rows(report['rows']), 'config': validate_config(report.get('config')),
               'seed': report['settings']['seed'], 'settings': deepcopy(report['settings']),
               'runner_spec': validate_runner_spec(report['runner_spec']), 'baseline': deepcopy(ZERO_SCENARIO),
               'scenario': validate_scenario(failure['scenario']), 'requirements': validate_requirements(report['requirements']),
               'runtime': runtime,
               'observations': {'baseline': deepcopy(baseline['result']), 'stress': deepcopy(failure['result'])}}
    if 'provenance' in report:
        fixture['provenance'] = validate_config(report['provenance'])
    fixture['content_hashes'] = {field: canonical_hash(fixture[field]) for field in _HASH_FIELDS}
    fixture['fixture_hash'] = canonical_hash(fixture)
    _validated_fixture(fixture)
    receipt = {'schema_version': 'backtest-witness.failure-receipt.v1', 'report_id': report['report_id'],
               'strategy_ref': reference, 'runner_spec': deepcopy(fixture['runner_spec']),
               'fixture_hash': fixture['fixture_hash'], 'content_hashes': deepcopy(fixture['content_hashes']),
               'runtime': runtime, 'scope': {'settings': deepcopy(report['settings']),
               'coverage': deepcopy(report['coverage']), 'reduction': deepcopy(failure['reduction'])},
               'explanation': 'Content hashes and observations are reproducibility receipts, not signatures or source-authenticity guarantees. This full-tape policy regression covers only the saved simulated execution assumptions; it does not certify performance.'}
    if 'provenance' in fixture:
        receipt['provenance'] = deepcopy(fixture['provenance'])
    generated = '''"""Execution policy regression exported by Tradeoff; keep the fixture beside this file."""
from pathlib import Path
from tradeoff.execution import resolve_execution_runner
from tradeoff.failure_reproduce import load_failure_fixture, assert_failure_resilience


def test_failure_resilience():
    fixture = load_failure_fixture(Path(__file__).with_name("failure-fixture.json"))
    run = resolve_execution_runner(fixture["strategy_ref"], **fixture["runner_spec"])
    assert_failure_resilience(run, fixture)
'''
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename, value in (('failure-fixture.json', fixture), ('failure-receipt.json', receipt)):
        (output / filename).write_text(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + '\n', encoding='utf-8')
    (output / 'test_failure_resilience.py').write_text(generated, encoding='utf-8')
    return {'fixture': 'failure-fixture.json', 'test': 'test_failure_resilience.py', 'receipt': 'failure-receipt.json'}
