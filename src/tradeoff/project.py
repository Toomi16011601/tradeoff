"""Private local audit settings with bounded static strategy discovery.

Setup never imports project code. A review acknowledgement permits later local
imports; static discovery does not certify imports or arbitrary scripts as safe.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from .project_source import current_project_source as _project_context

_SCHEMA = 'tradeoff.project.v1'
_ENGINES = ('callback', 'targets', 'pandas', 'backtrader', 'backtesting')
_REFERENCE = r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*'
_DATA_KEYS = ('symbol', 'timezone', 'timestamp_column', 'timestamp_kind', 'bar_duration',
              'session_close', 'column_map')
_SCOPE = ('Static discovery is bounded. Review imports, decorators, class construction, helpers and '
          'top-level statements before using --review-imports. Check executes reviewed local code. '
          'This acknowledgement covers imported dependencies and companion files too; their changes '
          'are not tracked. Clock examples must be replaced with your actual data conventions.')


def _error(code, message):
    exc = ValueError(message)
    exc.code = code
    return exc


def _audit_defaults():
    from .cli import _audit_options
    parser = argparse.ArgumentParser(add_help=False)
    _audit_options(parser)
    return vars(parser.parse_args([]))


def _inspect(path):
    from .strategy_onboarding import _main_guard
    try:
        content = path.read_bytes()
        tree = ast.parse(content.decode('utf-8'), filename='<local-strategy>')
    except (SyntaxError, UnicodeError):
        raise _error('INVALID_STRATEGY_SOURCE', 'Strategy must be valid UTF-8 Python source') from None
    bases, run_names = set(), {'Backtest', 'run', 'plot'}
    modules = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in ('backtesting', 'backtesting.lib'):
            for item in node.names:
                if item.name in ('Strategy', 'SignalStrategy', 'TrailingStrategy'):
                    bases.add(item.asname or item.name)
                if item.name == 'Backtest':
                    run_names.add(item.asname or item.name)
        elif isinstance(node, ast.Import):
            modules.update(item.asname or item.name.split('.')[0] for item in node.names
                           if item.name in ('backtesting', 'backtesting.lib'))
    candidates = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if any((isinstance(base, ast.Name) and base.id in bases) or
               (isinstance(base, ast.Attribute) and base.attr in ('Strategy', 'SignalStrategy', 'TrailingStrategy')
                and isinstance(base.value, ast.Name) and base.value.id in modules)
               for base in node.bases):
            candidates.append(node.name)
            bases.add(node.name)
    execution = []

    def scan(node):
        if isinstance(node, ast.If) and _main_guard(node.test):
            for child in node.orelse:
                scan(child)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Defaults/decorators execute on import; function bodies do not.
            for child in [*node.decorator_list, node.args, node.returns]:
                if child is not None:
                    scan(child)
            return
        if isinstance(node, ast.Lambda):
            for child in [*node.args.defaults, *(value for value in node.args.kw_defaults if value is not None)]:
                scan(child)
            return
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else None)
            if name in run_names:
                execution.append({'call': name, 'line': node.lineno})
        for child in ast.iter_child_nodes(node):
            scan(child)

    for node in tree.body:
        scan(node)
    return {'classes': candidates, 'import_time_calls': execution,
            'source_sha256': hashlib.sha256(content).hexdigest()}


def _path(root, value):
    return (root / Path(value).expanduser()).resolve()


def _relative(root, value):
    return os.path.relpath(Path(value).expanduser().resolve(), root)


def _module(root, source):
    try:
        parts = list(source.relative_to(root).with_suffix('').parts)
    except ValueError:
        return None
    if parts[-1] == '__init__':
        parts.pop()
    if not parts or any(not item.isidentifier() for item in parts):
        return None
    return '.'.join(parts)


def _assess(settings, root, *, acknowledge=False, selected_class=None):
    from .data import load_data
    source = _path(root, settings['strategy'])
    scan = _inspect(source)
    issues = []
    if scan['import_time_calls']:
        issues.append({'code': 'IMPORT_TIME_EXECUTION', 'message':
                       'Recognized unguarded Backtest/run/plot execution must be moved behind a main guard '
                       'or into a separate reviewed importable strategy module.'})
    module = _module(root, source)
    if selected_class is not None:
        if selected_class not in scan['classes'] or module is None:
            raise _error('INVALID_STRATEGY_SELECTION', 'Choose a statically discovered Strategy class in an importable project module')
        settings['adapter'] = f'{module}:{selected_class}'
        settings['engine'] = 'backtesting'
    if settings['adapter'] is None:
        if len(scan['classes']) == 1 and module:
            settings['adapter'] = f"{module}:{scan['classes'][0]}"
            settings['engine'] = 'backtesting'
        else:
            issues.append({'code': 'STRATEGY_SELECTION_REQUIRED', 'message':
                           'Select one native class with --strategy-class NAME, or supply --adapter module:callable '
                           'and --engine for an already reviewed supported adapter.'})
    if acknowledge:
        settings['review'] = {'acknowledged': True, 'source_sha256': scan['source_sha256']}
    if (not settings['review']['acknowledged'] or
            settings['review']['source_sha256'] != scan['source_sha256']):
        issues.append({'code': 'IMPORT_REVIEW_REQUIRED', 'message':
                       'Review this source and its imports/companion files, then pass --review-imports; '
                       'setup has not imported strategy code.'})
    options = settings['data_options']
    if options['timestamp_kind'] is None:
        issues.append({'code': 'TIMESTAMP_KIND_REQUIRED', 'message':
                       'Declare --timestamp-kind close or --timestamp-kind open --bar-duration DURATION; '
                       'a timezone does not establish what a bar label means.'})
    try:
        load_data(_path(root, settings['data']), **{**options, 'timestamp_kind': options['timestamp_kind'] or 'close'})
    except (ValueError, OSError) as exc:
        issues.append({'code': getattr(exc, 'code', 'INVALID_DATA'), 'message': str(exc)})
    if settings['config'] is not None:
        from .validation import validate_config
        validate_config(json.loads(_path(root, settings['config']).read_text(encoding='utf-8')))
    return scan, issues


def _validate(settings):
    expected = {'schema_version', 'strategy', 'data', 'adapter', 'engine', 'engine_settings',
                'config', 'data_options', 'audit_options', 'review'}
    invalid = not isinstance(settings, dict) or set(settings) != expected
    if invalid or settings['schema_version'] != _SCHEMA:
        raise _error('INVALID_PROJECT', 'Unsupported project manifest; use a tradeoff.project.v1 manifest from tradeoff init')
    for key in ('strategy', 'data'):
        if not isinstance(settings[key], str) or not settings[key] or '\x00' in settings[key]:
            raise _error('INVALID_PROJECT', 'Project source and data paths must be nonempty strings')
    if settings['config'] is not None and (not isinstance(settings['config'], str) or not settings['config'] or '\x00' in settings['config']):
        raise _error('INVALID_PROJECT', 'Project config must be a local file path or null')
    if (settings['engine'] not in _ENGINES or
            (settings['adapter'] is not None and (not isinstance(settings['adapter'], str) or
             re.fullmatch(_REFERENCE, settings['adapter'], flags=re.ASCII) is None))):
        raise _error('INVALID_PROJECT', 'Project needs a supported engine and an importable module:attribute adapter')
    review = settings['review']
    if (not isinstance(review, dict) or set(review) != {'acknowledged', 'source_sha256'} or
        type(review['acknowledged']) is not bool or
        (review['source_sha256'] is not None and (not isinstance(review['source_sha256'], str) or
         re.fullmatch('[a-f0-9]{64}', review['source_sha256']) is None))):
        raise _error('INVALID_PROJECT', 'Project review must contain an explicit acknowledgement and source digest')
    options = settings['data_options']
    if not isinstance(options, dict) or set(options) != set(_DATA_KEYS):
        raise _error('INVALID_PROJECT', 'Project data_options contain unsupported fields')
    for key, value in options.items():
        if key == 'column_map':
            if value is not None and (not isinstance(value, dict) or any(
                    not isinstance(k, str) or not isinstance(v, str) for k, v in value.items())):
                raise _error('INVALID_PROJECT', 'Project column_map must map column names to source columns')
        elif value is not None and not isinstance(value, str):
            raise _error('INVALID_PROJECT', 'Project data conventions must be strings or null')
    defaults = _audit_defaults()
    audit = settings['audit_options']
    if not isinstance(audit, dict) or set(audit) != set(defaults):
        raise _error('INVALID_PROJECT', 'Project audit_options contain unsupported fields')
    integers = {'seed', 'min_history', 'max_probes', 'max_calls', 'fill_lag_bars'}
    for key, value in audit.items():
        if key == 'trace_kind':
            valid = value in (None, 'target_units', 'observed_position')
        elif key in integers:
            valid = type(value) is int
        else:
            valid = type(value) in (int, float) and math.isfinite(value)
        if not valid:
            raise _error('INVALID_PROJECT', 'Project audit options have invalid values')
    from .validation import validate_config
    validate_config(settings['engine_settings'])
    if not isinstance(settings['engine_settings'], dict):
        raise _error('INVALID_PROJECT', 'Project engine_settings must be a JSON object')
    return settings


def _write_new(path, settings):
    # Exclusive creation also refuses dangling symlinks and racing initializers.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(settings, stream, indent=2, allow_nan=False)
        stream.write('\n')


def _persist(path, settings, original):
    # Do not replace a manifest changed by another local process during preflight.
    if path.is_symlink() or path.read_bytes() != original:
        raise _error('PROJECT_CHANGED', 'Project manifest changed during validation; rerun check')
    content = json.dumps(settings, indent=2, allow_nan=False) + '\n'
    fd, temporary = tempfile.mkstemp(prefix='.tradeoff-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _summary(path, scan, issues):
    command = ['tradeoff', 'check', '--project', str(path)]
    codes = {issue['code'] for issue in issues}
    if 'IMPORT_REVIEW_REQUIRED' in codes:
        command.append('--review-imports')
    if 'TIMESTAMP_KIND_REQUIRED' in codes:
        command.extend(['--timestamp-kind', 'close'])
    if 'TIMEZONE_REQUIRED' in codes:
        command.extend(['--timezone', 'UTC'])
    if 'SESSION_CLOSE_REQUIRED' in codes:
        command.extend(['--timezone', 'UTC', '--session-close', '16:00'])
    if 'STRATEGY_SELECTION_REQUIRED' in codes and scan['classes']:
        command.extend(['--strategy-class', scan['classes'][0]])
    return {'status': 'NEEDS_INPUT' if issues else 'READY', 'project': str(path),
            'strategy_classes': scan['classes'], 'issues': issues,
            'next_command': shlex.join(command), 'next_command_is_example': bool(issues),
            'scope': _SCOPE}


def _init(args):
    from .cli import data_options
    args._phase = 'preflight'
    path = Path(args.project).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise _error('PROJECT_EXISTS', 'Project manifest already exists; use tradeoff check with resolution flags or choose --project NEW_FILE')
    root = path.parent.resolve()
    options = data_options(args)
    settings = {'schema_version': _SCHEMA, 'strategy': _relative(root, args.strategy),
                'data': _relative(root, args.data), 'adapter': args.adapter,
                'engine': args.engine or 'backtesting',
                'engine_settings': json.loads(args.engine_settings) if args.engine_settings else {},
                'config': _relative(root, args.config) if args.config else None,
                'data_options': options, 'audit_options': {key: getattr(args, key) for key in _audit_defaults()},
                'review': {'acknowledged': False, 'source_sha256': None}}
    _validate(settings)
    scan, issues = _assess(settings, root, acknowledge=args.review_imports, selected_class=args.strategy_class)
    _write_new(path, settings)
    summary = _summary(path, scan, issues)
    if args.json:
        print(json.dumps(summary, allow_nan=False))
    else:
        print(f"{summary['status']}: saved private local settings to {path}")
        for issue in issues:
            print(f"- {issue['message']}")
        print(_SCOPE)
        print(('Example next command (declare actual conventions): ' if issues else 'Next: ') + summary['next_command'])
    return 0


def _check(args):
    from .cli import _audit, data_options, validate_output
    args._phase = 'preflight'
    path = Path(args.project).expanduser().absolute()
    if path.is_symlink():
        raise _error('INVALID_PROJECT', 'Project manifest must be a regular local file, not a symbolic link')
    original = path.read_bytes()
    settings = _validate(json.loads(original))
    root = path.parent.resolve()
    overrides = data_options(args)
    for key, value in overrides.items():
        if value is not None:
            settings['data_options'][key] = value
    for key in _audit_defaults():
        if getattr(args, key) is not None:
            settings['audit_options'][key] = getattr(args, key)
    for key in ('adapter', 'engine'):
        if getattr(args, key) is not None:
            settings[key] = getattr(args, key)
    for key in ('strategy', 'data', 'config'):
        if getattr(args, key) is not None:
            replacement = str(Path(getattr(args, key)).expanduser())
            if key == 'strategy' and _path(root, replacement) != _path(root, settings[key]):
                settings['review'] = {'acknowledged': False, 'source_sha256': None}
                if args.adapter is None:
                    settings['adapter'] = None
            settings[key] = replacement
    if args.engine_settings is not None:
        settings['engine_settings'] = json.loads(args.engine_settings)
    _validate(settings)
    folder = (root / Path(args.output).expanduser()) if args.output else root / '.tradeoff' / f'check-{uuid4().hex[:12]}'
    args._phase = 'output'
    folder = validate_output(folder)
    args._phase = 'preflight'
    scan, issues = _assess(settings, root, acknowledge=args.review_imports, selected_class=args.strategy_class)
    if issues:
        summary = _summary(path, scan, issues)
        details = '; '.join(issue['message'] for issue in issues)
        raise _error('PROJECT_NEEDS_INPUT', details + ' Example next command: ' + summary['next_command'])
    requirements = {'backtesting': ('backtesting', 'audit'),
                    'pandas': ('pandas', 'adapters'),
                    'backtrader': ('backtrader', 'adapters')}
    if settings['engine'] in requirements:
        dependency, extra = requirements[settings['engine']]
        if importlib.util.find_spec(dependency) is None:
            raise _error('OPTIONAL_ENGINE_REQUIRED', f'This engine requires {dependency}; install with python -m pip install '
                         f'"tradeoff[{extra}] @ git+https://github.com/Toomi16011601/tradeoff.git"')
    if json.loads(original) != settings:
        _persist(path, settings, original)
    runtime = SimpleNamespace(**settings['audit_options'], **{**settings['data_options'],
        'column_map': json.dumps(settings['data_options']['column_map']) if settings['data_options']['column_map'] else None},
        adapter=settings['adapter'], engine=settings['engine'], engine_settings=json.dumps(settings['engine_settings']),
        data=str(_path(root, settings['data'])), config=str(_path(root, settings['config'])) if settings['config'] else None,
        output=str(folder), json=args.json)
    try:
        with _project_context(root, _path(root, settings['strategy']), scan['source_sha256']):
            if args.json:
                with redirect_stdout(io.StringIO()):
                    code = _audit(runtime)
            else:
                code = _audit(runtime)
    finally:
        args._phase = getattr(runtime, '_phase', 'execution')
    report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    replay = shlex.join(['tradeoff', 'reproduce', str(folder / 'reproducer.json')]) if report.get('witness') else None
    if args.json:
        print(json.dumps({'status': report['status'], 'report_id': report['report_id'],
                          'report': str(folder / 'report.json'), 'interface': str(folder / 'index.html'),
                          'project': str(path), 'replay': replay}, allow_nan=False))
    elif replay:
        print(f'Replay from {root}: {replay}')
    return code


def _options(parser):
    from .cli import _audit_options, add_data_options, add_diagnostics_option
    parser.add_argument('--project', '--manifest', default='tradeoff.json', help='Private local manifest path (default: tradeoff.json)')
    parser.add_argument('--strategy-class', help='Select one statically discovered Backtesting.py class')
    parser.add_argument('--adapter', help='Explicit importable module:attribute for a supported adapter')
    parser.add_argument('--engine', choices=_ENGINES, help='Explicit adapter type; discovered native classes use backtesting')
    parser.add_argument('--engine-settings', help='JSON object of native engine options')
    parser.add_argument('--config', help='Local JSON callback configuration file')
    parser.add_argument('--review-imports', action='store_true', help='Acknowledge review of source, imports, decorators and companion files before local execution')
    parser.add_argument('--json', action='store_true')
    add_data_options(parser)
    parser.set_defaults(timestamp_kind=None)
    add_diagnostics_option(parser)
    _audit_options(parser)


def add_project_commands(subparsers):
    setup = subparsers.add_parser('init', help='Save private audit settings; inspect source without importing it')
    _options(setup)
    setup.add_argument('--strategy', required=True, help='Local Python strategy source; not executed during init')
    setup.add_argument('--data', required=True, help='Local historical CSV or JSON bars')
    setup.set_defaults(handler=_init)
    check = subparsers.add_parser('check', help='Audit the reviewed local project using saved settings')
    _options(check)
    check.add_argument('--strategy', help='Reviewed strategy source, relative to the manifest')
    check.add_argument('--data', help='Historical data path, relative to the manifest')
    check.add_argument('--output', help='Fresh output path relative to the manifest; default .tradeoff/check-UNIQUE')
    check.set_defaults(**{key: None for key in _audit_defaults()}, handler=_check)
