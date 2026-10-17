# Connect an agent to the local failure lab

Tradeoff is a crash-test and debugging tool you install and run on your own computer before deploying a strategy. Your copy tests your strategy and saves reports on your device; it does not depend on the publisher's computer being online. The execution path is:

```text
Trading decision function → Backtesting.py Strategy → native simulated orders
                         → Tradeoff cost/delay scenarios + your policy
                         → JSON evidence → strategy repair → saved-case replay
```

There are two useful meanings of “agent” here:

| Role | What it supplies or does |
| --- | --- |
| Trading agent | Supplies the strategy's historical trading decisions. The small example uses a deterministic Python function. |
| Coding agent | Runs the local checker, reads JSON evidence, edits the strategy and replays the saved failure. |

A coding agent can call an ordinary subprocess or Python function as a tool. This release has no dedicated agent SDK, MCP server, universal connector or live broker integration. The browser UI explores the completed evidence; new simulations run through the CLI or Python API.

## Run the complete small example

From the repository root, with a virtual environment active:

```bash
python -m pip install '.[lab]'
python -m examples.agent_integration --output failure-output-agent
# Expected exit 1: FAILURE_FOUND is the intended teaching result.
```

Open `failure-output-agent/index.html` from your file manager in a browser. This is a saved report file; no server is needed. Use a new or empty output directory for each run. The example uses synthetic data and needs no AI API key or price download. [Environment setup](quickstart.md#1-install-from-the-checkout).

The explicit teaching policy allows at most **0.5 percentage points** of return deterioration from the same baseline and requires at least **one closed trade**. Minimum return is disabled. A losing baseline can meet this policy: it checks execution sensitivity, not profitability. The lab reruns its default declared suite of additional commission, spread and delay scenarios.

## Understand the example files

[`agent.py`](../examples/agent_integration/agent.py) contains the decision function:

```python
def decide(history, position, *, lookback=3):
    if len(history) < lookback:
        return "hold"
    if position == 0 and history[-1] > history[-lookback]:
        return "buy"
    if position > 0 and history[-1] < history[-lookback]:
        return "close"
    return "hold"
```

`history` is a tuple of close prices visible at the current simulated decision time. `position` is the current native position. It returns `"buy"`, `"close"` or `"hold"`; it does not place a broker order. It is ordinary deterministic Python so a repeated historical run can reproduce its decisions without network calls.

[`strategy.py`](../examples/agent_integration/strategy.py) contains `AgentStrategy`, the Backtesting.py adapter. It calls the decision function from `next()`, uses native market entries/manual closes, and waits while an order is pending. That lets extra delay affect fills and later decisions through the real simulator state. The saved import reference is:

```text
examples.agent_integration.strategy:AgentStrategy
```

[`__init__.py`](../examples/agent_integration/__init__.py) builds the synthetic input, sets the teaching policy and exports `run_example(output, *, config=None)`, which runs the lab, saves the artifacts and returns the full report. [`__main__.py`](../examples/agent_integration/__main__.py) exposes the CLI with `--output` and `--json`.

The included wrapper supports long/flat decisions on one instrument. For shorts, sizing rules or other native order behavior, write a Backtesting.py `Strategy` class and use the [native execution interface](integrations.md#native-strategy-execution). The example's limited decision interface is not the full engine's contract.

## Replace the decisions and historical data

Keep real agent code and private prices in a **separate private project**. Install Tradeoff in that project’s environment and run the CLI from its root, where your strategy module is importable. The repository example is for learning with synthetic inputs.

1. Copy the example pattern into your own importable private project module. Replace `decide` with the historical decision logic you want to test, keeping its long/flat contract if you reuse this adapter.
2. Supply one instrument's complete OHLCV history instead of the bundled synthetic tape. The CLI accepts CSV or JSON through `--data`, including ordinary provider headers with explicit symbol/timezone/session conventions. [Import guide](data-import.md).
3. Choose requirements before interpreting the run. Keep a minimum closed-trade requirement if an inactive strategy should not count as a repair.
4. Run the strategy class with `lab`, then inspect `report.json` and replay any verified failure.

For example, after saving your class as `my_agent.strategy:AgentStrategy` and your policy as `requirements.json`:

```bash
tradeoff lab --adapter my_agent.strategy:AgentStrategy --engine backtesting \
  --data daily.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --requirements requirements.json --output failure-output-my-agent --json
```

Open `failure-output-my-agent/index.html` to inspect the report on your computer. Your coding agent can read `failure-output-my-agent/report.json` directly.

This example assumes date-only labels and `Date,Open,High,Low,Close,Volume` headers. Choose the dataset's actual conventions. For hourly source bar-open labels, use `--timestamp-kind open --bar-duration 1h`; `--column-map '{"Time":"Datetime"}'` preserves the original clock for a strategy needing `Time`. No missing bars or exchange calendar are inferred.

Native CLI preflight catches some missing columns, referenced globals left at `None` and all-zero volume used by a strategy. Declare hidden prerequisites with repeated `--require-column` and `--require-global` flags. Companion state still needs a reviewed importable adapter; `--companion-data data/market.csv` records the dependency's path/hash without loading it into the strategy. Explicit `--allow-zero-volume` means partial validation, not a restored volume filter. Callbacks and dynamic helpers cannot be fully inspected. [Prerequisite checks](data-import.md#check-strategy-prerequisites).

The native engine receives the complete input frame. Pass only the information available at the simulated decision time into your agent, and respect delayed availability of records and features. An agent that calls a model or remote service on every decision can change across identical reruns; use deterministic historical decision logic for the simplest reproducible integration.

If you replay a fixed cache of external decisions, key it by the information actually available at each decision time. That checks the cached decisions under the tested execution assumptions. It does **not** validate that the original agent would adapt to different cash, positions or fills under stress. A fresh API response is not a reproducible historical decision record.

Only import and execute strategy code you trust: adapters are normal, unsandboxed Python code running locally. Keep proprietary code and credentials in your own project, outside this repository. Tradeoff has no built-in uploads, account or model service. Your chosen agent controls any context it sends to its own provider; a local tool does not make a cloud agent offline.

## Let a coding agent read the result

Run the example with `--json` to get a machine-readable summary. Exit **1 is a finding**, not an execution error; exit **2 means inconclusive, invalid or error**. Read `report.json` for full metrics, requirements, scenario coverage and native observations rather than asking the agent to infer numbers from HTML.

This small local tool wrapper can be called by a coding agent from the checkout root:

```python
import json
from pathlib import Path
import subprocess
import sys


def check_strategy(output):
    result = subprocess.run(
        [sys.executable, "-m", "examples.agent_integration",
         "--output", str(output), "--json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 2:
        raise RuntimeError(result.stderr or result.stdout)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Checker exited {result.returncode}: {result.stderr}")

    summary = json.loads(result.stdout)
    report = json.loads(Path(summary["artifacts"]["json"]).read_text())
    failure = report.get("failure")
    return {
        "status": report["status"],
        "requirements": report["requirements"],
        "baseline_metrics": report["baseline"]["metrics"],
        "stress_metrics": failure["metrics"] if failure else None,
        "violations": failure["violations"] if failure else [],
        "coverage": report["coverage"],
        "report_path": summary["artifacts"]["json"],
    }


finding = check_strategy("failure-output-agent-tool")  # New/empty directory.
print(finding)
```

For another strategy, make the subprocess call `tradeoff lab --adapter ... --data ... --requirements ... --json` instead, adding the dataset conventions above. Its command summary stores the report path under `summary["report"]`, rather than the example's `summary["artifacts"]["json"]`. Both point to the same full report schema. The [Python runner API](integrations.md#native-strategy-execution) avoids a subprocess when your agent tool runs in Python.

Native `lab --json` and `audit --json` return input errors as `{"status":"ERROR","phase":"data","error":{"code":"...","message":"...","type":"...","hint":"..."}}`. Handle these before opening a report. A completed `INCONCLUSIVE` report instead contains unavailable or unstable evidence and may include a diagnostics hint. The lab summary includes `input_checks`; read its warnings before treating the run as meaningful.

For a caught strategy exception, rerun with `--diagnostics private-trace.txt` in a new file outside the report output directory. It records raw local tracebacks that can contain private source lines and paths; do not automatically pass it to a remote agent or attach it to an issue. Portable reports retain safe errors. Third-party indicator version mismatches still require manual investigation; the lab does not automatically patch arbitrary Python code.

A useful repair loop reads `status`, policy violations, baseline/stress metrics and coverage, then inspects paired observations before changing code. A valid failure can coexist with unavailable scenarios; a partial suite is not a complete pass. Keep the original fixture and policy fixed while testing a repair.

## Replay after a repair

From the repository root, with the example module importable:

```bash
tradeoff replay-failure failure-output-agent/failure-fixture.json
# Exit 1 while the saved breach remains; 0 when current baseline and stress pass.
python -m pip install 'pytest>=9.0.3'
python -m pytest failure-output-agent/test_failure_resilience.py
# Expected failure until a repair meets the saved requirements.
```

An in-place decision-logic change uses the same saved strategy reference. To test an alternative class explicitly:

```bash
tradeoff replay-failure failure-output-agent/failure-fixture.json \
  --adapter my_agent.strategy:RepairedStrategy --config repaired-parameters.json
```

A real agent project's strategy module must be installed or otherwise importable in the replay/test environment. `examples/` is a checkout example, not an installed package module. Run from the strategy project root so declared companion files remain available under their saved relative paths. Their hashes are checked before runner resolution and execution; the files are not bundled. Source hashes and known runtime versions record provenance without prohibiting code repairs. Replay keeps every saved input bar and the declared policy, repeats the current baseline and saved stress, and refuses engine/version mismatch or unstable observations. A passing repair is evidence for that saved case; use separate reserved cases to assess a broader change.

Tradeoff records native simulation results, including fees, open holdings and pending orders. OHLC simulations cannot establish live fills or profitability. [Execution semantics](failure-lab.md#cost-and-delay-semantics) · [Execution contract](execution-contract.md) · [Report schema](report-schema.md)
