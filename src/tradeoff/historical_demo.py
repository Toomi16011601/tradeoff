"""Reproducible native-engine showcase using Backtesting.py's bundled GOOG bars."""
import json


STRATEGY_REF = 'tradeoff.historical_strategy:SmaCross'
REQUIREMENTS = {'min_return_pct': None, 'max_return_drop_pct': 2,
                'min_closed_trades': 1}


def _stress_label(scenario):
    parts = []
    for field, label in (('commission_bps', 'commission'), ('spread_bps', 'spread')):
        if scenario[field]:
            parts.append(f"+{scenario[field]:g} bps {label}")
    if scenario['delay_bars']:
        count = scenario['delay_bars']
        parts.append(f"+{count} {'bar' if count == 1 else 'bars'} delay")
    return ', '.join(parts) or 'no added execution stress'


def historical_rows():
    """Use the package's public sample, preserving its date-only index order.

    Midnight UTC encodes the sample's date labels for the lab; it does not
    assert that a GOOG trading session closed at midnight.
    """
    from backtesting.test import GOOG

    return [{'timestamp': day.strftime('%Y-%m-%dT00:00:00+00:00'),
             'symbol': 'GOOG',
             'open': float(bar.Open), 'high': float(bar.High),
             'low': float(bar.Low), 'close': float(bar.Close),
             'volume': int(bar.Volume)}
            for day, bar in GOOG.iterrows()]


def run_history_demo(output):
    """Run a complete native stress lab and export a replayable local result."""
    from .cli import prepare_output, validate_output
    from .execution import make_backtesting_execution_runner
    from .failure_cli import _save
    from .failure_lab import run_failure_lab

    validate_output(output)
    from .historical_strategy import SmaCross

    rows = historical_rows()
    runner = make_backtesting_execution_runner(SmaCross)
    report = run_failure_lab(runner, rows, {}, requirements=REQUIREMENTS,
        strategy_ref=STRATEGY_REF, provenance={
            'input': 'GOOG daily OHLCV sample bundled with Backtesting.py 0.6.6; '
                     'date-only index encoded as midnight UTC for bar ordering, not an exchange close.',
            'source': 'https://kernc.github.io/backtesting.py/doc/examples/Quick%20Start%20User%20Guide.html',
            'strategy': 'Tradeoff long/flat 10/20-day SMA crossover, adapted from the '
                        'Backtesting.py tutorial concept (its example also shorts).',
            'policy': 'At least one closed trade and no more than 2 percentage points of '
                      'return loss under the declared stress suite; no baseline profit floor.',
            'scope': 'Historical simulation, not evidence of profitable or live trading.'})
    folder = prepare_output(output)
    _save(report, folder, STRATEGY_REF)
    return report, folder


def command(args):
    """CLI wrapper; a verified policy breach deliberately exits with status 1."""
    args._phase = 'output'
    from .cli import validate_output
    validate_output(args.output)
    args._phase = 'settings'
    from .adapters._shared import engine_version
    if engine_version('backtesting') != '0.6.6':
        raise ImportError("Historical demo needs Backtesting.py 0.6.6; run python -m pip install '.[lab]'")
    try:
        from backtesting.test import GOOG  # noqa: F401 - verify the bundled sample is importable
    except ImportError as exc:
        raise ImportError("Historical demo dependencies are unavailable; run python -m pip install '.[lab]'") from exc
    args._phase = 'execution'
    report, folder = run_history_demo(args.output)
    failure = report.get('failure') or {}
    artifacts = {name: str(folder / relative)
                 for name, relative in report['artifacts'].items()}
    artifacts['html'] = str(folder / 'index.html')
    summary = {'status': report['status'], 'dataset': report['dataset'],
               'baseline_metrics': report['baseline']['metrics'],
               'stress_metrics': failure.get('metrics'),
               'failed_scenario': failure.get('scenario'),
               'requirements': report['requirements'], 'coverage': report['coverage'],
               'artifacts': artifacts}
    if args.json:
        print(json.dumps(summary, allow_nan=False))
    else:
        print(f"{report['status']}: GOOG historical sample, {report['dataset']['row_count']} daily bars")
        print(f"Coverage: {report['coverage']['completed']}/{report['coverage']['total']} native stress scenarios")
        for label, metrics in (('Baseline', summary['baseline_metrics']),
                               ('Saved stress', summary['stress_metrics'])):
            if metrics:
                print(f"{label}: {metrics['return_pct']:.2f}% return, "
                      f"{metrics['closed_trades']} closed trades")
        print(f"Open report file: {artifacts['html']}")
        if failure:
            print(f"Failing stress: {_stress_label(failure['scenario'])}")
            drop = summary['baseline_metrics']['return_pct'] - summary['stress_metrics']['return_pct']
            print(f"Return deterioration: {drop:.2f} percentage points "
                  f"(example limit {report['requirements']['max_return_drop_pct']:g})")
            print(f"Replay: tradeoff replay-failure {artifacts['fixture']}")
            print('Exit 1 is expected while this saved policy breach remains.')
    return {'NO_FAILURE_OBSERVED': 0, 'FAILURE_FOUND': 1,
            'BASELINE_FAILED': 1, 'INCONCLUSIVE': 2}[report['status']]
