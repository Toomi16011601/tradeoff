# Historical GOOG demo

Run `tradeoff demo-history --output historical-output` after installing `.[lab]`. Open `historical-output/index.html` as a file; no server is needed. The command deliberately exits 1 when its example policy fails. `--json` gives a machine-readable summary.

The input is the 2,148 daily GOOG OHLCV bars from `backtesting.test.GOOG` in pinned Backtesting.py 0.6.6, covering 19 August 2004 through 1 March 2013. Tradeoff does not download or redistribute this data separately. The data's date-only labels are encoded as midnight UTC to preserve the native row order; that is **not** a claimed exchange close time. The [Backtesting.py tutorial](https://kernc.github.io/backtesting.py/doc/examples/Quick%20Start%20User%20Guide.html) introduces the data and an SMA crossover. Tradeoff supplies its own long/flat variant: buy after the 10-day average crosses above the 20-day, and close after it crosses below. Unlike the tutorial example, it does not short.

The native baseline starts with 10,000 cash, zero commission and spread, next-open fills, default full-size `buy()` orders, and no forced liquidation of an open trade at the final bar. Its reported return includes marked-to-market open holdings. The demo policy requires at least one closed trade and permits at most a 2-percentage-point drop from that baseline. It sets no minimum profitable return. The finite default suite adds 5–200 bps commission, 5–25 bps spread, 1–2 extra bars of discretionary market-order delay, and a combined case. Delay leaves native protective-order timing alone. Each scenario executes twice; a saved failure gets fresh baseline and stress verification.

With this pinned engine, the baseline ends at 75,645.99 (656.46% return; 46 closed trades). The first failing case adds 5 bps commission and ends at 72,620.69 (626.21% return), a 30.25-percentage-point deterioration. All 12 scenarios complete. The test suite compares the reported baseline with an independent direct `Backtest(GOOG, SmaCross, ...)` run using the same settings.

The output includes `report.json`, offline `index.html`, `failure-fixture.json`, `failure-receipt.json`, and `test_failure_resilience.py`. Replay with:

```bash
tradeoff replay-failure historical-output/failure-fixture.json
# Expected exit 1 while the saved breach remains.
```

The fixture retains all original input bars, the strategy reference, engine settings, policy, baseline and stress observations. It is a regression test for this historical simulation, **not** evidence that a strategy will make money or that future costs will match these assumptions. To test your own strategy, use [`tradeoff lab`](failure-lab.md) with your own data, explicit timestamp convention and chosen policy. Review any generated files before sharing; they can contain the entire input tape.
