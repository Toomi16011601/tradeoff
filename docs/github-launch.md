# GitHub launch details

The public project is [**Tradeoff**](https://github.com/Toomi16011601/tradeoff), version 0.3.0 alpha. Source installation is supported; no PyPI package or tagged GitHub release has been published. [Hosted CI results](https://github.com/Toomi16011601/tradeoff/actions/workflows/tests.yml) are separate from the recorded local acceptance checks.

## Copy-ready metadata

| Field | Value |
| --- | --- |
| GitHub owner | `Toomi16011601` |
| Repository name | `tradeoff` |
| Display name | Tradeoff |
| Python distribution | `tradeoff` |
| Python import | `tradeoff` |
| Command | `tradeoff` |
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

The account-specific repository name `Toomi16011601/tradeoff` was absent when checked before renaming the existing repository. The PyPI JSON endpoint for `tradeoff` returned HTTP 404. These checks establish neither worldwide brand availability nor trademark clearance, and do not reserve the package name. Recheck before any package publication.

Tradeoff was previously published as BacktestWitness. The product name, repository, distribution, command and Python imports now use `tradeoff`. Source installation is supported; no published PyPI install is implied.

## Compatibility and earlier artifacts

The former `backtest-witness` command and `backtest_witness` Python namespace remain compatibility aliases, including saved built-in callback references. New integrations should use `tradeoff`.

Serialized `backtest-witness.*` and `edgelab.*` schema IDs, along with receipt runtime keys `backtest_witness_version` and `edgelab_version`, retain their original meanings. Renaming a product does not require editing saved fixtures or their hashes. Existing screenshot assets are earlier-version captures and can show BacktestWitness branding.

### Replaying earlier local artifacts

The older, prepublication `edgelab` Python namespace is not automatically aliased. Override an old built-in callback reference with its matching current callback. For an earlier **Riskkit** fixture, this checks the local repair against the original saved tapes without changing the fixture or its hashes:

```bash
tradeoff reproduce oldfixture.json \
  --adapter tradeoff.cases.riskkit:fixed_run
```

Use the callback appropriate to the saved case; the Riskkit repair is not a replacement for another strategy. Python tests exported under the older `edgelab` name need their imports and runner reference updated, or can be regenerated from a new audit. Tests exported under `backtest_witness` retain the compatibility import.
