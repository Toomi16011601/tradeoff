"""Validate the deliberately narrow, JSON-only callback contract."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from .privacy import reject_sensitive_data


def parse_timestamp(value, label="timestamp"):
    """Read an aware ISO-8601 timestamp; comparisons use actual instants."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a timezone-aware ISO-8601 string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a timezone-aware ISO-8601 string") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return result


def _json_value(value, label, ancestors=None, depth=0):
    if depth > 256:
        raise ValueError(f"{label} exceeds the supported JSON nesting depth")
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} must contain finite JSON numbers")
        return
    if not isinstance(value, (list, dict)):
        raise ValueError(f"{label} must contain only JSON values")
    ancestors = set() if ancestors is None else ancestors
    if id(value) in ancestors:
        raise ValueError(f"{label} contains a cycle and cannot be JSON")
    ancestors.add(id(value))
    try:
        if isinstance(value, list):
            for index, child in enumerate(value):
                _json_value(child, f"{label}[{index}]", ancestors, depth + 1)
        else:
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{label} must contain string JSON object keys")
                _json_value(child, f"{label}.{key}", ancestors, depth + 1)
    finally:
        ancestors.remove(id(value))


def canonical_hash(value):
    """SHA-256 of UTF-8 JSON with sorted keys and finite numbers."""
    _json_value(value, "hash input")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_config(config=None):
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    reject_sensitive_data(config, label='config')
    _json_value(config, "config")
    return deepcopy(config)


def validate_rows(rows):
    """Return copied bars with explicit availability; reject ambiguous tapes."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a nonempty list of JSON objects")
    reject_sensitive_data(rows, label='rows')
    _json_value(rows, "rows")
    validated = deepcopy(rows)
    previous = None
    symbol = None
    for index, row in enumerate(validated):
        label = f"rows[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{label} must be a JSON object")
        required = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
        for field in required:
            if field not in row:
                raise ValueError(f"{label}.{field} is required")
        timestamp = parse_timestamp(row["timestamp"], f"{label}.timestamp")
        if previous is not None and timestamp <= previous:
            raise ValueError(f"{label}.timestamp must be strictly increasing and unique")
        previous = timestamp
        row.setdefault("available_at", row["timestamp"])
        available = parse_timestamp(row["available_at"], f"{label}.available_at")
        if available < timestamp:
            raise ValueError(f"{label}.available_at cannot precede timestamp")
        row["timestamp"] = timestamp.astimezone(timezone.utc).isoformat()
        row["available_at"] = available.astimezone(timezone.utc).isoformat()
        if not isinstance(row["symbol"], str) or not row["symbol"].strip():
            raise ValueError(f"{label}.symbol must be a nonempty string")
        if symbol is not None and row["symbol"] != symbol:
            raise ValueError("rows must contain exactly one symbol")
        symbol = row["symbol"]
        for field in ("open", "high", "low", "close", "volume"):
            number = row[field]
            if type(number) not in (int, float):
                raise ValueError(f"{label}.{field} must be a finite number")
            try:
                finite = math.isfinite(number)
            except OverflowError:
                finite = False
            if not finite or number < 0 or (field != "volume" and number == 0):
                adjective = "nonnegative" if field == "volume" else "positive"
                raise ValueError(f"{label}.{field} must be {adjective} and finite")
        if row["high"] < max(row["open"], row["close"], row["low"]):
            raise ValueError(f"{label}.high must cover open, low and close")
        if row["low"] > min(row["open"], row["close"], row["high"]):
            raise ValueError(f"{label}.low must cover open, high and close")
        _json_value(row, label)
    return validated


def normalize_target(value, label="target"):
    """Validate native signed units and give equivalent numbers stable JSON forms."""
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite numeric quantity")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be a finite numeric quantity")
    if type(value) is float and value.is_integer():
        return int(value)
    return value


def validate_trace(trace, rows):
    if not isinstance(trace, list) or len(trace) != len(rows):
        raise ValueError("trace must contain exactly one record per input row")
    validated = []
    for index, (record, row) in enumerate(zip(trace, rows)):
        label = f"trace[{index}]"
        if not isinstance(record, dict):
            raise ValueError(f"{label} must be a JSON object")
        instant = parse_timestamp(record.get("timestamp"), f"{label}.timestamp")
        if instant != parse_timestamp(row["timestamp"]):
            raise ValueError(f"{label}.timestamp must match its input row")
        target = normalize_target(record.get("target"), f"{label}.target")
        reject_sensitive_data(record)
        _json_value(record, label)
        copied = deepcopy(record)
        copied["timestamp"] = instant.astimezone(timezone.utc).isoformat()
        copied["target"] = target
        validated.append(copied)
    return validated


def prefix_trace(trace, cutoff=None):
    """Decision equivalence deliberately ignores diagnostic features/reasons."""
    instant = parse_timestamp(cutoff, "cutoff") if cutoff is not None else None
    return [
        {"timestamp": record["timestamp"], "target": record["target"]}
        for record in trace
        if instant is None or parse_timestamp(record["timestamp"]) <= instant
    ]
