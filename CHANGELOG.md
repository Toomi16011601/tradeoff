# Changelog

## 0.4.0 — 2026-10-24

- Center the first-use workflow on future-data dependencies: inspect changed unavailable records, compare the earlier decision, and verify a repair against the original saved fixture.
- Add static `init` setup and one-command `check` reruns with a private project manifest, explicit data conventions, source review acknowledgement and fresh local output directories.
- Compile current local source during checks and replay, including eager/lazy helpers, so stale bytecode cannot falsely verify a repair; preserve callback module state and restore import context.
- Redesign the temporal report as a graphite-and-teal investigation workspace, expose recorded repair verification, and put decision evidence ahead of conditional economics.
- Add a one-command public Riskkit bug investigation with a one-row synthetic witness, unchanged-fixture repair replay, active-repair check and a separate full historical GOOG negative control.
- Add an explicit policy-file setup command and put completed scenario coverage and missing relative-loss limits in the CLI summary. Existing `lab` defaults and the offline report renderer are unchanged.
- Add static script inspection for strategy classes and import-time run/plot hints, plus a native-baseline metric comparison step for an existing Backtesting.py strategy. Neither step executes code during static inspection or proves full strategy equivalence.
- Make the own-strategy walkthrough start with policy choice and baseline comparison rather than an arbitrary absolute return/drawdown example that can stop stress before it runs.

## 0.3.0 — 2026-10-17 · public source alpha

### Tradeoff rename

- Rename the public repository and product to Tradeoff; use `tradeoff` for the distribution, CLI and Python imports.
- Retain the `backtest-witness` command and `backtest_witness` Python namespace as compatibility aliases.
- Preserve saved schema IDs, receipt metadata keys and fixture hashes; earlier report screenshots retain their former branding.

### Hosted compatibility fixes

- Keep report rendering compatible with Python 3.10 by avoiding reused quote delimiters inside an f-string.
- Install the configured build backend with the development extra so archive privacy tests work in clean environments without preinstalled setuptools or wheel.

### Final release audit

- Reject recognized sensitive fields nested inside Python tuples before serializing reports, with the same cycle/depth checks as lists.
- Preserve the saved runner settings and starting capital during repair replay, so changing the simulation environment cannot turn a failed policy into a passing repair. Strategy source and parameter repairs remain supported.

### Data import and integration checks

- Make own-device execution explicit and use direct report-file opening throughout setup; remove local web addresses and server commands from the normal walkthroughs.
- Accept provider-style CSV headers with explicit symbol, timezone, session-close and bar-open duration conventions; retain source clocks and extra input columns with target-to-source mappings.
- Reject ambiguous headers, DST-ambiguous naive timestamps, missing volume and conflicting mappings; report zero-volume and irregular-spacing limitations without filling observations.
- Preflight occupied outputs before strategy import or execution, and return safe structured CLI errors with phase and code.
- Add bounded native strategy column/global checks, explicit prerequisites, partial-validation acknowledgements and project-local companion path/hash bindings for replay.
- Record available strategy/adapter source hashes and known runtime package versions without blocking source repairs or claiming a bundled environment.
- Add opt-in private local diagnostics outside portable reports, using exclusive file creation and owner-only POSIX permissions.

### Agent onboarding

- Explain the strategy-testing workflow and the roles of the trading agent, native simulator and coding agent.
- Add a runnable agent decision function, native strategy adapter and machine-readable check with replayable failure evidence.
- Document the first-use install/run/replay path and check it separately from the optional public-strategy casebook in CI.

### Privacy and security hardening

- Remove identifying launch/session/history metadata from the publication snapshot and normalize source archive ownership/timestamps.
- Reject recognized sensitive inputs and exports; omit ordinary callback exception messages from portable evidence and replay errors.
- Confine HTTP preview to known loopback report artifacts with no-follow filesystem traversal, host/origin checks and CSP.
- Pin CI action commits, restrict token access, and tighten security-fixed development/build minimums.

### Strategy failure lab

- Native Backtesting.py execution reruns under additional commission, spread and market-order bar delay, with authentic equity, closed/open trades and pending orders.
- Declared resilience requirements, repeatability gates, bounded scenario reduction, paired observations and hashed failure fixtures with generated pytest replay.
- Offline failure lab interface and public original/causal strategy casebook, alongside the existing future-data debugger.
- Python execution API, `lab`, `lab-cases` and `replay-failure` workflows. Backtesting.py 0.6.6 is the verified execution backend; reports disclose unsupported scenarios and incomplete search.

## 0.2.0 — unreleased

- Renamed the local project from EdgeLab to BacktestWitness; distribution/CLI `backtest-witness`, Python module `backtest_witness`.

- Finite signed/fractional targets, real engine multi-unit shorts and reversals.
- Direct strategy-class loading, numeric/pandas signal adapters and saved adapter replay.
- Backtesting.py now defaults to upstream nonexclusive orders; set `exclusive_orders: true` to retain 0.1.0 replacement behavior.
- Fixed-notional and stop-distance risk sizing with lot rounding and availability checks.
- Signed ledgers with partial closes, exposure caps, short borrow and insolvency observations.
- Pinned Riskkit and CoinGlass public examples, original source/licenses, verified future-dependency fixtures and causal repairs.
- Public casebook command and offline signed-position evidence reports.

## 0.1.0 — unreleased

- Future-availability intervention audits with repeatability controls and bounded reduction.
- Portable fixture receipts and generated pytest invariance tests.
- Conditional one-share cost/delay projections and real optional engine adapters.
- Offline evidence reports and three no-key synthetic demo cases.

The 0.1.0 scope was one instrument, long/flat targets and deterministic callbacks. The earlier 0.1.0 and 0.2.0 versions were local development versions and were not published.
