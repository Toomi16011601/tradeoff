# Quickstart

BacktestWitness is a local crash-test and debugging lab for a trading strategy before deployment. Your strategy decides what to trade, Backtesting.py 0.6.6 simulates its orders, and BacktestWitness checks how extra execution costs and delays affect your declared requirements.

The browser opens a completed run's interactive report. Start new runs from the CLI or Python. This unreleased alpha installs from a repository checkout; the core requires Python 3.10+.

## 1. Install from the checkout

Run these commands from the repository root, where `pyproject.toml` and `examples/` are located:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[lab]'
```

On Windows PowerShell, replace the activation command with `.\.venv\Scripts\Activate.ps1`. The `lab` extra installs the pinned native execution engine. The example uses synthetic prices and needs no data download, credentials or AI API keys.

## 2. Run the small agent example

```bash
python -m examples.agent_integration --output failure-output-agent
```

**Expected: `FAILURE_FOUND` and exit code 1.** The example is designed to teach the failure loop. Its baseline makes closed trades; execution stress breaches a declared relative-return policy: at most 0.5 percentage points of deterioration from its own baseline, with at least one closed trade. Minimum return is disabled, so the policy is not a profitability test. A failure is a useful result, not a crashed installation. Use a new or empty output directory; choose another name for later runs.

The files separate the decisions from the simulator:

- [`agent.py`](../examples/agent_integration/agent.py): the small deterministic trading decision function you can replace.
- [`strategy.py`](../examples/agent_integration/strategy.py): a Backtesting.py adapter that converts long/flat decisions into native orders.
- [`__init__.py`](../examples/agent_integration/__init__.py): synthetic input, explicit policy, run and artifact export.
- [`__main__.py`](../examples/agent_integration/__main__.py): the CLI entry point and JSON summary.

The [agent integration walkthrough](agent-integration.md) explains how to replace each part and let a coding agent consume the results.

## 3. Open and inspect the report

```bash
backtest-witness serve --directory failure-output-agent
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Ctrl+C stops the loopback server. Secure HTTP preview supports macOS/Linux; on other platforms, open the trusted generated `failure-output-agent/index.html` directly. The HTML contains its data, CSS and JavaScript and works offline.

Start with the baseline and policy, select a stressed scenario in the matrix, then inspect its native equity, positions and trades. Verified failure evidence records the reduced stress and changed observations. Replay & repair points to the fixture, pytest regression and receipt. These are saved results; changing a selection does not run the strategy again.

You should have:

| File | Purpose |
| --- | --- |
| `report.json` | Structured policy, metrics, scenarios, coverage and native observations |
| `index.html` | Offline interactive report |
| `failure-fixture.json` | Saved tape, runner, policy and verified stress |
| `failure-receipt.json` | Evidence and integrity receipt |
| `test_failure_resilience.py` | Regression assertion for a repair |

The last three files exist only for verified stress failures.

## 4. Replay the failure

From the checkout root, with the same environment active:

```bash
backtest-witness replay-failure failure-output-agent/failure-fixture.json
# Expected exit 1: the saved policy breach is reproduced.
python -m pip install 'pytest>=9.0.3'
python -m pytest failure-output-agent/test_failure_resilience.py
# Expected test failure while the breach remains.
```

The saved runner is `examples.agent_integration.strategy:AgentStrategy`. The checkout root makes this example module importable. For a separate agent project, install its strategy package or otherwise make its module importable in the environment that runs replay and pytest.

## Test your own strategy

For a native Backtesting.py class, save `requirements.json`:

```json
{
  "min_return_pct": 0,
  "max_drawdown_pct": 20,
  "max_return_drop_pct": 2,
  "min_closed_trades": 5
}
```

These illustrative thresholds are user policy, not a trading recommendation. Return/drawdown are percentages; deterioration is the percentage-point drop from the same strategy's baseline. Set a nullable field to `null` to disable it. The default minimum return is 0%; other limits are disabled and minimum closed trades is zero. A baseline that already fails absolute requirements yields `BASELINE_FAILED`.

```bash
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data bars.csv --requirements requirements.json --output failure-output
```

Keep real agent code and private prices in a separate private project. Install BacktestWitness into that project's environment and run the CLI from there. Use one instrument's complete OHLCV history. `MyStrategy` must be importable. `--config parameters.json` passes strategy parameters to `Backtest.run`. The native adapter can also handle short orders; the small agent example's decision wrapper is intentionally long/flat.

