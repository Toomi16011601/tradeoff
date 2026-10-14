# Architecture

```text
CSV / JSON → validation → fresh native execution → policy suite + reduced stress
                                              ├→ fixture + pytest + receipt
                                              └→ native equity/trades → offline report

CSV / JSON → validation → future-data callback reruns → audit + reduced witness
                                                     ├→ invariant fixture + pytest
Original price tape + paired signed targets ──────────┴→ projection → offline report
```

`execution.py` resolves Backtesting.py 0.6.6 Strategy classes and explicit four-argument execution callbacks. A fresh native Backtest and broker run every scenario. Added costs follow native accounting; a broker-local version-gated hook delays discretionary market orders/manual closes while retaining native protective SL/TP timing, cancellation and cash/sizing feedback. Positive delay refuses unsupported orders. It preserves open terminal holdings and pending orders.

`failure_lab.py` validates finite observations, repeats executions, independently summarizes native equity, applies user requirements and reduces stress over declared tested values. The invocation budget includes repeatability and final verification. Every original input bar remains present; nonmonotonic strategy behavior prevents a global minimum claim. `failure_reproduce.py` exports/replays full-tape policy fixtures, pytest regressions and integrity receipts. `failure_cli.py` provides `lab`, `lab-cases` and `replay-failure`.

The existing future-data path remains independent. `validation.py` owns timestamp, JSON, OHLC and trace contracts. `mutations.py` generates future-only interventions. `audit.py` owns repeatability, budget and row-edit reduction. `reproduce.py` exports/replays hashed invariant fixtures. `economics.py` owns illustrative signed ledgers on the original price tape; these do not become native execution accounting. `adapters/` isolates optional engine/dataframe dependencies and resolves saved audit adapter descriptors. `sizing.py` computes causal quantities.

`cases/` loads pinned public source definitions, verifies their bytes and applies disclosed causal patches in memory. Its audit and execution runners use separate contracts; synthetic execution data and provenance are explicit. `report/` renders computed results into self-contained HTML without rerunning strategies or recomputing verdicts. `cli.py` composes local workflows and serves existing files on localhost.

The core uses the Python standard library; optional engines, pandas and NumPy load lazily through extras. Backtesting.py is the first execution backend. Backtrader/pandas/numeric targets retain their future-data scope. Explicit execution callbacks own their claimed simulator accounting.

Report CSS/JavaScript are package resources inlined into generated HTML; no frontend build or runtime network request is needed. Native execution and temporal audit artifacts have distinct schemas and replay assertions. [Execution contract](execution-contract.md), [report schemas](report-schema.md), [methodology](methodology.md).

Callbacks execute ordinary user code and must expose a simulation-only entry point. Rerun checks do not isolate hidden state or external side effects. Keep proprietary strategies, account data and credentials outside the repository; all bundled examples use synthetic data.
