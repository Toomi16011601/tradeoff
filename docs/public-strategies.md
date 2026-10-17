# Public strategy failure and future-data cases

## Native execution failure casebook

The 0.3.0 failure lab reruns both pinned Backtesting.py 0.6.6 examples and their disclosed causal variants with native costs and market-order delay. It records engine equity, positions, closed/open trades and pending orders. Original strategy bytes and MIT notices remain unchanged.

```bash
python -m pip install -e ".[dev,cases]"
tradeoff lab-cases --output failure-public-output
# Expected exit 1: at least one variant has a policy failure.
```

Run these commands on your own computer, then open `failure-public-output/index.html` from your file manager in a browser. The reports are saved on your device and need no server to view.

Choose `--case riskkit` or `--case coinglass`, and `--variant original`, `fixed` or `both`. The default policy disables minimum return, caps deterioration at 0.05 percentage points from each variant's own baseline and requires one closed trade. Losing baselines remain visible; this policy does not establish profitability. Custom `--requirements` and `--scenarios` change the tested scope. A completed casebook returns 1 when any policy fails, 0 only for completed scoped passes, and 2 when any variant is inconclusive.

| Variant | Baseline closed trades | Verified result | Reduced additional commission |
| --- | --- | --- | --- |
| Riskkit original | 5 | `FAILURE_FOUND` | 5 bps |
| Riskkit causal variant | 3 | `FAILURE_FOUND` | 10 bps |
| CoinGlass original | 1 | `FAILURE_FOUND` | 25 bps |
| CoinGlass causal variant | 1 | `FAILURE_FOUND` | 25 bps |

These are observed results of the declared default synthetic casebook, not broker estimates, exact break-even costs or globally minimal failures. Each reduced scenario has zero added spread and delay; the full declared suite also includes native spread/delay scenarios. The generated `case-results.json` and individual `report.json` files retain metrics, invocation coverage, policy and provenance. No historical market performance claim follows from these tapes.

`fixed` repairs the separate future-data dependency described below. It is not an execution-resilient repair: both causal variants still breach this execution policy. Original variants retain known lookahead problems, so their returns cannot support a causal or alpha claim. Compare each variant only with its own native baseline under the stated assumptions.

### Execution input disclosure

Riskkit's original 160-bar leakage fixture leaves its causal variant inactive after warmup. For execution investigation, a separate frozen `riskkit_execution_rows.json` contains **400 bars**: the unchanged 160 original bars followed by 240 constructed oscillating bars. The tail closes are `100 + 12*sin(i/10) + uniform[-0.25,0.25]` with Python seed 17; each next open equals the previous close, the high/low envelope is a coherent 0.3%, and volume is 1,000. The tail deliberately creates post-warmup roundtrips. The original leakage tape and vendored source files are unchanged.

CoinGlass uses its existing frozen **256-bar** synthetic tape, described below. Both original and causal variants close trades on that input. The case loader exposes `execution_rows` and `execution_input` separately from the audit `rows` and provenance so reports disclose which tape was used.

### Save and replay the policy failure

```bash
tradeoff replay-failure failure-public-output/riskkit-original/failure-fixture.json
# Exit 1: comparable saved stress still breaches its policy.
python -m pytest failure-public-output/riskkit-original/test_failure_resilience.py
# Expected to fail until an execution repair meets the saved requirements.
```

Use the fixture paths in your generated report. Repair replay repeats both current baseline and saved stress on the full unchanged tape and policy; it does not silently relax the threshold or drop original history. An explicit adapter/config override supports a new repair, but switching to the causal variant alone is not a promised pass. Minimum closed trades prevents these public cases from passing with an inactive replacement. A passing saved case is a scoped regression; evaluate separate reserved cases for broader behavior. [Failure lab](failure-lab.md), [execution contract](execution-contract.md), [Python replay integration](integrations.md).

## Existing future-data casebook

