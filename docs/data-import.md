# Import your strategy's historical data

Run BacktestWitness from your own project, where the strategy module and any companion inputs are available. The importer reads local files. It does not download prices, scan the project for credentials, initialize your strategy's external state or fill missing observations.

## Use an ordinary provider CSV

For daily data with `Date,Open,High,Low,Close,Volume` headers:

```bash
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --data daily.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --requirements requirements.json --output failure-output --json
```

Replace the symbol, timezone and closing time with your declared dataset conventions. `16:00` is an illustrative regular close, not an exchange-calendar lookup. Early closes, holidays and session changes are not inferred. This command assumes you have already saved your [requirements](failure-lab.md#declare-what-failure-means).

The importer accepts case-insensitive `Open`, `High`, `Low`, `Close`, `Volume` and `Symbol` headers. It recognizes `Timestamp`, `Datetime`, `Date` or `Time` as time-column candidates. Column names must be unique, including after trimming and ignoring case. If multiple time columns exist, select one with `--timestamp-column Datetime`.

One file must represent one instrument. If the file has no symbol column, supply `--symbol`; the filename is never used to guess it. An explicit symbol cannot silently replace a different embedded symbol. Missing OHLCV fields, invalid prices, duplicate or unsorted timestamps and inconsistent row widths are errors. Missing volume is not replaced with zero.

## Declare what timestamps mean

| Source labels | Required choice |
| --- | --- |
| Aware ISO datetime at bar close | Default `--timestamp-kind close` |
| Naive datetime | Add `--timezone` with an IANA name |
| Date only, such as `2025-01-03` | Add `--timezone` and `--session-close HH:MM` |
| Datetime at bar open | Add `--timestamp-kind open --bar-duration 1h` or another fixed duration |

Close timestamps and `available_at` are normalized to UTC. A missing `available_at` defaults to the bar close. Existing availability cannot precede the normalized close. Supply extended ISO dates or datetimes; epoch numbers and locale-specific date formats are unsupported. Ambiguous or nonexistent naive times at daylight-saving changes need explicit timezone-aware input.

Fixed durations accept positive integer `s`, `m`, `h` or `d` units. A day means exactly 24 hours; it is not an exchange session. `--bar-duration` is only for bar-open datetimes. Date-only session labels use the declared session close and cannot be treated as bar opens.

For hourly source labels at bar open:

```bash
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --data hourly.csv --symbol DEMO --timestamp-kind open --bar-duration 1h \
  --requirements requirements.json --output hourly-failure-output --json
```

No bars are inserted. Execution delay counts observed bars, so one extra daily bar can mean a missed trading session rather than a fixed 24-hour wait. Irregular spacing is reported as a warning; market closures and missing observations can both cause it.

## Preserve source clocks and feature columns

Original noncanonical time columns, such as `Date` or `Datetime`, remain available alongside normalized `timestamp`. Additional input columns are retained. CSV extras use scalar JSON numbers, booleans or null where parsable; other cells remain strings. Existing JSON input may retain nested feature values, though a strategy must handle their meaning itself.

Some strategies need the original bar-open clock for a time-of-day filter. Copy that source field with a target-to-source mapping:

```bash
backtest-witness lab --adapter my_strategy:MyStrategy --engine backtesting \
  --data hourly.csv --symbol DEMO --timestamp-kind open --bar-duration 1h \
  --column-map '{"Time":"Datetime"}' --require-column Time \
  --requirements requirements.json --output time-filter-output --json
```

Here `Time` contains the original `Datetime` string; `timestamp` contains the calculated bar close. A strategy can explicitly parse `Time` with `pandas.to_datetime`. The importer does not silently convert the source clock or calculate indicators.

`--column-map` also accepts explicit canonical mappings for nonstandard headers, such as `{"open":"o","high":"h","low":"l","close":"c","volume":"v"}`. It rejects mappings that replace already detected canonical market fields or overwrite a different extra column.

## Check strategy prerequisites

Native `lab` preflight inspects direct strategy-method data attributes and module-global loads. It can catch a missing `self.data.Time`, a referenced module global still set to `None`, or an all-zero volume feed used by the strategy. It does not inspect every helper, dynamic lookup or initialization path. Importing the strategy happens before these checks and can execute Python.

Declare dependencies the bounded inspection may miss:

```bash
backtest-witness lab --adapter strategy_adapter:MyStrategy --engine backtesting \
  --data daily.csv --symbol DEMO --timezone America/New_York --session-close 16:00 \
  --require-column Regime --require-global MARKET_FILTER \
  --companion-data data/market.csv \
  --requirements requirements.json --output declared-input-output --json
```

Only include declarations your strategy actually needs. Repeating `--require-column`, `--require-global` and `--companion-data` adds dependencies. Required column names are case-sensitive for extra features. Declarations validate presence and initialization; they do not verify a feature's economic or causal correctness.

A companion-market filter often needs an importable adapter to initialize the original module's state before exporting the strategy class. Supplying `--companion-data` records the file; it does **not** read that file into a strategy global or create `Regime` for you. A third-party indicator helper broken by a dependency-version change still requires a reviewed manual repair or a compatible dependency version.

For an intentionally optional global, `--allow-uninitialized-global OPTIONAL_CACHE` acknowledges an existing `None` value and records a warning. It cannot waive an explicit `--require-global OPTIONAL_CACHE`. Do not use it to bypass missing market-filter state.

## Understand volume warnings

All-zero volume produces `ZERO_VOLUME` data warnings. When the inspected native strategy reads volume, preflight refuses to run until you supply a suitable feed or explicitly pass `--allow-zero-volume`.

That flag records **partial strategy validation**. For example, a `Volume >= rolling_mean(Volume)` condition is ineffective when every value is zero. Acknowledgement does not restore the missing feature or validate the complete strategy. Choosing a more faithful feed is preferable.

## Keep replay dependencies available

`--companion-data` accepts files inside the current project. The saved `runner_spec` binds their project-relative paths and SHA-256 hashes. Replays check those files before resolving the runner and before execution; missing or changed files refuse comparison. Run replay and generated pytest from the same project root, or restore the same relative layout and contents in another project.

Companion contents are **not copied or bundled**. Exported fixtures do not contain a self-contained strategy environment. Keep the source, companion files and dependency lock separately. Native CLI reports record available strategy/adapter file hashes and known runtime package versions as provenance. Source hashes document the tested code; they do not prohibit strategy changes during repair or cover every imported helper.

## Read errors without sharing private traces

`lab --json` and `audit --json` return structured input errors with exit 2:

```json
{
  "status": "ERROR",
  "phase": "data",
  "error": {
    "code": "TIMEZONE_REQUIRED",
    "type": "DataImportError",
    "message": "Naive dates and times require an explicit timezone (IANA name)",
    "hint": "Rerun with --diagnostics <private-file-outside-output> for a private local traceback; review that file before sharing."
  }
}
```

An `INCONCLUSIVE` report can instead mean a callback failed during the simulation. Its portable evidence omits arbitrary exception text. To inspect the actual exception locally, opt in to a new private trace file outside the report directory:

```bash
backtest-witness lab --adapter my_strategy:MyStrategy --data bars.csv \
  --output debug-output --diagnostics private-trace.txt --json
```

Add the same data/import and policy flags as your original command. The diagnostics parent directory must exist. Existing files and final-component symlinks are refused; the file is created with owner-only permissions where supported. Traces may include private paths, source lines and exception messages, but no captured local-variable dump. They are not embedded in report JSON, HTML or stdout. Keep them outside shared artifacts and review before sharing. [Security boundaries](../SECURITY.md).

## Python import API

```python
from backtest_witness.data import load_data, inspect_data

rows = load_data("daily.csv", symbol="DEMO", timezone="America/New_York",
                 session_close="16:00")
warnings = inspect_data(rows)
```

The API accepts `timestamp_column`, `timestamp_kind`, `bar_duration` and `column_map` with the same explicit conventions. It returns validated copies of rows. Existing normalized lowercase CSV and JSON remain supported. `DataImportError` exposes safe `code` and `columns`; warnings have `code`, `message` and `columns`.
