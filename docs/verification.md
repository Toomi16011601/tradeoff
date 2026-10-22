# Verification

Tradeoff 0.3.0 is a public source alpha. The checks below are local acceptance evidence, not a security or profitability certificate. [Hosted CI results](https://github.com/Toomi16011601/tradeoff/actions/workflows/tests.yml) record runs for published commits. The data-import and integration-check build, recorded before the Tradeoff rename, passed **621 tests** on Python 3.12.14, including native execution, input validation, replay and private diagnostics. The renamed source passes **627 tests** locally; hosted results are recorded separately.

The linked screenshots are earlier-version captures and still show BacktestWitness branding. They document the synthetic report flows inspected before the rename.

## Historical GOOG showcase — 22 October 2026

`tradeoff demo-history` runs a Tradeoff long/flat 10/20-day SMA crossover on the 2,148 GOOG daily bars bundled with Backtesting.py 0.6.6. The direct native baseline check matches the lab's 75,645.99 final equity and 46 closed trades. A further 5-bps commission reduces final equity to 72,620.69; all 12 native stress scenarios complete, and fresh reruns verify the declared 2-percentage-point deterioration breach. CLI replay and the generated pytest both fail as expected while the breach remains.

The full local suite passes **654 tests**. The source and wheel build include the new demo, strategy, compatibility aliases and guide. The wheel was installed to a separate target and run outside the checkout using existing native dependencies; the installed command exported and replayed the same failure. A scan of the five generated files found no local home path or private trading identifiers. This is a package smoke test, not a fresh dependency-resolution audit or a visual check of the larger historical report. [Inputs, assumptions and limitations](historical-demo.md).

## Tradeoff rename — 17 October 2026

A fresh wheel installation verifies both command names, installed report assets, the native agent example and saved-failure replay. Earlier `backtest_witness` callback references and generated pytest files still reproduce their expected failure; the same old fixture passes with the causal callback and keeps identical bytes. Compatibility imports share exception classes and local diagnostic state without loading optional trading frameworks. Serialized schema IDs and receipt keys remain unchanged. These checks cover naming compatibility, not new strategy capabilities.

## Final release audit — 17 October 2026

Independent reviews covered publication files and both reachable Git commits, source/wheel archives, screenshot pixels/metadata, privacy/report boundaries, native execution and replay. Two newly reproduced issues were fixed: sensitive fields in tuple-valued direct Python exports now fail before files are created; repair replay now rejects changed runner settings or starting capital instead of allowing percentage losses to be diluted. New regressions include both report writers, mixed sequence cycles, native settings changes and callback capital changes while retaining valid strategy/configuration repairs.

A fresh clean lab environment resolves Backtesting.py 0.6.6, pandas 3.0.6, NumPy 2.5.4 and Bokeh 3.10.1. OSV queries over 28 public runtime, optional and build/development package-version pairs returned no advisory matches at this audit time. This does not certify unknown vulnerabilities, native libraries or every possible resolution. Source archives remain anonymous, and no private trading code/data was copied into the public tree. Hosted CI is configured to run on each push; its results are recorded separately.

## First-use agent integration

A fresh downloaded snapshot was installed with the documented regular `pip install '.[lab]'` command in a new virtual environment with no inherited packages and `PYTHONPATH` unset. Imports resolve to the installed wheel, including privacy guards. The resolver selected Backtesting.py 0.6.6, pandas 3.0.6, NumPy 2.5.4 and Bokeh 3.10.1 on Python 3.12.14.

The example completes all 12 scenarios in 30 native invocations. Its single closed baseline trade returns 1.5%; the saved additional 100-bps commission case returns 0.879%, a 0.621-percentage-point drop exceeding the explicit 0.5-point teaching limit. The plain command and documented coding-agent JSON wrapper work. CLI replay and the generated pytest reproduce the expected `ResilienceError`; these intentional policy failures are separate from the passing repository test suite.

The same synthetic decision function and adapter were then placed in a separate project folder. The installed `lab --adapter demo_agent.strategy:AgentStrategy` command, saved-case replay and generated pytest all work there without the repository on the import path. No private trading code or credentials were used. The first-use CI job checks this install/run/replay path; see the linked workflow for its hosted results. Desktop (1440 × 1000) and mobile (390 × 844) browser checks cover scenario changes, keyboard bar inspection and contained page width, with no console warnings/errors. The same synthetic agent case is shown in the [desktop capture](assets/agent-integration-desktop.jpg) and [mobile capture](assets/agent-integration-mobile.jpg).

## Real-data onboarding checks

Two additional public projects were checked in separate new virtual environments using regular wheel installs, without inherited site packages or a development import path. Local patch-wheel updates were applied during the walkthroughs. Original strategy files, historical inputs, engine profiles, policy and eight scenarios were kept fixed against the preceding evaluation; third-party code and downloaded prices are not bundled here.

| Project and historical tape | Result and remaining setup |
| --- | --- |
| [RSI Regime, pinned source](https://github.com/jballaith/Trading_Strategy_RSI_Regime/tree/64fd903b026b5455d2c325f443e219becc89f259): 751 AAPL daily bars in 2023–2025, with padded SPY data | Raw provider CSVs load directly. Bare-class run is refused at preflight because `SPY_OK` is unset; an 11-nonblank-line adapter still initializes the author's companion filter. Baseline return is −0.0934%; two extra observed bars give −8.4260%. The tested nonfinalizing profile remains explicit: upstream `finalize_trades=True` is unsupported. |
| [SMI Momentum Breakout, pinned source](https://github.com/nyashamutazu/smi-momentum-breakout/tree/11147ea6f36d218a856acaed6a2a1de8450c1e41): 6,178 replacement EURUSD hourly bars in 2025 | Preflight refuses missing `Time` and then all-zero `Volume`. Mapping the original source clock needs no prepare callback, but an upstream pandas-ta label incompatibility still needs a 10-line compatibility helper. Explicit zero-volume acknowledgement permits **partial validation only**: the original volume filter cannot be validated on this feed. Baseline return is −4.2977%; 5 additional commission bps give −15.6469%. |

Both disclosed integrations complete eight scenarios in 22 native invocations. Their baseline and scenario trade/equity observations match the preceding corrected evaluation; CLI replay and generated pytest reproduce the expected policy breaches. The SMI full suite takes roughly 2½–3 minutes locally: retaining source-clock strings avoids implicit type changes, but the strategy repeatedly parses them during reruns. This is a practical cost of the simpler CSV path.

Occupied outputs are rejected in under 0.1 seconds before strategy import or engine execution. A changed declared SPY companion file refuses replay until restored. Opt-in owner-only diagnostics identify the third-party indicator error while portable reports omit its raw exception text. Report input warnings appear before the scenario matrix; desktop/mobile checks cover keyboard disclosure, scenario selection, bar inspection, contained page width and console errors.

These are two Backtesting.py integrations, not tests of arbitrary agents or engines. Both baselines lose money; the fixed policy deliberately allows that to isolate additional execution sensitivity. Companion initialization, timestamp conventions, dependency repairs and suitable market data still require user judgment. The tests establish reproducibility and clearer setup failures, not alpha, complete strategy fidelity or automatic project integration.

## Strategy execution and replay

Native tests use Backtesting.py 0.6.6 and temporal adapter tests use Backtrader 1.9.78.123. Coverage includes zero-stress parity, cost/sizing feedback, market entry/manual-close delay, shorts, protective orders, cancellation, open holdings, pending tail orders, insolvency, finite native observations, explicit requirements, budgets and generated failure-to-repair replay.

Both pinned public strategies and their disclosed causal variants complete all 12 declared execution scenarios on frozen synthetic tapes. Each reproduces the stated 0.05-percentage-point deterioration policy with at least one closed baseline trade. Reduced additional commissions are 5 bps for Riskkit original, 10 bps for Riskkit causal and 25 bps for both CoinGlass variants. These are tested grid cases, not global break-even boundaries. CoinGlass's causal case changes native return from approximately 3.25% to 2.49% with one extra market-order bar. Synthetic cases do not establish market alpha.

The saved public temporal-audit fixtures reproduce their original dependencies and pass with the matching causal repair. A constructed native roundtrip reproduces its policy failure, passes with an explicit repaired strategy and preserves fixture bytes. Public execution cases intentionally return exit 1 for their teaching failures; CI checks that exact exit code.

## Interface and packaging

The documented first-use flow now states that each user runs their own copy on their own device, then opens the generated `index.html` file. Setup guides contain no local web addresses or server steps. The example completes all 12 scenarios and writes the report; static artifact checks confirm embedded data, CSS and JavaScript, no external assets or fetch/XHR dependency, and valid sibling-file links. Direct file navigation is blocked by the local browser-automation policy, so this documentation update does not claim an independently verified browser file-opening check.

Desktop, mobile and narrow report inspections cover scenario selection, paired equity/position changes, divergence navigation, keyboard sliders, terminal holdings and incomplete states. The hardened HTTP preview's CSP preserves packaged styling and interactive controls; mobile inspection shows no page-level overflow or console warnings/errors. [Desktop](assets/failure-lab-desktop.png), [mobile](assets/failure-lab-mobile.png).

Wheel and source builds include inline report assets, pinned sources/licenses, frozen inputs and product documentation. Source archive ownership fields are anonymous and timestamps stable; an independently extracted source archive builds a wheel. Bundled upstream source and license bytes remain unchanged. A regular wheel installation is checked outside the source checkout with isolated Python. Both installed public casebooks reproduce their expected outcomes. The installed native casebook also completes with socket connections blocked.

## Privacy and security

The publication snapshot excludes internal session notes, old identifying Git history, stale packages, caches, virtual environments and generated private artifacts. Screenshots show synthetic reports without account identity, browser chrome or location metadata. The GitHub hosting account is public; commit attribution uses a neutral project identity.

Regression checks cover recognized sensitive inputs, malformed output, trace diagnostics, callback exceptions/replay tracebacks, export references and gallery labels. Fixtures are rejected rather than silently redacted, preserving replay integrity. Preview tests cover traversal, symlinks at every path component, host/origin validation, known-artifact allowlists, directory-listing refusal and security headers. Independent review reproduced and verified fixes for additional export and ancestor-symlink edge cases. [Security policy and limits](../SECURITY.md), [audit scope](security-review.md).

Local verification used Python 3.12.14 and the stated engine versions. Core CI is configured for Python 3.10/3.12/3.13, with optional cases on 3.12; the pinned cases extra requires Python 3.11+. The optional secure HTTP preview supports macOS/Linux and fails clearly elsewhere. Direct HTML opening is the documented viewing path; its browser integration is not independently verified here. Reports retain full simulation data and arbitrary imported callbacks remain ordinary unsandboxed Python.
