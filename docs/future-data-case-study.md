# Public bug: future volatility changes an earlier position

This case reproduces a defect already present in Riskkit's published Backtesting.py example. The original source and position sizer are pinned and unchanged. **The positive witness uses a synthetic stress tape.** A separate historical GOOG control does not show an earlier-position difference under the declared tests.

## Run the complete investigation

From a Tradeoff checkout with Python 3.12:

```bash
python -m pip install '.[audit]'
tradeoff demo-bug --output bug-output --json
```

Open `bug-output/index.html` as a file. A successful demonstration returns workflow `VERIFIED` and exits 0 only after all of these checks:

1. The original callback produces a repeatable `FOUND` audit.
2. The saved fixture still fails with the original callback.
3. The repaired callback passes **that identical fixture**.
4. A fresh repaired audit finds no dependency within its inspected scope.
5. The repaired strategy holds nonzero positions after warmup on the full selected tape.

Keep the JSON, fixture, receipt and generated pytest beside the report. The output also retains unchanged upstream source/license files and separate repaired and historical-control reports. Use a new or empty output directory.

## The existing source defect

Pinned source: [Riskkit Backtesting.py example](https://github.com/HasibVortex369/riskkit/blob/99d1d167dc55c8a564526ef42d87e298f3e74fad/examples/backtesting_py_strategy.py), commit `99d1d167dc55c8a564526ef42d87e298f3e74fad`. The original example and [position sizer](https://github.com/HasibVortex369/riskkit/blob/99d1d167dc55c8a564526ef42d87e298f3e74fad/src/riskkit/sizing.py) are MIT licensed, copyright 2026 Hasib. Their notices accompany the bundled bytes.

The strategy computes a 100-bar rolling volatility estimate and calls `.bfill()`. Backward filling copies the first later complete estimate into earlier missing slots. Its 30-bar moving-average signal can trade before the 100-bar estimate was available, letting future prices influence earlier sizing.

The source strategy SHA-256 is `c048814bd21cae26002958c9b769c52ecf89ce052c89a47b18476015b4700d9b`; the sizer SHA-256 is `d32d36591d22b5643224075f854385015f01ff9a6a1a19e9169c4e581cd26f95`. Tradeoff verifies these bytes before loading the original classes and helpers. It omits upstream network/main paths; it preserves the trading rules, sizer, cash 100,000, commission 0.002 and nonexclusive order behavior.

## The observed witness

| Evidence | Result |
| --- | --- |
| Selected input | 400 hourly synthetic OHLCV bars |
| Earlier observed position | **29 → 31 units** at January 2, 2024, 18:00 UTC |
| Fixed cutoff | January 2, 2024, 20:00 UTC |
| Reduced future edit | One record: index 99, January 5, 2024, 03:00 UTC |
| Original saved-fixture replay | Dependency reproduced |
| Local repair on the same fixture | Pass |
| Repaired full-tape activity | 95 nonzero-position bars after warmup |

The detector retains every input row, timestamp and availability label. Rows available by the cutoff remain identical. Tests independently run the real Backtesting.py engine and compare the two observed-position traces, including 29 and 31 units at the affected bar. They also check that replay does not alter fixture bytes.

The input begins with the existing 160-bar seeded Riskkit stress tape and extends it with 240 disclosed oscillating bars so the repaired strategy can trade after warmup. [Exact data construction](public-strategies.md). It is a code-debugging counterexample, not a historical return or profitability study. Reduction removes unnecessary tested edits; it does not prove a globally smallest counterexample.

## The repair and its tradeoff

The local repair changes:

```diff
- return pd.Series(values).rolling(n).std().bfill().values
+ return pd.Series(values).rolling(n).std().values
```

Backtesting.py then waits for complete trailing indicators before calling `next()`. **This changes the warmup policy and skips the original early trades.** It does not preserve those trades or optimize their returns. Checking nonzero post-warmup activity prevents an entirely inactive replacement from being presented as a useful repair.

From the Tradeoff checkout, replay independently:

```bash
tradeoff reproduce bug-output/reproducer.json
# Expected exit 1: dependency reproduced.
tradeoff reproduce bug-output/reproducer.json \
  --adapter tradeoff.cases.riskkit:fixed_run
# Expected exit 0: the saved invariant holds.
```

The generated `test_future_invariance.py` likewise fails while resolving the original callback. To test a repair, use the explicit override above or an intentional source repair in your own project; do not alter the hashed input fixture.

## Historical GOOG negative control

The upstream example itself uses the 2,148-bar GOOG sample bundled with Backtesting.py 0.6.6 (2004–2013). The demo reruns that full sample with the original source/settings and declared audit scope. It returns `NO_DEPENDENCY_OBSERVED`: the tested edits do not change earlier positions. The original sizing cap can hide the noncausal indicator's effect on orders.

Development probes also compared all exposed early cutoffs 30–98 with the existing scale-up/down intervention families without observing an earlier-position difference. Those probes are not evidence of global independence. The saved historical-control report records the command's own scope and budget, separately from those exploratory checks.

The sample's date-only labels are encoded as midnight UTC to retain order; this is not a claimed exchange close. Raw dependency `GOOG.csv` SHA-256: `60e961a567490b157f71888df9e6afb36190a34a40a6286aa38988e2343f1b1a`. Tradeoff reads the installed dependency sample and does not separately redistribute it. [Original data tutorial](https://kernc.github.io/backtesting.py/doc/examples/Quick%20Start%20User%20Guide.html).

The positive synthetic witness establishes a real dependency in the pinned public code. It does **not** establish that the original full GOOG backtest was affected, that every Riskkit strategy has this defect, or that the causal repair will make money. No upstream issue, review or patch has been sent. [Methodology](methodology.md) · [Set up your project](quickstart.md).
