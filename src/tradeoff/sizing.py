"""Causal signed sizing helpers; these produce quantities, not broker orders.

Risk equity is a positive static input. A stop defines sizing distance only;
gaps, fills, commissions and dynamic broker equity are outside these helpers.
"""

from decimal import Decimal, ROUND_FLOOR
from math import nextafter
from numbers import Integral, Real

from .validation import normalize_target, parse_timestamp, validate_rows


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    native = int(value) if isinstance(value, Integral) else float(value)
    native = normalize_target(native, label)
    if positive and native <= 0:
        raise ValueError(f"{label} must be positive")
    return native


def _sequence(values, count, label):
    if isinstance(values, (str, bytes, dict)):
        raise ValueError(f"{label} must be a numeric sequence aligned to rows")
    try:
        result = list(values)
    except TypeError as exc:
        raise ValueError(f"{label} must be a sequence aligned to rows") from exc
    if len(result) != count:
        raise ValueError(f"{label} length must match input rows")
    return result


def _inputs(rows, directions, lot_size):
    tape = validate_rows(rows)
    signals = [_number(value, f"directions[{index}]") for index, value in
               enumerate(_sequence(directions, len(tape), "directions"))]
    for index, (row, direction) in enumerate(zip(tape, signals)):
        if direction not in (-1, 0, 1):
            raise ValueError(f"directions[{index}] must be -1, 0 or 1")
        if direction and parse_timestamp(row["available_at"]) > parse_timestamp(row["timestamp"]):
            raise ValueError(f"rows[{index}].close is not available at its decision timestamp")
    lot = None if lot_size is None else Decimal(str(_number(lot_size, "lot_size", positive=True)))
    return tape, signals, lot


def _units(quantity, direction, lot):
    if lot is not None:
        quantity = (quantity / lot).to_integral_value(rounding=ROUND_FLOOR) * lot
    # Decimal arithmetic protects declared lot boundaries such as 0.3 / 0.1.
    # A conversion to binary float must not round an exposure ceiling upward.
    units = float(quantity)
    units = normalize_target(units, "sized target")
    if Decimal(str(units)) > quantity:
        units = nextafter(float(units), 0)
    return normalize_target(direction * units, "sized target")


def size_by_notional(rows, directions, *, notional, lot_size=None):
    """Size -1/0/1 directions by fixed positive notional at available closes.

    Lot sizes use the decimal representation of the supplied number and round
    down toward zero. Each nonzero target has absolute notional at most the
    declared ceiling; the caller's inputs are left untouched.
    """
    ceiling = Decimal(str(_number(notional, "notional", positive=True)))
    tape, signals, lot = _inputs(rows, directions, lot_size)
    return [_units(ceiling / Decimal(str(row["close"])), direction, lot) if direction else 0
            for row, direction in zip(tape, signals)]


def size_by_risk(rows, directions, stops, *, equity, risk_fraction, max_notional, lot_size=None):
    """Size by static equity × risk_fraction / stop distance, capped by notional.

    Long stops must be below close and short stops above. Flat signals may use
    null stops. This computes units; it does not simulate a stop fill or promise
    that realized losses remain within the sizing budget.
    """
    equity = Decimal(str(_number(equity, "equity", positive=True)))
    fraction = _number(risk_fraction, "risk_fraction", positive=True)
    if fraction > 1:
        raise ValueError("risk_fraction must be at most one")
    risk_budget = equity * Decimal(str(fraction))
    ceiling = Decimal(str(_number(max_notional, "max_notional", positive=True)))
    tape, signals, lot = _inputs(rows, directions, lot_size)
    stops = _sequence(stops, len(tape), "stops")
    targets = []
    for index, (row, direction, stop) in enumerate(zip(tape, signals, stops)):
        if not direction:
            if stop is not None:
                _number(stop, f"stops[{index}]")
            targets.append(0)
            continue
        stop = Decimal(str(_number(stop, f"stops[{index}]", positive=True)))
        close = Decimal(str(row["close"]))
        distance = (close - stop) * direction
        if distance <= 0:
            side = "below" if direction > 0 else "above"
            raise ValueError(f"stops[{index}] must be {side} close for this direction")
        quantity = min(risk_budget / distance, ceiling / close)
        targets.append(_units(quantity, direction, lot))
    return targets
