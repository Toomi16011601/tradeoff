# Connect a trading agent

Tradeoff is a local tool your agent calls. Your existing agent and broker integration keep making and executing decisions. Tradeoff records evidence and evaluates it; it has no order-execution method.

## 1. Install and connect

Open a terminal in **your trading project's folder**. Use its Python environment, or a separate tool environment if dependencies conflict. The following installs from this GitHub repository, not a similarly named package on PyPI:

```bash
python -m pip install --upgrade "pip>=26.2"
python -m pip install 'tradeoff[mcp] @ git+https://github.com/Toomi16011601/tradeoff.git'
tradeoff connect --project .
```

For a checkout of Tradeoff, install with `python -m pip install '.[mcp]'` first, then point `--project` at your trading workspace. Python 3.10+ is supported; 3.12 is used in the walkthrough.

If you need a separate environment, create it first. Keep `.venv-tradeoff/` out of version control using your project’s ignore rules:

```bash
python3.12 -m venv .venv-tradeoff
source .venv-tradeoff/bin/activate
python -m pip install --upgrade "pip>=26.2"
python -m pip install 'tradeoff[mcp] @ git+https://github.com/Toomi16011601/tradeoff.git'
tradeoff connect --project .
```

On Windows (PowerShell), use the environment directly:

```powershell
py -3.12 -m venv .venv-tradeoff
.\.venv-tradeoff\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\.venv-tradeoff\Scripts\python.exe -m pip install 'tradeoff[mcp] @ git+https://github.com/Toomi16011601/tradeoff.git'
.\.venv-tradeoff\Scripts\tradeoff.exe connect --project .
.\.venv-tradeoff\Scripts\tradeoff.exe doctor --project .
```

`connect` initializes private `.tradeoff/feedback/` storage and writes an ignored, private `connection/` folder:

| File | Use |
| --- | --- |
| `AGENT_SETUP.md` | Registration instructions and a copyable prompt for your coding agent. |
| `mcp.json` | Common MCP JSON configuration with your installed Python and project paths filled in. |
| `codex.toml` | Codex MCP configuration in its native TOML format. |
| `connection.json` | Managed-file checksums and local paths for repeat setup/diagnostics. |

The command verifies the chosen installed interpreter **outside your project**, then records/binds a synthetic intent, retries it and evaluates it through actual local MCP calls in a temporary workspace. That workspace is deleted. It never reads your strategy files, contacts a broker/model, starts your trading agent, or edits global agent configuration. Its result **`SETUP_READY` does not prove your real agent is connected**.

For a separately installed tool interpreter, use `tradeoff connect --project . --python /absolute/path/to/tool-env/bin/python`. It must already contain Tradeoff and the pinned MCP extra. Virtual environment executable paths are preserved. On Windows use the environment's `Scripts/python.exe`.

Choose `--environment simulated` for simulations, `paper` for paper trading (the default for a new workspace), or `live_import` for local live-record imports. The network connector always uses Alpaca paper. Repeating setup preserves evidence and the existing environment; changing environments requires a separate workspace. Edited/foreign connection files are preserved: move the `connection` folder aside yourself before regenerating. After moving a project or environment, rerun `connect` and update the registered client entry.

Python/CLI-only users can still install the core and run `tradeoff feedback init --project .`; MCP and `connect`'s MCP self-test are optional for that path.

## 2. Let your coding agent wire the hook

Paste this in the agent CLI opened on your trading project:

