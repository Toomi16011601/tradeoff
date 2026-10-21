# Quickstart

Tradeoff is a local crash-test and debugging lab for a trading strategy before deployment. Your strategy decides what to trade, Backtesting.py 0.6.6 simulates its orders, and Tradeoff checks how extra execution costs and delays affect your declared requirements.

**Install and run your own copy on your own device.** Tests use your computer and save results in a local folder. The project maintainers do not host your runs or need to keep a computer online. Open the saved `index.html` file in your browser to inspect a completed run; no server is needed. Start new runs from the CLI or Python. This alpha installs from a repository checkout; the core requires Python 3.10+.

## 1. Install from the checkout

Clone the repository onto your device, then install from its root folder, where `pyproject.toml` and `examples/` are located:

```bash
git clone https://github.com/Toomi16011601/tradeoff.git
cd tradeoff
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[lab]'
```

On Windows PowerShell, replace the activation command with `.\.venv\Scripts\Activate.ps1`. The `lab` extra installs the pinned native execution engine. The example uses synthetic prices and needs no data download, credentials or AI API keys.

### Upgrading an existing environment

If this environment already contains the former `backtest-witness` distribution, remove it before installing from the Tradeoff checkout:

```bash
python -m pip uninstall backtest-witness
python -m pip install '.[lab]'
```

Tradeoff provides the legacy command and Python imports itself. Remove the old distribution first so the two packages do not share installed files. Saved fixtures and generated tests need no edits.

## 2. Run the small agent example

```bash
python -m examples.agent_integration --output failure-output-agent
```

**Expected: `FAILURE_FOUND` and exit code 1.** The example is designed to teach the failure loop. Its baseline makes closed trades; execution stress breaches a declared relative-return policy: at most 0.5 percentage points of deterioration from its own baseline, with at least one closed trade. Minimum return is disabled, so the policy is not a profitability test. A failure is a useful result, not a crashed installation. Use a new or empty output directory; choose another name for later runs. The CLI rejects occupied outputs before importing or executing a strategy.

The files separate the decisions from the simulator:

- [`agent.py`](../examples/agent_integration/agent.py): the small deterministic trading decision function you can replace.
- [`strategy.py`](../examples/agent_integration/strategy.py): a Backtesting.py adapter that converts long/flat decisions into native orders.
- [`__init__.py`](../examples/agent_integration/__init__.py): synthetic input, explicit policy, run and artifact export.
- [`__main__.py`](../examples/agent_integration/__main__.py): the CLI entry point and JSON summary.

The [agent integration walkthrough](agent-integration.md) explains how to replace each part and let a coding agent consume the results.

## 3. Open the report file

Find **`failure-output-agent/index.html`** on your device using Finder or File Explorer and open it in your browser. Double-click the file or use your browser's Open File command. The HTML contains its data, CSS and JavaScript and works offline. You do not need a server, a website address or a process left running after the test finishes.

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
tradeoff replay-failure failure-output-agent/failure-fixture.json
# Expected exit 1: the saved policy breach is reproduced.
python -m pip install 'pytest>=9.0.3'
python -m pytest failure-output-agent/test_failure_resilience.py
# Expected test failure while the breach remains.
```

The saved runner is `examples.agent_integration.strategy:AgentStrategy`. The checkout root makes this example module importable. For a separate agent project, install its strategy package or otherwise make its module importable in the environment that runs replay and pytest.

## Test your own strategy

Keep real agent code and private prices in a separate private project. Install Tradeoff into that project's environment and run the CLI from there. Use one instrument's complete OHLCV history. `MyStrategy` must be importable. `--config parameters.json` passes strategy parameters to `Backtest.run`. The native adapter can also handle short orders; the small agent example's decision wrapper is intentionally long/flat. If the class lives in a script that runs a backtest or plot on import, first run `tradeoff inspect-script path/to/script.py`; [move it into a safe importable module](script-strategy-onboarding.md) rather than importing the whole running script.

Before using private data, check the three boundaries of this local workflow:

1. **Code:** importing the strategy runs ordinary Python without a sandbox. Review its imports and keep live credentials out of the environment.
2. **Files:** `index.html`, `report.json` and replay fixtures can retain complete simulation inputs. Keep the output folder private and inspect files before sharing them.
3. **Agents:** Tradeoff does not upload the run, but a cloud coding agent may send any files or output you give it to its provider. Share only what you intend to disclose. See the [security guidance](../SECURITY.md).

For a native Backtesting.py class, choose a policy before interpreting results:

```bash
tradeoff init-requirements --max-return-drop-pct 2 --min-closed-trades 1 \
  --output requirements.json
