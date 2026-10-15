# BacktestWitness

**Crash-test a trading strategy before you deploy it. Keep a test for the fix.**

BacktestWitness is a local debugging lab for strategies you or your agent already wrote. It runs the strategy in **Backtesting.py 0.6.6**, adds fees, spread and market-order delay, and checks the results against a policy you choose. When it verifies a failure, it saves the evidence and a regression test you can replay after a repair.

```text
Your agent's decisions → Backtesting.py simulates orders
                      → BacktestWitness stresses execution and checks your policy
                      → You or a coding agent reads JSON, repairs the strategy, replays the test
```

The browser UI is an interactive report of a **completed run**. Create new runs with the CLI or Python API. BacktestWitness does not choose trades, connect to a live broker or provide a universal agent connector. It needs no AI API keys; passing a simulation does not establish profitability or live execution quality.

**Local • Offline reports • Python 3.10+ • MIT • 0.3.0 unreleased alpha**

## Run your first agent example

From the repository checkout root, create an environment and install the execution dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[lab]'
python -m examples.agent_integration --output failure-output-agent
# Expected exit 1: this teaching example deliberately breaches its stress policy.
backtest-witness serve --directory failure-output-agent
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1`. Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The preview server supports macOS/Linux; on other platforms, open the trusted generated `failure-output-agent/index.html` directly. Ctrl+C stops the server.

The example uses synthetic prices and a small deterministic decision function. Its Backtesting.py adapter turns those decisions into native orders. Inspect the baseline, select a stressed scenario, then read its policy violation and replay evidence. Use a new or empty output directory for each run. [Step-by-step quickstart](docs/quickstart.md).

![Synthetic agent example: two extra delay bars change return from 1.50% to -0.60%.](docs/assets/agent-integration-desktop.jpg)

## Connect your own agent

Use [`examples/agent_integration/agent.py`](examples/agent_integration/agent.py) to learn the decision interface. Keep your real agent code and private prices in a **separate private project**; install BacktestWitness in that project’s environment and run it there. The example adapter supports long/flat decisions; strategies with other order behavior can use the native Backtesting.py class interface.

A coding agent can call the local CLI with `--json` and read `report.json` as structured tool output. No new SDK or MCP server is required. [Agent integration walkthrough](docs/agent-integration.md) explains the two roles, the runnable files, the data contract and a subprocess tool wrapper.

Already have an importable Backtesting.py strategy? Save your requirements and run:

```bash
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --data bars.csv --requirements requirements.json --output failure-output
```

[Native execution guide](docs/failure-lab.md) · [Engine integrations and Python API](docs/integrations.md)

## Read, repair and replay

| Result | Meaning |
| --- | --- |
| `FAILURE_FOUND` | A repeated stressed run breaches your policy; inspect scenario coverage too. |
| `BASELINE_FAILED` | The baseline already breaches your absolute requirements. |
| `NO_FAILURE_OBSERVED` | The completed declared suite meets your policy. |
| `INCONCLUSIVE` | Unstable, unavailable, unsupported or incomplete evidence prevents a comparable conclusion. |

Every run saves `report.json` and an offline `index.html`. A verified stress failure also saves `failure-fixture.json`, `failure-receipt.json` and `test_failure_resilience.py`.

```bash
backtest-witness replay-failure failure-output-agent/failure-fixture.json
# Expected exit 1 while the saved policy breach remains.
```

Run this example's replay from the checkout root so its strategy module can be imported. Repair replay checks the current baseline and saved stress against the unchanged tape and policy. A passing repair covers that saved case; it does not establish global robustness. [Repair workflow](docs/quickstart.md#replay-a-repair) · [Artifact schema](docs/report-schema.md)

## Explore further

The public strategy casebook is a larger synthetic debugging example using pinned Riskkit and CoinGlass code. Its causal variants repair independently reproduced future-data defects, not execution resilience. [Public sources and scope](docs/public-strategies.md).

```bash
# Public case pins require Python 3.11+.
python -m pip install '.[cases]'
backtest-witness lab-cases --output failure-public-output
# Expected exit 1: the variants breach the declared teaching policy.
```

A separate **future-data audit** changes records unavailable at a fixed cutoff and checks whether earlier decisions change. Its illustrative economic projection is separate from the native execution ledger. Existing Backtrader, pandas and numeric-target integrations retain this audit scope. [Future-data workflow](docs/quickstart.md#future-data-audits) · [Callback contract](docs/callback-contract.md) · [Methodology](docs/methodology.md)

Native execution retains open terminal holdings and pending orders, and preserves native protective SL/TP timing. Some order types are unsupported under added delay. [Execution contract and limits](docs/execution-contract.md).

## Develop and contribute

```bash
python -m pip install -e '.[dev,adapters,cases,lab]'
python -m pytest
python -m build
```

[Contributing](CONTRIBUTING.md) · [Architecture](docs/architecture.md) · [Local verification](docs/verification.md) · [Release checklist](docs/launch-checklist.md) · [Changelog](CHANGELOG.md)

Prior work includes [Freqtrade lookahead analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/), [SharpeBench](https://github.com/general-liquidity/sharpebench), [QuantStats](https://github.com/ranaroussi/quantstats), [Backtrader](https://www.backtrader.com/) and [Backtesting.py](https://kernc.github.io/backtesting.py/). BacktestWitness focuses on explicit policy, repeatable failures, paired evidence and repair replay; it makes no first-ever detector claim.

Licensed under [MIT](LICENSE). Install from this checkout; no PyPI publication or public repository is implied.