```text
Connect this project to the installed Tradeoff decision-feedback tool.

Inspect the existing decision callback and broker submission path. Use the
tradeoff.feedback Recorder API or the local Tradeoff MCP tools. Record the
explicit intent BEFORE submission; after submission, bind the actual returned
order ID. Record holds and skips too. Use stable event IDs so retries deduplicate.

Read Tradeoff's decision schema. Map the real action, signed quantity, agent
version, opportunity ID, timestamped input/reference, and explicit outcome
horizon. Ask me only for strategy-specific choices the code cannot establish.
Do not invent timestamps, historical initial inventory, costs or quantities.

Initialize the local feedback project if needed. Add a test that records and
binds a fake order without contacting a broker. Use normalized imports for
offline evidence. If I configure Alpaca paper sync, capture initial inventory
before new episodes; missing historical evidence must remain unresolved.

Keep strategy behavior unchanged. Do not place/cancel orders, access a live
endpoint, collect credentials into files, or upload data. Show the local report
filename, integration diff, and remaining evidence gaps. Register a comparison
plan before the evaluation period if comparing a proposed agent version.
```

This is a one-time integration request. A rating-only or already-submitted-order callback may need to be split so recording happens before submission. Tradeoff does not silently scan every project file or connect to an arbitrary agent without a hook.

## 3. Python hook

The caller supplies a validated intent, using the schema returned by:

```python
from tradeoff.feedback.contracts import schema_for
decision_schema = schema_for("decision")
```

Insert this sequence around **your existing code**:

```python
from tradeoff.feedback.recorder import Recorder

recorder = Recorder(".")
intent = my_agent.decide(history)  # Your adapter returns the decision-schema dict.
receipt = recorder.record_decision(intent, event_id="run-42-decision-1")
order = my_broker.submit_existing_policy_order(intent)  # Your existing broker call.
recorder.bind_order(
    {"decision_id": intent["decision_id"], "source_alias": "paper",
     "order_id": order.id},
    event_id="run-42-binding-1",
)
```

`my_agent` and `my_broker` stand for your own objects. For holds/skips, record a zero signed quantity and do not submit or bind an order. Reuse the event ID after a lost acknowledgement; assign a new ID for a new decision. Each episode needs a unique context ID across sources. Store quantities and prices as decimal strings, not binary floats. All timestamps require an explicit timezone.

[Runnable synthetic example](../examples/decision_feedback/__main__.py) · [TradingAgents rating hook](../examples/decision_feedback/tradingagents_hook.py). The TradingAgents hook requires caller-owned intent/size; `REVIEW` cannot become a trade.

## 4. Register the generated local MCP entry

Open `.tradeoff/feedback/connection/AGENT_SETUP.md` on your device. Your coding agent can do the client-specific configuration step, preserving other servers/settings:

