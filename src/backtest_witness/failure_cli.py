"""Local native execution workflows; optional packages are imported on demand."""
import json
from pathlib import Path


def _json_file(path, default):
    return json.loads(Path(path).read_text(encoding='utf-8')) if path else default


def _save(report, folder, reference):
    from .failure_reproduce import export_failure_reproducer
    from .report import write_failure_report
    report['artifacts'] = {'json': 'report.json'}
    if report.get('failure'):
        report['artifacts'].update(export_failure_reproducer(report, folder, reference))
    write_failure_report(report, folder)


def _announce(report, folder, *, as_json=False):
    from .cli import DIAGNOSTICS_HINT
    if as_json:
        summary = {'status': report['status'], 'report_id': report['report_id'],
                   'report': str(folder / 'report.json'), 'interface': str(folder / 'index.html'),
                   'input_checks': report.get('input_checks', {})}
        if report['status'] == 'INCONCLUSIVE':
            summary['hint'] = DIAGNOSTICS_HINT
        print(json.dumps(summary, allow_nan=False))
    else:
        print(f"{report['status']}: {report['headline']}\nOpen: {folder / 'index.html'}")
        if report['status'] == 'INCONCLUSIVE':
            print(DIAGNOSTICS_HINT)


def lab(args):
    from .cli import data_options, load_data, prepare_output, validate_output
    from .data import inspect_data
    from .failure_lab import run_failure_lab, validate_requirements, _suite
    from .validation import validate_config
    args._phase = 'output'
    validate_output(args.output)
    args._phase = 'data'
    rows = load_data(args.data, **data_options(args))
    args._phase = 'config'
    config = validate_config(_json_file(args.config, {}))
    args._phase = 'requirements'
    requirements = validate_requirements(_json_file(args.requirements, None))
    args._phase = 'scenarios'
    scenarios = _json_file(args.scenarios, None)
    _suite(scenarios)
    args._phase = 'settings'
    settings = validate_config(json.loads(args.engine_settings) if args.engine_settings else {})
    if args.engine == 'backtesting':
        from .execution import _settings
        _settings(settings)
    else:
        from .adapters._shared import settings_dict
        settings_dict(settings, {})
    if args.max_calls < 0:
        raise ValueError('max_calls must be a nonnegative integer')
    args._phase = 'integration'
    from .execution import companion_manifest, resolve_execution_runner
    companions = companion_manifest(args.companion_data or [])
    integration = {'required_columns': args.require_column or [],
                   'required_globals': args.require_global or [],
                   'allow_zero_volume': args.allow_zero_volume,
                   'allow_uninitialized_globals': args.allow_uninitialized_global or [],
                   'companions': companions}
    args._phase = 'strategy_import'
    runner = resolve_execution_runner(args.adapter, engine=args.engine, engine_settings=settings,
                                      integration=integration)
    args._phase = 'preflight'
    input_checks = {'data_warnings': inspect_data(rows), **runner.preflight(rows)}
    provenance = {**runner.source_provenance, 'companions': companions}
    args._phase = 'output'
    folder = prepare_output(args.output)
    args._phase = 'execution'
    report = run_failure_lab(runner, rows, config,
        scenarios=scenarios, requirements=requirements, provenance=provenance,
        seed=args.seed, max_calls=args.max_calls, strategy_ref=args.adapter)
    report['input_checks'] = input_checks
    args._phase = 'save'
    _save(report, folder, args.adapter)
    _announce(report, folder, as_json=args.json)
    return {'FAILURE_FOUND': 1, 'BASELINE_FAILED': 1,
            'NO_FAILURE_OBSERVED': 0, 'INCONCLUSIVE': 2}[report['status']]


def lab_cases(args):
    from .cases import CASES, get_case
    from .cli import prepare_output
    from .failure_lab import run_failure_lab
    from .report import write_failure_gallery
    # A teaching deterioration policy, explicitly unrelated to profitability.
    args._phase = 'output'
    from .cli import validate_output
    validate_output(args.output)
    args._phase = 'requirements'
    requirements = _json_file(args.requirements,
        {'min_return_pct': None, 'max_return_drop_pct': 0.05, 'min_closed_trades': 1})
    args._phase = 'scenarios'
    scenarios = _json_file(args.scenarios, None)
    args._phase = 'output'
    folder = prepare_output(args.output)
    args._phase = 'execution'
    entries, summaries = [], []
    variants = ('original', 'fixed') if args.variant == 'both' else (args.variant,)
    for name in ([args.case] if args.case else CASES):
        case = get_case(name)
        for variant in variants:
            reference = case[f'{variant}_execution_ref']
            callback = case[f'{variant}_execution']
            provenance = {**case['provenance'], 'variant': variant,
                'input': case['execution_input'],
                'workflow': 'native execution failure lab',
                'policy': 'Relative deterioration on a synthetic stress tape; baseline profitability is not assumed.',
                'variant_scope': ('Original public code includes the independently reproduced future-data dependency.'
                    if variant == 'original' else 'Disclosed local causal patch; this does not claim an execution-resilient repair.')}
            report = run_failure_lab(callback, case['execution_rows'](), case['config'],
                scenarios=scenarios, requirements=requirements, seed=args.seed,
                max_calls=args.max_calls, strategy_ref=reference, provenance=provenance)
            slug = f'{name}-{variant}'
            destination = folder / slug
            destination.mkdir()
            _save(report, destination, reference)
            entries.append({'name': f'{name.title()} · {variant}', 'status': report['status'],
                'path': f'{slug}/index.html', 'description': provenance['variant_scope']})
            summaries.append({'case': name, 'variant': variant, 'status': report['status'],
                'baseline': report['baseline'].get('metrics'),
                'failure_scenario': (report.get('failure') or {}).get('scenario'),
                'coverage': report['coverage'], 'provenance': provenance})
            if not args.json:
                print(f"{slug}: {report['status']}")
    (folder / 'case-results.json').write_text(json.dumps(
        {'schema_version': 'backtest-witness.execution-cases.v1', 'cases': summaries},
        indent=2, allow_nan=False) + '\n', encoding='utf-8')
    index = write_failure_gallery(folder, entries)
    if args.json:
        print(json.dumps({'cases': summaries, 'interface': str(index)}, allow_nan=False))
    else:
        print(f'\nOpen: {index}\nPreview: backtest-witness serve --directory {folder}')
    if any(item['status'] == 'INCONCLUSIVE' for item in summaries):
        return 2
    return 1 if any(item['status'] in ('FAILURE_FOUND', 'BASELINE_FAILED') for item in summaries) else 0


