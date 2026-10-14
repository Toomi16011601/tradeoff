"""Deterministic, coherent interventions on bars unavailable at a cutoff."""

from copy import deepcopy
import math
import sys
from .validation import parse_timestamp

MUTATION_NAMES = ("scale_up", "scale_down")


def mutate_future(rows, cutoff, mutation_name, indices=None):
    """Return a full tape and changed records; timestamps/history never move."""
    if mutation_name not in MUTATION_NAMES:
        raise ValueError(f"unsupported mutation {mutation_name!r}")
    instant = parse_timestamp(cutoff, "cutoff")
    selected = set(indices) if indices is not None else None
    mutated = deepcopy(rows)
    changes = []
    requested_factor = 4.0 if mutation_name == "scale_up" else 0.25
    for index, (before, after) in enumerate(zip(rows, mutated)):
        if selected is not None and index not in selected:
            continue
        available = before.get("available_at", before["timestamp"])
        if parse_timestamp(available, "available_at") <= instant:
            continue
        largest = max(before[field] for field in ("open", "high", "low", "close", "volume"))
        factor = min(requested_factor, sys.float_info.max / largest) if requested_factor > 1 else requested_factor
        # The division bound can round upward by an ulp. Check actual products
        # before accepting the scale; at the finite maximum an up-edit may be
        # unrepresentable, in which case factor 1 preserves the input.
        if requested_factor > 1:
            while any(not math.isfinite(before[field] * factor)
                      for field in ("open", "high", "low", "close", "volume")):
                factor = math.nextafter(factor, 1.0)
        # Avoid overflowing huge finite bars or underflowing positive subnormals.
        price_fields = ("open", "high", "low", "close")
        scaled_prices = [before[field] * factor for field in price_fields]
        if any(value == 0 for value in scaled_prices):
            scaled_prices = [before[field] for field in price_fields]
        for field, value in zip(price_fields, scaled_prices):
            after[field] = value
        after["volume"] = before["volume"] * factor
        if after != before:
            changes.append({"index": index, "timestamp": before["timestamp"], "available_at": available, "before": deepcopy(before), "after": deepcopy(after)})
    return mutated, changes
