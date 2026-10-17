"""Conditional signed-quantity accounting on the original midpoint tape.

This model is separate from engine accounting. Decisions become eligible after
an explicit positive bar lag, then rebalance at the next eligible open.
"""

from math import isclose, isfinite, ulp

from .validation import parse_timestamp, validate_rows, validate_trace


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        valid = isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (value <= 0 if positive else value < 0):
        bound = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be finite and {bound}")
    return float(value)


def _finite(*values, what="prices and settings"):
    try:
        valid = all(isfinite(value) for value in values)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"accounting overflow: {what} must yield finite balances")


def _above_cap(exposure, equity, max_leverage):
    if equity <= 0:
        return exposure > 0
    capacity = equity * max_leverage
    return exposure > capacity and not isclose(exposure, capacity, rel_tol=1e-12)


def project(rows, trace, *, initial_cash=1000, fee_fixed=1, fee_bps=0,
            spread_bps=2, slippage_bps=2, fill_lag_bars=1,
            max_leverage=1, short_borrow_bps_annual=0):
    """Project signed target units with a gross-exposure cap and no final exit.

    Entry fees belong to average per-unit basis; closing fees and accrued short
    borrow belong to realized P&L. Risk-reducing closes can settle negative cash.
    The cap controls new exposure, without inventing maintenance liquidation.
    Rejected targets retry until a later eligible signal replaces them.
    """
    rows = validate_rows(rows)
    trace = validate_trace(trace, rows)
    initial_cash = _number(initial_cash, "initial_cash", positive=True)
    fee_fixed = _number(fee_fixed, "fee_fixed")
    fee_bps = _number(fee_bps, "fee_bps")
    spread_bps = _number(spread_bps, "spread_bps")
    slippage_bps = _number(slippage_bps, "slippage_bps")
    max_leverage = _number(max_leverage, "max_leverage")
    if max_leverage < 1:
        raise ValueError("max_leverage must be finite and at least 1")
    short_borrow_bps_annual = _number(short_borrow_bps_annual, "short_borrow_bps_annual")
    if type(fill_lag_bars) is not int or fill_lag_bars < 1:
        raise ValueError("fill_lag_bars must be a positive integer")
    adverse_fraction = spread_bps / 20000 + slippage_bps / 10000
    if adverse_fraction >= 1:
        raise ValueError("half spread plus slippage must be below 10000 bps")

    cash, quantity, basis, realized, total_fees = initial_cash, 0, 0.0, 0.0, 0.0
    total_borrow_cost = 0.0
    peak, max_drawdown = initial_cash, 0.0
    fills, rejected, curve, borrow_charges, risk_events = [], [], [], [], []
    for index, row in enumerate(rows):
        if index > 0 and quantity < 0 and short_borrow_bps_annual > 0:
            previous = rows[index - 1]
            seconds = (parse_timestamp(row["timestamp"]) -
                       parse_timestamp(previous["timestamp"])).total_seconds()
            borrow_notional = abs(quantity) * previous["close"]
            charge = (borrow_notional * (short_borrow_bps_annual / 10000)
                      * (seconds / (365 * 86400)))
            cash -= charge
            realized -= charge
            total_borrow_cost += charge
            _finite(borrow_notional, charge, cash, realized, total_borrow_cost)
            borrow_charges.append({"timestamp": row["timestamp"],
                                   "previous_timestamp": previous["timestamp"],
                                   "quantity": abs(quantity),
                                   "reference_price": previous["close"],
                                   "basis_notional": borrow_notional,
                                   "annual_bps": short_borrow_bps_annual,
                                   "elapsed_seconds": seconds, "amount": charge})
        signal_index = index - fill_lag_bars
        if signal_index >= 0:
            signal = trace[signal_index]
            target = signal["target"]
            if target != quantity:
                delta = target - quantity
                _finite(delta, what="rebalance quantity")
                traded_units = abs(delta)
                side = "buy" if delta > 0 else "sell"
                price = row["open"] * (1 + adverse_fraction if side == "buy"
                                       else 1 - adverse_fraction)
                if price == 0:
                    raise ValueError("accounting precision is insufficient to represent a positive fill price")
                notional = traded_units * price
                if notional == 0:
                    raise ValueError("accounting precision is insufficient to represent a positive trade notional")
                _finite(price, notional)
                fee = fee_fixed + notional * (fee_bps / 10000)
                next_cash = cash - delta * price - fee
                reference_value = target * row["open"]
                _finite(fee, next_cash, reference_value)
                reference_equity = next_cash + reference_value
                reference_exposure = abs(reference_value)
                _finite(reference_equity, reference_exposure)
                order = {"timestamp": row["timestamp"],
                         "signal_timestamp": signal["timestamp"], "side": side,
                         "quantity": traded_units, "signed_quantity": delta,
                         "target_quantity": target, "reference_price": row["open"],
                         "fill_price": price, "notional": notional, "fee": fee}
                same_direction = ((quantity > 0 and target > 0) or
                                  (quantity < 0 and target < 0))
                reducing = target == 0 or (same_direction and abs(target) < abs(quantity))
                # A few floating-point ulps at an exact boundary are harmless;
                # do not let a fixed monetary tolerance fund tiny accounts.
                cash_tolerance = 4 * ulp(max(abs(cash), notional, fee))
                reason = None
                if not reducing:
                    if reference_equity <= 0:
                        reason = "new exposure requires positive post-trade equity"
                    elif _above_cap(reference_exposure, reference_equity, max_leverage):
                        reason = "gross exposure exceeds leverage cap"
                    elif max_leverage == 1 and target > 0 and next_cash < -cash_tolerance:
                        reason = "insufficient cash"
                if reason:
                    rejected.append({**order, "reason": reason, "available_cash": cash,
                                     "post_trade_equity": reference_equity,
                                     "gross_exposure": reference_exposure,
                                     "max_leverage": max_leverage})
                else:
                    cash = next_cash
                    old_units = abs(quantity)
                    old_direction = 1 if quantity > 0 else -1
                    closes = quantity != 0 and ((quantity > 0) != (delta > 0))
                    closing_units = min(old_units, traded_units) if closes else 0
                    closing_fee = fee * (closing_units / traded_units)
                    if closing_units:
                        realized += closing_units * old_direction * (price - basis) - closing_fee
                    if target == 0:
                        basis = 0.0
                    elif not same_direction:
                        opening_units = abs(target)
                        opening_fee = fee - closing_fee
                        basis = price + (opening_fee / opening_units) * (1 if target > 0 else -1)
                    elif abs(target) > old_units:
                        opening_units = traded_units
                        entry_basis = price + (fee / opening_units) * (1 if target > 0 else -1)
                        basis = (basis * (old_units / abs(target))
                                 + entry_basis * (opening_units / abs(target)))
                    quantity = target
                    total_fees += fee
                    fills.append({**order, "cash_after": cash,
                                  "quantity_after": quantity})
        position_value = quantity * row["close"]
        _finite(position_value)
        equity = cash + position_value
        exposure = abs(position_value)
        leverage = exposure / equity if equity > 0 else None
        _finite(equity, exposure, total_fees, realized, basis)
        if leverage is not None:
            _finite(leverage)
        nonpositive = equity <= 0
        cap_breached = _above_cap(exposure, equity, max_leverage)
        if nonpositive or cap_breached:
            risk_events.append({"timestamp": row["timestamp"], "quantity": quantity,
                                "equity": equity, "gross_exposure": exposure,
                                "max_leverage": max_leverage,
                                "nonpositive_equity": nonpositive,
                                "leverage_cap_breached": cap_breached})
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
        _finite(max_drawdown)
        curve.append({"timestamp": row["timestamp"], "equity": equity,
                      "quantity": quantity, "gross_exposure": exposure, "leverage": leverage})

    final_equity = curve[-1]["equity"]
    open_pnl = quantity * (rows[-1]["close"] - basis)
    net_pnl = final_equity - initial_cash
    if not isclose(realized + open_pnl, net_pnl, rel_tol=1e-10, abs_tol=1e-9):
        raise ValueError("accounting precision is insufficient to reconcile fills with cash; use a smaller capital/price scale")
    return_pct = net_pnl / initial_cash * 100
    _finite(open_pnl, net_pnl, return_pct)
    return {"initial_cash": initial_cash, "final_cash": cash,
            "final_quantity": quantity, "final_equity": final_equity,
            "equity_curve": curve, "fills": fills, "rejected_orders": rejected,
            "total_fees": total_fees, "realized_pnl": realized, "open_pnl": open_pnl,
            "net_pnl": net_pnl, "return_pct": return_pct,
            "max_drawdown_pct": max_drawdown, "total_borrow_cost": total_borrow_cost,
            "borrow_charges": borrow_charges, "risk_events": risk_events}


