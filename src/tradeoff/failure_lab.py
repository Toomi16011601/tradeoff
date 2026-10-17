"""Bounded, repeatable policy-failure search over native execution observations.

This module deliberately has no optional engine imports. A runner owns native
execution; this module independently validates and summarizes its observations.
"""
from copy import deepcopy
from datetime import datetime, timezone
import uuid
from .privacy import callback_error, reject_sensitive_data

from .validation import canonical_hash, normalize_target, parse_timestamp, validate_config, validate_rows

SCHEMA_VERSION = 'backtest-witness.failure-lab.v1'
ZERO_SCENARIO = {'commission_bps': 0, 'spread_bps': 0, 'delay_bars': 0}
DEFAULT_REQUIREMENTS = {'min_return_pct': 0, 'max_drawdown_pct': None,
                        'max_return_drop_pct': None, 'min_closed_trades': 0}


def validate_scenario(value):
    if not isinstance(value, dict) or set(value) - set(ZERO_SCENARIO):
        raise ValueError('scenario must contain only commission_bps, spread_bps and delay_bars')
    result = dict(ZERO_SCENARIO, **deepcopy(value))
    for field, number in result.items():
        normalize_target(number, field)
        if number < 0 or (field == 'delay_bars' and type(number) is not int):
            raise ValueError(f'{field} must be nonnegative' + (' and an integer' if field == 'delay_bars' else ''))
    return result


def validate_requirements(value=None):
    value = validate_config(value)
    if set(value) - set(DEFAULT_REQUIREMENTS):
        raise ValueError('Unknown failure requirement')
    result = dict(DEFAULT_REQUIREMENTS, **value)
    for field, number in result.items():
        if number is None and field != 'min_closed_trades':
            continue
        normalize_target(number, field)
        if field == 'min_closed_trades' and (type(number) is not int or number < 0):
            raise ValueError('min_closed_trades must be a nonnegative integer')
        if field in ('max_drawdown_pct', 'max_return_drop_pct') and number < 0:
            raise ValueError(f'{field} must be nonnegative or null')
    return result


def validate_runner_spec(value):
    spec = validate_config(value)
    if (set(spec) - {'engine', 'engine_settings', 'integration'}
            or not {'engine', 'engine_settings'} <= set(spec)
            or spec['engine'] not in ('callback', 'backtesting')):
        raise ValueError('Execution runner_spec must specify callback or backtesting and engine_settings')
    spec['engine_settings'] = validate_config(spec['engine_settings'])
    if 'integration' in spec:
        from .execution import validate_integration
        spec['integration'] = validate_integration(spec['integration'])
    return spec


def validate_execution_result(value, rows, scenario):
    """Require finite complete observations, retaining all fields for equality."""
    result = validate_config(value)
    required = ('engine', 'engine_version', 'initial_cash', 'effective_settings', 'scenario',
                'timing', 'warnings', 'equity', 'trades', 'open_trades', 'pending_orders')
    if any(field not in result for field in required):
        raise ValueError('Execution result lacks required native observations')
    for field in ('engine', 'engine_version', 'timing'):
        if not isinstance(result[field], str) or not result[field]:
            raise ValueError(f'Execution {field} must be a nonempty string')
    cash = normalize_target(result['initial_cash'], 'initial_cash')
    if cash <= 0:
        raise ValueError('initial_cash must be positive and finite')
    validate_config(result['effective_settings'])
    if validate_scenario(result['scenario']) != scenario:
        raise ValueError('Execution scenario must match the requested scenario')
    for field in ('warnings', 'equity', 'trades', 'open_trades', 'pending_orders'):
        if not isinstance(result[field], list):
            raise ValueError(f'Execution {field} must be a list')
    if len(result['equity']) != len(rows):
        raise ValueError('Execution equity must have exactly one observation per original input row')
    for index, (point, row) in enumerate(zip(result['equity'], rows)):
        if not isinstance(point, dict):
            raise ValueError('Execution equity observations must be objects')
        timestamp = parse_timestamp(point.get('timestamp'), f'equity[{index}].timestamp')
        if timestamp != parse_timestamp(row['timestamp']):
            raise ValueError('Execution equity timestamps must match original rows in order')
        point['timestamp'] = timestamp.astimezone(timezone.utc).isoformat()
        point['position'] = normalize_target(point.get('position'), f'equity[{index}].position')
        normalize_target(point.get('equity'), f'equity[{index}].equity')
    if any(not isinstance(item, str) for item in result['warnings']):
        raise ValueError('Execution warnings must contain strings')
    _validate_native_records(result, len(rows))
    return result


