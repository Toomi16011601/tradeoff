# Native strategy failure lab

The lab reruns a strategy in Backtesting.py 0.6.6 with altered execution assumptions. It records the engine's actual equity, positions, closed trades, open trades and pending orders. Its results are separate from the illustrative economic projection in the future-data audit.

## Start locally

```bash
python -m pip install -e ".[dev,lab]"
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data bars.csv --output failure-output
backtest-witness serve --directory failure-output
```

Use an importable Backtesting.py Strategy class. OHLCV input follows the [callback data contract](callback-contract.md); one instrument, aware timestamps and complete original history. Config JSON passes strategy parameters to `Backtest.run`.

For the pinned public strategies:

```bash
# Public case pins require Python 3.11+; locally tested on Python 3.12.
python -m pip install -e ".[dev,cases]"
backtest-witness lab-cases --output failure-public-output
# Expected exit 1: the casebook reproduces its declared policy failures.
backtest-witness serve --directory failure-public-output
```

The casebook tests original code and disclosed causal variants on frozen **synthetic** inputs. Its default policy allows at most 0.05 percentage points of deterioration from each variant's baseline, with at least one closed trade; minimum return is disabled. A baseline may lose money. Riskkit has a separate 400-bar execution input exercising post-warmup roundtrips; its 160-bar leakage fixture is preserved. The causal variant fixes the previously identified future-data dependency; it is not advertised as an execution-resilient repair.

## Declare what failure means

Save a JSON file, for example `requirements.json`:

```json
{
  "min_return_pct": 0,
  "max_drawdown_pct": 20,
  "max_return_drop_pct": 2,
  "min_closed_trades": 5
}
```

Pass `--requirements requirements.json`. These illustrative thresholds are a policy you choose before interpreting the results; they are not a trading recommendation. Percent return/drawdown and percentage-point deterioration have different units. Set a nullable requirement to `null` to disable it. The default minimum return is 0%, with drawdown/deterioration limits disabled and no minimum trade count. Closed trades exclude holdings still open at the end. A minimum trade count can prevent an inactive replacement from passing a repair test.

The baseline must meet absolute requirements. `BASELINE_FAILED` means it already fails, so stress is not blamed for that failure. `FAILURE_FOUND` means a repeated stressed run breaches a requirement. `NO_FAILURE_OBSERVED` means the completed declared suite passes. `INCONCLUSIVE` means instability, invalid/unsupported execution, or an incomplete passing suite prevents a comparable conclusion. A valid failure can coexist with other unavailable scenarios; every cell remains visible.

## Cost and delay semantics

Scenario values are **additional** to baseline settings:

```json
[
  {"name": "10 bps more commission", "commission_bps": 10},
  {"name": "One extra bar", "delay_bars": 1},
  {"name": "Combined", "commission_bps": 25, "spread_bps": 10, "delay_bars": 1}
]
```

Pass `--scenarios scenarios.json`. Omitted fields default to zero. A basis point is 0.01 percentage points. Additional commission follows native entry/exit charges. Additional spread follows native entry-price adjustment; it is not a full bid/ask order-book simulation.

Zero extra delay uses native next-open execution. One extra bar delays discretionary market entries and manual market closes by one further bar. Pending orders remain visible/cancellable, and delayed fills feed back into native affordability, sizing, cash and future decisions. Protective SL/TP brackets retain native timing. Positive-delay scenarios reject standalone stop/limit entries and trade-on-close execution; they do not approximate them silently. Open terminal positions are marked, and tail orders remain pending. No final exit is invented.

The delay hook is broker-local and gated to Backtesting.py 0.6.6. Orders submitted during `Strategy.init()` are unsupported in positive-delay scenarios because the initial feed exposes the full tape. Install the `lab` extra for the version pin. Other versions and unsupported execution engines refuse clearly. Backtrader remains supported by the [future-data audit integration](integrations.md).

## Reproduce and repair

A verified failure exports:

- `failure-fixture.json`: full unchanged tape, config, native baseline settings, stress, policy, version and hashes;
- `test_failure_resilience.py`: an importable pytest assertion against baseline and saved stress;
- `failure-receipt.json`: result/environment observations and integrity receipt;
- `report.json` and `index.html`: machine-readable evidence and the offline interface.

```bash
backtest-witness replay-failure failure-output/failure-fixture.json
# Exit 1: saved policy failure reproduced; 2: uncomparable/invalid.

python -m pytest failure-output/test_failure_resilience.py
# Expected to fail while the policy breach remains.

backtest-witness replay-failure failure-output/failure-fixture.json \
  --adapter my_strategy:RepairedStrategy --config repaired-parameters.json
```

Repair replay checks the current baseline and saved stress against the same requirements, using the unchanged hashed tape. It permits an explicit strategy/config replacement and prints the override. A version mismatch or unstable result refuses a repair claim. A passing repair covers this case; evaluate separate reserved cases before treating the change as broadly robust.

Reduction lowers scenario dimensions over declared tested levels while keeping every original bar. Strategy behaviour can be nonmonotonic as costs change sizing, so a reduced failure is not a globally minimal scenario or an exact break-even boundary. `--max-calls` counts every native invocation, including repeatability, reduction and final verification.

## Python and agent integration

```python
from backtest_witness.execution import resolve_execution_runner
from backtest_witness.failure_lab import run_failure_lab

run = resolve_execution_runner("my_strategy:MyStrategy", engine="backtesting",
                               engine_settings={"cash": 10000})
report = run_failure_lab(run, rows, config={"lookback": 20},
    requirements={"min_return_pct": 0, "max_drawdown_pct": 20},
    strategy_ref="my_strategy:MyStrategy")
```

The JSON report exposes policies, scenario results, unavailable reasons, coverage and paired evidence. An explicit `engine='callback'` can load a four-argument execution runner returning the [execution contract](execution-contract.md). Such callbacks own their accounting; the harness validates their output shape and repeatability, not their claimed simulator authenticity. `lab --json` emits a structured command summary. [Runnable public API example](../examples/failure_lab.py).

## Interpretation

The lab finds sensitivity under explicit simulation assumptions. It does not establish live fills, statistical significance, alpha, global robustness, model training hygiene or profitability. OHLC data cannot determine every intrabar path. Order-book liquidity, real latency, borrow availability, multi-asset portfolios and maintained forward-validation custody are outside this release. Use established engines and compare exact assumptions when investigating failures.