- For clients using `mcpServers` JSON, merge the generated `mcp.json` entry into that client's MCP settings.
- **Codex uses TOML**, not the JSON wrapper. Merge `codex.toml` into a trusted project's `.codex/config.toml` or your existing local Codex config, preserving other settings. Reload the client's MCP connection. [Official Codex configuration](https://developers.openai.com/codex/mcp).

The generated entry uses an absolute installed-environment Python path and `-I -m tradeoff feedback mcp --project <your workspace>`. `-I` avoids importing a same-named module from the client/project directory. No local web address or hosted service is involved. Each user runs their own stdio process on their own device.

Setup never changes an agent client's config automatically. The client manages when the server starts. Keep generated files private: they contain local paths. Inspect the ten tools in your client, then give your agent the generated integration prompt. Registering MCP makes the tool available; wiring the real callback and its fake-broker test is still required.

## Check setup and evidence

From the trading workspace:

```bash
tradeoff doctor --project .
tradeoff doctor --project . --json
```

`doctor` opens a read-only SQLite snapshot and verifies its hash chain. If generated connection files exist, it checks their integrity and probes their interpreter outside the project. It does **not** start your target MCP server, seed records, run strategies, sync a broker or write reports/configuration. Tradeoff’s default SQLite DELETE journal mode is supported. WAL-mode databases are safely blocked: even SQLite `mode=ro` can create WAL sidecars, while immutable reads could miss pending evidence. Keep the source unchanged and use a separate consistent SQLite backup in default DELETE mode for diagnostics.

Setup readiness, evidence completeness and real-hook verification are separate fields. No decisions means `NO_DECISIONS`, not a pass. Missing explicit bindings differ from bound orders whose evidence has not been imported. An order reporting fills without enough matching execution records produces a separate fill-evidence warning. Waiting horizons use `WAIT`; a matured horizon without an eligible mark needs evidence. Initial inventory must precede new episodes, and missing fees stay unknown. The doctor never fabricates those records.

Diagnostic summaries contain counts and fixed next steps, not decision payloads or broker IDs. A saved self-test or stored decision cannot verify your actual integration, so `agent_hook` remains `NOT_VERIFIED`; inspect and test the callback yourself. A `PASS` storage check verifies the local chain, not market truth or a security boundary.

## 5. Collect paper evidence and evaluate

Only configure sync if you use Alpaca paper. Provide `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` to the local process environment, using your own credential manager or local setup. Do not commit them. Other operations do not read them, and Tradeoff never includes them in reports or MCP results.

```bash
tradeoff feedback sync-alpaca-paper --source-alias paper \
  --start 2026-01-05T14:00:00Z --end 2026-01-05T16:00:00Z --json
tradeoff feedback evaluate --as-of 2026-01-05T16:00:00Z --json
tradeoff feedback report --as-of 2026-01-05T16:00:00Z --output feedback-output
```

Those timestamps are examples: choose the actual requested interval and evaluation time. An initial sync done **before** new trading supplies a possible future baseline, not a historical one. Syncs overlap two days by default to catch late observations, but cannot certify complete economic history. Unsupported activities, missing fees or capped/failed fetches remain visible. A sync does not evaluate newly recorded decisions before their horizon has matured.

Open **`feedback-output/index.html`**. The market need not be open to evaluate stored records. Recording new real paper outcomes needs your own configured agent/account and elapsed observation time. Tradeoff itself never starts trading.

## Automatically collect outcome prices

Once the recording hook works, configure the **existing local price CSV** used by your agent. Your coding agent can do this once from the real data contract. Tradeoff reads the one selected file; it does not scan directories or contact a provider.

For a single-instrument CSV with aware `timestamp`, decimal `price` and optional `available_at` columns:

```bash
tradeoff feedback price-source --project . --data data/prices.csv \
  --symbol SPY --currency USD --source my-market-data --feed my-feed \
  --price-kind mid --available-at-column available_at
tradeoff feedback collect --project . --output feedback-output-collected
```

Use the **actual** symbol, source, feed and price kind declared in your decisions. `mid` is appropriate only for midpoint observations; a close cannot be relabelled as a quote. For a file with `Date,Close`, set `--timestamp-column Date --price-column Close --price-kind close`, and explicitly supply `--timezone` and `--session-close` for date-only labels. These are caller-owned conventions; no exchange calendar, adjustment policy or historical availability is inferred. Select a completed, stable single-instrument snapshot.

If your file has no original receipt-time column, omit `--available-at-column`. Each newly collected observation then becomes available **when Tradeoff actually reads it**, not at its historical price timestamp. That supports retrospective evaluation now, without claiming that you knew the price earlier. Historical `--as-of` needs genuine recorded availability at or before that cutoff. A collection cutoff later than the actual read time is rejected.

After configuration, future runs need only:

```bash
tradeoff feedback collect --project . --json
```

The result contains refreshed feedback, collection counts and unresolved reasons. Add `--output` with a fresh name to create an offline report; open its `index.html` as a file. No server is needed. This is an explicit one-shot command that your agent or scheduler can invoke; it does not install a background task.

- Only matured decisions with an exact matching symbol/currency/source/feed/price-kind contract receive observations. Holds and skips have outcomes too.
- A selected price must be at or before the declared horizon and within its freshness tolerance; future-only or stale prices remain unresolved. Pending horizons stay waiting.
- Original decimal strings are preserved. Repeated collection adds no duplicates or changed receipt times; conflicting stored observations stop collection before new marks are appended.
- This completes **horizon-price feedback**. It does not invent fills, historical inventory or missing fees, calculate causal execution impact, or establish complete net trading returns.

Source settings stay in ignored `.tradeoff/feedback/price-source.json`, with a project-relative file path. Repeating the same setup preserves it; changing settings requires `--replace`. Reconfigure after moving an external data source. Source files are bounded to 16 MiB/100000 rows. Recognized secrets and conflicting embedded source identities are rejected. A configured local file remains user-supplied evidence, not authenticated market data.

For Python, call `FeedbackApp.configure_price_source({...})` and `FeedbackApp.collect_outcomes({})`. MCP exposes the same operations as `tradeoff_configure_price_source` and `tradeoff_collect_outcomes`; the latter returns feedback directly, with an optional fresh report directory. [Real FinRL pilot and reproducible commands](public-agent-pilot.md).

## Comparison plans, corrections and CLI input

Register a plan with `FeedbackApp.register_comparison({"event_id": ..., "plan": ...})` or its MCP tool. `schema_for("comparison_plan")` lists the exact fields. Register it before its future window; revisions require a new plan ID with `supersedes_plan_id`. A late revision remains retrospective.

CLI `record`, `bind-order`, `import` and `plan` accept the same argument object as their MCP tool through `--input file.json` or `--input -` (stdin). `import` takes `{"records": [...]}`; imported history is always labeled imported. `evaluate`, `compare` and `report` accept `--as-of-seq` for a retained evidence head. Every `--project` points at your workspace root, not the private database file.

Cost corrections append a new cost with `corrects_cost_id`. To resolve an earlier cost-scope declaration, append a new `cost_scope` with `supersedes_scope_hash` equal to the SHA-256 of the previous canonical scope payload. Old heads and exported reports stay unchanged. Unlinked or branched changes remain unresolved.

Feedback subcommand exit codes: `0` means the operation completed (possibly with insufficient evidence), `1` means partial broker sync, and `2` means invalid/failed operation. `connect` exits `0` for its successful isolated setup and `2` for blocked/invalid setup. `doctor` exits `1` for setup/evidence gaps, `2` for invalid arguments/failed invocation, and `0` only when the generated setup is usable and stored evidence is available or waiting without a diagnosed evidence gap. Even exit `0` does not verify the real hook. A zero exit is never a profitability certificate.

## Simulated account comparison

The existing comparison workflow also supports an explicitly modeled, USD, long-only, single-stock cash account per version. Use **different** `baseline_source_alias` and `candidate_source_alias` values for the two isolated simulated accounts. This does not turn paper or broker evidence into simulated evidence or backdate imported capture.

Save this argument object as `simulation-plan.json`, substituting the versions, source aliases, symbol and market-data contract actually recorded in your evidence:

```json
{
  "event_id": "register-simulation-plan-1",
  "plan": {
    "plan_id": "simulation-plan-1",
    "baseline_version": "v1",
    "candidate_version": "v2",
    "window_start": "2026-01-05T14:30:00+00:00",
    "window_end": "2026-01-07T14:30:00+00:00",
    "metric": "simulated_account_return_bps",
    "horizon_policy": "decision_at_declared_end",
    "reference_policy": "exact_reference",
    "cost_policy": "complete_modeled",
    "match_policy": "same_market_calendar",
    "minimum_pairs": 1,
    "simulation": {
      "baseline_source_alias": "baseline-simulation",
      "candidate_source_alias": "candidate-simulation",
      "initial_cash": "100",
      "currency": "USD",
      "symbol": "SYNTH",
      "asset_class": "us_equity",
      "valuation_source": "fixture",
      "valuation_feed": "daily",
      "price_kind": "close",
      "initial_at": "2026-01-05T14:30:00+00:00",
      "terminal_at": "2026-01-07T14:30:00+00:00",
      "expected_decisions": 2,
      "cost_model_id": "explicit-fill-fees-v1",
      "execution_policy_id": "recorded-fills-include-shortfall-v1",
      "timestamp_policy": "declared_historical_ordering",
      "acknowledge_assumptions": true
    }
  }
}
```

```bash
tradeoff feedback plan --input simulation-plan.json --project .
tradeoff feedback compare --plan-id simulation-plan-1 --as-of 2026-02-01T00:00:00+00:00 --project .
tradeoff feedback report --plan-id simulation-plan-1 --as-of 2026-02-01T00:00:00+00:00 --output feedback-simulation-report --project .
```

Python uses the existing `FeedbackApp.register_comparison`, `FeedbackApp.compare_versions` and `FeedbackApp.export_feedback` operations; MCP uses the same existing registration, comparison and export tools. There is no separate simulation tool. The normal `comparison_plan` schema includes all fields above; revisions still require a new plan ID and the existing supersession rules.

Both versions must cover every common opportunity, including holds/skips, with matching decision times, horizons and exogenous reference prices/source/feed/kind. Adjacent horizons must reach the next decision and finally `terminal_at`; `expected_decisions` is the full count per version. The example declares two adjacent opportunities, not two closed trades. Initial inventory must be established as flat with no open orders. Exact, available valuation marks must cover the shared calendar through the terminal timestamp. Different agent inputs may have different hashes; the shared market path is checked separately.

Every fill needs complete **modeled** cost coverage and explicit fill-linked charges for each applicable component, including fills belonging to a still-open holding. Declare genuinely inapplicable components in a modeled `cost_scope`; absent fees are never zero. Fill prices contain the recorded execution effect; the explicit charges are added once. The cost/execution IDs name caller-owned assumptions, not authenticated schedules or execution guarantees.

The result uses `tradeoff.simulated-account-comparison.v1`. Valid `MODELED_ACCOUNT_COMPARISON` results report cash plus marked holdings, modeled net account return and candidate-minus-baseline difference. `matched_count` is common calendar opportunities; `pairs` stays empty. `INSUFFICIENT_EVIDENCE` or `NOT_COMPARABLE` results keep account metrics unknown and disclose exclusions. The report shows **MODELED SIMULATION**, return percentages, delta percentage points, fees, drawdown and turnover; retrospective capture and timestamp warnings stay visible. This is modeled research under declared assumptions, not observed broker profit, proof of prospective knowledge, or automatic agent optimization.

## Privacy and troubleshooting

- `PROJECT_NOT_INITIALIZED`: run `tradeoff connect --project .` with the same workspace (or `feedback init` for Python-only usage).
- `SETUP_BLOCKED`: use the interpreter named by `--python` to install Tradeoff and its `mcp` extra; a source checkout on `PYTHONPATH` alone is not an installation. Probe errors are bounded and raw subprocess output is discarded.
- `CONNECTION_CONFLICT`: preserve edited connection files, move that folder aside, and rerun `connect`. Evidence is never reset.
- `ENVIRONMENT_CONFLICT`: use the existing recording environment or choose a separate workspace.
- `MCP_NOT_INSTALLED`: install the `mcp` extra in the exact environment your agent launches.
- `OUTPUT_EXISTS`: choose a fresh report/demo output directory.
- `BROKER_NOT_CONFIGURED`: configure local paper credentials only if you want that connector; offline imports/demo need none.
- `SOURCE_CHANGED`: use a separate source alias or project for another account. Never join accounts by symbol/time alone.
- Unknown net or missing attribution is an evidence gap to resolve, not a failed trading recommendation. Inspect Data quality first.

Database, input snapshots and reports can contain proprietary records. Input content is opt-in; references/hashes are the default. Portable exports pseudonymize broker IDs and reject recognized secrets, but need your review before sharing. Tradeoff has no telemetry or upload service. A cloud coding agent's provider policy still applies to whatever that agent sends externally.