def _validate_native_records(result, row_count):
    def bar(value, label, *, nullable=False, future=False):
        if value is None and nullable:
            return
        if type(value) is not int or value < 0 or (not future and value >= row_count):
            raise ValueError(f'{label} must be an integer bar index within the input history' if not future
                             else f'{label} must be a nonnegative integer bar index')

    def number(value, label, *, positive=False, nonzero=False, nullable=False):
        if value is None and nullable:
            return
        value = normalize_target(value, label)
        if (positive and value <= 0) or (nonzero and value == 0):
            raise ValueError(f'{label} must be positive' if positive else f'{label} must be nonzero signed size')

    schemas = {
        'trades': ('entry_bar', 'exit_bar', 'size', 'entry_price', 'exit_price', 'pnl', 'commission'),
        'open_trades': ('entry_bar', 'size', 'entry_price', 'pnl', 'sl', 'tp'),
        'pending_orders': ('size', 'limit', 'stop', 'sl', 'tp', 'is_contingent', 'parent_entry_bar', 'created_bar', 'due_bar'),
    }
    for field, required in schemas.items():
        for index, record in enumerate(result[field]):
            label = f'{field}[{index}]'
            if not isinstance(record, dict) or any(key not in record for key in required):
                raise ValueError(f'{label} lacks required native observation fields')
            number(record['size'], label + '.size', nonzero=True)
            if field == 'pending_orders':
                for key in ('limit', 'stop', 'sl', 'tp'):
                    number(record[key], label + '.' + key, positive=True, nullable=True)
                if type(record['is_contingent']) is not bool:
                    raise ValueError(f'{label}.is_contingent must be a boolean')
                for key in ('parent_entry_bar', 'created_bar'):
                    bar(record[key], label + '.' + key, nullable=True)
                bar(record['due_bar'], label + '.due_bar', nullable=True, future=True)
                if record['created_bar'] is not None and record['due_bar'] is not None and record['due_bar'] <= record['created_bar']:
                    raise ValueError(f'{label}.due_bar must follow created_bar')
            else:
                bar(record['entry_bar'], label + '.entry_bar')
                number(record['entry_price'], label + '.entry_price', positive=True)
                number(record['pnl'], label + '.pnl')
                if 'commission' in record:
                    # Native commission can include rebates, so require finite
                    # numeric observations without assuming a positive fee.
                    number(record['commission'], label + '.commission')
                if field == 'trades':
                    bar(record['exit_bar'], label + '.exit_bar')
                    if record['exit_bar'] < record['entry_bar']:
                        raise ValueError(f'{label}.exit_bar must not precede entry_bar')
                    number(record['exit_price'], label + '.exit_price', positive=True)
                else:
                    for key in ('sl', 'tp'):
                        number(record[key], label + '.' + key, positive=True, nullable=True)


def execution_metrics(result):
    cash = result['initial_cash']
    final = result['equity'][-1]['equity']
    peak, drawdown = cash, 0
    for point in result['equity']:
        peak = max(peak, point['equity'])
        drawdown = max(drawdown, (peak - point['equity']) / peak * 100)
    metrics = {'return_pct': (final - cash) / cash * 100, 'net_profit': final - cash,
               'final_equity': final, 'max_drawdown_pct': drawdown,
               'closed_trades': len(result['trades'])}
    canonical_hash(metrics)  # Extreme finite inputs can still overflow arithmetic.
    return metrics


def requirement_violations(metrics, requirements, baseline_metrics=None):
    errors = []
    if requirements['min_return_pct'] is not None and metrics['return_pct'] < requirements['min_return_pct']:
        errors.append(f"Return {metrics['return_pct']:.6g}% is below required minimum {requirements['min_return_pct']:.6g}%")
    if requirements['max_drawdown_pct'] is not None and metrics['max_drawdown_pct'] > requirements['max_drawdown_pct']:
        errors.append(f"Drawdown {metrics['max_drawdown_pct']:.6g}% exceeds maximum {requirements['max_drawdown_pct']:.6g}%")
    if metrics['closed_trades'] < requirements['min_closed_trades']:
        errors.append(f"Closed trades {metrics['closed_trades']} is below required minimum {requirements['min_closed_trades']}")
    if baseline_metrics is not None and requirements['max_return_drop_pct'] is not None:
        drop = baseline_metrics['return_pct'] - metrics['return_pct']
        if drop > requirements['max_return_drop_pct']:
            errors.append(f"Return drop {drop:.6g} percentage points exceeds maximum {requirements['max_return_drop_pct']:.6g} relative to the same baseline")
    return errors


