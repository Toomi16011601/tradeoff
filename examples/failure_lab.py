"""Run a public causal variant through the Python API; outputs stay local.

Install from the checkout: python -m pip install -e '.[dev,cases]'
Run: python -m examples.failure_lab
The frozen input is synthetic, and the policy measures deterioration, not alpha.
"""
from pathlib import Path


def main():
    from backtest_witness.cases import get_case
    from backtest_witness.failure_lab import run_failure_lab
    from backtest_witness.failure_reproduce import export_failure_reproducer
    from backtest_witness.report import write_failure_report
    case = get_case('riskkit')
    report = run_failure_lab(case['fixed_execution'], case['execution_rows'](),
        requirements={'min_return_pct': None, 'max_return_drop_pct': 0.05, 'min_closed_trades': 1},
        strategy_ref=case['fixed_execution_ref'],
        provenance={**case['provenance'], 'input': case['execution_input'], 'variant': 'fixed'})
    folder = Path('failure-output-api')
    if folder.exists():
        raise ValueError('Choose a new output folder to preserve earlier evidence')
    folder.mkdir()
    report['artifacts'] = {'json': 'report.json'}
    if report['failure']:
        report['artifacts'].update(export_failure_reproducer(report, folder, case['fixed_execution_ref']))
    write_failure_report(report, folder)
    print(report['status'], folder.resolve() / 'index.html')


if __name__ == '__main__':
    main()
