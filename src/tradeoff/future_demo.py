"""Investigate a pinned public-code defect on an explicitly synthetic tape.

The original full GOOG example is retained as a historical negative control.
Optional engine imports remain inside the workflow, after output validation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ORIGINAL_REF = 'tradeoff.cases.riskkit:original_run'
FIXED_REF = 'tradeoff.cases.riskkit:fixed_run'
ORIGINAL_SETTINGS = {'min_history': 45, 'max_probes': 8, 'max_calls': 768}
CONTROL_SETTINGS = {'min_history': 45, 'max_probes': 8, 'max_calls': 96}
GOOG_CSV_SHA256 = '60e961a567490b157f71888df9e6afb36190a34a40a6286aa38988e2343f1b1a'
LICENSE_SHA256 = 'c8d9693e0a93487c3719bcf12251799dd6edc1bd5e1099939727add33c482c7e'


def _require_dependencies():
    from .adapters._shared import engine_version
    hint = ("Public bug demo needs Backtesting.py 0.6.6 and pandas. From the repository checkout, "
            "run python -m pip install '.[audit]'; otherwise run python -m pip install "
            "'tradeoff[audit] @ git+https://github.com/Toomi16011601/tradeoff.git'")
    if engine_version('backtesting') != '0.6.6':
        raise ImportError(hint)
    try:
        from backtesting import test
    except ImportError as exc:
        raise ImportError(hint) from exc
    path = Path(test.__file__).with_name('GOOG.csv')
    if hashlib.sha256(path.read_bytes()).hexdigest() != GOOG_CSV_SHA256:
        raise ValueError('Bundled GOOG sample hash does not match the inspected Backtesting.py 0.6.6 input')


def _run_audit(callback, rows, reference, settings, provenance):
    from .audit import audit
    result = audit(callback, rows, {}, strategy_ref=reference,
                   trace_kind='observed_position', **settings)
    result['provenance'] = deepcopy(provenance)
    result['adapter_info'] = {**deepcopy(getattr(callback, 'adapter_info', {})),
                              'version': '0.6.6', 'provenance': deepcopy(provenance)}
    result['runner_spec'] = {'engine': 'callback', 'engine_settings': {}}
    result['coverage']['notes'].append(
        'Evidence compares native observed positions; no profitability or global leak-free claim is made.')
    return result


def run_future_demo(output, *, rows=None, input_description=None):
    """Export original evidence and verify the repair on that exact saved case.

    Supplied rows are preserved in full; a missing witness or inactive repair
    produces INCOMPLETE rather than a successful demonstration.
    """
    from .cli import prepare_output, validate_output
    validate_output(output)
    _require_dependencies()
    from .adapters._shared import engine_version
    from .cases import riskkit
    from .cases._loader import SOURCE_DIR, load_source
    from .historical_demo import historical_rows
    from .report import write_report
    from .reproduce import (InvarianceError, UnstableRunError, assert_future_invariance,
                            export_reproducer, load_fixture)
    from .validation import canonical_hash, validate_rows

    default_input = rows is None
    tape = validate_rows(riskkit.execution_rows() if default_input else rows)
    description = (riskkit.EXECUTION_INPUT if default_input else
                   (input_description or 'User-supplied OHLCV tape; origin and market clock declared by the caller.'))
    provenance = deepcopy(riskkit.PROVENANCE)
    provenance.update({
        'tested_versions': {name: engine_version(name) for name in ('backtesting', 'pandas', 'numpy')},
        'input': description,
        'input_kind': 'synthetic' if default_input else 'user_supplied',
        'input_sha256': canonical_hash(tape),
        'fixed_patch': 'Remove only .bfill() from rolling_std: .rolling(n).std().bfill().values '
                       'becomes .rolling(n).std().values. Native indicator warmup moves first next() '
                       'from index 30 to index 100 (31st to 101st bar). Trading rules and sizer stay unchanged. '
                       'The saved-case pass can be flat during warmup; activity is checked separately on the full original tape.',
        'scope': 'A real pre-existing public-code defect on an explicitly synthetic stress input. '
                 'This does not establish that the original full-GOOG backtest had changed positions, '
                 'or that this repair removes every future-data dependency.',
        'isolation': 'Execute the pinned original helper/class definitions and exact dependency-free sizer. '
                     'Omit upstream imports and __main__ printing/network paths; use fresh native engine state.',
    })
    if not default_input:
        provenance['scope'] = ('A bounded future-only intervention on the supplied full tape. '
                               'No observed witness is presumed; a passing repair covers only a saved case.')
    source_bytes = {}
    for name, expected in (('riskkit_strategy.py', riskkit.STRATEGY_HASH),
                           ('riskkit_sizing.py', riskkit.SIZING_HASH),
                           ('riskkit_LICENSE', LICENSE_SHA256)):
        path = SOURCE_DIR / name
        load_source(path, expected)
        source_bytes[name] = path.read_bytes()
    provenance['source_files'] = {name: {'path': f'source/{name}', 'sha256': hashlib.sha256(raw).hexdigest()}
                                  for name, raw in source_bytes.items()}

    folder = prepare_output(output)
    original = _run_audit(riskkit.original_run, tape, ORIGINAL_REF, ORIGINAL_SETTINGS, provenance)
    if default_input:
        original['headline'] = ('Public Riskkit defect reproduced on a SYNTHETIC stress tape'
                                if original['status'] == 'FOUND' else
                                'Riskkit investigation on a SYNTHETIC stress tape')
    fixed = _run_audit(riskkit.fixed_run, tape, FIXED_REF, CONTROL_SETTINGS, provenance)
    original['artifacts'] = {'json': 'report.json'}
    fixed['artifacts'] = {'json': 'report.json'}
    original['original_replay'] = {'status': 'MISSING', 'reason': 'No verified original witness was exported.',
                                   'adapter': ORIGINAL_REF}
    original['repair_replay'] = {'status': 'MISSING', 'reason': 'No saved original witness is available to replay.',
                                 'adapter': FIXED_REF}
    if original['status'] == 'FOUND':
        original['artifacts'].update(export_reproducer(original, folder, ORIGINAL_REF))
        fixture_path = folder / original['artifacts']['fixture']
        fixture_bytes = fixture_path.read_bytes()
        fixture = load_fixture(fixture_path)
        try:
            assert_future_invariance(riskkit.original_run, fixture)
        except InvarianceError as exc:
            original['original_replay'].update(status='DEPENDENCY_REPRODUCED', reason=str(exc))
        except (UnstableRunError, ValueError) as exc:
            original['original_replay'].update(status='FAILED', reason=str(exc))
        else:
            original['original_replay'].update(status='NOT_REPRODUCED', reason='Original callback was invariant on replay.')
        try:
            assert_future_invariance(riskkit.fixed_run, fixture)
        except (InvarianceError, UnstableRunError, ValueError) as exc:
            original['repair_replay'].update(status='FAILED', reason=str(exc))
        else:
            original['repair_replay'].update(status='PASS', reason='Repeated repaired runs preserve past positions on the exact saved tapes, cutoff, configuration and seed.')
        if fixture_path.read_bytes() != fixture_bytes:
            raise ValueError('Saved paired fixture changed during repair verification')

    active = sum(item['target'] != 0 for item in fixed['baseline']['trace'][100:])
    original['repair_activity'] = {
        'status': 'PASS' if active else 'FAILED', 'nonzero_bars': active,
        'warmup_end_index': 100, 'input_hash': fixed['dataset']['input_hash'],
        'reason': 'Full-tape repaired native trace has post-warmup nonzero positions.' if active else
                  'No post-warmup positions observed; invariance alone cannot verify an active repair.',
    }
    goog_provenance = {**deepcopy(provenance),
        'input': "Historical GOOG daily OHLCV sample bundled with Backtesting.py 0.6.6, also used by upstream's original example. "
                 'Complete 2,148-bar sample. Date-only labels encoded as midnight UTC for ordering, '
                 'not claimed exchange closes; available_at equals that explicit label convention.',
        'input_kind': 'historical', 'input_file_sha256': GOOG_CSV_SHA256,
        'scope': 'Negative control for the original full-GOOG example; unchanged positions in inspected interventions '
                 'do not establish global invariance. The notional cap can hide changes in backfilled indicators.'}
    goog = validate_rows(historical_rows())
    goog_provenance['input_sha256'] = canonical_hash(goog)
    historical = _run_audit(riskkit.original_run, goog, ORIGINAL_REF, CONTROL_SETTINGS, goog_provenance)
    historical['headline'] = ('HISTORICAL GOOG: no position dependency observed in inspected interventions'
                              if historical['status'] == 'NO_DEPENDENCY_OBSERVED' else
                              f"HISTORICAL GOOG control: {historical['status']}")
    historical['artifacts'] = {'json': 'report.json'}
    original['historical_control'] = {
        'status': historical['status'], 'reason': historical['reason'],
        'dataset': historical['dataset'], 'coverage': historical['coverage'],
        'report': 'historical-control/index.html',
        'scope': 'The original full historical GOOG sample is a separate bounded negative control; '
                 'the synthetic witness is not evidence that its positions were affected.',
    }
    verified = (original['status'] == 'FOUND'
                and original['original_replay']['status'] == 'DEPENDENCY_REPRODUCED'
                and original['repair_replay']['status'] == 'PASS'
                and fixed['status'] == 'NO_DEPENDENCY_OBSERVED'
                and original['repair_activity']['status'] == 'PASS')
    original['workflow_status'] = 'VERIFIED' if verified else 'INCOMPLETE'
    original['artifacts'].update({'fixed_report': 'fixed/index.html',
                                  'historical_control': 'historical-control/index.html'})
    for report_folder in (folder, folder / 'fixed', folder / 'historical-control'):
        source_folder = report_folder / 'source'
        source_folder.mkdir(parents=True)
        for name, raw in source_bytes.items():
            (source_folder / name).write_bytes(raw)
    write_report(fixed, folder / 'fixed')
    write_report(historical, folder / 'historical-control')
    write_report(original, folder)
    return original, folder


def command(args):
    """Exit zero only for a reproduced original defect and verified active repair."""
    from .cli import validate_output
    args._phase = 'output'
    validate_output(args.output)
    args._phase = 'settings'
    _require_dependencies()
    args._phase = 'execution'
    report, folder = run_future_demo(args.output)
    artifacts = {name: str(folder / relative) for name, relative in report['artifacts'].items()}
    artifacts['html'] = str(folder / 'index.html')
    summary = {'status': report['workflow_status'], 'original_status': report['status'],
               'input': report['provenance']['input'], 'dataset': report['dataset'],
               'witness': {key: report['witness'][key] for key in
                           ('cutoff', 'decision_timestamp', 'before_decision', 'after_decision')}
                          if report['witness'] else None,
               'original_replay': report['original_replay'], 'repair_replay': report['repair_replay'],
               'repair_activity': report['repair_activity'], 'historical_control': report['historical_control'],
               'artifacts': artifacts}
    if args.json:
        print(json.dumps(summary, allow_nan=False))
    else:
        print(f"{summary['status']}: existing public Riskkit defect on a SYNTHETIC 400-bar stress tape")
        witness = summary['witness']
        if witness:
            print(f"Past native position: {witness['before_decision']['target']} to {witness['after_decision']['target']} "
                  f"at {witness['decision_timestamp']} (fixed cutoff {witness['cutoff']})")
        print(f"Original replay: {summary['original_replay']['status']}; same-fixture repair: {summary['repair_replay']['status']}")
        print(f"Repaired full-tape activity: {summary['repair_activity']['nonzero_bars']} nonzero bars after warmup")
        print(f"Separate full historical GOOG control: {summary['historical_control']['status']}")
        print(f"Open report: {artifacts['html']}")
        if 'fixture' in artifacts:
            print(f"Original replay (expected exit 1): tradeoff reproduce {artifacts['fixture']}")
            print(f"Repaired replay: tradeoff reproduce {artifacts['fixture']} --adapter {FIXED_REF}")
    return 0 if report['workflow_status'] == 'VERIFIED' else 2


def add_future_demo_command(sub):
    from .cli import add_diagnostics_option
    parser = sub.add_parser('demo-bug', help='Reproduce a public-code future-data bug on a labelled synthetic tape, then verify its repair')
    parser.add_argument('--output', default='bug-output')
    parser.add_argument('--json', action='store_true', help='Emit a structured workflow summary')
    add_diagnostics_option(parser)
    parser.set_defaults(handler=command)
