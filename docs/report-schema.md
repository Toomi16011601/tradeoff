# Reports and offline interfaces

## Native execution report

`tradeoff.report.render_failure_report(report)` returns self-contained HTML. `write_failure_report(report, output_dir)` writes `index.html` and readable `report.json`; fixture/test export belongs to the caller. `write_failure_gallery(output_dir, entries)` links local case reports. Rendering does not execute strategies or manufacture evidence.

### `backtest-witness.failure-lab.v1`

| Field | Meaning |
| --- | --- |
| `schema_version` | `backtest-witness.failure-lab.v1` |
| `report_id`, `created_at` | Report identity and aware creation timestamp |
| `status`, `headline`, `reason` | `FAILURE_FOUND`, `BASELINE_FAILED`, `NO_FAILURE_OBSERVED` or `INCONCLUSIVE`, with explanation |
| `strategy_ref`, `runner_spec` | Importable runner reference; execution engine/settings descriptor |
| `dataset` | Symbol, row count, start/end and input hash |
| `requirements` | Nullable minimum return / maximum drawdown / percentage-point deterioration; minimum closed trades |
| `settings`, `coverage` | Seed/call budget; invocations, completed/total scenarios, completeness and notes |
| `baseline` | Zero-additional-stress status, result, metrics, violations and reason |
| `scenarios` | Named scenario objects plus status, result, metrics, violations and reason |
| `failure` | Verified reduced scenario, result, metrics, violations, differences and reduction scope; otherwise null |
| `rows`, `config` | Complete input history/config retained for artifact export |
| `artifacts`, `provenance` | Relative sibling artifact files; optional public source/data disclosures |

Each baseline/scenario entry is `PASS`, `FAIL`, `UNAVAILABLE` or `NOT_RUN`. Unavailable values remain absent with a reason. A report may establish a verified failure even when other scenarios are unavailable. `coverage.runs` counts every native invocation, including repeats, reduction and final verification. A negative conclusion requires the completed declared suite. Metrics are `return_pct`, `net_profit`, `final_equity`, `max_drawdown_pct` and `closed_trades`, derived from native observations with initial cash included in drawdown peaks.

Execution results contain engine/version, initial cash, effective settings, scenario, timing, warnings, an equity/position observation for every original input row, closed trades, open trades and pending orders. Signed positions preserve short and multi-unit quantities. Closed native trades record entry/exit bars, prices, size, net P&L and commission. Open trade observations and pending orders remain separate; open P&L is not a settled account ledger. [Execution contract](execution-contract.md).

`failure.differences` pairs timestamp, before/after position and before/after equity. It localizes divergence without allocating profit causally. `failure.reduction` records complete/runs and a plain-language tested scope; the full input history is retained, and a reduced stress is not a global minimum.

### Failure artifacts and replay

A verified stress failure exports:

- `failure-fixture.json` (`backtest-witness.failure-fixture.v1`): full unchanged rows, config, seed, settings, runner reference/descriptor, baseline/stress, requirements, runtime and historical observations; content hashes and fixture hash bind these inputs.
- `failure-receipt.json` (`backtest-witness.failure-receipt.v1`): report identity, runner, hashes, runtime, coverage/reduction scope and optional provenance.
- `test_failure_resilience.py`: a pytest assertion resolving the saved runner and loading its sibling fixture lazily.

`tradeoff replay-failure failure-fixture.json` repeats current baseline and saved stress, applying the saved policy. Explicit adapter/config overrides support repair without editing fixture hashes. Historical observations describe the original failure; repair returns need not match them. Both current runs must meet requirements, including minimum closed trades when declared. A runtime engine/version mismatch or nonrepeatable result refuses comparison. Hashes are integrity receipts, not signatures, source-authenticity guarantees or proof of reserved-data custody.

The native interface includes a scenario matrix, keyboard-operable scenario selection, paired native equity/position tables, closed/open trade observations, pending orders, failure reduction and replay downloads. Settings, unavailable reasons, public provenance and scope remain visible. Reports have no remote assets or runtime network calls; keep downloads beside the HTML.

