# Strategy and engine integrations

BacktestWitness checks a strategy you already provide. A trading agent supplies the decisions; Backtesting.py executes its native orders; BacktestWitness reruns it under execution stress and reports policy violations. A coding agent can run the same CLI or Python calls and read structured JSON to guide a repair. The browser is an offline report of a completed run.

Start with the [runnable agent integration](agent-integration.md) for a small decision function, native adapter and local tool wrapper, or the [quickstart](quickstart.md) for the install/run/replay flow. There is no agent SDK, MCP server or live broker connection in this release.

Execution failure investigation and future-data invariance use separate runner contracts. Backtesting.py 0.6.6 is the first native execution backend; Backtrader, pandas and numeric targets retain their future-data audit scope.

## Native strategy execution

```bash
python -m pip install '.[lab]'
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data bars.csv --requirements requirements.json --output failure-output
```

Each scenario creates fresh strategy and native broker state. Additional commission/spread feed into native fees, affordability and sizing; the output records native equity, signed positions, closed trades, open trades and pending orders. Positive delay postpones discretionary market entries and manual closes beyond native next-open execution. Protective SL/TP keeps native timing. Delayed standalone stop/limit orders, market orders created in `Strategy.init`, and `trade_on_close` refuse comparison. No terminal liquidation is added. Other Backtesting.py versions refuse execution, because the delay hook depends on the tested broker implementation.

```python
from backtest_witness.execution import resolve_execution_runner
from backtest_witness.failure_lab import run_failure_lab

run = resolve_execution_runner("my_strategy:MyStrategy", engine="backtesting",
                               engine_settings={"cash": 10000})
report = run_failure_lab(
    run, rows, config={"lookback": 20},
    requirements={"min_return_pct": 0, "max_drawdown_pct": 20,
                  "min_closed_trades": 5},
    strategy_ref="my_strategy:MyStrategy",
)
```

Use an installed or otherwise importable strategy module. Run checkout examples and their generated tests/replays from the repository root; `examples/` is not included in the installed package.

`rows` must satisfy the [data contract](callback-contract.md); config maps to `Backtest.run` strategy parameters. The API accepts `scenarios`, `seed`, `max_calls` and optional provenance. Its report exposes requirements, coverage, unavailable reasons and full native observations. [Runnable example](../examples/failure_lab.py), [failure lab guide](failure-lab.md), [execution contract](execution-contract.md).

Custom preprocessing uses `make_backtesting_execution_runner(MyStrategy, prepare=prepare_features, engine_settings=...)`. The factory reruns preparation under the seed on every tape. Preparation may add columns but must preserve the complete original index and OHLCV. Export it through an importable four-argument callback, then use `lab --engine callback`. Explicit callbacks return `run(rows, config, seed, scenario)` observations and own their simulator accounting; shape validation and repeated equality do not prove accounting authenticity.

For an alternative repair runner from Python:

```python
from backtest_witness.failure_reproduce import load_failure_fixture, assert_failure_resilience

fixture = load_failure_fixture("failure-output/failure-fixture.json")
repair = resolve_execution_runner("my_strategy:RepairedStrategy",
                                  **fixture["runner_spec"])
assert_failure_resilience(repair, fixture, config={"lookback": 30})
```

The assertion repeats current baseline and saved stress, requires the saved engine/version and unchanged policy, and raises `ResilienceError` for a comparable policy failure. Invalid/nonrepeatable executions raise `ValueError`. Historical observations remain evidence of the original failure; repairs need not reproduce their returns. Generated pytest uses the sibling fixture and saved runner. [Report/artifact schema](report-schema.md).

## Future-data audit integrations

Install extras from this checkout:

```bash
python -m pip install '.[adapters]'
```

The future-data integration tests execute **Backtrader 1.9.78.123** and **Backtesting.py 0.6.6**, with pandas 2.2.3 and NumPy 2.3.5 in the local Python 3.12 build environment. Compatibility with other versions is not implied. The core works without these optional dependencies.

## Backtrader future-data adapter

```python
import backtrader as bt
from backtest_witness.adapters.backtrader import make_backtrader_runner

class MyStrategy(bt.Strategy):
    def next(self):
        # Your strategy; this example intentionally stays flat.
        pass

run = make_backtrader_runner(MyStrategy)
```

Each callback call creates a new Cerebro, feed, broker, strategy and analyzer. Public analyzer hooks capture position after strategy processing, including warmup bars. Strategy config maps to framework strategy parameters; optional factory `engine_settings` configures the engine. Finite signed observed positions are supported, including multi-unit shorts and fractional holdings allowed by the engine. The adapter does not report pending order intention or recreate canceled/rejected orders as targets.