```

This example asks whether stress reduces return by more than 2 **percentage points** versus the same baseline and requires at least one closed trade. The values are illustrative, not a trading recommendation. The generated policy has no minimum return or drawdown limit unless you explicitly add them with `--min-return-pct` or `--max-drawdown-pct`. This prevents an arbitrary absolute target from stopping the stress search before it starts. If you omit `--requirements` entirely, the existing default still requires nonnegative return but sets no relative return-drop limit; a severely weakened strategy can pass that default policy. A baseline already failing an absolute requirement yields `BASELINE_FAILED` with zero stress scenarios run. [Policy details](failure-lab.md#declare-what-failure-means).

```bash
tradeoff lab --adapter my_strategy:MyStrategy --engine backtesting \
  --engine-settings '{"cash": 10000, "commission": 0.001}' \
  --data daily.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --requirements requirements.json --output failure-output --json
```

Open **`failure-output/index.html`** from your project folder to view this run's report.

If you have the original strategy's Backtesting.py baseline, save its native return, drawdown, trade count and final equity to `native-baseline.json`, then compare it with `tradeoff check-baseline failure-output/report.json --expected native-baseline.json`. Investigate mismatches before relying on the stress finding. This checks the supplied metrics; it does not prove identical trades or data. [Exact steps for script-style strategies](script-strategy-onboarding.md).

This command accepts an ordinary provider CSV:

```csv
Date,Open,High,Low,Close,Volume
2025-01-02,100,102,99,101,1200
2025-01-03,101,103,100,102,1400
```

Supply enough bars for warmup and trading; these two rows only illustrate the schema. Choose the actual instrument, timezone and session-close convention for your dataset. A declared regular close does not account for early closes or an exchange calendar. Symbols and timezones are never inferred from filenames or your computer settings.

For intraday timestamps labeling **bar opens**, use `--timestamp-kind open --bar-duration 1h` for hourly bars. Timestamps then normalize to bar closes; the original `Datetime` column is retained. If your strategy needs `Time`, add `--column-map '{"Time":"Datetime"}' --require-column Time` to copy the original source clock. Naive datetimes need `--timezone`. [Import options and examples](data-import.md).

Already-normalized lowercase CSV remains supported without these conversion flags. JSON accepts a list of row objects or `{"rows": [...]}`. Normalized timestamps are aware UTC bar-close times; `available_at` defaults to `timestamp`. No missing bars or volume values are invented. The engine receives the complete table, so your logic must respect which records and features were actually available at each decision time. [Data contract](callback-contract.md).

Native preflight checks direct data-column reads and referenced module globals still set to `None`. Use `--require-column` and `--require-global` for prerequisites the bounded inspection may miss. If a strategy depends on companion-market data, initialize that state in an importable adapter and declare `--companion-data data/market.csv` to bind its hash for replay. The tool does not initialize state for you. All-zero volume used by a strategy blocks execution unless `--allow-zero-volume` explicitly acknowledges partial validation. [Prerequisites and limitations](data-import.md#check-strategy-prerequisites).

Extra stress fields are `commission_bps`, `spread_bps` and integer `delay_bars`; omitted fields are zero. Pass a JSON suite with `--scenarios scenarios.json`. Positive delay postpones discretionary market entries/manual closes beyond native next-open timing; protective SL/TP retains native timing. Delayed standalone stop/limit orders, market orders from `Strategy.init` and `trade_on_close` are unavailable. [Full execution guide](failure-lab.md).

## Replay a repair

Edit the original strategy in place, then rerun the saved fixture or generated test. To check a different class or configuration explicitly:

```bash
tradeoff replay-failure failure-output/failure-fixture.json \
  --adapter my_strategy:RepairedStrategy --config repaired-parameters.json
