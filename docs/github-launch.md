# GitHub launch details

The public project is [**BacktestWitness**](https://github.com/Toomi16011601/backtest-witness), version 0.3.0 alpha. Source installation is supported; no PyPI package or tagged GitHub release has been published. [Hosted CI results](https://github.com/Toomi16011601/backtest-witness/actions/workflows/tests.yml) are separate from the recorded local acceptance checks.

## Copy-ready metadata

| Field | Value |
| --- | --- |
| GitHub owner | `Toomi16011601` |
| Repository name | `backtest-witness` |
| Display name | BacktestWitness |
| Python distribution | `backtest-witness` |
| Python import | `backtest_witness` |
| Command | `backtest-witness` |
| Version | `0.3.0` — alpha |
| License | MIT |

**Description — 137 characters:**

> Strategy failure lab for trading bots. Stress real engine costs and delays, investigate failures, and export replayable regression tests.

**README tagline:**

> Crash-test a trading strategy before you deploy it. Keep a test for the fix.

**GitHub topics:**

`trading`, `backtesting`, `stress-testing`, `lookahead-bias`, `algorithmic-trading`, `quantitative-finance`, `python`, `pytest`, `backtesting-py`, `backtrader`, `regression-testing`, `debugging`, `reproducibility`

Position this as an alpha strategy failure lab: stress native engine costs and delays, investigate reproducible policy breaches, and export tests for repair replay. Backtesting.py 0.6.6 is the first verified execution backend. Backtrader, pandas, numeric targets and callbacks retain their existing future-data audit scope. Explicit execution callbacks own their accounting.

The two public strategies run pinned original code and disclosed causal variants on frozen synthetic tapes. Their public policy tests relative deterioration, disables minimum return and requires a closed trade. A causal repair is not an execution-resilient repair, and a losing baseline is not hidden. One-instrument simulations and bounded negative results do not certify global robustness or predict profit. [Execution semantics](failure-lab.md), [public evidence](public-strategies.md).

## Naming checks — 2026-10-17

The former working name was EdgeLab. That name already belongs to a [PyPI trading CLI](https://pypi.org/project/edgelab/) and an [existing trading project](https://github.com/loksundar/edgelab), so it would confuse discovery and package installation.

A global GitHub repository-name search for `backtest-witness` returned no matches. The PyPI JSON endpoint for `backtest-witness` returned HTTP 404. These are availability observations on the stated date, not a reservation, an exhaustive trademark search or a legal claim. The account-specific repository name was rechecked immediately before creation. Recheck the package name before any package publication.

The local workspace folder remains named `edgelab`; it is not the public repository or package name. Legacy wire schema IDs retain the historical name. Stored artifact formats remain readable and fixture validation/hashes are preserved. The README uses the actual public repository URL. Installation still uses the source checkout; no published PyPI install is implied.

## Replaying earlier local artifacts

The former `edgelab` Python namespace is not automatically aliased. Override an old built-in callback reference with its matching new callback. For an earlier **Riskkit** fixture, this checks the local repair against the original saved tapes without changing the fixture or its hashes:

```bash
backtest-witness reproduce oldfixture.json \
  --adapter backtest_witness.cases.riskkit:fixed_run
```

Use the callback appropriate to the saved case; the Riskkit repair is not a replacement for another strategy. Previously exported Python tests need both their imports and the runner reference updated, or can be regenerated from a new audit.
