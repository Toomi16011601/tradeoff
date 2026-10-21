# Native strategy failure lab

The lab runs on your own computer and reruns a strategy in Backtesting.py 0.6.6 with altered execution assumptions. It saves the engine's actual equity, positions, closed trades, open trades and pending orders on your device. Its results are separate from the illustrative economic projection in the future-data audit.

## Start locally

```bash
python -m pip install '.[lab]'
tradeoff init-requirements --max-return-drop-pct 2 --min-closed-trades 1 \
  --output requirements.json
tradeoff lab --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data daily.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --requirements requirements.json --output failure-output --json
```

Open `failure-output/index.html` from your file manager in a browser. The report is a saved file; viewing it needs no server or connection to the publisher's computer.

Install from the checkout, then run from your own project's root with an importable Backtesting.py `Strategy` class. The example uses provider-style `Date,Open,High,Low,Close,Volume` headers; choose the actual symbol, timezone and closing convention for your data. Config JSON passes strategy parameters to `Backtest.run`. For a class inside a script that also runs a backtest, follow the [static inspection and baseline comparison guide](script-strategy-onboarding.md).

For intraday bar-open labels, use `--timestamp-kind open --bar-duration 1h`; normalized close times remain separate from preserved source-clock columns. Existing normalized CSV/JSON is also accepted. No missing observations, volume or exchange calendar is invented. [Import guide](data-import.md).

The CLI validates an occupied output directory before importing a strategy or starting simulations. Choose a new or empty directory for each run.

## Check inputs before interpreting results

Native CLI preflight inspects direct strategy-method data attributes and referenced globals initialized to `None`. `--require-column Time` and `--require-global MARKET_FILTER` add explicit prerequisites when helpers or dynamic access hide a dependency. These checks are bounded; they cannot verify arbitrary Python setup or financial semantics.

Preserved extra input columns reach the native frame. For a strategy that needs its original bar-open clock, `--column-map '{"Time":"Datetime"}'` copies the source string while the engine index uses normalized bar-close time. A companion-market filter still needs initialization in an importable adapter. `--companion-data data/market.csv` binds the selected file's relative path and hash; it does not populate a strategy global.

All-zero volume is visible as a data warning. If the inspected strategy reads volume, it blocks the run unless `--allow-zero-volume` explicitly acknowledges partial validation. `--allow-uninitialized-global NAME` acknowledges an intentionally optional `None` global; it cannot waive an explicit required global. Neither acknowledgement repairs missing strategy inputs.