## Backtesting.py future-data adapter

```python
from backtesting import Strategy
from backtest_witness.adapters.backtesting import make_backtesting_runner

class MyStrategy(Strategy):
    def init(self):
        pass

    def next(self):
        pass

run = make_backtesting_runner(MyStrategy)
```

Each call creates a new Backtest and recording subclass. `init()` can inspect the full frame, so full-sample preprocessing bugs remain observable; `next()` uses the engine's progressive view. Warmup bars have declared zero positions, and recorded positions are aligned to the full original index. Terminal trade finalization is disabled; it must not manufacture a close solely to complete the trace.

The public [Backtesting.py API](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html) explains next-open execution, warmup and initialization. [Backtrader analyzer documentation](https://www.backtrader.com/docu/analyzers/analyzers/) describes the capture hooks.

## Run the repository examples

Create input bars from the bundled synthetic dataset:

```bash
python -c "import json; from backtest_witness.demos import synthetic_rows; print(json.dumps(synthetic_rows()))" > bars.json
backtest-witness audit --adapter examples.backtrader_demo:leaky_run \
  --data bars.json --output backtrader-report --trace-kind observed_position
backtest-witness audit --adapter examples.backtesting_demo:leaky_run \
  --data bars.json --output backtesting-report --trace-kind observed_position
```

Both files also expose `clean_run` for comparison. Findings return exit code 1, so shell pipelines must treat that as a finding rather than a crash. For integration development, install `'.[dev,adapters]'` with pip, then run `python -m pytest tests/test_adapters.py` for actual engine controls. These examples are checkout files, not package-shipped modules.

## What future-data adapters record

Both adapters expose `run.trace_kind = "observed_position"` and `run.adapter_info`. The CLI uses that metadata unless explicitly overridden. Engine positions differ from desired target units: a past intention might change without a filled position changing. The audit therefore detects dependencies visible in the position trace only.

The report's economic projection applies its own signed rebalances, fill delay, costs and exposure cap to recorded positions. This is an illustrative model, **not** the engine's actual ledger. The adapters do not claim order-level fill parity. Unavailable-data restrictions are the strategy's responsibility; engines receive the complete table so that mistakes can be detected.

Build an integration for another engine by honoring the [callback contract](callback-contract.md), documenting its trace meaning and testing a planted defect plus a clean control on real executions.

## Audit a class without writing a callback

```bash
backtest-witness audit --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "margin": 0.5}' \
  --data bars.json --output strategy-report --initial-cash 10000 --max-leverage 2
```

The engine settings describe the actual engine run; projection settings independently describe the conditional ledger. Backtesting.py `margin` is the required fraction of position value (0.5 permits 2× engine leverage). Backtrader accepts `cash`, `commission` and `leverage`; Backtesting.py accepts `cash`, `commission`, `spread`, `trade_on_close`, `margin` and boolean `exclusive_orders`. The latter defaults to upstream's `False`, allowing position accumulation; use `True` for order replacement behavior, including compatibility with BacktestWitness 0.1.0. Engines impose their own sizing and broker rules. Backtesting.py's standard engine fills whole units; its fractional order argument is a fraction of available equity, not fractional shares. Core target/signal adapters accept fractional quantities.

Saved fixtures preserve the selected adapter and effective engine options. `backtest-witness reproduce fixture.json` and the generated pytest reconstruct the same runner. Override a repaired class with `--adapter fixed_strategy:MyStrategy`; use `--engine callback` when the override is a raw callback instead of a class.

## Numeric or pandas signals

```python
def positions(rows, config, seed):
    return [5 if row["close"] > row["open"] else -3 for row in rows]

def signals(frame, units=5):
    return ((frame.close > frame.close.rolling(5).mean()).astype(int) * units)
```

Use `--engine targets` for the first function and `--engine pandas` for the second. The pandas input has a UTC DatetimeIndex, lowercase OHLCV and all original fields; return an identically indexed numeric Series or a DataFrame with `target`. Configure a different column with `--engine-settings '{"target_column":"position"}'`. These functions demonstrate interface shape; respect `available_at` for delayed records.

For derived features in a Backtesting.py strategy, `make_backtesting_runner(MyStrategy, prepare=prepare_features)` reruns preprocessing under the seed on every supplied tape. The engine frame has Titlecase OHLCV and a naive DatetimeIndex representing UTC, consistent with the existing engine feeds. `prepare_features(frame)` must retain the exact index and OHLCV; it may add feature columns. This differs from the UTC-aware lowercase pandas signal interface. Use an importable callback that reconstructs the factory when exporting custom preprocessing. [Public cases](public-strategies.md) show a complete example.
