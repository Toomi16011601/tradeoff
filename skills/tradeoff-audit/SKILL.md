---
name: tradeoff-audit
description: Check a local Backtesting.py trading strategy for future-data dependencies with Tradeoff, explain the evidence, and verify an authorized repair against its saved reproducer. Use with historical OHLCV data; this is not live trading or a profitability assessment.
license: MIT
---

# Tradeoff audit

Help the user reach a useful local audit result, including a clear explanation when the project is unsupported or missing inputs. Tradeoff's `init`, `check` and `reproduce` workflow uses the **CLI**. Its separate decision-feedback MCP tools do not expose these audit commands.

Use [the setup guide](references/setup.md) for installation, command examples, timestamp choices and troubleshooting. You need a terminal-capable agent and a local Python environment; no broker, AI key or marketplace tool is required.

## Check fit first — no installation

Read the selected strategy project's files: strategy, imports, runner, dependencies and data provenance. The checkout containing this skill is the tool, not the audit target. Check fit **before** creating a venv, installing packages, importing project code, running a project script or writing a manifest. A dependency name alone doesn't identify the strategy's engine.

- **Unsupported:** If the selected strategy runs on another engine, name the engine and the source evidence. Stop without installing or running anything. This skill's automatic setup is for Backtesting.py; don't port the strategy or claim it passed.
- **Need input:** If you can't identify the intended strategy, find usable price data, establish its clock, or run the original logic safely with its actual settings, say what's missing and ask the smallest question that unblocks it. Stop before setup. In a mixed repo, inspect the selected target or ask which one; don't reject the whole repo based on an unrelated import.
- **Ready:** If you can identify a Backtesting.py strategy compatible with 0.6.6, usable OHLCV data and the execution settings, proceed with setup and the audit in this turn. Fit is a source-based assessment, not an audit result.

## Review inputs

Read relevant source before execution. `tradeoff inspect-script FILE --json` and `tradeoff init` inspect source without importing it; static inspection does not establish that imports are safe. Unguarded downloads, backtests, plots, model calls and broker connections need attention before execution. If an importable extraction is needed, preserve decision logic and helpers and disclose the extraction; make source edits only within the user's authorization.

Get the data's instrument, timezone and bar-label convention from its documented provenance or the user. Date-only rows need a session close; bar-open labels need a bar duration. Examples and generated suggestions are not evidence for these values. Ask for missing data or ambiguous conventions instead of substituting a demo tape, guessing a clock or downloading replacement prices silently.

Check whether the strategy uses its timestamp index for trading decisions. The native adapter supplies a naive UTC **bar-close** index after normalization. An original local-time or bar-open index can therefore have different hour/day semantics. Preserve those semantics through a reviewed, authorized adaptation or report the integration blocker; a completed run alone does not establish equivalence.

## Set up and check

Use the CLI and `audit` extra from the same Tradeoff checkout as this skill when available. Follow the guide to install into an isolated environment outside the strategy project. Keep the same interpreter for setup, checks and replay; use its absolute path with `-m tradeoff`.

From the strategy project root, initialize the actual files with `init --strategy FILE --data FILE --json` and the confirmed data options. Supply the actual `--strategy-class` and `--engine-settings` when required. Preserve explicit `Backtest.run(...)` strategy-parameter overrides in a JSON object passed through `--config FILE`; those parameters are separate from the `Backtest(...)` engine settings. Add `--review-imports` only after reviewing the selected source and relevant dependencies. If a manifest exists, resolve it with `check --project FILE`; do not overwrite it to erase earlier settings or a blocker.

Run `check --json`. Read the returned JSON and its report, not just the process exit code:

| Result | Interpretation |
| --- | --- |
| Exit 1, `FOUND` | A future-input change affected an earlier observed decision. Inspect the paired evidence. |
| Exit 0, `NO_DEPENDENCY_OBSERVED` | None was observed within the reported input, interventions and budget. |
| `NEEDS_INPUT` | Resolve the named setup choices. `init` can exit 0 after writing an incomplete manifest; this is not a completed audit. |
| Exit 2, `INCONCLUSIVE` or `ERROR` | Resolve the named blocker or report the limitation. This is not a pass. |

Keep fresh output directories and retain incomplete coverage, native warnings, warmup and activity information. Do not alter sizing, cash, fees, input conventions or engine settings just to obtain a preferred result. Open the returned HTML path directly as a file. No web server is needed.

For native adapters, the audit compares **observed positions**, so a changed intention without a changed position can remain undetected. The report's economic projection is a separate illustrative ledger with its own cash/cost settings, not the native account. Do not infer native profit, filled orders or inactivity from that projection. If engine output is repetitive, capture stdout/stderr separately in local files and summarize the warnings while retaining the full private log.

## Verify a repair when authorized

For a finding, preserve `reproducer.json` and confirm the unchanged strategy reproduces it before editing. Run the printed `replay` command from the strategy project root using the same environment; a reproduced dependency exits 1. If it is unstable or invalid, report that first.

When the user has authorized a repair, fix the decision logic while retaining the saved fixture, input tape, cutoff and execution assumptions. Replay that **same** fixture; use `--adapter module:RepairedStrategy` for an explicitly different class. Exit 0 means the saved case passes. Explain any warmup or activity change, then run a fresh audit to look beyond that case. A strategy that stops trading has not demonstrated a useful trading improvement.

## Return a useful result

Lead with what happened in trading terms. Use the audit status for the verdict:

- `FOUND`: “Changing [later input] changed the earlier position from [A] to [B].” A verified change is a finding even if the search stopped early or ran out of time narrowing the example. Don't describe the remaining changed bars as all necessary.
- `NO_DEPENDENCY_OBSERVED`: “Earlier positions stayed the same under the tested price and volume changes.” Read the native baseline trace: if every position was zero, say the strategy held no position on the original tape. Name material inputs the audit left unchanged (for example sentiment) from the strategy and coverage notes. Neither result clears the whole strategy.
- `INCONCLUSIVE`: Say what prevented a reliable comparison. If setup stopped before execution, say “No audit ran,” explain why, and give the next step.

Give one next step and, if produced, the local report path. Distinguish source suspicions from observed changes, and an original replay from a verified repair. Mention material limitations or changes to the tested strategy/data without dumping logs.

Keep reports and fixtures local: they can contain the full input history. Do not upload project files, reports, credentials or raw diagnostics to a marketplace or external tool as part of this workflow. The user's chosen agent/provider determines where its context goes; a local CLI does not make that agent offline. Do not place orders or start the project's live runner. Report bounded debugging evidence without promising profitable trading or a globally clean strategy.
