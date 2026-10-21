"""Bounded, local checks for bringing an existing Backtesting.py strategy into Tradeoff.

Script inspection parses source without importing it. Baseline comparison reads an
existing Tradeoff report and user-exported native statistics; it runs no strategy.
"""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path
import re


_NATIVE_KEYS = {
    'Return [%]': 'return_pct',
    'Max. Drawdown [%]': 'max_drawdown_pct',
    '# Trades': 'closed_trades',
    'Equity Final [$]': 'final_equity',
}
_METRICS = ('return_pct', 'max_drawdown_pct', 'closed_trades', 'final_equity')
_CONTEXT = ('dataset_hash', 'engine_settings')
_RUN_CALLS = {'Backtest', 'run', 'plot'}
_KNOWN_STRATEGY_BASES = {'Strategy', 'SignalStrategy', 'TrailingStrategy'}
_SCOPE = ('Matching only the provided baseline metrics does not prove strategy equivalence. '
          'Use the same historical bars and native engine settings as the original run; '
          'a matching dataset hash and engine settings verify only the declared context.')


def _call_name(node):
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _main_guard(node):
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    left, right = node.left, node.comparators[0]
    return ((isinstance(left, ast.Name) and left.id == '__name__'
             and isinstance(right, ast.Constant) and right.value == '__main__')
            or (isinstance(right, ast.Name) and right.id == '__name__'
                and isinstance(left, ast.Constant) and left.value == '__main__'))


