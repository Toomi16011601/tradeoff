"""Run with python -m examples.agent_integration from the repository checkout."""
import argparse
import json
from pathlib import Path
import sys

from . import run_example


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='failure-output-agent',
                        help='New or empty directory for local evidence')
    parser.add_argument('--json', action='store_true', help='Print one machine-readable result')
    args = parser.parse_args(argv)
    try:
        report = run_example(args.output)
    except (ImportError, ValueError, OSError) as exc:
        if args.json:
            print(json.dumps({'status': 'ERROR', 'error': str(exc)}, allow_nan=False))
        else:
            print(f'Cannot run example: {exc}', file=sys.stderr)
        return 2

    folder = Path(args.output).expanduser().resolve()
    failure = report.get('failure') or {}
    artifacts = {'json': str(folder / 'report.json'), 'html': str(folder / 'index.html')}
    artifacts.update({key: str(folder / name) for key, name in report['artifacts'].items()})
    summary = {'status': report['status'], 'baseline_metrics': report['baseline']['metrics'],
               'stress_metrics': failure.get('metrics'), 'failed_scenario': failure.get('scenario'),
               'requirements': report['requirements'], 'coverage': report['coverage'],
               'artifacts': artifacts}
    code = {'NO_FAILURE_OBSERVED': 0, 'FAILURE_FOUND': 1,
            'BASELINE_FAILED': 1, 'INCONCLUSIVE': 2}[report['status']]
    if args.json:
        print(json.dumps(summary, allow_nan=False))
    else:
        print(f"1. Ran the local Python agent on {report['dataset']['row_count']} synthetic bars.")
        print(f"2. Tested native cost/spread/delay scenarios: {report['status']}.")
        for label, metrics in (('Baseline', summary['baseline_metrics']),
                               ('Saved stress', summary['stress_metrics'])):
            if metrics:
                print(f"   {label}: return {metrics['return_pct']:.3f}%; "
                      f"closed trades {metrics['closed_trades']}.")
        if report['status'] == 'FAILURE_FOUND':
            print('   A policy breach is the expected teaching outcome (exit 1).')
        print(f"3. Inspect JSON: {artifacts['json']}\n   Open HTML: {artifacts['html']}")
        if failure:
            print(f"   Replay: python -m backtest_witness replay-failure {artifacts['fixture']}")
            print(f"   Regression: python -m pytest {artifacts['test']}")
    return code


if __name__ == '__main__':
    raise SystemExit(main())