Tradeoff runs the original trading logic from two public MIT-licensed examples through **Backtesting.py**, retains the actual quantities, and compares decisions before a fixed cutoff. The problems are already present in the pinned source; Tradeoff does not insert a defect into either original.

The inputs are frozen **synthetic stress tapes**, chosen to exercise the published logic. These are code-debugging case studies, not historical return studies, profitability evidence, endorsements, or claims that the same defect affects every strategy in either project. The causal repairs are local Tradeoff variants; they have not been submitted upstream.

## Run both future-data cases

Use Python 3.11 or newer for the pinned numerical dependencies. The full workflow was verified with Python 3.12.14.

```bash
python -m pip install -e ".[dev,cases]"
tradeoff cases --output public-output
```

Open `public-output/index.html` to view the gallery of original and repaired reports for each example. The original produces a hashed fixture and a runnable failing regression test; the command also verifies that the repair passes that **same fixture**. Choose one example with `--case riskkit` or `--case coinglass`.

| Published example | Verified earlier decision | Reduced future edits | Original | Local causal repair |
| --- | --- | --- | --- | --- |
| Riskkit `RiskkitSMA` | 29 → 31 units at 2024-01-02 18:00 UTC | 1 row | `FOUND` | Same fixture passes; `NO_DEPENDENCY_OBSERVED` in its inspected fresh audit |
| CoinGlass `SimpleCoinGlassStrategy` | 67 → 0 units at 2024-01-10 20:00 UTC | 2 rows | `FOUND` | Same fixture passes; `NO_DEPENDENCY_OBSERVED` in its inspected fresh audit |

These reductions preserve the complete original history and cutoff. They are greedy reductions of changed rows, not proofs of globally minimal counterexamples. A repaired negative audit covers the declared interventions, not all possible bugs.

## Riskkit: future volatility changes position sizing

