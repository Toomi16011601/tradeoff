# Quickstart

Tradeoff tests whether changing unavailable future input changes an earlier strategy decision. A finding produces paired evidence and a saved regression test. A repair is checked against that same fixture.

Your installed copy runs on your own device. Open the generated `index.html` file to inspect a completed run; no server or hosted account is needed.

## 1. Install from the checkout

Python 3.12 is the recommended tested setup. Core commands require Python 3.10+; the optional pinned public casebook requires Python 3.11+.

```bash
git clone https://github.com/Toomi16011601/tradeoff.git
cd tradeoff
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install '.[audit]'
```

On Windows use `py -3.12 -m venv .venv`, then `.\.venv\Scripts\Activate.ps1`. If this environment contains the old `backtest-witness` distribution, uninstall it first so installed files do not overlap.

## 2. Run the public bug investigation

```bash
tradeoff demo-bug --output bug-output --json
```

The command runs an existing defect in pinned Riskkit source on a clearly labeled **synthetic** stress tape, exports a witness, confirms the original still fails its saved fixture, and verifies the disclosed repair. It also checks that the repaired strategy remains active. A complete verified demonstration exits **0**; an incomplete demonstration exits **2**.

Open **`bug-output/index.html`**. Start with the changed input and earlier position, then inspect saved-fixture repair verification. The source, data construction, warmup change and tested limits are disclosed. The original full historical GOOG input was a negative control: tested edits did not change earlier positions because the position cap masked the faulty feature. [Case study](future-data-case-study.md).

## 3. Set up your own strategy

Work in your own strategy project and environment. You can install the public source directly there:

```bash
python -m pip install 'tradeoff[audit] @ git+https://github.com/Toomi16011601/tradeoff.git'
```

For one importable Backtesting.py class in `strategy.py` and a daily CSV with `Date,Open,High,Low,Close,Volume`:

```bash
tradeoff init --strategy strategy.py --data prices.csv \
  --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --timestamp-kind close --review-imports
tradeoff check --json
```

Choose your feed's actual conventions. Intraday bar-open labels need `--timestamp-kind open --bar-duration 1h` for hourly data. Aware timestamps already supply a timezone; date-only labels need a timezone and session close. No exchange calendar or missing bars are inferred. [Data import](data-import.md).

`init` never imports the strategy. It detects recognizable classes and writes a local `tradeoff.json`; missing or ambiguous settings are shown as `NEEDS_INPUT`. Supply the named flags to `check` to resolve and save them. Multiple classes need `--strategy-class MyStrategy`. Other supported adapters can be selected explicitly with `--adapter module:callable --engine targets|pandas|callback|backtrader|backtesting`.

Review the module and its imports before passing `--review-imports`. Recognized unguarded backtest/plot calls block execution: move them behind `if __name__ == "__main__":` or into another script. The tool does not rewrite an arbitrary project or certify that importing it is safe. Changes to the reviewed source require renewed acknowledgement; dependency and companion-file changes are your responsibility. [Script onboarding](script-strategy-onboarding.md).

## 4. Run checks and open the report

After setup, rerun **`tradeoff check`**. Default runs use fresh `.tradeoff/check-…` folders, so repeated checks do not overwrite evidence. The summary gives `report`, `interface` and `replay` paths/commands; a coding agent can consume the JSON.

From another directory, use `tradeoff check --project /path/to/project/tradeoff.json`. Source, data and explicit relative output paths resolve from the manifest's directory. Keep strategy credentials out of the environment: a check executes ordinary reviewed Python, not a sandbox.

An audit exits **1** for `FOUND`, **0** for `NO_DEPENDENCY_OBSERVED`, and **2** for invalid or inconclusive evidence. A finding is a useful result, not an installation crash. No observation is a bounded negative result, not a global absence-of-leakage certificate.

## Replay a repair

Keep the saved `reproducer.json` unchanged. From the strategy project root, edit the strategy and run the `replay` command printed by `check`. To select a different repaired class:

```bash
tradeoff reproduce .tradeoff/check-RUN/reproducer.json \
  --adapter strategy:RepairedStrategy
```

Replace `check-RUN` with the actual generated folder. The original callback should exit **1** while the dependency remains. The repaired callback exits **0** only if the saved invariant holds; invalid or unstable comparison exits **2**. New strategy parameters and broader data behavior need fresh audits too. Keep the full tape, cutoff, availability and fixture hashes unchanged.

The report exposes a recorded repair result when one exists. A proposed patch or a separately passing audit alone is labeled **Repair not verified**. [Agent workflow](agent-integration.md) · [Fixture contract](callback-contract.md).

## Future-data audits

Direct CLI use remains available without a manifest:

```bash
tradeoff audit --adapter strategy:MyStrategy --engine backtesting \
  --data prices.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --output audit-output --json
```

Use your real data conventions and native settings. Callback adapters return one finite signed target per input row; native adapters record observed positions. Findings save `reproducer.json`, `receipt.json` and `test_future_invariance.py` beside the report. [Adapters](integrations.md) · [Methodology and limits](methodology.md).

## Execution costs and agent examples

The separate `lab` workflow reruns native fees, spread and discretionary order delay against an explicit policy. It uses a different fixture and result vocabulary. [Failure lab](failure-lab.md), [execution contract](execution-contract.md), and [historical execution demo](historical-demo.md).

The smaller synthetic decision-agent example remains available from the checkout:

```bash
python -m examples.agent_integration --output failure-output-agent
# Exit 1 is its expected execution-policy failure.
tradeoff replay-failure failure-output-agent/failure-fixture.json
# Exit 1 until its policy breach is repaired.
```

## Commands and exit codes

| Command | Exit 0 | Exit 1 | Exit 2 |
| --- | --- | --- | --- |
| `init` | Settings saved; inspect READY/NEEDS_INPUT | — | Invalid input / existing manifest |
| `check` / `audit` | No dependency observed | Future-data dependency found | Needs input / inconclusive / error |
| `demo-bug` | Public defect and saved-fixture repair verified | — | Verification incomplete / error |
| `reproduce` | Saved invariant holds | Dependency reproduced | Unstable / invalid / error |
| `lab` / agent example | Declared execution suite passes | Policy failure | Inconclusive / invalid / error |
| `replay-failure` | Saved execution policy passes | Comparable policy failure | Unstable / invalid / error |

Reports and fixtures can contain the full input tape. Tradeoff has no built-in upload, but your chosen coding agent may send files you give it to its provider. [Security boundaries](../SECURITY.md).
