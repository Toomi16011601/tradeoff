# Bring an existing Backtesting.py strategy into Tradeoff

Use this path when a public or private project defines a `Strategy` class inside a script that also runs a backtest or opens a plot. Work in **your own project** with your own historical data. Tradeoff runs locally; it does not need your files copied into this repository.

## 1. Inspect the script without running it

```bash
tradeoff inspect-script path/to/original.py --json
```

The command parses the file and lists candidate strategy classes and obvious top-level backtest/plot calls. It does **not** import or execute the target. This is a bounded source scan, not a safety check: dynamic imports, decorators, helpers and imported modules may also have effects.

Make a small importable module for the strategy class and the imports/helpers it needs. If the original script puts its run and plot calls behind `if __name__ == "__main__":`, importing its class may be appropriate after reviewing its other top-level code. If it runs those calls on import, move the class and its dependencies into a separate module; importing the original script through a one-line wrapper would still run them. Keep live broker credentials and account state out of this simulation environment.

The result should be an import reference such as `strategy_adapter:MyStrategy`. Tradeoff does not automatically rewrite arbitrary scripts, import untrusted code during inspection, or invent missing strategy state.

## 2. Save the original engine baseline

In the original project's environment, run the unmodified strategy against the historical data and settings you intend to compare. If its script stores the `Backtest.run()` result in `stats`, export four native metrics:

```python
stats[["Return [%]", "Max. Drawdown [%]", "# Trades", "Equity Final [$]"]].to_json(
    "native-baseline.json"
)
```

Use the same Backtesting.py **0.6.6**, complete bar tape, starting cash, commission, sizing, strategy parameters and engine settings for the Tradeoff run. A different data conversion, warmup, final liquidation or engine option can change the baseline. Tradeoff refuses unsupported settings such as `finalize_trades=True`; do not silently drop a setting to force a comparison.

## 3. Choose what counts as a failure and run

This example tests sensitivity to a 2-percentage-point return drop and requires one closed trade. Choose values that fit your question; these are illustrative thresholds, not a target return or a trading recommendation.

```bash
tradeoff init-requirements --max-return-drop-pct 2 --min-closed-trades 1 \
  --output requirements.json

tradeoff lab --adapter strategy_adapter:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data daily.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --requirements requirements.json --output failure-output --json
```

Run from the strategy project's root so `strategy_adapter` is importable. Declare the **actual** symbol, timezone and timestamp convention for the feed. The example uses daily date-only labels; [other data formats](data-import.md) need different options. A verified policy breach exits 1; that is a finding, not a crashed run.

## 4. Check the baseline before using the stress finding

```bash
tradeoff check-baseline failure-output/report.json --expected native-baseline.json --json
```

This compares the supplied native metrics with Tradeoff's unstressed baseline. A mismatch means the integration or simulation context needs investigation before you trust the stress result. Inspect data rows and timestamp conversion, initial cash, fees, strategy parameters, trade timing, order settings, and the exact class/helpers imported. Optional reference context fields can check a declared dataset hash and engine settings; without them, the tool labels that context unverified. Even four matching summary metrics do not prove identical orders, positions or live behavior.

`MATCH` requires all four metrics plus matching declared dataset hash and engine settings. `METRICS_MATCH_CONTEXT_UNVERIFIED` means all four metrics match but at least one context field was not supplied; `PARTIAL_MATCH` means some metrics were not supplied. Those matching outcomes exit 0 only for the checks actually performed. `MISMATCH` exits 1, and invalid or unavailable evidence exits 2.

Open `failure-output/index.html` on your device to inspect the policy, completed scenario count, native trades and paired observations. `NO_FAILURE_OBSERVED` only means completed scenarios met the declared policy. Without `max_return_drop_pct`, a large drop from baseline can still pass if the other limits hold. A baseline that breaches an absolute limit produces `BASELINE_FAILED` before stress begins.

If the lab finds a verified failure, keep the original fixture and [replay it after a repair](quickstart.md#replay-a-repair). Never put private strategy code, historical data or report output into the public Tradeoff repository.
