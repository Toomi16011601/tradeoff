"""Capture one-feed Backtrader holdings via public Analyzer hooks.

Documentation: https://www.backtrader.com/docu/analyzers/analyzers/
"""

from ..validation import validate_config, validate_rows, validate_trace
from ._shared import engine_version, frame_from_rows, numeric_setting, position_target, seeded, settings_dict


def make_backtrader_runner(strategy_class, *, engine_settings=None):
    """Return run(rows, config, seed), rebuilding Cerebro and strategy each time.

    config is passed as strategy parameters. Supported engine settings are cash
    proportional commission and leverage (at least one). Feed timestamps are normalized to UTC; the
    returned trace preserves the caller's timestamps and records actual holdings,
    including prenext warmup. Availability is audited by BacktestWitness, not enforced by
    the engine feed. Extra row fields are not exposed through this OHLCV feed.
    """
    options = settings_dict(engine_settings, {"cash": 10000, "commission": 0, "leverage": 1})
    options["leverage"] = numeric_setting(options["leverage"], "leverage", minimum=1)

    def run(rows, config, seed):
        rows = validate_rows(rows)
        config = validate_config(config)
        try:
            import backtrader as bt
        except ImportError as exc:
            raise ImportError("Backtrader adapter requires pip install '.[adapters]'") from exc
        if not isinstance(strategy_class, type) or not issubclass(strategy_class, bt.Strategy):
            raise ValueError("strategy_class must be a Backtrader Strategy subclass")

        class PositionRecorder(bt.Analyzer):
            def start(self):
                self.records = []

            def next(self):
                index = len(self.strategy) - 1
                if index != len(self.records) or index >= len(rows):
                    raise ValueError("engine did not advance one row per position observation")
                self.records.append({"timestamp": rows[index]["timestamp"],
                                     "target": position_target(self.strategy.getposition(self.data).size),
                                     "features": {"capture": "observed_position"}})

            def get_analysis(self):
                return self.records

        with seeded(seed):
            cerebro = bt.Cerebro(stdstats=False)
            cerebro.adddata(bt.feeds.PandasData(dataname=frame_from_rows(rows)))
            cerebro.addstrategy(strategy_class, **config)
            cerebro.addanalyzer(PositionRecorder, _name="backtest_witness_positions")
            cerebro.broker.setcash(options["cash"])
            cerebro.broker.setcommission(commission=options["commission"], leverage=options["leverage"])
            strategies = cerebro.run(runonce=False, preload=True)
            trace = strategies[0].analyzers.backtest_witness_positions.get_analysis()
        return validate_trace(trace, rows)

    run.trace_kind = "observed_position"
    run.adapter_info = {"engine": "backtrader", "version": engine_version("backtrader"),
                        "engine_settings": options,
                        "warmup": "Analyzer prenext records positions from the first bar.",
                        "timing": "Observed holdings after broker processing and strategy callbacks; not intended targets.",
                        "economics": "Projecting this trace adds BacktestWitness's declared signal-to-fill lag to engine-observed holdings."}
    return run
