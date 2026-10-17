# Methodology and limits

Tradeoff has two assertions: execution resilience under declared simulation assumptions, and future-data invariance at a fixed cutoff. They use separate observations, schemas and replay tests.

## Native execution failure procedure

1. Validate the complete one-instrument tape, strategy config, engine settings, nonnegative stress scenarios and user requirements.
2. Run the zero-additional-stress baseline twice in fresh native Backtesting.py 0.6.6 state. Compare full observations, including equity, trades and pending orders.
3. If baseline absolute requirements pass, repeat each declared cost/delay scenario. Record PASS, FAIL, UNAVAILABLE or NOT_RUN with its concrete reason.
4. Select a reproducible policy breach and lower scenario dimensions over declared tested levels plus zero. Preserve every original bar and reserve final repeated baseline/stress verification.
5. Export the full-tape fixture, generated pytest and receipt, with native observations and the declared search scope.
6. Replay a repair against current baseline and the saved stress under the same requirements and tape; refuse unstable or engine/version-mismatched comparison.

The default suite adds 5/10/25/50/100/200 bps commission, 5/10/25 bps native spread, one/two extra delay bars and a combined 25-bps commission / 10-bps spread / one-bar-delay scenario. Costs add to baseline settings. Commission follows native entry/exit charges; spread follows native entry-price adjustment. These are engine assumptions, not order-book liquidity estimates. Every invocation, including repeats, reduction and final verification, counts toward the call budget.

Zero extra delay preserves native timing. Positive delay postpones discretionary market entries and manual market closes beyond normal next-open matching. Pending orders stay visible/cancellable; cash, affordability and sizing feed back into later native decisions. Protective SL/TP retains native timing. Delayed standalone stop/limit orders, `Strategy.init` market orders and `trade_on_close` are unsupported and reported unavailable. Open terminal holdings remain marked and tail orders pending; no final exit is invented.

Summaries derive return and maximum drawdown from the native equity stream, including initial cash in the running peak. A closed-trade requirement excludes still-open holdings. Open native trade P&L may exclude entry fees, while equity includes charged fees; open-trade observations are not a settled account ledger. The existing temporal audit projection is not reused.

| Result | Supported conclusion |
| --- | --- |
| `FAILURE_FOUND` | A repeated stressed simulation breaches the declared policy; other unavailable cells remain visible. |
| `BASELINE_FAILED` | Baseline already fails absolute requirements; stress is not blamed for it. |
| `NO_FAILURE_OBSERVED` | The completed declared suite meets the requirements. |
| `INCONCLUSIVE` | Invalid, unstable, unsupported or incomplete passing evidence prevents a comparable conclusion. |

Requirements must be explicit when interpreting a result. Nullable minimum return, maximum drawdown and maximum return deterioration can be disabled. Return/drawdown use percentages; deterioration uses percentage points relative to the same variant's baseline. The default minimum return is 0%, other limits are disabled and minimum closed trades is zero. Public synthetic cases instead disable minimum return, cap deterioration at 0.05 percentage points and require one closed trade, so losing baselines remain visible. These are teaching policies, not trading recommendations.

Changed paired equity/positions locate divergence, not causal allocations of lost profit. Costs can change position sizes and subsequent strategy paths nonmonotonically. A reduced failure covers declared tested levels; it is not a globally minimal scenario or an exact break-even boundary. Passing replay covers the saved case and can overfit it; separate reserved cases are needed to assess broader behavior. A minimum trade count helps prevent an inactive replacement from passing.

Native execution support is gated to Backtesting.py 0.6.6. Explicit four-argument callbacks own their claimed simulator accounting. This release does not model live fills, real latency, full intrabar paths, order-book liquidity, multi-asset portfolios, training hygiene, statistical significance, alpha, profitability or maintained forward-validation custody. [Execution guide](failure-lab.md), [execution contract](execution-contract.md).

## Future-data invariant

Tradeoff tests a temporal invariant: changing records unavailable at a fixed cutoff should not change targets already produced at or before that cutoff. It is an intervention test of a local callback, not an economic certification.

## Future-data audit procedure

1. Validate input bars, configuration and complete target trace. Repeat the baseline with fresh input copies.
2. Sample cutoffs after declared warmup, up to the search budget.
3. Scale future-available OHLC/volume deterministically while preserving timestamps, coherent bars and input history.
4. Repeat the intervention and compare timestamp/target pairs through the fixed cutoff.
5. When a reproducible difference is found, remove unnecessary row edits while preserving the witness. Verify the final paired inputs within the call budget.
6. Export the paired fixture, receipt and regression test. Render evidence and conditional modeled economics.

