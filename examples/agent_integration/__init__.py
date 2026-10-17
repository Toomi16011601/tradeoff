"""A small agent-to-native-engine integration, runnable from the checkout.

Install: python -m pip install '.[lab]'
Run: python -m examples.agent_integration --output failure-output-agent
The synthetic tape and deterioration policy teach integration, not profitability.
"""
from datetime import datetime, timedelta, timezone


STRATEGY_REF = 'examples.agent_integration.strategy:AgentStrategy'
REQUIREMENTS = {'min_return_pct': None, 'max_return_drop_pct': 0.5,
                'min_closed_trades': 1}


def synthetic_rows():
    """Return a fresh frozen one-instrument rise/fall/flat teaching tape."""
    closes = (100, 100, 101, 102, 104, 106, 108, 110, 108,
              106, 104, 102, 100, 100, 100, 100, 100)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index, close in enumerate(closes):
        opening = closes[max(0, index - 1)]
        rows.append({'timestamp': (start + timedelta(days=index)).isoformat(),
                     'symbol': 'AGENT-SYN', 'open': opening,
                     'high': max(opening, close) + 1,
                     'low': min(opening, close) - 1, 'close': close, 'volume': 1000})
    return rows


def run_example(output, *, config=None):
    """Run the existing full default stress suite and save its real evidence.

    Optional config overrides native strategy parameters, e.g. units/lookback.
    New or empty output is checked before loading or executing the strategy.
    """
    from tradeoff.cli import prepare_output

    folder = prepare_output(output)
    from tradeoff.execution import make_backtesting_execution_runner
    from tradeoff.failure_lab import run_failure_lab
    from tradeoff.failure_reproduce import export_failure_reproducer
    from tradeoff.report import write_failure_report
    from .strategy import AgentStrategy

    options = {'units': 30, 'lookback': 3}
    if config is not None:
        options.update(config)
    runner = make_backtesting_execution_runner(AgentStrategy)
    report = run_failure_lab(runner, synthetic_rows(), options,
        requirements=REQUIREMENTS, strategy_ref=STRATEGY_REF,
        provenance={'input': 'Frozen synthetic 17-bar one-instrument teaching tape.',
                    'policy': 'At least one closed trade; maximum 0.5 percentage-point '
                              'return deterioration. No minimum-profit requirement.',
                    'agent': 'Ordinary deterministic Python long/flat decision function.'})
    report['artifacts'] = {'json': 'report.json'}
    if report.get('failure'):
        report['artifacts'].update(export_failure_reproducer(report, folder, STRATEGY_REF))
    write_failure_report(report, folder)
    return report
