"""Minimal causal callback. Replace this function with your engine's trace."""


def run(rows, config, seed):
    window = int(config.get("window", 5))
    if window < 1:
        raise ValueError("window must be positive")
    trace = []
    for i, row in enumerate(rows):
        # The decision uses only records available at this bar's close.
        known = [r["close"] for r in rows[:i + 1]
                 if r["available_at"] <= row["timestamp"]][-window:]
        mean = sum(known) / len(known) if known else None
        target = int(len(known) == window and row["close"] > mean
                     and row["available_at"] <= row["timestamp"])
        trace.append({"timestamp": row["timestamp"], "target": target,
                      "features": {"trailing_mean": mean}})
    return trace