Later availability includes delayed earlier events. The cutoff never moves during reduction. The full dataset is retained, so changing warmup/history length cannot create an artificial comparison. “Reduced” describes removal of tested edits; it does not mean the globally smallest counterexample.

## Meaning of future-data results

| Result | Supported conclusion | Unsupported conclusion |
|---|---|---|
| FOUND | Saved future-only intervention reproducibly changes a tested past target | Every leak found; source line identified; all historical profit is invalid |
| NO_DEPENDENCY_OBSERVED | Inspected interventions leave tested targets unchanged | Leak-free; statistically valid alpha; safe to trade |
| INCONCLUSIVE | Comparison could not be established under the stated conditions | Clean or leaky |

Budget and scope are part of the result. The detector stops on an observed witness; it does not enumerate all defects. Unchanged targets can hide changed continuous scores. OHLC/volume mutations do not test extra feature fields, publication-date corrections, retrieval leakage, survivorship, pretrained model contamination, news timing, private caches or multi-asset dependencies. An adversarial or stateful callback can invalidate comparison assumptions. Reruns check target repeatability, not the full dependency graph.

## Temporal audit economic projection

Both decision traces use the **original unperturbed price tape**. Signal at bar t executes at the open t + `fill_lag_bars`, with a minimum lag of one bar. Treat input OHLC as reference midpoint prices. For side +1 (buy) or −1 (sell):

```text
fill = reference_open × [1 + side × (full_spread_bps/2 + slippage_bps)/10000]
fee  = fixed_fee + abs(quantity × fill) × fee_bps/10000
```

Targets are finite signed quantities, including fractional units. Each fill trades target minus current quantity; a reversal is one rebalance with its fee allocated between closing and opening units. Average entry basis includes opening fees. Closing fees and short borrow reduce realized P&L. Repeated targets produce no additional fills. Persistent rejected targets retry; tail signals without an eligible future bar remain unapplied. Terminal equity marks signed holdings at the last close, with no invented exit. Realized plus open P&L reconciles with terminal equity minus starting cash.

`max_leverage` (default 1) caps new gross exposure relative to post-trade reference-open equity. Short cash proceeds cannot increase that capacity. Over-cap targets are rejected completely; risk-reducing closes and partial reductions remain allowed after loss or insolvency, even if settled cash becomes negative. Close-time cap breaches and nonpositive equity are recorded as `risk_events`; the projection does not impose maintenance margin or forced liquidation. Leveraged long borrowing has no financing charge in this model.

`short_borrow_bps_annual` (default 0) accrues against previous short quantity × previous close, over the actual interval between aware timestamps, using a 365-day year. The charge reduces cash and realized P&L and appears in a separate borrow ledger. There are no dividends, borrow recalls, locate availability, taxes, perpetual funding or security-specific margin rules. The projection is conditional on the declared assumptions; it does not establish live executability.

Sensitivity cases remove fill and borrow costs, double them, or add one fill-delay bar. Leverage remains fixed. The one-share buy/hold reference uses the same capital and price model but is not exposure-matched. Differences are conditional intervention effects under this model, not measured causal shares of original backtest profit. This temporal-audit projection does not claim actual engine ledger parity, especially for observed-position adapters. Native execution reports use the separate engine reruns described above.

The implementation uses finite binary floats and checks reconciliation with a 1e-9 absolute / 1e-10 relative tolerance. Extreme capital/price scales that lose economically meaningful fill precision are rejected. If a main projection cannot be represented, the CLI preserves the audit finding and exports, showing unavailable economics with the specific reason. Invalid economic parameters are rejected. An invalid stress case is marked `UNAVAILABLE` rather than assigned a zero P&L.

## Receipts

Content hashes detect accidental changes to saved inputs/configuration. They are not signatures, third-party attestations, proofs of code identity, dependency locks or evidence that a model has never seen the test data. Save your source revision and environment separately when making a research claim.

## Prior art

[Freqtrade](https://www.freqtrade.io/en/stable/lookahead-analysis/) already tests lookahead through reruns and comparison. [SharpeBench](https://github.com/general-liquidity/sharpebench) covers framework-neutral audit/stress workflows. Tradeoff focuses on bounded failure investigation, saved evidence and portable regression tests around existing engines; it makes no first-ever stress-testing or detector claim. Optional engine behavior follows the public [Backtesting.py API](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html) and [Backtrader analyzer hooks](https://www.backtrader.com/docu/analyzers/analyzers/).
