"""Real optional engine controls: audit clean_run or planted leaky_run.

Install: pip install -e '.[adapters]'
Run: backtest-witness audit --adapter examples.backtesting_demo:leaky_run --data bars.json --output backtesting-report
"""

from backtesting import Strategy

from backtest_witness.adapters.backtesting import make_backtesting_runner


class CleanStrategy(Strategy):
    def init(self):
        pass

    def next(self):
        if len(self.data) == 2 and self.data.Close[-1] > 9:
            self.buy(size=1)


class LeakyStrategy(Strategy):
    """Planted defect: init receives full data and caches a future statistic."""

    def init(self):
        self.full_sample_high = max(self.data.Close)

    def next(self):
        if len(self.data) == 2 and self.full_sample_high < 2 * self.data.Close[-1]:
            self.buy(size=1)


clean_run = make_backtesting_runner(CleanStrategy)
leaky_run = make_backtesting_runner(LeakyStrategy)