```

Both the current baseline and saved stress must meet the unchanged policy on the full saved tape. Engine/version mismatch or unstable observations refuses comparison. Declared companion files must remain available under their saved project-relative paths with unchanged hashes; they are not bundled. Run replay from the project root. Keep the fixture and receipt unchanged. A passing case is a scoped regression; assess separate reserved cases to see whether the change generalizes. [Python replay API](integrations.md#native-strategy-execution).

## Commands and exit codes

| Command | Exit 0 | Exit 1 | Exit 2 |
| --- | --- | --- | --- |
| `init-requirements` / `inspect-script` | Policy created / source scanned | — | Invalid input / error |
| `check-baseline` | Supplied metrics match | A supplied metric or context differs | Invalid / unavailable report or reference |
| Agent example / `lab` | Completed suite passes | Verified stress failure or baseline failure | Inconclusive / invalid / error |
| `lab-cases` | All variants have completed scoped passes | At least one policy failure | Any inconclusive case / invalid / error |
| `replay-failure` | Current baseline and saved stress meet policy | Comparable policy breach reproduced | Unstable / invalid / unavailable / error |
| `audit` | No dependency observed | Future-data dependency found | Inconclusive / invalid / error |
| `reproduce` | Tested future-data invariant holds | Dependency reproduced | Unstable / invalid fixture / error |

`--json` on the agent example and `lab` emits a structured command summary pointing to `report.json`; read that file for full metrics and evidence. `lab --json` and `audit --json` also return safe command errors with `status: "ERROR"`, a `phase` and `error.code`. A completed `INCONCLUSIVE` report is distinct from an input error. No built-in cloud upload occurs. [Coding-agent tool wrapper](agent-integration.md#let-a-coding-agent-read-the-result).

For an opaque strategy exception, rerun `lab` or `audit` with `--diagnostics private-trace.txt`, using a new file **outside** the report output directory. This opt-in file can contain private source lines, paths and raw exception messages; portable reports and stdout retain safe summaries. Existing diagnostic files are never overwritten. Third-party indicator/helper incompatibilities still need manual investigation and a reviewed repair. [Troubleshooting and privacy](data-import.md#read-errors-without-sharing-private-traces).

## Larger public strategy casebook

```bash
# Public dependency pins require Python 3.11+; tested locally on Python 3.12.
python -m pip install '.[cases]'
tradeoff lab-cases --output failure-public-output
# Expected exit 1: public variants breach their declared stress policy.
```

Open the generated `failure-public-output/index.html` file in your browser.

The casebook uses frozen synthetic inputs and pinned public strategies. Its policy disables minimum return, permits at most 0.05 percentage points of deterioration and requires one closed trade. Losing baselines are allowed. `fixed` labels a disclosed causal variant of an independently reproduced future-data defect; it does not mean execution resilience. [Sources and scope](public-strategies.md).

## Future-data audits

This separate workflow tests whether changing unavailable future records changes earlier decisions:

```bash
tradeoff demo --output demo-output
python -m pytest demo-output/leaky/test_future_invariance.py
# Expected failure: the planted dependency remains.
tradeoff reproduce demo-output/leaky/reproducer.json \
  --adapter tradeoff.demos:causal_run
# Exit 0: the saved invariant holds with this replacement.
tradeoff audit --adapter examples.custom_adapter:run --data bars.csv \
  --output audit-output --min-history 5 --max-probes 20 --max-calls 160
```

Three-argument audit callbacks return one finite signed target per row. Findings export `reproducer.json`, `receipt.json` and `test_future_invariance.py`. Their curves are illustrative projections on the original tape, separate from native execution reports.

`tradeoff cases --output public-output` retains the public future-data casebook and same-fixture causal repair checks. [Callback contract](callback-contract.md) · [Engine integrations](integrations.md) · [Position sizing](position-sizing.md). Use each command's `--help` for all options.
