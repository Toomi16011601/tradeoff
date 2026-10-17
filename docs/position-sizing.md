# Position sizing and shorts

A target is the whole desired position, in units. `10 → 6 → -4 → 0` means reduce a long by 4, sell 10 to reverse to a 4-unit short, then buy 4 to flatten. A repeated target holds the position. Finite fractional quantities are valid. Tradeoff compares exact quantities, so sizing leaks remain visible even without a change in direction.

## Fixed notional

```python
from tradeoff.sizing import size_by_notional

def positions(rows, config, seed):
    directions = [1 if row['close'] > row['open'] else -1 for row in rows]
    return size_by_notional(rows, directions, notional=500, lot_size=1)
```

Use this function with `--engine targets`. Directions must be -1/0/1. The helper divides the notional ceiling by each available bar's close and rounds down toward zero to the declared lot size. A 100-unit price and 500-unit ceiling produces 5 units. The ceiling applies at the decision price; a later fill can gap. Delayed current bars are rejected for nonzero directions.

Lot calculations use the decimal representation of the supplied parameters. Returned quantities are native numbers; subsequent binary-float multiplication can differ by one representable step (for example `0.1 * 3`). The projection allows a small relative tolerance at exact exposure-cap boundaries and rejects unrepresentable accounting scales.

## Stop-distance risk sizing

```python
from tradeoff.sizing import size_by_risk

targets = size_by_risk(
    rows, directions, stops,
    equity=10000, risk_fraction=0.01, max_notional=5000, lot_size=1,
)
```

For a long at 100 with stop 95, a 100-unit risk budget initially permits 20 units; a 5000-unit notional cap permits 50, so the result is 20. For a short, the stop must be above the close. Flat directions may use a null stop. `equity` is a declared static sizing input; it is not the live engine's changing equity. The helper does not submit stops or simulate their execution. Gaps and costs can exceed the sizing budget.

## Independent ledger

`project(rows, trace, max_leverage=1, short_borrow_bps_annual=100, ...)` projects next-open rebalances. It accounts for partial closes, average opening basis and reversals. Opening fees enter cost basis; closing fees and accrued short borrowing reduce realized P&L. Realized plus open P&L must equal terminal equity minus initial cash.

Short proceeds remain cash, but new exposure is capped by post-trade equity. At the default 1× cap, an account with 1000 equity cannot establish a 2000-notional short merely because selling it would raise cash. Risk-reducing exits remain allowed after insolvency and can settle debt. Events are recorded without maintenance-margin liquidation. Borrow accrues on previous short units and previous close over actual elapsed intervals, with a 365-day convention. Borrow defaults to zero; financing interest, dividends, recalls and broker-specific margin rules are absent.

The ledger is conditional and separate from each adapter's engine. Use the engine's own sizing policy for actual broker behavior and Tradeoff to test whether unavailable data changes its observed quantities.
