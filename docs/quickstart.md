# Quickstart

Tradeoff tests whether changing unavailable future input changes an earlier strategy decision. A finding produces paired evidence and a saved regression test. A repair is checked against that same fixture.

Your installed copy runs on your own device. Open the generated `index.html` file to inspect a completed run; no server or hosted account is needed.

Choose a starting point:

- **[Try the demo](#1-install-from-the-checkout):** use the included strategy and data to see a verified bug and repair. You do not need your own strategy, live market data or API keys.
- **[Let your agent set it up](../README.md#let-your-agent-set-it-up):** give a coding agent the setup prompt, then let it inspect your strategy project and explain any missing inputs. The agent needs permission to run local commands and read the relevant files.

## 1. Install from the checkout

You need **Git** and **Python 3.12** for the commands below. Get Git from its [official installation page](https://git-scm.com/install/) and see [Python.org downloads](https://www.python.org/downloads/) for official Python options. Use a maintained Python 3.12 setup for your operating system or package manager; on Linux, include its venv package if packaged separately.

Open **Terminal** on macOS/Linux or **PowerShell** on Windows. First check that the tools are available:

```bash
# macOS / Linux
git --version
python3.12 --version
```

```powershell
# Windows PowerShell
git --version
py -3.12 --version
```

Git should print a version, and Python should print `Python 3.12.x`. After installing a missing tool, close and reopen your terminal before checking again.

Python 3.12 is the recommended tested setup. Core and decision-feedback commands require Python 3.10+; optional engine extras (`audit`, `lab`, `adapters`, `cases`) require Python 3.11+ for their patched dependencies.

**macOS / Linux:** copy these commands into Terminal, one line at a time. They download the public source, create a project-local Python environment, install the demo dependencies and run the investigation.

```bash
git clone https://github.com/Toomi16011601/tradeoff.git
cd tradeoff
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade "pip>=26.2"
python -m pip install '.[audit]'
tradeoff demo-bug --output bug-output --json
```

**Windows PowerShell:** use this complete alternative. It calls the local environment directly, so you do not need to activate it or change PowerShell's execution policy.

```powershell
git clone https://github.com/Toomi16011601/tradeoff.git
cd tradeoff
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python.exe -m pip install ".[audit]"
.\.venv\Scripts\tradeoff.exe demo-bug --output bug-output --json
```

The initial download and installation need internet access. The demo itself uses included source and data and does not connect to a broker or market-data service. If reusing an environment containing the old `backtest-witness` distribution, uninstall it first so installed files do not overlap; a fresh `.venv` avoids that overlap.

## 2. Run the public bug investigation

The final command above runs an existing defect in pinned Riskkit source on a clearly labeled **synthetic 400-bar stress tape**, exports a witness, confirms the original still fails its saved fixture, and verifies the disclosed repair. It also checks that the repaired strategy remains active after warmup.

Expect JSON containing **`"status": "VERIFIED"`** when the full demonstration succeeds, with exit code **0**. An incomplete demonstration exits **2**; read its error or report before treating it as verified.

In Finder or File Explorer, open the downloaded **`tradeoff`** folder, then **`bug-output`**, and double-click **`index.html`** to open the report in your browser. On Linux, use your file manager. Start with the changed input and earlier position, then inspect saved-fixture repair verification.

To run the demo again, use a fresh output name, for example `tradeoff demo-bug --output bug-output-2 --json` (Windows: `.\.venv\Scripts\tradeoff.exe demo-bug --output bug-output-2 --json`). Tradeoff refuses to overwrite a nonempty output folder; open the report in the new folder after each run.

The repair changes indicator warmup and skips the original early trades. Its **PASS** covers the exact saved fixture; it does not establish profitability or that every future-data dependency is gone. The original full historical GOOG input was a negative control: tested edits did not change earlier positions because the position cap masked the faulty feature. [Case study and tested limits](future-data-case-study.md).

### If setup stops

- **`git` or `python3.12` is not found / `py -3.12` cannot find Python:** install the prerequisite above, reopen Terminal or PowerShell, and repeat the version check. On Windows, ensure your Python installation includes the `py` launcher or Python install manager.
- **`tradeoff` is not found on macOS/Linux:** return to the `tradeoff` folder and run `source .venv/bin/activate`, then retry. If installation did not complete, rerun `python -m pip install '.[audit]'` in that environment.
- **Windows cannot find `.\.venv\Scripts\tradeoff.exe`:** run commands from the `tradeoff` folder, create `.venv` if needed, and repeat `.\.venv\Scripts\python.exe -m pip install ".[audit]"`. Use that local executable for later `tradeoff` commands too.
- **Missing demo dependencies:** repeat the `.[audit]` installation using the same environment as the demo. A plain `pip install .` does not install these optional dependencies.

## 3. Set up your own strategy

Work in your own strategy project and environment. You can install the public source directly there:

```bash
python -m pip install --upgrade "pip>=26.2"
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
## Agent feedback setup

For recording your own agent's decisions and matching execution outcomes, use the [decision-feedback walkthrough](decision-feedback.md) and [copyable integration prompt](feedback-integration.md#2-let-your-coding-agent-wire-the-hook). Run `tradeoff feedback demo --output feedback-output-demo` after installing the checkout, then open `feedback-output-demo/report/index.html`. This workflow has no local web server. MCP is optional; it uses stdio on your device.
