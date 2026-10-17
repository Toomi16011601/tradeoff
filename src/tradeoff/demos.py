"""Small synthetic controls: no downloads, credentials or private market data."""

from datetime import datetime, timedelta, timezone
import math


def synthetic_rows(count=48):
    """Generate a deterministic, coherent one-symbol bar tape."""
    if type(count) is not int or count < 4:
        raise ValueError("count must be an integer >= 4")
    start = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    rows = []
    previous = 100.0
    for index in range(count):
        close = round(100 + 0.18 * index + 6 * math.sin(index / 4) + 2 * math.cos(index / 9), 4)
        timestamp = (start + timedelta(hours=index)).isoformat()
        rows.append({"timestamp": timestamp, "available_at": timestamp, "symbol": "SYNTH", "open": previous,
                     "high": round(max(previous, close) + 1.2, 4), "low": round(min(previous, close) - 1.1, 4),
                     "close": close, "volume": 1000 + 37 * (index % 11)})
        previous = close
    return rows


def leaky_run(rows, config, seed):
    """Planted defect: normalize every decision by a future full-tape mean."""
    full_sample_mean = sum(row["close"] for row in rows) / len(rows)
    return [{"timestamp": row["timestamp"], "target": int(row["close"] > full_sample_mean),
             "features": {"full_sample_mean": full_sample_mean}, "reason": "Close above full-tape mean (planted future dependency)"}
            for row in rows]


def causal_run(rows, config, seed):
    """Control: bar-close decision uses the trailing history including this bar."""
    lookback = config.get("lookback", 5)
    if type(lookback) is not int or lookback < 1:
        raise ValueError("lookback must be an integer >= 1")
    trace = []
    for index, row in enumerate(rows):
        history = rows[max(0, index - lookback + 1):index + 1]
        mean = sum(record["close"] for record in history) / len(history)
        trace.append({"timestamp": row["timestamp"], "target": int(row["close"] > mean),
                      "features": {"trailing_mean": mean}, "reason": "Close above causal trailing mean"})
    return trace


def make_unstable_run():
    """Construct the deliberately stateful control independently for each demo."""
    calls = 0
    def run(rows, config, seed):
        nonlocal calls
        calls += 1
        return [{"timestamp": row["timestamp"], "target": calls % 2, "reason": "Planted persistent callback state"} for row in rows]
    return run


unstable_run = make_unstable_run()
