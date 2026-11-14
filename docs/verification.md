# Verification

Tradeoff is public source alpha software. The checks below are local acceptance evidence, not a security or profitability certificate. [Hosted CI results](https://github.com/Toomi16011601/tradeoff/actions/workflows/tests.yml) record runs for published commits. The data-import and integration-check build, recorded before the Tradeoff rename, passed **621 tests** on Python 3.12.14, including native execution, input validation, replay and private diagnostics. That earlier renamed source passed **627 tests** locally; later acceptance checks follow below.

The current future-data investigation screenshots show Tradeoff 0.4.0. Other linked screenshots include earlier-version captures with BacktestWitness branding and document those earlier flows.

## Attribution and replay regression audit (0.6.1) — 14 November 2026

The recreated Python **3.12.13** environment passed **1,054 tests**, with **2 explicit paper-account/LLM opt-in skips**. Actual Backtesting.py 0.6.6, Backtrader and MCP integrations were installed. Independent review reproduced the defects before their fixes and checked the final changes. Main-process Python coverage measured **84.5% of statements** and **79.6% of branches**; this does not include code executed only by isolated subprocesses or browser JavaScript.

- New regressions cover residual native holdings after insolvency, simulator-setting changes hidden behind callback wrappers, impossible fill timing, excessive quantities, replacement/retry chains, conflicting provenance and horizon prices, and future evidence entering historical comparisons. Valid partial fills and strategy/configuration repairs remain supported.
- **30 selected source mutations** were detected by tests. The first run exposed three coverage gaps; new regressions catch the cutoff-boundary, oversized-history-record and conflicting-fill-ID faults. This is a bounded fault set, not an exhaustive project-wide mutation score.
- **500 seeded, adequately funded ledger scenarios**, each with 24 bars, matched an independent Decimal cash-flow oracle across long/short/flat positions, reversals, costs, short borrow and execution lags. Maximum equity disagreement was approximately **1.02e-10**. This does not test live liquidity or native broker liquidation rules.
- Fresh core-only and full-feature wheels completed **35 installed-user scenarios** outside the checkout, including workspaces with spaces, repeated setup, diagnostics, public bug reproduction/repaired replay, native policy-failure replay, both public casebooks and historical engine data. Expected policy-failure and missing-extra exit codes were checked explicitly.
- **Five previously recorded public FinRL runs** retained their exact earlier account comparisons, zero-new-mark collection retries, valid export hashes and incomplete earlier checkpoints. Real stdio MCP exposed **10 tools** and returned a **1,250,621-byte** evaluation. These are recorded-evidence software replays; no policies were retrained and no new unseen-data performance claim is made.
- The repaired optional feedback preview passed desktop **1280 × 720**, mobile **390 × 844** and keyboard checks. Packaged styles/scripts loaded without console errors; the three evidence JSON files were served, while database access remained blocked. The normal workflow still opens local report files directly.

Wheel/source archives were inspected for source parity, integrity, normalized ownership metadata and unintended local artifacts. This scoped inspection and the tests are not a universal security guarantee. Live broker access, full paid-model agent runs and profitability remain outside these checks.

## Large histories and modeled account comparisons (0.6.0) — 13 November 2026

The full local Python **3.12.13** suite passed **987 tests**, with **2 explicit paper-account/LLM opt-in skips**. Regression checks cover histories above 1 MiB through Python, the installed CLI, real local MCP, offline report/evidence export and receipt hashes. The incoming record limit remains 1 MiB. Derived histories use bounded-record output validation and streaming hashing/export/stdout; HTML rendering and MCP text transport still materialize complete strings.

Collection report-validation failures roll back pending marks. If a subsequent export fails after valid observations commit, the operation explicitly reports `COLLECTED_EXPORT_FAILED`; retrying preserves saved evidence and does not duplicate marks. Existing small-report canonical bytes and identifiers remain compatible.

A fresh Python environment installed the candidate wheel and the normal pinned FinRL/PPO/MCP packages with **190 compatible packages**. Five policies were freshly trained for **20,032 steps each** using the same fixed seeds and original training slice. All policy tensors and **60** baseline/candidate financial paths matched the earlier frozen experiment. Independent Decimal ledger replay, prefix causality and repeated-inference checks passed. This reuses already inspected historical data for software regression; it is not a fresh unseen-data trading result.

All **five** paired 400-bar FinRL histories completed normal public `collect_outcomes`, `evaluate_decisions`, `compare_versions` and `export_feedback` calls without a research fallback. Each comparison covered **399** common calendar opportunities, including holds and open terminal stock. All five report exports succeeded, including report JSON files of approximately **1.14–1.37 MB**. Installed CLI and real stdio MCP also passed a roughly **1.25 MB** evaluation response, comparison, zero-new-mark retry and report export. Export receipt hashes matched their files; earlier sequence checkpoints still showed unavailable outcomes and blocked premature comparisons. Manual report-layout review was completed.

The explicit account mode is restricted to one USD cash equity, flat starting inventory and long-only positions. It requires complete modeled cost scopes and fill-linked charges, exact shared market references/valuations and a complete adjacent calendar. Missing or conflicting evidence blocks the result. Cost and execution policy IDs are caller-declared labels, not source attestations. Existing episode attribution, unavailable observed net, historical capture labels and observed-cost comparisons remain unchanged. These checks establish working modeled research comparisons, not improved forecasts, authenticated brokerage profits or general trading improvement. [Contract and setup](feedback-integration.md#simulated-account-comparison).

## Research desk interface — 30 October 2026

The local Python 3.12 suite passed **714 tests**, including actual optional-framework integrations. The report-focused subset passed **108 tests**. The refresh changes report styles, templates and demo media; detector, replay and execution logic are unchanged.

Direct-file Chrome checks covered temporal reports in found, no-dependency-observed and inconclusive states, both demo galleries, and the native execution report at desktop (1440 × 1100) and mobile widths (390 and 360 pixels). No page-width overflow, JavaScript errors or external requests were observed. Checks also covered keyboard skip links, report-view navigation, bar inspection, native scenario selection, first divergence, sibling artifact opening, readable no-JavaScript reports and light print output. [Desktop preview](assets/future-data-investigation.png) · [Mobile preview](assets/future-data-investigation-mobile.png).

The 26-second README GIF uses fresh Riskkit demo evidence and unretouched report crops, with clean scene cuts and selected CLI JSON fields explicitly labelled. A fresh run returned `VERIFIED`, reproduced **29 → 31** on the synthetic 400-bar tape, and passed repaired replay on the unchanged saved fixture. The repair remains active for **95 bars** after warmup; the historical GOOG control remains a bounded negative result. Each frame labels the synthetic input; the repair's warmup change and saved-case limit remain visible.

## Future-data workflow — 24 October 2026

The integrated local suite passed **710 tests** on Python 3.12. Follow-up working-directory guidance was checked with **41 report tests** after that run. The standard-library-only installation also passed **592 tests**, with 82 optional cases skipped. Hosted CI tests the published commit separately, including Python 3.10/3.12/3.13 and the full optional integrations.

An isolated wheel installation outside the checkout, without a development import path, resolved Backtesting.py 0.6.6, pandas 3.1.0 and NumPy 2.5.4. Its installed `demo-bug` command returned `VERIFIED`: unchanged public Riskkit code produced the **29 → 31** earlier-position witness after one unavailable-row edit. The original fixture replay failed as expected, the repair replay passed without changing fixture bytes, and the repaired full tape had **95 nonzero-position bars** after warmup. Actual installed dependency versions are recorded in the exported provenance.

**That positive input is synthetic.** The original 2,148-bar historical GOOG sample is a separate bounded negative control, with no earlier-position dependency observed. Removing `.bfill()` changes native warmup and skips the original early trades; the result is a debugging counterexample and case-specific repair verification, not historical profitability evidence. [Exact source, data and limits](future-data-case-study.md).

Separate synthetic strategy projects exercise the documented `init`/`check` flow, daily provider CSV flags, manifest-relative paths, fresh outputs, original failure and same-fixture repair. Four installed-package regressions cover matching stale bytecode in the strategy, eager helper, package helper and lazy helper: unchanged originals fail CLI replay and exported pytest; real repairs pass. Protected sibling directories no longer prevent unrelated callback imports, while selected strategy import errors remain visible.

Chrome inspection opens the generated HTML **directly as a file**, with no server. Desktop (1440 × 1100), mobile (390 × 844), keyboard navigation, clipboard feedback, source/test links in separate tabs and all four no-JavaScript views pass, with no page errors, external requests or page-width overflow. The report distinguishes verified, failed and unverified repairs. Local-project commands identify the strategy project root and the report path to replace; built-in demos retain export-directory commands. [Current screenshot](assets/future-data-investigation.png).

Source/wheel builds and publication scans include the new modules, inline assets and upstream licenses, with no generated private outputs, known local home paths or private trading material identified. Relative Markdown links and screenshot metadata were checked. This is a scoped inspection, not a security certificate; imported strategies still execute as ordinary Python and fixtures retain their input data.

## Historical GOOG showcase — 22 October 2026

`tradeoff demo-history` runs a Tradeoff long/flat 10/20-day SMA crossover on the 2,148 GOOG daily bars bundled with Backtesting.py 0.6.6. The direct native baseline check matches the lab's 75,645.99 final equity and 46 closed trades. A further 5-bps commission reduces final equity to 72,620.69; all 12 native stress scenarios complete, and fresh reruns verify the declared 2-percentage-point deterioration breach. CLI replay and the generated pytest both fail as expected while the breach remains.

The full local suite passes **654 tests**. The source and wheel build include the new demo, strategy, compatibility aliases and guide. The wheel was installed to a separate target and run outside the checkout using existing native dependencies; the installed command exported and replayed the same failure. A separate clean Python 3.12 environment installed the documented `pip install '.[lab]'` with no inherited packages or `PYTHONPATH`, resolving Backtesting.py 0.6.6 and pandas 3.0.6. Its installed CLI completed all 12 scenarios and replayed the saved failure.

A scan of the five generated files found no local home path or private trading identifiers. Static parsing of the 4.7 MB report confirmed the failure status, scenario coverage, local artifact links and no external resources. Browser security policy blocked direct inspection of this local file, so the larger historical report has **not** had a new desktop/mobile visual check. [Inputs, assumptions and limitations](historical-demo.md).

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

## Interface and packaging — earlier acceptance

The documented first-use flow now states that each user runs their own copy on their own device, then opens the generated `index.html` file. Setup guides contain no local web addresses or server steps. The example completes all 12 scenarios and writes the report; static artifact checks confirm embedded data, CSS and JavaScript, no external assets or fetch/XHR dependency, and valid sibling-file links. At that earlier acceptance, the browser-automation policy blocked direct file navigation. The 0.4.0 direct-file inspection is recorded above.

Desktop, mobile and narrow report inspections cover scenario selection, paired equity/position changes, divergence navigation, keyboard sliders, terminal holdings and incomplete states. The hardened HTTP preview's CSP preserves packaged styling and interactive controls; mobile inspection shows no page-level overflow or console warnings/errors. [Desktop](assets/failure-lab-desktop.png), [mobile](assets/failure-lab-mobile.png).

Wheel and source builds include inline report assets, pinned sources/licenses, frozen inputs and product documentation. Source archive ownership fields are anonymous and timestamps stable; an independently extracted source archive builds a wheel. Bundled upstream source and license bytes remain unchanged. A regular wheel installation is checked outside the source checkout with isolated Python. Both installed public casebooks reproduce their expected outcomes. The installed native casebook also completes with socket connections blocked.

## Privacy and security

The publication snapshot excludes internal session notes, old identifying Git history, stale packages, caches, virtual environments and generated private artifacts. Screenshots show synthetic reports without account identity, browser chrome or location metadata. The GitHub hosting account and commit attribution are public.

Regression checks cover recognized sensitive inputs, malformed output, trace diagnostics, callback exceptions/replay tracebacks, export references and gallery labels. Fixtures are rejected rather than silently redacted, preserving replay integrity. Preview tests cover traversal, symlinks at every path component, host/origin validation, known-artifact allowlists, directory-listing refusal and security headers. Independent review reproduced and verified fixes for additional export and ancestor-symlink edge cases. [Security policy and limits](../SECURITY.md), [audit scope](security-review.md).

Local verification used Python 3.12.14 and the stated engine versions. Core CI is configured for Python 3.10/3.12/3.13, with optional cases on 3.12; the pinned cases extra requires Python 3.11+. The optional secure HTTP preview supports macOS/Linux and fails clearly elsewhere. Direct HTML opening is the documented viewing path; the 0.4.0 check above verifies its temporal-report interface in Chrome. Reports retain full simulation data and arbitrary imported callbacks remain ordinary unsandboxed Python.

## Agent feedback acceptance

The local decision-feedback extension was checked on 2026-11-04. Its evidence classes are deliberately separate:

| Check | Evidence and scope |
| --- | --- |
| Core ledger, attribution, costs and comparison | Independent exact fixtures, retry/restart/concurrency checks, correction revisions and safe argument failures. The synthetic two-pair candidate delta is −80 bps. |
| MCP | Actual MCP 2.3.0 stdio negotiation, tool discovery, recording retry, evaluation, oversized/invalid arguments, safe results and captured stderr. No model or broker needed. |
| Offline interface | Actual Chrome file opening at 1440/390/360px on complete and unknown-cost reports; keyboard skip/table/navigation, no JavaScript, light print and reduced motion. No page overflow, external requests or page errors observed. |
| Public native engine — RETROSPECTIVE | Pinned Riskkit original strategy/sizer in Backtesting.py 0.6.6 on the bundled 2,148-bar historical GOOG tape. All 32 native closed-trade gross values match exact decimal-text projections; native net plus commission agrees within 0.000001 USD of that gross. One open native holding and one pending protective order remain unchanged. |
| Public TradingAgents contract — SYNTHETIC decisions | Hook contract checked at `c4544913a14ed3df5f1ed7b9e8483270ce20682a`, with a real historical GOOG observation and an explicitly synthetic caller-owned decision. Rating is diagnostic, no invented quantity; REVIEW cannot submit an intent. No upstream implementation copied. |
| Alpaca paper account | **NOT_RUN**. Protocol-shaped HTTP responses exercise GET-only behavior, pagination, source identity, late activities and safe failures. These are not an actual account API test. |
| Full public LLM agent | **NOT_RUN**. The real runtime/model test is opt-in and separate from the contract fixture. |
| Better prospective trading | **NOT_ESTABLISHED**. Requires newly captured decisions, matured outcomes and a predeclared evaluation. No profit or winner claim. |

The native import example reconstructs normalized IDs and decision scaffolding from closed-trade aggregates; it is not an actual broker-order/fill adapter. Native float observations carry a precision note. Historical dates use midnight UTC ordering labels, not actual session-close or intraday execution times. Missing/unallocated fees stay unknown. It does not certify historical strategy correctness, live execution or causal improvement.

The synthetic demo runs through the same recording, binding, import and export API as agent integrations. Database/report contents remain private user records; exports are not automatically safe to publish. No real account credentials or private trading project was used in these checks. [Integration guide](feedback-integration.md) · [Source example](../examples/decision_feedback/agent.py).

The independent final review reproduced six issues that were fixed with behavioral regressions: per-order commission completeness, modeled non-applicability, late economic activity dates, restarting attribution from a later verified inventory baseline, opaque generated episode IDs and direct Python envelope privacy checks. Additional checks cover mixed comparison cohorts, unsupported order asset classes, malformed activity dates and equivalent timezone representations. Feedback checks pass **109 tests**, with the two external-account/model tests explicitly skipped.

The pre-publication whole-repository run passed **820 tests**, with **2 intentional external-integration skips**, using Python **3.12.13**, including existing native-framework and audit/lab checks. Publication CI then exposed Python 3.10's handling of `Z` timestamps; evaluation now normalizes all input evidence before comparing times. The updated local Python **3.10.20** core run passed **705 tests**, with **88 optional-integration skips**. The source and wheel archive checks exclude internal plans, private stores, credentials and local account paths; source ownership fields remain anonymous. CI covers the existing Python matrix plus a dedicated MCP job. [Publication PR and CI results](https://github.com/Toomi16011601/tradeoff/pull/13).

The **0.5.0 wheel** was installed outside the checkout in a fresh environment: core imports and the account-free demo worked without optional dependencies; a missing MCP extra returned the safe setup error. After installing the extra, the installed client/server negotiated and exposed all eight tools. Updated metadata/feedback/archive regressions passed **120 tests**, with the same two external checks skipped.

## Local setup and diagnostics (0.5.1)

`connect` was tested from a fresh wheel installation outside the checkout, in a separate virtual environment with spaces in the path. A core-only install reported the missing optional SDK without creating target storage. After installing the MCP extra, the isolated Python/stdio test passed, and a separate SDK client launched the generated configuration and discovered all eight tools in the selected workspace. The target ledger contained no synthetic self-test records. Codex TOML and MCP JSON entries agreed; Windows-style backslashes, spaces and Unicode parsed correctly. This checks generated configuration and protocol behavior, not registration in every agent client.

Diagnostics and repeated setup preserved file contents, modification times and modes. Regression checks cover edited/foreign connection files and manifest fields, environment conflicts, missing bindings versus missing order evidence, filled orders with missing execution records, incomplete inventory/costs, waiting versus missing horizon marks, corrupted evidence and bounded subprocess failures. Closed and active/uncheckpointed WAL databases are safely refused before SQLite opens them; no sidecar files are created or modified. Default DELETE journal mode remains supported.

The final whole-repository Python **3.12.13** run passed **852 tests**, with **2 explicit external-account/model skips**. The Python **3.10.20** feedback/branding/archive check passed **136 tests**, with **15 optional SDK/framework/external-integration skips**. An independent final review confirmed the three corrected issues: WAL sidecar writes, missing fill evidence appearing usable, and edited manifest metadata being overwritten.

Real hook installation remains `NOT_VERIFIED` by these commands. No actual paper-account API, full public LLM-agent runtime or prospective trading improvement was tested for this setup update; their existing opt-in checks and limits remain unchanged. Generated local paths, private stores and test environments are excluded from the public repository and build artifacts.


## Real public-agent feedback loop (0.5.2)

A normal full installation of pinned FinRL `7e98df4` and Tradeoff passed dependency checks. The upstream `DRLAgent` and `StockTradingEnv` executed normally, using a real saved/reloaded SB3 PPO policy trained for 2,048 steps on 1,600 public GOOGL observations, followed by 128 decisions on 129 held-out observations. No mock policy, extracted environment-file import, private project, brokerage account or paid model was used. [Reproduction, source pins and data checksum](public-agent-pilot.md).

The deterministic run produced 128 holds; a separately labelled seeded stochastic run produced 67 fills and 61 holds. Both had 128 unavailable outcomes before collection and 128 available outcomes afterward. Recording preserved every native action, cash balance, holding and account-value observation. Repeating collection appended zero marks, while replaying the old evidence head retained the old missing outcomes. Historical records stayed `LATE_CAPTURE`; uncertain timing, attribution and observed net costs stayed unresolved. This proves integration and price-feedback completion, not profitable or prospective trading.

The final whole-repository Python 3.12 run passed **888 tests**, with **2 explicit account/LLM opt-in skips**. Python 3.10's feedback/branding/archive checks passed **165 tests**, with **16 optional integration skips**. A freshly built wheel also passed the installed CLI-to-MCP workflow outside the checkout: configure one source, complete 128 outcomes, open an offline report, discover ten tools and retry collection without adding events.

An independent review reproduced and verified fixes for conflicting duplicate mark IDs, earlier observation conflicts hidden by later candidates, future-cutoff fabricated availability and FinRL's terminal-only day. Narrow review verification passed 36 tests, including a check against the real installed upstream environment. Collector tests additionally cover exact decimals, source identity, stale/future prices, receipt-time preservation, home-path normalization, atomic failures and private settings. The generated real-data report was inspected at desktop width and an emulated 390px mobile viewport; document scroll width matched viewport width, with intentional navigation/table scrolling contained within their panels.

Local CSV collection requires an explicit stable source file and truthful feed/time conventions. It is not automatic market-data authentication or a broker-fee collector. The actual Alpaca account and full LLM-agent checks remain unrun and separately opt-in. No private trading files or generated runtime evidence are part of the publication source.