`lab --json` returns safe structured input errors with phase and code. For a caught strategy exception, use `--diagnostics private-trace.txt` with a new file outside the report output. That private file can reveal source lines, paths and raw exception messages. Indicator/helper incompatibilities in third-party code may still require a reviewed manual repair or dependency pin. [Input declarations and troubleshooting](data-import.md#check-strategy-prerequisites).

For the pinned public strategies:

```bash
# Public case pins require Python 3.11+; locally tested on Python 3.12.
python -m pip install -e ".[dev,cases]"
tradeoff lab-cases --output failure-public-output
# Expected exit 1: the casebook reproduces its declared policy failures.
```

Open `failure-public-output/index.html` to browse the generated reports.

The casebook tests original code and disclosed causal variants on frozen **synthetic** inputs. Its default policy allows at most 0.05 percentage points of deterioration from each variant's baseline, with at least one closed trade; minimum return is disabled. A baseline may lose money. Riskkit has a separate 400-bar execution input exercising post-warmup roundtrips; its 160-bar leakage fixture is preserved. The causal variant fixes the previously identified future-data dependency; it is not advertised as an execution-resilient repair.

## Declare what failure means

Create a policy file with thresholds you choose:

```bash
tradeoff init-requirements --max-return-drop-pct 2 --min-closed-trades 1 \
  --output requirements.json
```

The command writes a complete policy with `min_return_pct` and `max_drawdown_pct` set to `null`, a 2-percentage-point maximum drop from the same baseline, and a minimum of one closed trade. It refuses to overwrite an existing file. You can also set an absolute return or drawdown limit explicitly; percent return/drawdown and percentage-point deterioration have different units. These numbers illustrate the workflow, not a trading recommendation. Closed trades exclude holdings still open at the end. A minimum trade count can prevent an inactive replacement from passing a repair test.

Pass `--requirements requirements.json` to `lab`. Omitting that flag retains the older default: minimum return 0%, with drawdown and relative-deterioration limits disabled and no minimum trade count. Under that policy, a large return decline versus a profitable baseline can still pass. The CLI summary calls out this missing limit and scenario coverage; the offline report lists the policy and coverage in its requirements and scope sections. Read those fields before interpreting `NO_FAILURE_OBSERVED`.

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

The delay hook is broker-local and gated to Backtesting.py 0.6.6. Orders submitted during `Strategy.init()` are unsupported in positive-delay scenarios because the initial feed exposes the full tape. Install the `lab` extra for the version pin. Other versions and unsupported execution engines refuse clearly. Terminal finalization is fixed to `finalize_trades=False`; `finalize_trades=True` is unsupported. An upstream project using final liquidation therefore has a different engine profile; assess and disclose that difference rather than silently treating it as equivalent. Backtrader remains supported by the [future-data audit integration](integrations.md).

## Reproduce and repair

A verified failure exports:

- `failure-fixture.json`: full unchanged tape, config, native baseline settings, stress, policy, version and hashes;
- `test_failure_resilience.py`: an importable pytest assertion against baseline and saved stress;
- `failure-receipt.json`: result/environment observations and integrity receipt;
- `report.json` and `index.html`: machine-readable evidence and the offline interface.

```bash
tradeoff replay-failure failure-output/failure-fixture.json
# Exit 1: saved policy failure reproduced; 2: uncomparable/invalid.

python -m pytest failure-output/test_failure_resilience.py
# Expected to fail while the policy breach remains.

tradeoff replay-failure failure-output/failure-fixture.json \
  --adapter my_strategy:RepairedStrategy --config repaired-parameters.json
```

Repair replay checks the current baseline and saved stress against the same requirements, using the unchanged hashed tape. It permits an explicit strategy/config replacement and prints the override. A version mismatch or unstable result refuses a repair claim. A passing repair covers this case; evaluate separate reserved cases before treating the change as broadly robust.

Run replay and generated pytest from the strategy project root. Declared companion files are checked for availability and unchanged hashes before resolving the runner and executing it. They are not copied into exports. Keep their saved relative layout, source and dependency environment separately: a fixture is not a bundled strategy environment. Native CLI report provenance records available strategy/adapter file hashes and known engine, pandas and NumPy versions. Those source hashes document the tested state; repairs remain allowed and imported helpers are not exhaustively captured.

Reduction lowers scenario dimensions over declared tested levels while keeping every original bar. Strategy behaviour can be nonmonotonic as costs change sizing, so a reduced failure is not a globally minimal scenario or an exact break-even boundary. `--max-calls` counts every native invocation, including repeatability, reduction and final verification.

## Python and agent integration

```python
from tradeoff.execution import resolve_execution_runner
from tradeoff.failure_lab import run_failure_lab

run = resolve_execution_runner("my_strategy:MyStrategy", engine="backtesting",
                               engine_settings={"cash": 10000}, integration={})
checks = run.preflight(rows)
report = run_failure_lab(run, rows, config={"lookback": 20},
    requirements={"min_return_pct": 0, "max_drawdown_pct": 20},
    strategy_ref="my_strategy:MyStrategy", provenance=run.source_provenance)
report["input_checks"] = checks
```

The JSON report exposes policies, scenario results, unavailable reasons, coverage and paired evidence. Python callers enable optional native input checks with `integration={}` or explicit declarations; the CLI enables them automatically. An explicit `engine='callback'` can load a four-argument execution runner returning the [execution contract](execution-contract.md). Automatic inspection cannot see a callback's wrapped strategy. Such callbacks own their accounting; the harness validates their output shape and repeatability, not their claimed simulator authenticity. `lab --json` emits a structured command summary, including input checks. [Runnable public API example](../examples/failure_lab.py).

## Interpretation

The lab finds sensitivity under explicit simulation assumptions. It does not establish live fills, statistical significance, alpha, global robustness, model training hygiene or profitability. OHLC data cannot determine every intrabar path. Order-book liquidity, real latency, borrow availability, multi-asset portfolios and maintained forward-validation custody are outside this release. Use established engines and compare exact assumptions when investigating failures.