def replay_failure(args):
    from .execution import resolve_execution_runner, validate_integration, _check_companions
    from .failure_reproduce import load_failure_fixture, assert_failure_resilience, ResilienceError
    args._phase = 'config'
    fixture = load_failure_fixture(args.fixture)
    reference = args.adapter or fixture['strategy_ref']
    spec = fixture['runner_spec']
    args._phase = 'integration'
    if 'integration' in spec:
        _check_companions(validate_integration(spec['integration']))
    args._phase = 'strategy_import'
    runner = resolve_execution_runner(reference, **spec)
    args._phase = 'config'
    config = _json_file(args.config, None)
    if args.adapter or args.config:
        print(f'Repair override: adapter={reference}; config={args.config or "saved configuration"}')
    args._phase = 'execution'
    try:
        assert_failure_resilience(runner, fixture, config=config)
    except ResilienceError as exc:
        print(f'FAILURE REPRODUCED: {exc}')
        return 1
    print('PASS: baseline and saved stress meet the declared requirements in this replay.')
    return 0


def add_failure_commands(subparsers):
    from .cli import add_data_options, add_diagnostics_option
    execution = subparsers.add_parser('lab', help='Rerun a strategy under native engine cost and extra market-order delay')
    execution.add_argument('--adapter', required=True, help='Importable module:Strategy, or execution callback')
    execution.add_argument('--engine', choices=['backtesting', 'callback'], default='backtesting',
                           help='Verified execution backend or explicit four-argument execution callback')
    execution.add_argument('--engine-settings', help='JSON native baseline options, such as {"cash": 10000, "commission": 0.001}')
    execution.add_argument('--data', required=True, help='CSV or JSON bars')
    execution.add_argument('--config', help='JSON file of strategy parameters')
    add_data_options(execution)
    execution.add_argument('--require-column', action='append', help='Required case-sensitive strategy feature column; repeat as needed')
    execution.add_argument('--require-global', action='append', help='Required initialized module global used by the native strategy; repeat as needed')
    execution.add_argument('--allow-zero-volume', action='store_true', help='Acknowledge an all-zero-volume feed when the strategy reads volume')
    execution.add_argument('--allow-uninitialized-global', action='append', help='Explicitly acknowledge an intentionally unset module global; repeat as needed')
    execution.add_argument('--companion-data', action='append', help='Bind a project-local companion input file by relative path and SHA-256; repeat as needed')
    execution.add_argument('--output', default='failure-output')
    execution.set_defaults(handler=lab)
    cases = subparsers.add_parser('lab-cases', help='Run pinned public strategies through the native execution failure lab')
    cases.add_argument('--case', choices=['riskkit', 'coinglass'])
    cases.add_argument('--variant', choices=['original', 'fixed', 'both'], default='both')
    cases.add_argument('--output', default='failure-public-output')
    cases.set_defaults(handler=lab_cases)
    for parser in (execution, cases):
        add_diagnostics_option(parser)
        parser.add_argument('--scenarios', help='JSON file of named additional commission/spread/delay scenarios')
        parser.add_argument('--requirements', help='JSON file with explicit minimum return/drawdown/relative-loss/trade requirements')
        parser.add_argument('--seed', type=int, default=7)
        parser.add_argument('--max-calls', type=int, default=96, help='Total execution invocation budget, including repeatability and reduction')
        parser.add_argument('--json', action='store_true', help='Emit a structured command summary')
    replay = subparsers.add_parser('replay-failure', help='Check baseline and saved native stress; retain the unchanged hashed fixture')
    replay.add_argument('fixture')
    replay.add_argument('--adapter', help='Importable repaired strategy/callback override')
    replay.add_argument('--config', help='JSON file of repaired strategy parameters; does not modify the saved fixture')
    add_diagnostics_option(replay)
    replay.set_defaults(handler=replay_failure)
