# Connect a trading agent

Tradeoff is a local tool your agent calls. Your existing agent and broker integration keep making and executing decisions. Tradeoff records evidence and evaluates it; it has no order-execution method.

## 1. Install in your agent's environment

For this local checkout:

```bash
python -m pip install '.[mcp]'
```

Use `python -m pip install .` if you only need Python/CLI. Python 3.10+ is supported; the walkthrough uses 3.12. Windows users can call `.venv\Scripts\python.exe` and `.venv\Scripts\tradeoff.exe` directly, without activation.

Open your **trading project**, then initialize:

```bash
tradeoff feedback init --environment paper --project .
```

This creates a private `.tradeoff/feedback/` folder with its own ignore file. Choose `--environment simulated` for simulations, or `live_import` for local live-record imports. The network connector always uses Alpaca paper. Use a separate project for a different environment; initialization never resets existing evidence.

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

## 4. Optional local MCP

Add an MCP server to **your agent client's local configuration**. Replace the two absolute paths with the Python executable in your environment and your trading workspace. Configuration wrappers vary by client; this is the common `mcpServers` shape:

```json
{
  "mcpServers": {
    "tradeoff": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "tradeoff", "feedback", "mcp", "--project", "/absolute/path/to/trading-project"]
    }
  }
}
```

On Windows, use the environment's `Scripts/python.exe` path with JSON-escaped backslashes or forward slashes. The agent client starts a stdio process on **your device**. There is no localhost URL and no dependency on the publisher's computer.

The eight tools are `tradeoff_record_decision`, `tradeoff_bind_order`, `tradeoff_import_evidence`, `tradeoff_register_comparison`, `tradeoff_sync_paper_evidence`, `tradeoff_evaluate_decisions`, `tradeoff_compare_versions`, and `tradeoff_export_feedback`. They share Python/CLI logic and fixed schemas. They accept no shell command, arbitrary broker URL or unrestricted output path. Evaluation is read-only; recording, sync and export write local state. This boundary is not an OS sandbox for an agent that already has other tools.

Initialize the feedback project first, then reload your agent client after adding the configuration so it starts the new server. If it cannot discover the tools, check the configured Python executable and project path; both must exist on the same device as that agent client.

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

## Comparison plans, corrections and CLI input

Register a plan with `FeedbackApp.register_comparison({"event_id": ..., "plan": ...})` or its MCP tool. `schema_for("comparison_plan")` lists the exact fields. Register it before its future window; revisions require a new plan ID with `supersedes_plan_id`. A late revision remains retrospective.

CLI `record`, `bind-order`, `import` and `plan` accept the same argument object as their MCP tool through `--input file.json` or `--input -` (stdin). `import` takes `{"records": [...]}`; imported history is always labeled imported. `evaluate`, `compare` and `report` accept `--as-of-seq` for a retained evidence head. Every `--project` points at your workspace root, not the private database file.

Cost corrections append a new cost with `corrects_cost_id`. To resolve an earlier cost-scope declaration, append a new `cost_scope` with `supersedes_scope_hash` equal to the SHA-256 of the previous canonical scope payload. Old heads and exported reports stay unchanged. Unlinked or branched changes remain unresolved.

JSON exit codes: `0` means the operation completed (possibly with insufficient evidence), `1` means partial broker sync, and `2` means invalid/failed operation. A zero exit is never a profitability certificate.

## Privacy and troubleshooting

- `PROJECT_NOT_INITIALIZED`: run `tradeoff feedback init --project` with the same workspace.
- `MCP_NOT_INSTALLED`: install the `mcp` extra in the exact environment your agent launches.
- `OUTPUT_EXISTS`: choose a fresh report/demo output directory.
- `BROKER_NOT_CONFIGURED`: configure local paper credentials only if you want that connector; offline imports/demo need none.
- `SOURCE_CHANGED`: use a separate source alias or project for another account. Never join accounts by symbol/time alone.
- Unknown net or missing attribution is an evidence gap to resolve, not a failed trading recommendation. Inspect Data quality first.

Database, input snapshots and reports can contain proprietary records. Input content is opt-in; references/hashes are the default. Portable exports pseudonymize broker IDs and reject recognized secrets, but need your review before sharing. Tradeoff has no telemetry or upload service. A cloud coding agent's provider policy still applies to whatever that agent sends externally.
