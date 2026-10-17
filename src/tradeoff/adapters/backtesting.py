"""Capture Backtesting.py holdings through public Strategy hooks.

Documentation: https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html
"""

import warnings

from ..validation import validate_config, validate_rows, validate_trace
from ._shared import engine_version, frame_from_rows, numeric_setting, position_target, seeded, settings_dict


def make_backtesting_runner(strategy_class, *, engine_settings=None, prepare=None):
    """Return run(rows, config, seed) using a fresh Backtest and subclass.

    config is passed to Backtest.run as strategy parameters. Warmup bars before
    the first next() callback remain zero because the engine has not processed
    broker orders. Open terminal positions remain open. Positions are net and
    hedging is disabled. Margin is in (0, 1], with one meaning no leverage.
    exclusive_orders defaults to False, matching upstream accumulation and
    partial-cover behavior; explicitly True replaces positions on each order.
    Extra row fields are not supplied to the OHLCV feed; availability is audited
    by Tradeoff rather than enforced by the engine feed. Optional prepare(frame)
    runs afresh under the seed and may add columns, preserving the input OHLCV
    and index. Its preprocessing is part of the callback being audited.
    """
    options = settings_dict(engine_settings, {"cash": 10000, "commission": 0,
                                             "spread": 0, "trade_on_close": False, "margin": 1,
                                             "exclusive_orders": False})
    options["margin"] = numeric_setting(options["margin"], "margin", minimum=0,
                                        maximum=1, exclusive_minimum=True)
    if type(options["exclusive_orders"]) is not bool:
        raise ValueError("exclusive_orders must be a boolean")
    if prepare is not None and not callable(prepare):
        raise ValueError("prepare must be a callable or None")

    def run(rows, config, seed):
        rows = validate_rows(rows)
        config = validate_config(config)
        try:
            from backtesting import Backtest, Strategy
        except ImportError as exc:
            raise ImportError("Backtesting.py adapter requires pip install '.[adapters]'") from exc
        if not isinstance(strategy_class, type) or not issubclass(strategy_class, Strategy):
            raise ValueError("strategy_class must be a Backtesting.py Strategy subclass")
        trace = [{"timestamp": row["timestamp"], "target": 0,
                  "features": {"capture": "warmup_flat"}} for row in rows]

        class RecordingStrategy(strategy_class):
            def next(self):
                super().next()
                index = len(self.data) - 1
                trace[index] = {"timestamp": rows[index]["timestamp"],
                                "target": position_target(self.position.size),
                                "features": {"capture": "observed_position"}}

        with seeded(seed), warnings.catch_warnings():
            # Statistics omit open terminal trades; the adapter records holdings
            # instead of returning those statistics, and explicitly preserves them.
            warnings.filterwarnings("ignore", message="Some trades remain open.*", category=UserWarning)
            frame = frame_from_rows(rows)
            if prepare is not None:
                import pandas as pd
                expected_index = frame.index.copy()
                original_ohlcv = frame.copy(deep=True)
                frame = prepare(frame)
                if not isinstance(frame, pd.DataFrame):
                    raise ValueError("prepare must return a DataFrame")
                if not frame.index.equals(expected_index):
                    raise ValueError("prepare must preserve the complete original index")
                fields = original_ohlcv.columns.tolist()
                if (not frame.columns.is_unique or not set(fields) <= set(frame.columns)
                        or not frame[fields].equals(original_ohlcv)):
                    raise ValueError("prepare must preserve original OHLCV values and unique columns")
            backtest = Backtest(frame, RecordingStrategy, **options,
                                hedging=False,
                                finalize_trades=False)
            backtest.run(**config)
        return validate_trace(trace, rows)

    run.trace_kind = "observed_position"
    run.adapter_info = {"engine": "backtesting", "version": engine_version("backtesting"),
                        "engine_settings": options,
                        "warmup": "First bar and indicator warmup bars are explicitly flat; engine next() begins later.",
                        "timing": "Observed holdings after broker processing and Strategy.next(); not intended targets.",
                        "economics": "Projecting this trace adds Tradeoff's declared signal-to-fill lag to engine-observed holdings."}
    if prepare is not None:
        run.adapter_info["extra_feature_preparation"] = (
            "Fresh seeded preprocessing adds features while retaining the complete original OHLCV tape.")
    return run