def inspect_script(path):
    """Find direct Strategy classes and recognizable calls without executing source.

    Recognized calls are hints, not a safety determination. Imports, decorators,
    other top-level statements, and dynamic calls can still have side effects.
    No source excerpt or path is returned in the portable result.
    """
    source_path = Path(path)
    try:
        source = source_path.read_text(encoding='utf-8')
    except UnicodeError:
        raise ValueError('Source must be UTF-8 Python text') from None
    try:
        tree = ast.parse(source, filename='<local-script>')
    except SyntaxError:
        raise ValueError('Source is not valid Python syntax') from None
    classes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(base, ast.Name) and base.id in _KNOWN_STRATEGY_BASES)
            or (isinstance(base, ast.Attribute) and base.attr in _KNOWN_STRATEGY_BASES)
            for base in node.bases
        ):
            classes.append({'name': node.name, 'line': node.lineno})
    import_calls, guarded_calls = [], []

    def scan(node, *, guarded=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            # Bodies are not invoked by definition alone. Decorators and class
            # construction may still have side effects: the scan is bounded.
            return
        if isinstance(node, ast.If) and _main_guard(node.test):
            for child in node.body:
                scan(child, guarded=True)
            for child in node.orelse:
                scan(child, guarded=guarded)
            return
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in _RUN_CALLS:
                (guarded_calls if guarded else import_calls).append(
                    {'call': name, 'line': node.lineno})
        for child in ast.iter_child_nodes(node):
            scan(child, guarded=guarded)

    for node in tree.body:
        scan(node)
    import_calls.sort(key=lambda item: item['line'])
    guarded_calls.sort(key=lambda item: item['line'])
    return {
        'status': 'INSPECTED',
        'strategy_classes': classes,
        'import_time_calls': import_calls,
        'main_guard_calls': guarded_calls,
        'recognized_import_time_calls_present': bool(import_calls),
        'scope': ('Bounded static scan of known Backtesting.py Strategy bases and recognizable Backtest/run/plot calls; '
                  'this is not a safety certification. Review imports, decorators, helpers and all top-level '
                  'statements before importing. Copy the class and required helpers into a reviewed '
                  'importable module, then check its native baseline.'),
    }


def _expected_metrics(expected):
    if not isinstance(expected, dict):
        raise ValueError('Expected native baseline must be a JSON object')
    allowed = set(_NATIVE_KEYS) | set(_METRICS) | set(_CONTEXT)
    if set(expected) - allowed:
        raise ValueError('Expected native baseline has unsupported fields')
    metrics = {}
    for name, value in expected.items():
        if name in _CONTEXT:
            continue
        key = _NATIVE_KEYS.get(name, name)
        if key in metrics:
            raise ValueError('Expected native baseline repeats a metric under two names')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Expected baseline metrics must be finite numbers')
        if key == 'closed_trades' and (int(value) != value or value < 0):
            raise ValueError('Expected closed trades must be a nonnegative integer')
        if key == 'max_drawdown_pct':
            value = abs(value) if name == 'Max. Drawdown [%]' else value
            if not 0 <= value <= 100:
                raise ValueError('Expected maximum drawdown must be a percentage from 0 to 100')
        metrics[key] = int(value) if key == 'closed_trades' else float(value)
    if not metrics:
        raise ValueError('Expected native baseline needs at least one supported metric')
    return metrics


def compare_baseline(report, expected, *, abs_tol=1e-6, rel_tol=1e-8):
    """Compare supplied native stats with the completed zero-stress report baseline.

    Optional dataset_hash and engine_settings in expected are checked against
    report provenance; absent context remains explicitly unverified. Tolerances
    account for JSON rounding and floating-point arithmetic, not broad drift.
    """
    if not isinstance(report, dict) or report.get('schema_version') != 'backtest-witness.failure-lab.v1':
        raise ValueError('Input is not a Tradeoff failure-lab report')
    spec = report.get('runner_spec')
    baseline = report.get('baseline')
    if (not isinstance(spec, dict) or spec.get('engine') != 'backtesting'
            or not isinstance(baseline, dict) or baseline.get('status') not in ('PASS', 'FAIL')
            or not isinstance(baseline.get('metrics'), dict)):
        raise ValueError('Report needs a completed native baseline')
    if not isinstance(abs_tol, (int, float)) or not isinstance(rel_tol, (int, float)) or (
        isinstance(abs_tol, bool) or isinstance(rel_tol, bool)
        or not math.isfinite(abs_tol) or not math.isfinite(rel_tol)
        or abs_tol < 0 or rel_tol < 0
    ):
        raise ValueError('Comparison tolerances must be finite nonnegative numbers')
    metrics = _expected_metrics(expected)
    observed = baseline['metrics']
    comparisons = {}
    for key in _METRICS:
        if key not in metrics:
            continue
        actual = observed.get(key)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
            raise ValueError('Report has invalid native baseline metrics')
        match = (actual == metrics[key] if key == 'closed_trades' else
                 math.isclose(actual, metrics[key], rel_tol=rel_tol, abs_tol=abs_tol))
        comparisons[key] = {'expected': metrics[key], 'observed': actual, 'match': match}
    context = {'dataset': 'UNVERIFIED', 'engine_settings': 'UNVERIFIED'}
    if 'dataset_hash' in expected:
        digest = expected['dataset_hash']
        if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('dataset_hash must be a lowercase SHA-256 digest')
        dataset = report.get('dataset')
        if not isinstance(dataset, dict) or not isinstance(dataset.get('input_hash'), str):
            raise ValueError('Report has no dataset hash')
        context['dataset'] = 'MATCH' if digest == dataset['input_hash'] else 'MISMATCH'
    if 'engine_settings' in expected:
        from .execution import _settings
        wanted = _settings(expected['engine_settings'])
        context['engine_settings'] = ('MATCH' if wanted == spec.get('engine_settings')
                                      else 'MISMATCH')
    all_match = all(item['match'] for item in comparisons.values()) and 'MISMATCH' not in context.values()
    status = ('MISMATCH' if not all_match else 'PARTIAL_MATCH' if len(comparisons) < len(_METRICS)
              else 'MATCH' if all(value == 'MATCH' for value in context.values())
              else 'METRICS_MATCH_CONTEXT_UNVERIFIED')
    return {'status': status, 'checked_metrics': list(comparisons),
            'unchecked_metrics': [key for key in _METRICS if key not in comparisons],
            'metrics': comparisons, 'context': context,
            'tolerance': {'absolute': abs_tol, 'relative': rel_tol}, 'scope': _SCOPE}


def _inspect_command(args):
    args._phase = 'preflight'
    result = inspect_script(args.script)
    if args.json:
        print(json.dumps(result, allow_nan=False))
    else:
        print('Candidate Strategy classes: ' + (', '.join(item['name'] for item in result['strategy_classes']) or 'none found'))
        if result['import_time_calls']:
            print('Recognized import-time calls: ' + ', '.join(
                f"{item['call']} (line {item['line']})" for item in result['import_time_calls']))
        print(result['scope'])
    return 0


def _baseline_command(args):
    args._phase = 'preflight'
    report = json.loads(Path(args.report).read_text(encoding='utf-8'))
    expected = json.loads(Path(args.expected).read_text(encoding='utf-8'))
    result = compare_baseline(report, expected)
    if args.json:
        print(json.dumps(result, allow_nan=False))
    else:
        print(result['status'])
        for key, item in result['metrics'].items():
            print(f"{key}: expected {item['expected']}, observed {item['observed']} "
                  f"({'match' if item['match'] else 'mismatch'})")
        print('Unchecked metrics: ' + (', '.join(result['unchecked_metrics']) or 'none'))
        print('Dataset: ' + result['context']['dataset'] + '; engine settings: ' + result['context']['engine_settings'])
        print(result['scope'])
    return 1 if result['status'] == 'MISMATCH' else 0


def add_onboarding_commands(subparsers):
    scan = subparsers.add_parser('inspect-script',
        help='Statically identify native Strategy classes and recognizable import-time calls')
    scan.add_argument('script', help='Local Python source file; never imported or executed')
    scan.add_argument('--json', action='store_true', help='Emit a structured local scan summary')
    scan.set_defaults(handler=_inspect_command)
    check = subparsers.add_parser('check-baseline',
        help='Compare an existing lab report baseline with exported native Backtesting.py stats')
    check.add_argument('report', help='Existing Tradeoff failure-lab report.json')
    check.add_argument('--expected', required=True,
        help='JSON object of selected original Backtesting.py stats or normalized metrics')
    check.add_argument('--json', action='store_true', help='Emit a structured comparison')
    check.set_defaults(handler=_baseline_command)
