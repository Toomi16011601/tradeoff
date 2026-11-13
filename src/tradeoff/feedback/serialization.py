"""Canonical historical output, with bounded records and streaming byte sinks.

Ingestion still uses contracts.canonical_json and its 1 MiB envelope. Only
explicit historical arrays may grow across envelopes; each record, ordinary
container, scalar, numeric value and the complete nesting depth stay bounded.
"""
from decimal import Decimal
import hashlib
import json
import math

from ..privacy import reject_sensitive_data
from .contracts import FeedbackError, MAX_BYTES, invalid, normalize_decimal

_EVALUATION_ARRAYS = ("decisions", "episodes", "findings", "groups")
_HISTORY_PATHS = {("events",), ("receipts",)}
for _prefix in ((), ("evaluation",), ("feedback", "evaluation")):
    _HISTORY_PATHS.update(_prefix + (name,) for name in _EVALUATION_ARRAYS)
    _HISTORY_PATHS.update(_prefix + ("groups", "*", name)
                          for name in ("exposure", "horizon_price_changes"))
for _prefix in ((), ("comparison",), ("feedback", "comparison")):
    _HISTORY_PATHS.update(_prefix + (name,) for name in ("pairs", "exclusions", "timeline"))


def _decimal(value):
    if not isinstance(value, Decimal):
        invalid()
    return normalize_decimal(value)


_ENCODER = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                            allow_nan=False, ensure_ascii=True, default=_decimal)


def _validate(value, path=(), ancestors=frozenset()):
    if len(path) > 32:
        invalid()
    if isinstance(value, str):
        if len(value) > 4096:
            invalid()
        return len(_ENCODER.encode(value))
    if value is None or isinstance(value, (bool, int, Decimal)):
        return len(_ENCODER.encode(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            invalid()
        return len(_ENCODER.encode(value))
    if not isinstance(value, (dict, list)) or id(value) in ancestors:
        invalid()
    history = isinstance(value, list) and path in _HISTORY_PATHS
    if not history and len(value) > 10000:
        invalid()
    parents = ancestors | {id(value)}
    size = 2
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 4096:
                invalid()
            size += len(_ENCODER.encode(key)) + 1 + _validate(child, path + (key,), parents)
        size += max(0, len(value) - 1)
    else:
        for child in value:
            child_size = _validate(child, path + ("*",), parents)
            if not history:
                size += child_size
        if not history:
            size += max(0, len(value) - 1)
    if size > MAX_BYTES:
        invalid()
    # Historical arrays contribute their delimiters to the containing envelope;
    # their individually checked records do not impose an aggregate byte limit.
    return size


def validate_output(value):
    """Validate a complete response before emitting any of its JSON bytes."""
    try:
        _validate(value)
        reject_sensitive_data(value)
    except FeedbackError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise FeedbackError("INVALID_EVIDENCE", "Feedback output contains invalid or recognized sensitive data") from None


def output_chunks(value):
    """Yield bounded chunks with the same bytes as the original canonical JSON."""
    validate_output(value)
    parts, size = [], 0
    for part in _ENCODER.iterencode(value):
        parts.append(part)
        size += len(part)
        if size >= 65536:
            yield "".join(parts)
            parts, size = [], 0
    if parts:
        yield "".join(parts)


def output_json(value):
    """Materialize JSON only for transports that require a complete string."""
    return "".join(output_chunks(value))


def output_hash(value):
    digest = hashlib.sha256()
    for chunk in output_chunks(value):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()
