"""Real optional engine controls: audit clean_run or planted leaky_run.

Install: pip install -e '.[adapters]'
Run: backtest-witness audit --adapter examples.backtrader_demo:leaky_run --data bars.json --output backtrader-report
"""

import backtrader as bt

from backtest_witness.adapters.backtrader import make_backtrader_runner


class CleanStrategy(bt.Strategy):
    """Uses only the current bar and submits an explicit one-unit order."""

    def next(self):
        if len(self) == 1 and self.data.close[0] > 9:
            self.buy(size=1)


class LeakyStrategy(bt.Strategy):
    """Planted defect: reads the full preloaded close array during setup."""

    def __init__(self):
        self.full_sample_high = max(self.data.close.array)

    def next(self):
        if len(self) == 1 and self.full_sample_high < 2 * self.data.close[0]:
            self.buy(size=1)


clean_run = make_backtrader_runner(CleanStrategy)
leaky_run = make_backtrader_runner(LeakyStrategy)