## Existing temporal audit interface

`tradeoff.report.render_report(report)` returns a self-contained HTML document.
`write_report(report, output_dir)` writes `index.html` and an unchanged, readable
`report.json`, and returns the HTML path. Fixture and test export belongs to the
caller; rendering does not run a callback or manufacture evidence.

`write_gallery(output_dir, scenarios)` writes a local `index.html`. Each scenario
has `name`, `status`, `path`, and `description`; `path` points to an existing report
relative to the gallery, such as `leaky/index.html`.

## `edgelab.audit.v1`

Serialized schema IDs retain the historical `edgelab.*` and `backtest-witness.*` prefixes after the Tradeoff rename. Receipt runtime keys remain `edgelab_version` and `backtest_witness_version`. Stored report/fixture/receipt formats, validation and content hashes retain their existing interpretation. Current imports and commands use `tradeoff`; `backtest_witness` imports and `backtest-witness` commands remain compatibility aliases.

The older `edgelab` Python namespace has no automatic alias. Its saved built-in callback references need an explicit `--adapter tradeoff...` override selecting the matching original or repaired callback. Do not edit a hashed fixture merely to rename its callback. [Backward replay example](github-launch.md#replaying-earlier-local-artifacts).

The report is a plain JSON-compatible dictionary. Its principal fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | `edgelab.audit.v1` |
| `report_id`, `created_at` | Audit identity and timezone-aware creation timestamp |
| `status`, `headline`, `reason` | Classification and the evidence or blocker behind it |
| `strategy_ref` | Importable `module:callable`, when supplied |
| `trace_kind` | `target_units`, or `observed_position` for an adapter recording holdings |
| `config` | Callback configuration, including an empty object when none is supplied |
| `dataset` | `symbol`, `row_count`, `start`, `end`, `input_hash` |
| `settings` | `seed`, `min_history`, `max_probes`, `max_calls` |
| `coverage` | Callback calls, inspected interventions, cutoff coverage, reduction and notes |
| `baseline.trace` | Original timestamp / finite signed target quantity records |
| `witness` | Verified paired decision evidence, or `null` |
| `economics` | Conditional projections and assumptions, or `null` |
| `economics_error` | Optional explanation when the economic model cannot produce a representable ledger |
| `artifacts` | Safe relative sibling paths to JSON, fixture, test and receipt |
| `repair_replay` | Optional recorded saved-fixture replay: `status`, repaired `adapter`, and optional `reason`; absent means repair not verified |
| `provenance.fixed_patch` | Optional disclosed repair description; explanatory text, not automatic source-line attribution |

The status vocabulary deliberately limits the claim:

- `FOUND`: an observed target at or before the fixed cutoff changed under a
  repeated intervention on records unavailable at that cutoff.
- `NO_DEPENDENCY_OBSERVED`: the inspected interventions did not change the
  observed past targets. This does not certify the strategy globally leak-free.
- `INCONCLUSIVE`: instability, callback errors, insufficient budget, or another
  stated blocker prevented a comparable result.

`coverage.runs` counts callback calls, including stability and reduction calls.
`coverage.probes` counts completed cutoff / mutation-family interventions.
`coverage.cutoffs_probed` counts sampled cutoffs actually inspected, and
`eligible_cutoffs` counts all eligible timestamps. `settings.max_probes` limits
the sampled cutoff count. `coverage.complete`, `reduction_runs`, and `notes`
disclose the search boundary, reduction work and unsupported fields.

## Witness

`witness` contains `cutoff`, `decision_timestamp`, `decision_index`,
`before_decision`, `after_decision`, `mutation_name`, `changed_rows`,
`original_rows`, `mutated_rows`, `mutated_trace`, `reduced`, and
`reduction_complete`. Decision indices and changed-row indices are zero-based.
Each changed row includes `index`, `timestamp`, `available_at`, `before`, and
`after`. Both full tapes retain their original history length and timestamps.

The Evidence view shows prefix decision targets, paired diagnostics, and each
changed OHLC / volume field with its event and availability timestamps.
Availability is the intervention boundary: a delayed record can have an earlier
event timestamp yet still be unavailable at the cutoff. Diagnostics such as
features and reasons do not determine target equivalence. Reduction is greedy
and bounded; a reduced witness is not guaranteed globally smallest.

## Conditional economics

`economics` contains `assumptions`, `original`, optional `intervention`, optional
`delta`, `sensitivity`, `benchmark`, and `explanation`. Both decision traces use
the **same original price tape**. Changed future prices are evidence for the
dependency, not a replacement price tape for the paired equity chart.

Optional `runner_spec` records adapter `engine` and `engine_settings`, and is bound into exported fixture hashes. Optional public-case `provenance` records the source commit, SHA-256 values, extraction boundaries, patches and synthetic inputs.

A ledger exposes `initial_cash`, `final_cash`, `final_quantity`, `final_equity`,
`net_pnl`, `total_fees`, `realized_pnl`, `open_pnl`, `return_pct`,
`max_drawdown_pct`, `equity_curve`, `fills`, and `rejected_orders`.
`equity_curve` is a list of `{timestamp, equity}` records. A fill includes its
fill and signal timestamps, side, quantity, reference and fill prices, notional,
fee, and resulting cash and quantity. The UI displays unspecified currency as
model units; it does not invent a currency denomination.

`delta` means intervention net P&L minus original net P&L under the declared
model. It is not a causal attribution of all strategy profit. Realized plus open
P&L reconciles to final equity minus starting cash; final holdings are marked at
the last close without an invented terminal sale. Observed-position adapters
disclose the additional execution-timing transformation.

Sensitivity entries contain `name`, `settings`, `original`, `intervention`, and
`delta`. An invalid stress can instead carry `status: "UNAVAILABLE"`, a `reason`,
and null ledgers / delta. The table shows those settings and the blocker with
absent values, rather than substituting zero. The benchmark is a one-share
buy-and-hold ledger, not a recommendation.

## Interface and portability

The four hash views are `#overview`, `#evidence`, `#reproducer`, and `#method`.
They are ordinary links, with arrow-key navigation as an enhancement. Without
JavaScript all four sections remain visible, and disclosure controls and file
links still work. The equity chart has a complete accessible table. Its range
control, previous / next buttons, and chart inspection update the selected
timestamp, projected balances and paired targets. The range also supports
native keyboard controls.

The Reproducer view exposes the actual exported filenames and the command
`python -m pytest test_future_invariance.py`. Copying has a selectable-text
fallback when the clipboard API is unavailable. A report without a verified
witness and exported test explains that no reproducer exists. A report without
an economic ledger shows an unavailable state without invented zero results.

CSS and JavaScript are package resources inlined into the report. There are no
remote fonts, modules, fetches, telemetry, or CDN dependencies. Mobile, print,
keyboard, and reduced-motion layouts are supported. Downloads require the
sibling files to remain with the HTML report.

## Data and path safety

All report-derived HTML is escaped. Embedded JSON uses an inert
`application/json` script and escapes angle brackets, ampersands and Unicode
line separators so strings cannot close the script. Interactive values are
written with `textContent`; report data is never inserted as active markup.

Artifact and gallery paths accept only letters, digits, underscores, hyphens,
periods, and relative directory separators. Empty components, `.` / `..`
components, absolute paths, backslashes, URL schemes, URL encoding, query
strings and markup characters raise `ValueError` before output is written.
HTML safety does not replace treating downloaded Python artifacts as code.
Fixtures are reproducibility receipts, not signed attestations.

Signed ledgers additionally expose `total_borrow_cost`, `borrow_charges`, and `risk_events`. Fills add `signed_quantity` and `target_quantity`; the existing `quantity` is the absolute traded delta. Equity curve points add signed `quantity`, `gross_exposure`, and `leverage` (null when equity is nonpositive). Leverage limits new exposure; risk events disclose drift and insolvency without a simulated forced exit.
