# Tradeoff skill

**Ask your agent. Get a local audit. Verify a repair.**

Start with a terminal-capable agent. It can check project fit by reading files alone. Running the audit needs Python 3.12, a Backtesting.py 0.6.6 strategy and historical OHLCV data.

## Start here

Give your agent this prompt:

```text
Clone https://github.com/Toomi16011601/tradeoff.git into a temporary folder
and follow skills/tradeoff-audit/SKILL.md to audit my current project.
Check fit before installing anything. Explain the result or what’s missing.
Leave strategy code and live trading alone.
```

Already loaded? **“Use Tradeoff to audit this project.”**

For a local or unpublished package, extract the whole folder and tell the agent:

```text
Read /absolute/path/to/tradeoff-audit/SKILL.md and use it to audit this project.
```

In a checkout, the path is `skills/tradeoff-audit/SKILL.md`. Keep `references`, `agents` and `LICENSE` with it. Client skill discovery varies; reading the entrypoint directly also works. A chat without local terminal access can explain the process but cannot run it on your device.

## What the agent does

1. Reads the strategy, imports, data and native settings. If unsupported or missing inputs, it stops here without installing anything.
2. Uses a compatible installation or creates an isolated tool environment.
3. Runs `init` and `check`, resolving actual inputs instead of guessing.
4. Opens the report file and explains the finding, coverage or blocker.
5. When a repair is authorized, replays the unchanged saved fixture and runs a fresh audit.

The audit uses the **CLI**. Registering MCP or buying external tools is unnecessary.

<details>
<summary>Manual tool installation</summary>

Create the tool environment outside a running trading environment.

macOS / Linux:

```bash
python3.12 -m venv tradeoff-env
tradeoff-env/bin/python -m pip install --upgrade "pip>=26.2"
tradeoff-env/bin/python -m pip install 'tradeoff[audit] @ git+https://github.com/Toomi16011601/tradeoff.git'
tradeoff-env/bin/python -m tradeoff --version
```

Windows PowerShell:

```powershell
py -3.12 -m venv tradeoff-env
.\tradeoff-env\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\tradeoff-env\Scripts\python.exe -m pip install 'tradeoff[audit] @ git+https://github.com/Toomi16011601/tradeoff.git'
.\tradeoff-env\Scripts\python.exe -m tradeoff --version
```

Record that interpreter's absolute path; use it for later commands from the strategy project. Install reviewed offline strategy dependencies there. Initial installation needs internet; auditing local files does not require a market-data service.

If you already cloned Tradeoff to read this skill, use that checkout instead of the GitHub requirement: `python -m pip install "/absolute/path/to/tradeoff[audit]"` with the isolated environment's Python. This keeps the CLI and skill in sync without a second clone.

</details>

<details>
<summary>Strategy, data and settings</summary>

Run from the strategy project root. Below, `python` means the tool environment's interpreter.

```bash
python -m tradeoff inspect-script strategy.py --json
```

Review source and helpers before execution. An authorized importable extraction or main guard can separate the strategy from downloads, plots or live runners; retain its logic and disclose edits. A wrapper importing an unguarded original still runs it. Imported code is ordinary Python, not a sandbox.

Preserve native `Backtest(...)` options through `--engine-settings`. Preserve `Backtest.run(...)` parameter overrides through `--config parameters.json`, for example `{"n1": 10, "n2": 20}` when those are the actual values. Missing overrides use class defaults. Report unsupported settings or unavailable state instead of substituting values.

Confirm the instrument, OHLCV columns, availability and bar-label convention. Naive timestamps need their timezone; date-only labels also need the actual session close. Bar-open data needs its duration. Ask when these are undocumented; examples and generated suggestions are not provenance.

The native adapter supplies a **naive UTC bar-close index**. Review strategies using index hours, weekdays or original open times: preserve those semantics through an authorized adaptation or report a blocker.

</details>

<details>
<summary>Run and interpret an audit</summary>

For a dataset **confirmed** to use US regular-session daily close labels:

```bash
python -m tradeoff init --strategy strategy.py --data prices.csv --symbol EXAMPLE --timezone America/New_York --session-close 16:00 --timestamp-kind close --review-imports --json
python -m tradeoff check --json
```

Replace files and conventions with actual inputs. Add `--strategy-class ActualClass` when needed. Hourly open labels use `--timestamp-kind open --bar-duration 1h`; aware timestamps include their timezone. Pass `--review-imports` only after review.

`init` can exit **0** with `NEEDS_INPUT`: settings were saved, but setup is incomplete. Resolve named choices through `check`; reuse an existing manifest instead of overwriting it. From another folder, add `--project /path/to/project/tradeoff.json`. Relative input/output paths resolve from that manifest.

| Check result | Meaning |
| --- | --- |
| Exit 1 · `FOUND` | The earlier position changed. Finishing the search or narrowing it to one bar isn't required to verify that change. |
| Exit 0 · `NO_DEPENDENCY_OBSERVED` | The tested price and volume changes didn't change an earlier position. Mention a flat baseline or relevant fields the audit didn't change. |
| Exit 2 | Invalid, blocked or inconclusive; read the status. |

Open the returned `interface` file. New checks use fresh `.tradeoff/check-…` directories; retain earlier evidence.

Native audits compare **observed positions**; unfilled changed intentions may remain undetected. Keep warmup, open holdings and warnings visible. The report's economic projection has independent cash/cost settings and is not the native ledger. Its rejections do not establish native inactivity or performance.

Capture repetitive stdout/stderr separately in private local files. Read JSON and summarize warnings without discarding the full log or changing strategy logic to hide them.

</details>

<details>
<summary>Verify a repair</summary>

Confirm the unchanged original reproduces the finding before editing. Keep `reproducer.json`, the input tape, cutoff and execution assumptions unchanged.

```bash
python -m tradeoff reproduce .tradeoff/check-RUN/reproducer.json
```

Use the actual path and run from the strategy project root. For a different class, append `--adapter strategy:RepairedStrategy`.

Exit **0** verifies the saved case; **1** means the dependency remains; **2** means invalid or unstable. Explain warmup/activity changes, then run a new audit with renewed source review when requested. No witness means no invented repair.

</details>

<details>
<summary>Troubleshooting</summary>

| Blocker | Next step |
| --- | --- |
| Missing command or engine | Use the recorded interpreter with `-m tradeoff`; install its `audit` extra. Prefer a normal install when diagnosing editable-pointer failures. |
| `PROJECT_EXISTS` | Reuse it with `check --project …`. |
| Multiple classes | Set `--strategy-class`. |
| Missing data or unclear clock | Ask for the actual file/convention. |
| Missing dependency, column or global | Supply the reviewed dependency or real input; retain filters. |
| Import side effects | Isolate the strategy through an authorized, disclosed edit. |
| Unsupported framework/settings | Report the integration blocker. |
| Nonempty output | Keep it; select a fresh directory. |

</details>

Default audit settings (`tradeoff.json`) and reports (`.tradeoff/`) are ignored for normal Git staging. If a default path is already tracked, stop and tell the user; don't change their Git history or index. Choose private locations for custom outputs and logs. Reports contain inputs; Git ignore rules do not encrypt them. Your agent's provider controls its context.
