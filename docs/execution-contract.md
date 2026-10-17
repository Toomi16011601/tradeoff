# Execution runner and failure artifacts

An execution runner is `run(rows, config, seed, scenario)`. It rebuilds state on each call and returns a finite JSON object:

```python
{
    "engine": "backtesting", "engine_version": "0.6.6",
    "initial_cash": 10000, "effective_settings": {...},
    "scenario": {"commission_bps": 0, "spread_bps": 0, "delay_bars": 0},
    "timing": "...", "warnings": [],
    "equity": [{"timestamp": "...", "position": 0, "equity": 10000}, ...],
    "trades": [...], "open_trades": [...], "pending_orders": [...]
}
```

Equity observations exactly match the complete original input row sequence. Native quantities are signed; positive long, negative short, zero flat. Equity includes the engine's charged fees and marks open positions. Closed native trades expose entry/exit bars, signed size, entry/exit prices, net P&L and commission. Open trade observations and pending orders remain separate; do not treat an open trade's displayed P&L as a settled account ledger.

Runner metadata includes `runner_spec = {"engine": "backtesting", "engine_settings": {...}}` or an explicit callback descriptor, plus optional `adapter_info`. Runtime engine/version and scenario are checked during replay. Callback executions own the truth of their simulator observations.

The `backtest-witness.failure-lab.v1` report includes baseline, scenario list, explicit requirements, run budget/coverage, optional reduced failure, full paired observations and artifact references. Summaries derive return and drawdown from the supplied native equity stream, including initial cash in the running peak. They do not reuse the invariant audit's projection.

The `backtest-witness.failure-fixture.v1` fixture binds the full tape, config, seed, baseline/stress, policy, runner settings and historical observations through content and fixture hashes. Historical results describe the original failure; a repaired strategy need not reproduce their P&L, but must meet the saved requirements under both current baseline and stress. Hashes are integrity receipts, not signed attestations or proof that a model has never seen a case. Repair replay also requires the saved runner specification and starting cash. Changing commission, spread, margin, execution mode or capital is a different simulation, not a repair of the saved case; strategy source and explicit strategy-configuration changes remain allowed. The generated pytest test resolves the saved runner lazily and uses its sibling fixture.

The earlier `edgelab.*` temporal-audit schemas and replay tests keep their existing meanings. Future-data invariance and execution resilience are different assertions and use different commands/artifacts.