Source: [Backtesting.py integration example](https://github.com/HasibVortex369/riskkit/blob/99d1d167dc55c8a564526ef42d87e298f3e74fad/examples/backtesting_py_strategy.py#L18-L51), pinned to commit `99d1d167dc55c8a564526ef42d87e298f3e74fad`.

The example computes a rolling standard deviation and calls `.bfill()`. Its 100-bar baseline fills the first 99 missing values with the first later complete estimate. The strategy can start trading after the 30-bar SMA warms up, so its earlier sizing consumes volatility from bars that have not happened yet.

This is a sizing bug: the original and intervention can both be long while holding different quantities. Reducing every position to a buy/flat boolean would miss it. Tradeoff runs the exact upstream `PositionSizer` and `SizingInputs` from [sizing.py](https://github.com/HasibVortex369/riskkit/blob/99d1d167dc55c8a564526ef42d87e298f3e74fad/src/riskkit/sizing.py), including its volatility adjustment, risk floors/ceilings and notional cap.

The local repair removes `.bfill()` from `rolling_std`. Backtesting.py then waits for the trailing indicators to warm up before calling `next()`. It changes the warmup policy; it does not tune the strategy for returns.

Original cash is 100,000 and commission is 0.002, as in the published example. The adapter retains the original nonexclusive order behavior, uses margin 1 and no hedging, and leaves terminal holdings open. No order quantity, stop, crossover condition or sizing parameter is replaced.

The frozen 160-bar tape uses NumPy seed 2: 25 closes at 100, 25 uniform closes between 45 and 155, then 110 closes at 100. High/low are close ± 2 and volume comes from a fixed seeded tape. The audit uses minimum history 45, eight sampled cutoffs and 256 callback calls. It reproduced the dependency in 238 calls, reducing to one future row.

## CoinGlass: sentiment remains a whole-series array

Source: [simple_backtest.py](https://github.com/aria-tjr/coinglass-trading-strategy/blob/761b236cfa93a1e6223ce5813da4b956a7481737/simple_backtest.py#L66-L166), pinned to commit `761b236cfa93a1e6223ce5813da4b956a7481737`.

Three parts of the original computation are unsafe for a historical decision:

- In `init()`, `self.sentiment = self.data.Sentiment` stores a complete array. It is not registered with `self.I`, so the stored array is not sliced by the engine as `next()` advances. Reading `self.sentiment[-1]` reads terminal sentiment at earlier bars.
- The preprocessing uses `rolling(3, center=True)`, so a sentiment value uses a following observation.
- Missing volume averages are filled with `volume.mean()` over the complete input; sentiment also uses backward filling.

The local repair registers sentiment through `self.I`, uses trailing volume/sentiment windows with `min_periods=1`, and uses forward-only filling. The RSI, EMA, ATR, entry/exit conditions, 10% relative sizing, stops and take-profit rules stay as published. Because several upstream unsafe operations coexist, the paired failure does not establish a separate impact for each one.

The loader extracts original helper functions and the strategy class using the Python AST. It also extracts the exact pure sentiment statements from `get_simple_data`, lines 147–166, into a function receiving the supplied raw DataFrame. Every intervention reruns those calculations. Data download, API connection, dotenv, reporting and `__main__` paths are omitted. No exchange connection or API key is used.

Original cash 100,000, commission 0.001 and exclusive orders are retained. The adapter uses margin 1, no hedging, and leaves terminal holdings open. Stops and fills are processed by the real engine; the trace contains observed signed quantities, not inferred entry signals.

The frozen 256-bar tape uses NumPy seed 73 and normally distributed log returns with standard deviation 0.07. Volume is 1,000 except the last three bars at 2,000. The audit uses minimum history 240, six sampled cutoffs and 128 callback calls. It reproduced the dependency in 36 calls and reduced to two future rows. The input's volatility is deliberately a stress case, not a representative market sample.

## Portable future-data regression workflow

After generating `public-output`, run an original fixture and then verify the repaired callback against it:

```bash
tradeoff reproduce public-output/riskkit-original/reproducer.json
tradeoff reproduce public-output/riskkit-original/reproducer.json \
  --adapter tradeoff.cases.riskkit:fixed_run
```

The original should exit 1 with a reproduced dependency; the repair should exit 0. The precise output paths appear in the command's summary and gallery. The exported pytest test imports `tradeoff.cases.riskkit:original_run`; switching its callback to the repaired reference verifies the same before/after tape.

You can also use the same registry from Python:

```python
from tradeoff.audit import audit
from tradeoff.cases import get_case

case = get_case("riskkit")
report = audit(
    case["original"], case["rows"](), case["config"],
    strategy_ref=case["original_ref"],
    trace_kind="observed_position",
    **case["audit_settings"],
)
assert report["status"] == "FOUND"
```

## Source integrity and licensing

The source files are bundled unchanged under `src/tradeoff/cases/sources/`, together with each project's MIT notice. Their bytes are checked before execution. Local repairs are applied only after verifying the original source hash; no patched upstream file is distributed under the original hash.

| Bundled file | Original SHA-256 |
| --- | --- |
| `riskkit_strategy.py` | `c048814bd21cae26002958c9b769c52ecf89ce052c89a47b18476015b4700d9b` |
| `riskkit_sizing.py` | `d32d36591d22b5643224075f854385015f01ff9a6a1a19e9169c4e581cd26f95` |
| `coinglass_strategy.py` | `2c97d75c14f74901493b3bf292d8f8e36787bb52b1c463828f83f60eda67fbd5` |

Riskkit is Copyright (c) 2026 Hasib. CoinGlass example code is Copyright (c) 2026 Aria Tajeri. The original MIT notices apply to those files. The pinned runtime is Backtesting.py 0.6.6, pandas 2.2.3 and NumPy 2.3.5. Tradeoff does not vendor either trading engine.

An audit witness establishes a changed historical position under a future-only intervention. Temporal audit economic projections remain Tradeoff's separately declared model; they are not the original engine's full ledger or causal attribution of profit. Native failure reports use actual engine reruns, as described above.
