# Agent decision feedback

Tradeoff records an agent's intended decisions, links them to execution evidence, and reports which outcomes and comparisons the data supports. It helps you decide **what to investigate or test next**. It does not optimize a strategy, place orders or prove a change will make money.

Everything runs on your device. Reports are files you open in a browser. There is no Tradeoff account, upload service, HTTP listener or required model API.

## Try it without a broker

From the checkout, after creating the virtual environment:

```bash
python -m pip install '.[mcp]'
tradeoff feedback demo --output feedback-output-demo
```

Open **`feedback-output-demo/report/index.html`**. The output is clearly labeled **synthetic**. The example has a partial-cancel long with gross `1` and net `0.95`, a short whose net stays unknown because borrow costs are missing, a mixed-version episode excluded from attribution, and two matched version pairs. The candidate-minus-baseline mean is **−80 bps**, on entry notional, for that eligible subset. It is a deliberately controlled example, not market performance.

No model, account, market connection or open market is needed. Repeating the demo needs a fresh output name. The optional MCP extra is needed only for agent clients using MCP; the Python/CLI demo works with a core installation too.

## Connect your agent once

[Follow the integration guide](feedback-integration.md). Your agent needs a callback **before it submits an order**, plus the returned order ID afterward. It also records holds and skips. After wiring this hook, recording is a function/tool call, not a form you complete for each trade.

You declare the action, signed quantity, version, opportunity, evaluation horizon, and timestamped reference. Tradeoff cannot infer your intent from an arbitrary project or a recommendation such as “Buy.” MCP exposes the schemas; Python exposes `schema_for("decision")`.

Run the initial paper sync **before** the first episode you want to attribute. It captures current inventory and open orders, with a snapshot window. Syncing an old account today cannot establish that its historical opening inventory was zero. Missing bindings, external trades or incomplete inventory remain visible exclusions.

## Read the report

| View | What it answers |
| --- | --- |
| Data quality | Were decisions captured in time? Are bindings, inventory and costs resolved? |
| Decisions | What did each version intend? Is its declared horizon mature? |
| Outcomes | Which flat-to-flat episodes are attributable? Which costs remain unknown? |
| Compare | How do eligible matched opening decisions differ under the recorded plan? |
| Evidence | Which sequence, normalized records and byte-integrity receipt support the result? |

Gross cash flow, observed net, modeled net and market-price outcomes are separate. Fees missing from a paper API are **not zero**. A price difference from the decision's quote includes intervening market movement and is not pure market impact. A sell that closes a long is not automatically a bearish prediction. Open holdings have no completed-episode profit.

Comparisons cover the **eligible both-traded subset** and disclose the remaining decisions. Holds, skips, unmatched periods, incompatible feeds, unknown costs and ambiguous ownership are excluded from the numeric pairs. Results are descriptive; no automatic winner is declared. A late plan or reconstructed record cannot become prospective just by changing its caller-supplied timestamp.

## Current boundaries

- First network connector: **Alpaca paper**, GET endpoints only. No submission, cancel or live endpoint.
- Supported attribution: USD equities, fractional/signed shares, separate flat-to-flat long/short episodes with a known initial inventory observation.
- Mixed versions/owners, within-fill reversals, unsupported child orders, corporate actions and FX stay excluded. No account-level portfolio-return claim.
- An observed zero needs explicit evidence and a declared applicable cost set. Personal taxes are outside this metric. A fee assumption is modeled evidence.
- SQLite and local clocks are user-editable. Hash-linked receipts detect changes relative to retained heads; they are not signatures or authenticated proof of prospective capture.
- Exports can contain proprietary trading records. Pseudonyms and recognized-secret checks do not make them safe to share automatically. Your external coding agent controls what it sends to its provider.

[Verification evidence and unrun checks](verification.md#agent-feedback-acceptance) · [Public integration example](../examples/decision_feedback/agent.py)
