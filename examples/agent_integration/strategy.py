"""Translate agent decisions into native Backtesting.py market orders."""
from backtesting import Strategy
from backtest_witness.privacy import ExecutionUnavailable

from .agent import decide


class AgentStrategy(Strategy):
    """Minimal long/flat adapter; the existing native broker owns accounting."""

    units = 30
    lookback = 3

    def init(self):
        if type(self.units) is not int or self.units < 1:
            raise ValueError('units must be a positive whole number')
        if type(self.lookback) is not int or self.lookback < 2:
            raise ValueError('lookback must be an integer of at least 2')

    def next(self):
        # Delayed entry and manual-close orders stay pending across callbacks.
        # Wait for them instead of submitting the same decision repeatedly.
        if self.orders:
            return
        history = tuple(float(close) for close in self.data.Close)
        action = decide(history, self.position.size, lookback=self.lookback)
        if action not in ('buy', 'close', 'hold'):
            raise ExecutionUnavailable('Agent must return buy, close or hold')
        if action == 'buy':
            self.buy(size=self.units)
        elif action == 'close':
            self.position.close()
