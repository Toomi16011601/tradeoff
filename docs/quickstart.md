# Quickstart

BacktestWitness 0.3.0 is an unreleased local alpha. Install from this checkout; the core requires Python 3.10+, and pinned public cases require Python 3.11+ (tested locally on Python 3.12).

## Open the strategy failure lab

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,cases]"
backtest-witness lab-cases --output failure-public-output
# Expected exit 1: public variants breach the declared stress policy.
backtest-witness serve --directory failure-public-output
```

Open `http://127.0.0.1:8765`; Ctrl+C stops the localhost server. Secure HTTP preview supports macOS/Linux and rejects other origins, directory listings and symlinks. On other platforms, open a trusted generated `index.html` directly; it includes its own data, CSS and JavaScript. The casebook requires no prices download, credentials or API keys. Keep output directories new or empty.

Select a public variant, inspect its baseline and scenario matrix, then choose a scenario for native equity, positions and trade observations. Verified failure evidence shows the reduced stress and earliest changed observation. Replay & repair links the saved fixture, pytest regression and receipt.

The public policy disables minimum return, permits at most 0.05 percentage points of deterioration and requires one closed trade. It permits losing baselines. `fixed` means a disclosed causal variant of an independently reproduced future-data defect; it does not mean execution resilience. Riskkit uses a separate extended synthetic execution tape; CoinGlass uses its existing synthetic tape. [Public sources and data](public-strategies.md).

```bash
backtest-witness replay-failure failure-public-output/riskkit-original/failure-fixture.json
# Exit 1 when its saved policy breach is reproduced.
python -m pytest failure-public-output/riskkit-original/test_failure_resilience.py
# Expected to fail while that breach remains.
```

Artifact links exist only for verified failures. Use the paths shown in your generated report, especially with a custom policy, scenario suite or run budget.

## Test your own strategy

```bash
python -m pip install -e ".[dev,lab]"
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data bars.csv --requirements requirements.json --output failure-output
```

`MyStrategy` must be an importable Backtesting.py class. Save `requirements.json` before interpreting results:

```json
{
  "min_return_pct": 0,
  "max_drawdown_pct": 20,
  "max_return_drop_pct": 2,
  "min_closed_trades": 5
}
```

These example thresholds are user policy, not a trading recommendation. Nullable fields accept `null` to disable a requirement; the default minimum return is 0%, other limits are disabled and minimum closed trades is zero. Return/drawdown are percentages; return deterioration is percentage points. A baseline already failing absolute requirements yields `BASELINE_FAILED`.

CSV shape:

```csv
timestamp,available_at,symbol,open,high,low,close,volume
2026-01-01T09:30:00+00:00,2026-01-01T09:30:00+00:00,DEMO,100,102,99,101,1200
2026-01-01T09:35:00+00:00,2026-01-01T09:35:00+00:00,DEMO,101,103,100,102,1400
```

This snippet illustrates the schema; supply complete history and enough bars for warmup and trading. JSON accepts a list of row objects or `{"rows": [...]}`. Times are aware bar-close timestamps, normalized to UTC; `available_at` defaults to `timestamp`. The strategy must respect delayed availability. The engine receives the complete table. One instrument is supported. Config JSON passes parameters to `Backtest.run`.

Additional stress uses `commission_bps`, `spread_bps` and integer `delay_bars`, with omitted fields zero. Pass a JSON suite using `--scenarios`. Positive delay postpones discretionary market entries/manual closes beyond next-open timing; protective SL/TP stays native. Delayed standalone stop/limit orders, `Strategy.init` market orders and `trade_on_close` are unavailable. [Full execution guide](failure-lab.md).

## Replay a repair

```bash
backtest-witness replay-failure failure-output/failure-fixture.json \
  --adapter my_strategy:RepairedStrategy --config repaired-parameters.json
```

Both current baseline and saved stress must meet the unchanged policy on the full saved tape. Engine/version mismatch and unstable observations refuse comparison. Keep the fixture and receipt unchanged. The generated test resolves the saved runner; an in-place strategy fix can pass it directly, while an explicit alternative class/config can be checked with the CLI or [Python replay API](integrations.md). A passing case is a scoped regression, not general validation.

## Commands and files

| Command | Exit 0 | Exit 1 | Exit 2 |
| --- | --- | --- | --- |
| `lab` | Completed suite passes | Verified stress failure or baseline failure | Inconclusive / invalid / error |
| `lab-cases` | All variants have completed scoped passes | At least one policy failure | Any inconclusive case / invalid / error |
| `replay-failure` | Current baseline and saved stress meet policy | Comparable policy breach reproduced | Unstable / invalid / unavailable / error |
| `audit` | No dependency observed | Future-data dependency found | Inconclusive / invalid / error |
| `reproduce` | Tested future-data invariant holds | Dependency reproduced | Unstable / invalid fixture / error |

Every lab report writes `index.html` and `report.json`; verified stress failures additionally write `failure-fixture.json`, `failure-receipt.json` and `test_failure_resilience.py`. The public gallery also writes `case-results.json`. `--json` emits structured summaries for local tooling. No cloud upload occurs.

## Existing future-data workflow

```bash
python -m pip install -e ".[dev]"
backtest-witness demo --output demo-output
python -m pytest demo-output/leaky/test_future_invariance.py
# Expected failure: the planted dependency remains.
backtest-witness reproduce demo-output/leaky/reproducer.json \
  --adapter backtest_witness.demos:causal_run
# Exit 0: the saved invariant holds with this replacement.
backtest-witness audit --adapter examples.custom_adapter:run --data bars.csv \
  --output audit-output --min-history 5 --max-probes 20 --max-calls 160
```

Three-argument audit callbacks return one finite signed target per row. Audit findings export `reproducer.json`, `receipt.json` and `test_future_invariance.py`. Their curves remain illustrative projections on the original price tape, separate from native execution reports.

`backtest-witness cases --output public-output` retains the public future-data casebook and same-fixture causal repair checks; use `--case riskkit` or `--case coinglass` for one. [Callback contract](callback-contract.md), [engine/signal integration](integrations.md), [position sizing](position-sizing.md). All CLI options are documented by the corresponding `--help`.
