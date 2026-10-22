"""A small, original long/flat SMA crossover for the public history demo.

This module is imported only by the optional native-engine demo or its replay.
"""
from backtesting import Strategy


def simple_moving_average(values, window):
    """Return a trailing average, with no signal before a full window exists."""
    prices = list(values)
    averages = [float('nan')] * len(prices)
    running = 0.0
    for index, price in enumerate(prices):
        running += float(price)
        if index >= window:
            running -= float(prices[index - window])
        if index >= window - 1:
            averages[index] = running / window
    return averages


class SmaCross(Strategy):
    """Buy when the 10-day average crosses above the 20-day; close below."""
    fast_window = 10
    slow_window = 20

    def init(self):
        self.fast = self.I(simple_moving_average, self.data.Close, self.fast_window)
        self.slow = self.I(simple_moving_average, self.data.Close, self.slow_window)

    def next(self):
        if self.fast[-2] <= self.slow[-2] and self.fast[-1] > self.slow[-1]:
            if not self.position:
                self.buy()
        elif self.fast[-2] >= self.slow[-2] and self.fast[-1] < self.slow[-1]:
            if self.position:
                self.position.close()