def compare_economics(rows, original_trace, intervention_trace=None, **settings):
    """Compare decisions on the same original tape, with disclosed sensitivities."""
    declared = {"initial_cash": 1000, "fee_fixed": 1, "fee_bps": 0,
                "spread_bps": 2, "slippage_bps": 2, "fill_lag_bars": 1,
                "max_leverage": 1, "short_borrow_bps_annual": 0}
    unknown = set(settings) - set(declared)
    if unknown:
        raise ValueError(f"unknown economics setting: {', '.join(sorted(unknown))}")
    declared.update(settings)
    rows = validate_rows(rows)

    def pair(model_settings):
        original = project(rows, original_trace, **model_settings)
        intervention = (project(rows, intervention_trace, **model_settings)
                        if intervention_trace is not None else None)
        delta = (intervention["net_pnl"] - original["net_pnl"]
                 if intervention is not None else None)
        if delta is not None:
            _finite(delta)
        return {"original": original, "intervention": intervention, "delta": delta}

    result = pair(declared)
    cost_names = ("fee_fixed", "fee_bps", "spread_bps", "slippage_bps", "short_borrow_bps_annual")
    sensitivity = []
    for name, modifications in (
        ("cost_free", {key: 0 for key in cost_names}),
        ("doubled_costs", {key: declared[key] * 2 for key in cost_names}),
        ("extra_bar_delay", {"fill_lag_bars": declared["fill_lag_bars"] + 1}),
    ):
        model_settings = {**declared, **modifications}
        try:
            stress = pair(model_settings)
        except ValueError as exc:
            # A stress setting can overflow even when the declared model is
            # valid. Keep that model useful and disclose unavailable stress
            # outputs; never serialize NaN/Infinity as attempted settings.
            recorded_settings = model_settings
            try:
                _finite(*model_settings.values())
            except ValueError:
                recorded_settings = {**declared, "cost_multiplier": 2}
            sensitivity.append({"name": name, "settings": recorded_settings,
                                "original": None, "intervention": None, "delta": None,
                                "status": "UNAVAILABLE", "reason": str(exc)})
        else:
            sensitivity.append({"name": name, "settings": model_settings, **stress})
    benchmark_trace = [{"timestamp": row["timestamp"], "target": 1} for row in rows]
    benchmark = project(rows, benchmark_trace, **declared)
    assumptions = {**declared, "currency": "model units",
                   "price_reference": "Original OHLC bars are reference midpoint prices.",
                   "fill_timing": "Bar-close signals rebalance at open of t + fill_lag_bars.",
                   "costs": "Half the full spread plus per-side slippage; fixed and notional fees once per delta rebalance, including reversal.",
                   "basis": "Average per-unit entry basis includes opening fees; partial-close fees and borrow costs enter realized P&L.",
                   "borrow": "Short borrow accrues on previous short units and previous close over actual timestamp intervals on a 365-day year.",
                   "terminal": "Signed open holdings marked at final close; no terminal exit or future borrow charge.",
                   "capital": "Signed fractional target units; new exposure capped by gross exposure/post-trade reference-open equity. Short proceeds do not increase capacity. Rejected targets retry.",
                   "margin": "Risk-reducing closes may settle cash debt; close-time insolvency and cap breaches are recorded without forced liquidation. No maintenance margin, financing interest, borrow recalls, dividends or security-specific margin rules.",
                   "benchmark": "One long unit from the first signal's eligible open, at the same costs, lag and cap; a reference, not exposure-matched."}
    explanation = "Conditional model outputs on the original price tape. The paired delta is intervention minus original net P&L; it is not causal profit attribution or recalculated engine performance."
    unavailable = [f"{item['name']}: {item['reason']}" for item in sensitivity
                   if item.get("status") == "UNAVAILABLE"]
    if unavailable:
        explanation += " Unavailable sensitivity: " + "; ".join(unavailable) + "."
    return {"assumptions": assumptions, **result, "sensitivity": sensitivity,
            "benchmark": benchmark, "explanation": explanation}