CSV shape:

```csv
timestamp,available_at,symbol,open,high,low,close,volume
2026-01-01T09:30:00+00:00,2026-01-01T09:30:00+00:00,DEMO,100,102,99,101,1200
2026-01-01T09:35:00+00:00,2026-01-01T09:35:00+00:00,DEMO,101,103,100,102,1400
```

Supply enough bars for warmup and trading; these two rows only illustrate the schema. JSON accepts a list of row objects or `{"rows": [...]}`. Timestamps are aware bar-close times, normalized to UTC. `available_at` defaults to `timestamp`. The engine receives the complete table, so your decision logic must respect which records and features were actually available at each decision time. [Data contract](callback-contract.md).

Extra stress fields are `commission_bps`, `spread_bps` and integer `delay_bars`; omitted fields are zero. Pass a JSON suite with `--scenarios scenarios.json`. Positive delay postpones discretionary market entries/manual closes beyond native next-open timing; protective SL/TP retains native timing. Delayed standalone stop/limit orders, market orders from `Strategy.init` and `trade_on_close` are unavailable. [Full execution guide](failure-lab.md).

## Replay a repair

Edit the original strategy in place, then rerun the saved fixture or generated test. To check a different class or configuration explicitly:

```bash
backtest-witness replay-failure failure-output/failure-fixture.json \
  --adapter my_strategy:RepairedStrategy --config repaired-parameters.json
```

Both the current baseline and saved stress must meet the unchanged policy on the full saved tape. Engine/version mismatch or unstable observations refuses comparison. Keep the fixture and receipt unchanged. A passing case is a scoped regression; assess separate reserved cases to see whether the change generalizes. [Python replay API](integrations.md#native-strategy-execution).

## Commands and exit codes

| Command | Exit 0 | Exit 1 | Exit 2 |
| --- | --- | --- | --- |
| Agent example / `lab` | Completed suite passes | Verified stress failure or baseline failure | Inconclusive / invalid / error |
| `lab-cases` | All variants have completed scoped passes | At least one policy failure | Any inconclusive case / invalid / error |
| `replay-failure` | Current baseline and saved stress meet policy | Comparable policy breach reproduced | Unstable / invalid / unavailable / error |
| `audit` | No dependency observed | Future-data dependency found | Inconclusive / invalid / error |
| `reproduce` | Tested future-data invariant holds | Dependency reproduced | Unstable / invalid fixture / error |

`--json` on the agent example and `lab` emits a structured command summary pointing to `report.json`; read that file for full metrics and evidence. No cloud upload occurs. [Coding-agent tool wrapper](agent-integration.md#let-a-coding-agent-read-the-result).

## Larger public strategy casebook

```bash
# Public dependency pins require Python 3.11+; tested locally on Python 3.12.
python -m pip install '.[cases]'
backtest-witness lab-cases --output failure-public-output
# Expected exit 1: public variants breach their declared stress policy.
backtest-witness serve --directory failure-public-output
```

The casebook uses frozen synthetic inputs and pinned public strategies. Its policy disables minimum return, permits at most 0.05 percentage points of deterioration and requires one closed trade. Losing baselines are allowed. `fixed` labels a disclosed causal variant of an independently reproduced future-data defect; it does not mean execution resilience. [Sources and scope](public-strategies.md).

## Future-data audits

This separate workflow tests whether changing unavailable future records changes earlier decisions:

```bash
backtest-witness demo --output demo-output
python -m pytest demo-output/leaky/test_future_invariance.py
# Expected failure: the planted dependency remains.
backtest-witness reproduce demo-output/leaky/reproducer.json \
  --adapter backtest_witness.demos:causal_run
# Exit 0: the saved invariant holds with this replacement.
backtest-witness audit --adapter examples.custom_adapter:run --data bars.csv \
  --output audit-output --min-history 5 --max-probes 20 --max-calls 160
```

Three-argument audit callbacks return one finite signed target per row. Findings export `reproducer.json`, `receipt.json` and `test_future_invariance.py`. Their curves are illustrative projections on the original tape, separate from native execution reports.

`backtest-witness cases --output public-output` retains the public future-data casebook and same-fixture causal repair checks. [Callback contract](callback-contract.md) · [Engine integrations](integrations.md) · [Position sizing](position-sizing.md). Use each command's `--help` for all options.