def paired_differences(before, after):
    return [{'timestamp': a['timestamp'], 'before_position': a['position'], 'after_position': b['position'],
             'before_equity': a['equity'], 'after_equity': b['equity']}
            for a, b in zip(before['equity'], after['equity'])
            if a['position'] != b['position'] or a['equity'] != b['equity']]


def _suite(scenarios):
    if scenarios is None:
        scenarios = ([{'name': f'Additional commission {n} bps', 'commission_bps': n} for n in (5, 10, 25, 50, 100, 200)]
                     + [{'name': f'Additional spread {n} bps', 'spread_bps': n} for n in (5, 10, 25)]
                     + [{'name': f'Extra delay {n} bars', 'delay_bars': n} for n in (1, 2)]
                     + [{'name': 'Combined execution stress', 'commission_bps': 25, 'spread_bps': 10, 'delay_bars': 1}])
    if not isinstance(scenarios, list):
        raise ValueError('scenarios must be a list')
    suite = []
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            raise ValueError(f'scenarios[{index}] must be a JSON object')
        item = validate_config(item)
        name = item.pop('name', f'Scenario {index + 1}')
        if not isinstance(name, str) or not name:
            raise ValueError('Scenario name must be a nonempty string')
        if set(item) == {'scenario'}:
            item = item['scenario']
        suite.append({'name': name, 'scenario': validate_scenario(item), **_empty_entry('NOT_RUN', 'Not run')})
    return suite


def _empty_entry(status, reason):
    return {'status': status, 'result': None, 'metrics': None, 'violations': [], 'reason': reason}


