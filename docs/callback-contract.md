# Callback contract

```python
run(rows: list[dict], config: dict, seed: int) -> list[dict]
```

Each invocation must reconstruct preprocessing, feeds, model state and engine state. Tradeoff deep-copies rows/config and repeats calls, but cannot force a callback to discard hidden caches, subprocess state or trained weights. Repeatability checks compare decisions; diagnostics may differ without changing the verdict.

## Input

One symbol per dataset. Strictly increasing, unique timezone-aware ISO timestamps. `timestamp` is the close of a bar. `available_at` is when that completed record can be used; it defaults to `timestamp` and cannot precede it. Prices must be finite and positive, volume finite and nonnegative, and highs/lows coherent. All values/config must be JSON-compatible. Additional fields survive copying but are not mutated by this release.

Validation normalizes timestamps to UTC. The callback receives the full table, including unavailable records. This is deliberate: bugs in full-frame preprocessing must be observable. Your own causal strategy must restrict access by availability, not assume the harness has hidden the future.

## Output

```python
{"timestamp": row["timestamp"], "target": 1,
 "features": {"signal": 0.6}, "reason": "above trailing mean"}
```

Return exactly one record per input row, in the same order. `target` is a finite signed number of units: positive long, negative short, zero flat. Fractional quantities are supported. Booleans, numeric strings and nonfinite values are rejected. Integral floats normalize to integers and negative zero to zero. It represents a complete desired position: moving from 5 to 3 trades a delta of -2 in the projection. Optional `features` and `reason` are diagnostics. Only timestamp and exact quantity determine equivalence; no tolerance hides sizing changes.

During warmup, return zero target for each bar. Choose `--min-history` to match intended warmup; it limits inspected cutoffs, not data preparation. Missing output, NaN and multiple instruments are unsupported. The audit detects quantity changes even when both versions remain long or remain short.

## Less wrapping

`--engine targets` accepts `positions(rows, config, seed)` returning numeric positions. `--engine pandas` accepts `signals(frame, **config)` returning a Series or a DataFrame's `target` column, with the exact original UTC index. It supplies lowercase OHLCV and all original fields. A shuffled, shortened or relabeled index is rejected. Use `--engine-settings '{"target_column":"position"}'` for another column. Both adapters construct traces for you. Existing engine classes load with `--engine backtesting` or `--engine backtrader`.

Fixtures save `runner_spec` to reconstruct the adapter and settings. Old callback fixtures without it still work. See [integrations](integrations.md).

## Observed positions

Real engine adapters record `observed_position`, not the strategy's intention. Use `--trace-kind observed_position`; otherwise the report would overstate the meaning of its trace. Observed positions may change after a fill and can conceal an intention that was rejected or not filled. Cost and delay projections apply another transformation and are illustrative for these traces.

## Stable errors

Invalid input fails before callback execution. Exceptions or invalid traces during auditing produce an inconclusive reason. An unstable fixture replay is an error/inconclusive result rather than a successful invariance assertion. Audit code does not interpret textual reasons, prove source lineage or intercept external market-data access.
