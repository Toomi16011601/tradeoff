# Verification

BacktestWitness 0.3.0 is an unreleased alpha. Hosted CI and publication remain pending. The checks below are local acceptance evidence, not a security or profitability certificate. The agent-onboarding build passes **492 tests** on Python 3.12.14, including the updated replay instructions and agent integration.

## First-use agent integration

A fresh downloaded snapshot was installed with the documented regular `pip install '.[lab]'` command in a new virtual environment with no inherited packages and `PYTHONPATH` unset. Imports resolve to the installed wheel, including privacy guards. The resolver selected Backtesting.py 0.6.6, pandas 3.0.6, NumPy 2.5.4 and Bokeh 3.10.1 on Python 3.12.14.

The example completes all 12 scenarios in 30 native invocations. Its single closed baseline trade returns 1.5%; the saved additional 100-bps commission case returns 0.879%, a 0.621-percentage-point drop exceeding the explicit 0.5-point teaching limit. The plain command and documented coding-agent JSON wrapper work. CLI replay and the generated pytest reproduce the expected `ResilienceError`; these intentional policy failures are separate from the passing repository test suite.

The same synthetic decision function and adapter were then placed in a separate project folder. The installed `lab --adapter demo_agent.strategy:AgentStrategy` command, saved-case replay and generated pytest all work there without the repository on the import path. No private trading code or credentials were used. The first-use CI job is configured but has not run on a hosting platform. Desktop (1440 × 1000) and mobile (390 × 844) browser checks cover scenario changes, keyboard bar inspection and contained page width, with no console warnings/errors. The same synthetic agent case is shown in the [desktop capture](assets/agent-integration-desktop.jpg) and [mobile capture](assets/agent-integration-mobile.jpg).

## Strategy execution and replay

Native tests use Backtesting.py 0.6.6 and temporal adapter tests use Backtrader 1.9.78.123. Coverage includes zero-stress parity, cost/sizing feedback, market entry/manual-close delay, shorts, protective orders, cancellation, open holdings, pending tail orders, insolvency, finite native observations, explicit requirements, budgets and generated failure-to-repair replay.

Both pinned public strategies and their disclosed causal variants complete all 12 declared execution scenarios on frozen synthetic tapes. Each reproduces the stated 0.05-percentage-point deterioration policy with at least one closed baseline trade. Reduced additional commissions are 5 bps for Riskkit original, 10 bps for Riskkit causal and 25 bps for both CoinGlass variants. These are tested grid cases, not global break-even boundaries. CoinGlass's causal case changes native return from approximately 3.25% to 2.49% with one extra market-order bar. Synthetic cases do not establish market alpha.

The saved public temporal-audit fixtures reproduce their original dependencies and pass with the matching causal repair. A constructed native roundtrip reproduces its policy failure, passes with an explicit repaired strategy and preserves fixture bytes. Public execution cases intentionally return exit 1 for their teaching failures; CI checks that exact exit code.

## Interface and packaging

Desktop, mobile and narrow report inspections cover scenario selection, paired equity/position changes, divergence navigation, keyboard sliders, terminal holdings and incomplete states. The hardened HTTP preview's CSP preserves packaged styling and interactive controls; mobile inspection shows no page-level overflow or console warnings/errors. [Desktop](assets/failure-lab-desktop.png), [mobile](assets/failure-lab-mobile.png).

Wheel and source builds include inline report assets, pinned sources/licenses, frozen inputs and product documentation. Source archive ownership fields are anonymous and timestamps stable; an independently extracted source archive builds a wheel. Bundled upstream source and license bytes remain unchanged. A regular wheel installation is checked outside the source checkout with isolated Python. Both installed public casebooks reproduce their expected outcomes. The installed native casebook also completes with socket connections blocked.

## Privacy and security

The publication snapshot excludes internal session notes, old identifying Git history, stale packages, caches, virtual environments and generated private artifacts. Screenshots show synthetic reports without account identity, browser chrome or location metadata. Repository owner settings are unset; commit attribution uses a neutral project identity.

Regression checks cover recognized sensitive inputs, malformed output, trace diagnostics, callback exceptions/replay tracebacks, export references and gallery labels. Fixtures are rejected rather than silently redacted, preserving replay integrity. Preview tests cover traversal, symlinks at every path component, host/origin validation, known-artifact allowlists, directory-listing refusal and security headers. Independent review reproduced and verified fixes for additional export and ancestor-symlink edge cases. [Security policy and limits](../SECURITY.md), [audit scope](security-review.md).

Only local Python 3.12.14 and the stated engine versions are verified. Core CI is configured for Python 3.10/3.12/3.13, with optional cases on 3.12; the pinned cases extra requires Python 3.11+. Secure HTTP preview supports macOS/Linux and fails clearly elsewhere. Direct HTML opening remains a trusted local-file alternative; its browser integration is not independently verified here. Reports retain full simulation data and arbitrary imported callbacks remain ordinary unsandboxed Python.
