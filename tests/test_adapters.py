"""Adapter behavior against installed engines, rather than engine doubles."""

import importlib.util
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest


# Backtrader 1.9.78.123 emits this upstream deprecation on Python >= 3.12.
pytestmark = pytest.mark.filterwarnings(
    r"ignore:datetime.datetime.utcnow\(\) is deprecated.*:DeprecationWarning:backtrader.cerebro")


def rows(count=12):
    start = datetime(2026, 1, 1, 16, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(days=i)).isoformat(), "symbol": "SYNTH",
             "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}
            for i in range(count)]


def require(engine):
    return pytest.importorskip(engine)


def test_importing_adapters_keeps_optional_engines_unloaded():
    code = """import sys
import backtest_witness.economics
import backtest_witness.adapters.backtrader
import backtest_witness.adapters.backtesting
assert not any(name in sys.modules for name in ('backtrader', 'backtesting', 'pandas', 'numpy'))
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_backtrader_captures_each_real_position_and_rebuilds_strategy():
    bt = require("backtrader")
    from backtest_witness.adapters.backtrader import make_backtrader_runner

    class Once(bt.Strategy):
        params = (("size", 1),)

        def __init__(self):
            self.ordered = False

        def next(self):
            if not self.ordered:
                self.buy(size=self.p.size)
                self.ordered = True

    runner = make_backtrader_runner(Once)
    data = rows(6)
    before = deepcopy(data)
    result = runner(data, {"size": 1}, 7)
    assert [entry["target"] for entry in result] == [0, 1, 1, 1, 1, 1]
    assert [entry["timestamp"] for entry in result] == [row["timestamp"] for row in data]
    assert runner(data, {"size": 1}, 7) == result
    assert runner.trace_kind == "observed_position"
    assert data == before


def test_backtrader_captures_multi_unit_shorts_increases_and_reversals():
    bt = require("backtrader")
    from backtest_witness.adapters.backtrader import make_backtrader_runner

    class Rebalance(bt.Strategy):
        def next(self):
            targets = {1: -2, 3: -3, 5: 1, 7: 0}
            if len(self) in targets:
                self.order_target_size(target=targets[len(self)])

    trace = make_backtrader_runner(Rebalance)(rows(9), {}, 7)
    assert [entry["target"] for entry in trace] == [0, -2, -2, -3, -3, 1, 1, 0, 0]


def test_backtesting_captures_complete_real_positions_including_warmup():
    api = require("backtesting")
    from backtest_witness.adapters.backtesting import make_backtesting_runner

    class Once(api.Strategy):
        size = 1

        def init(self):
            self.ordered = False

        def next(self):
            if not self.ordered:
                self.buy(size=self.size)
                self.ordered = True
            elif len(self.data) == 5:
                self.position.close()

    runner = make_backtesting_runner(Once)
    data = rows(6)
    before = deepcopy(data)
    result = runner(data, {"size": 1}, 7)
    assert [entry["target"] for entry in result] == [0, 0, 1, 1, 1, 0]
    assert [entry["timestamp"] for entry in result] == [row["timestamp"] for row in data]
    assert runner(data, {"size": 1}, 7) == result
    assert runner.trace_kind == "observed_position"
    assert data == before


def test_backtesting_does_not_drop_indicator_warmup_bars():
    api = require("backtesting")
    np = require("numpy")
    from backtest_witness.adapters.backtesting import make_backtesting_runner

    class Warmup(api.Strategy):
        def init(self):
            self.warm = self.I(lambda: np.array([np.nan, np.nan, 1, 1, 1, 1]))

        def next(self):
            if len(self.data) == 4:
                self.buy(size=1)
            if len(self.data) == 5:
                self.position.close()

    trace = make_backtesting_runner(Warmup)(rows(6), {}, 7)
    assert [entry["target"] for entry in trace] == [0, 0, 0, 0, 1, 0]
    assert trace[0]["features"]["capture"] == "warmup_flat"


@pytest.mark.parametrize("exclusive", [None, False, True])
def test_backtesting_matches_upstream_accumulation_partial_cover_and_reversal(exclusive):
    api = require("backtesting")
    pd = require("pandas")
    from backtest_witness.adapters.backtesting import make_backtesting_runner

    class Rebalance(api.Strategy):
        def init(self):
            pass

        def next(self):
            if len(self.data) == 2:
                self.sell(size=2)
            if len(self.data) == 4:
                self.sell(size=1)
            if len(self.data) == 6:
                self.buy(size=1)
            if len(self.data) == 8:
                self.buy(size=4)
            if len(self.data) == 10:
                self.position.close()

    data = rows(11)
    recorded = [0] * len(data)

    class UpstreamRecorder(Rebalance):
        def next(self):
            super().next()
            recorded[len(self.data) - 1] = self.position.size

    frame = pd.DataFrame({name.title(): [row[name] for row in data]
                          for name in ("open", "high", "low", "close", "volume")},
                         index=pd.to_datetime([row["timestamp"] for row in data], utc=True).tz_localize(None))
    options = {} if exclusive is None else {"exclusive_orders": exclusive}
    api.Backtest(frame, UpstreamRecorder, **options, finalize_trades=False).run()
    expected = ([0, 0, -2, -2, -1, -1, 1, 1, 4, 4, 0] if exclusive else
                [0, 0, -2, -2, -3, -3, -2, -2, 2, 2, 0])
    assert recorded == expected
    runner = make_backtesting_runner(Rebalance, engine_settings=options)
    trace = runner(data, {}, 7)
    assert [entry["target"] for entry in trace] == recorded
    assert runner.adapter_info["engine_settings"]["exclusive_orders"] is bool(exclusive)


@pytest.mark.parametrize("exclusive", [0, 1, "false", None])
def test_backtesting_exclusive_orders_requires_an_explicit_boolean(exclusive):
    from backtest_witness.adapters import make_backtesting_runner
    with pytest.raises(ValueError, match="exclusive_orders"):
        make_backtesting_runner(object, engine_settings={"exclusive_orders": exclusive})


@pytest.mark.parametrize("engine,setting", [("backtrader", {"leverage": 2}), ("backtesting", {"margin": 0.5})])
def test_engine_leverage_settings_are_applied_to_actual_broker(engine, setting):
    api = require(engine)
    adapter = importlib.import_module(f"backtest_witness.adapters.{engine}")

    class Leveraged(api.Strategy):
        def init(self):
            pass

        def next(self):
            index = len(self) if engine == "backtrader" else len(self.data)
            if index == (1 if engine == "backtrader" else 2):
                self.buy(size=15)

    runner = getattr(adapter, f"make_{engine}_runner")(Leveraged, engine_settings={"cash": 100, **setting})
    trace = runner(rows(6), {}, 7)
    assert trace[-1]["target"] == 15
    assert runner.adapter_info["engine_settings"].items() >= setting.items()


@pytest.mark.parametrize("engine,setting", [
    ("backtrader", {"leverage": 0.5}), ("backtrader", {"leverage": True}),
    ("backtesting", {"margin": 0}), ("backtesting", {"margin": 1.1}),
    ("backtesting", {"margin": float("nan")}), ("backtesting", {"margin": "0.5"}),
])
def test_engine_rejects_invalid_exposure_setting_before_running(engine, setting):
    adapter = importlib.import_module(f"backtest_witness.adapters.{engine}")
    with pytest.raises(ValueError, match="leverage|margin"):
        getattr(adapter, f"make_{engine}_runner")(object, engine_settings=setting)


def test_position_target_normalizes_numpy_holdings_without_coercing_strings_or_booleans():
    np = require("numpy")
    from backtest_witness.adapters._shared import position_target
    assert position_target(np.int64(-12)) == -12
    assert position_target(np.float32(-0.25)) == -0.25
    assert type(position_target(np.float64(-0.0))) is int
    for value in (True, np.bool_(True), "2", complex(1, 0), np.float64("nan")):
        with pytest.raises(ValueError, match="quantity"):
            position_target(value)


def test_backtesting_prepares_extra_feature_columns_afresh_inside_seeded_run():
    api = require("backtesting")
    from backtest_witness.adapters import make_backtesting_runner

    class FeatureStrategy(api.Strategy):
        def init(self):
            pass

        def next(self):
            if len(self.data) == 2 and self.data.Feature[-1] > 0:
                self.sell(size=3)

    calls = []

    def prepare(frame):
        assert "Feature" not in frame
        calls.append(random.random())
        frame["Feature"] = frame["Close"].rolling(2).mean()
        return frame

    runner = make_backtesting_runner(FeatureStrategy, prepare=prepare)
    data = rows(6)
    first = runner(data, {}, 7)
    assert [entry["target"] for entry in first] == [0, 0, -3, -3, -3, -3]
    assert runner(data, {}, 7) == first
    assert calls[0] == calls[1]
    assert "extra_feature_preparation" in runner.adapter_info


@pytest.mark.parametrize("mode", ["drop", "reindex", "price", "wrong_type"])
def test_backtesting_preparation_cannot_change_original_market_tape(mode):
    api = require("backtesting")
    from backtest_witness.adapters import make_backtesting_runner

    class Flat(api.Strategy):
        def init(self):
            pass

        def next(self):
            pass

    def prepare(frame):
        if mode == "drop":
            return frame.iloc[1:]
        if mode == "reindex":
            return frame.iloc[::-1]
        if mode == "price":
            frame["Close"] = 100
        if mode == "wrong_type":
            return frame.to_numpy()
        return frame

    with pytest.raises(ValueError, match="prepare|OHLCV|index|DataFrame"):
        make_backtesting_runner(Flat, prepare=prepare)(rows(6), {}, 7)


@pytest.mark.parametrize("engine", ["backtrader", "backtesting"])
def test_seeded_engine_run_preserves_callers_random_state(engine):
    api = require(engine)
    np = require("numpy")
    adapter = importlib.import_module(f"backtest_witness.adapters.{engine}")
    base = api.Strategy

    class RandomChoice(base):
        def __init__(self, *args, **kwargs):
            if engine == "backtesting":
                super().__init__(*args, **kwargs)

        def init(self):
            self.choice = random.random() + np.random.random()

        def next(self):
            if engine == "backtrader" and len(self) == 1:
                self.choice = random.random() + np.random.random()
                if self.choice > 1:
                    self.buy(size=1)
            elif engine == "backtesting" and len(self.data) == 2 and self.choice > 1:
                self.buy(size=1)

    runner = getattr(adapter, f"make_{engine}_runner")(RandomChoice)
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    first = runner(rows(), {}, 7)
    assert random.getstate() == python_state
    after = np.random.get_state()
    assert after[0] == numpy_state[0]
    assert (after[1] == numpy_state[1]).all()
    assert after[2:] == numpy_state[2:]
    assert runner(rows(), {}, 7) == first


@pytest.mark.parametrize("engine", ["backtrader", "backtesting"])
def test_real_engine_examples_prove_clean_and_leaky_controls(engine):
    require(engine)
    from backtest_witness.audit import audit

    example = importlib.import_module(f"examples.{engine}_demo")
    data = rows()
    clean = audit(example.clean_run, data, min_history=3, max_probes=3, max_calls=50,
                  trace_kind="observed_position")
    leaky = audit(example.leaky_run, data, min_history=3, max_probes=3, max_calls=50,
                  trace_kind="observed_position")
    assert clean["status"] == "NO_DEPENDENCY_OBSERVED"
    assert leaky["status"] == "FOUND"
    assert leaky["trace_kind"] == "observed_position"
    assert leaky["witness"]["before_decision"]["target"] != leaky["witness"]["after_decision"]["target"]


@pytest.mark.parametrize("engine", ["backtrader", "backtesting"])
def test_leaky_engine_example_also_reproduces_on_default_synthetic_tape(engine):
    require(engine)
    from backtest_witness.audit import audit
    from backtest_witness.demos import synthetic_rows

    example = importlib.import_module(f"examples.{engine}_demo")
    report = audit(example.leaky_run, synthetic_rows(), min_history=3,
                   max_probes=2, max_calls=50, trace_kind="observed_position")
    assert report["status"] == "FOUND"