def run_failure_lab(run, rows, config=None, *, scenarios=None, requirements=None,
                    seed=7, max_calls=96, strategy_ref=None, provenance=None):
    """Search only the declared finite stress levels, keeping the full tape.

    Four invocations are held back for fresh final baseline/stress verification.
    Repeated equality covers the entire execution object, including terminal
    orders and warnings. A partial passing suite is inconclusive.
    """
    if not callable(run):
        raise ValueError('run must be callable')
    rows, config = validate_rows(rows), validate_config(config)
    reject_sensitive_data(strategy_ref)
    requirements, suite = validate_requirements(requirements), _suite(scenarios)
    if type(seed) is not int or type(max_calls) is not int or max_calls < 0:
        raise ValueError('seed must be an integer and max_calls a nonnegative integer')
    spec = validate_runner_spec(getattr(run, 'runner_spec', {'engine': 'callback', 'engine_settings': {}}))
    report = {'schema_version': SCHEMA_VERSION, 'report_id': str(uuid.uuid4()),
              'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'INCONCLUSIVE',
              'headline': 'Execution comparison is inconclusive', 'reason': '', 'strategy_ref': strategy_ref,
              'runner_spec': spec,
              'dataset': {'symbol': rows[0]['symbol'], 'row_count': len(rows), 'start': rows[0]['timestamp'],
                          'end': rows[-1]['timestamp'], 'input_hash': canonical_hash(rows)},
              'requirements': requirements, 'settings': {'seed': seed, 'max_calls': max_calls},
              'coverage': {'runs': 0, 'completed': 0, 'total': len(suite), 'complete': False, 'notes': []},
              'baseline': _empty_entry('NOT_RUN', 'Not run'), 'scenarios': suite, 'failure': None,
              'artifacts': {}, 'rows': rows, 'config': config}
    if provenance is not None:
        report['provenance'] = validate_config(provenance)
    coverage = report['coverage']

    def repeated(stress, base=None):
        if coverage['runs'] + 2 > max_calls:
            return _empty_entry('NOT_RUN', 'Invocation budget cannot fit repeated execution')
        results = []
        try:
            for _ in range(2):
                coverage['runs'] += 1
                try:
                    result = run(deepcopy(rows), deepcopy(config), seed, deepcopy(stress))
                except Exception as exc:
                    return _empty_entry('UNAVAILABLE', callback_error(exc))
                results.append(validate_execution_result(result, rows, stress))
            if results[0] != results[1]:
                raise ValueError('Execution observations are not repeatable on identical inputs')
            if base is not None:
                for field in ('engine', 'engine_version', 'initial_cash'):
                    if results[0][field] != base['result'][field]:
                        raise ValueError(f'Baseline/stress {field} mismatch; comparison refused')
            metrics = execution_metrics(results[0])
            violations = requirement_violations(metrics, requirements, base['metrics'] if base is not None else None)
            return {'status': 'FAIL' if violations else 'PASS', 'result': results[0], 'metrics': metrics,
                    'violations': violations, 'reason': '; '.join(violations) if violations else 'Completed requirements met'}
        except Exception as exc:
            return _empty_entry('UNAVAILABLE', f'{type(exc).__name__}: {exc}')

    baseline = repeated(ZERO_SCENARIO)
    report['baseline'] = baseline
    if baseline['status'] not in ('PASS', 'FAIL'):
        report['reason'] = baseline['reason']
        for entry in suite:
            entry['reason'] = 'Baseline comparison unavailable'
        coverage['notes'].append(report['reason'])
        return report
    if baseline['status'] == 'FAIL':
        report.update(status='BASELINE_FAILED', headline='Baseline already breaches requirements', reason=baseline['reason'])
        for entry in suite:
            entry['reason'] = 'Baseline already fails absolute requirements; stress search not run'
        return report

    cache = {canonical_hash(ZERO_SCENARIO): baseline}
    for entry in suite:
        if coverage['runs'] + 2 + 4 > max_calls:
            entry['reason'] = 'Invocation budget exhausted while reserving four final verification runs'
            continue
        entry.update(repeated(entry['scenario'], baseline))
        cache[canonical_hash(entry['scenario'])] = deepcopy(entry)
    coverage['completed'] = sum(entry['status'] in ('PASS', 'FAIL') for entry in suite)
    coverage['complete'] = coverage['completed'] == len(suite)
    for entry in suite:
        if entry['status'] not in ('PASS', 'FAIL'):
            coverage['notes'].append(f"{entry['name']}: {entry['reason']}")
    failed = next((entry for entry in suite if entry['status'] == 'FAIL'), None)
    if failed is None:
        if coverage['complete']:
            report.update(status='NO_FAILURE_OBSERVED', headline='No failure observed in completed declared scenarios',
                          reason='All completed declared scenarios meet the requirements; this is not performance certification')
        else:
            report['reason'] = 'Some declared scenarios are unavailable or not run; no complete passing comparison'
        return report

    current, observed = deepcopy(failed['scenario']), failed
    start_runs, complete = coverage['runs'], True
    levels = {field: sorted({0} | {entry['scenario'][field] for entry in suite}) for field in ZERO_SCENARIO}
    changed = True
    while changed:
        changed = False
        for field in ZERO_SCENARIO:
            for level in levels[field]:
                if level >= current[field]:
                    break
                candidate = dict(current, **{field: level})
                key = canonical_hash(candidate)
                trial = cache.get(key)
                if trial is None:
                    if coverage['runs'] + 2 + 4 > max_calls:
                        complete = False
                        continue
                    trial = repeated(candidate, baseline)
                    cache[key] = trial
                if trial['status'] not in ('PASS', 'FAIL'):
                    complete = False
                if trial['status'] == 'FAIL':
                    current, observed, changed = candidate, trial, True
                    break
    # Fresh repeated baseline then stress, never replaced by cached search runs.
    final_base = repeated(ZERO_SCENARIO)
    final_stress = repeated(current, final_base) if final_base['status'] == 'PASS' else _empty_entry('UNAVAILABLE', 'Final baseline did not meet absolute requirements')
    if (final_base['status'] != 'PASS' or final_base['result'] != baseline['result']
            or final_stress['status'] != 'FAIL' or final_stress['result'] != observed['result']):
        report['reason'] = 'Final repeated baseline/stress verification changed or was unavailable: ' + final_base['reason'] + '; ' + final_stress['reason']
        coverage['notes'].append(report['reason'])
        return report
    report['failure'] = {'scenario': current, 'result': final_stress['result'], 'metrics': final_stress['metrics'],
                         'violations': final_stress['violations'],
                         'differences': paired_differences(final_base['result'], final_stress['result']),
                         'reduction': {'complete': complete, 'runs': coverage['runs'] - start_runs,
                                       'scope': 'Lower values from declared per-axis levels plus zero were tested with full unchanged history, config and seed; no global minimum or break-even boundary is claimed. Final four invocations repeat baseline and stress.'}}
    report.update(status='FAILURE_FOUND', headline='Reproducible simulated execution policy breach',
                  reason='; '.join(final_stress['violations']))
    return report
