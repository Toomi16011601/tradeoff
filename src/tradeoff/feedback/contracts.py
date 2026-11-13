"""Bounded, versioned feedback contracts using exact decimal text."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Any

from ..privacy import reject_sensitive_data

JsonObject = dict[str, Any]
MAX_BYTES = 1024 * 1024
COMPONENTS = ("commission", "transaction", "venue", "regulatory", "borrow", "financing")
ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"


class FeedbackError(ValueError):
    """Only developer-authored, non-sensitive error messages belong here."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def invalid():
    raise FeedbackError("INVALID_EVIDENCE", "Evidence does not match the supported feedback contract")


def decimal_text(value):
    """Format computed Decimal values without the ingestion precision bounds."""
    if not value.is_finite():
        invalid()
    result = format(value, "f")
    return "0" if not value else result.rstrip("0").rstrip(".") if "." in result else result


def normalize_decimal(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        invalid()
    text = str(value)
    if len(text) > 128 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        invalid()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        invalid()
    if not amount.is_finite():
        invalid()
    if len(amount.as_tuple().digits) > 40 or amount.as_tuple().exponent < -18 or amount.adjusted() > 39:
        invalid()
    return decimal_text(amount)


def utc_time(value) -> str:
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None or date.utcoffset() is None:
            invalid()
        return date.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError):
        invalid()


def _plain(value, depth=0, ancestors=frozenset()):
    if depth > 32:
        invalid()
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        if len(value) > 4096:
            invalid()
        return value
    if isinstance(value, Decimal):
        return normalize_decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            invalid()
        return value
    if not isinstance(value, (dict, list)) or id(value) in ancestors or len(value) > 10000:
        invalid()
    parents = ancestors | {id(value)}
    if isinstance(value, list):
        return [_plain(v, depth + 1, parents) for v in value]
    if any(not isinstance(k, str) for k in value):
        invalid()
    return {k: _plain(v, depth + 1, parents) for k, v in value.items()}


def canonical_json(value) -> str:
    try:
        result = json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)
        if len(result.encode()) > MAX_BYTES:
            invalid()
        return result
    except (ValueError, TypeError, RecursionError, OverflowError):
        invalid()


def parse_json(raw: str | bytes):
    if not isinstance(raw, (str, bytes)) or len(raw) > MAX_BYTES:
        invalid()

    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                invalid()
            out[k] = v
        return out

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: invalid())
        canonical_json(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        invalid()


def _object(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, "additionalProperties": False}


_ID = {"type": "string", "pattern": ID_PATTERN, "maxLength": 128}
_TEXT = {"type": "string", "maxLength": 4096}
_DECIMAL = {"type": ["string", "integer"], "x-feedback": "decimal"}
_TIME = {"type": "string", "format": "date-time", "x-feedback": "time"}
_CURRENCY = {"type": "string", "pattern": r"^[A-Z]{3}$"}


def _enum(*values):
    return {"type": "string", "enum": list(values)}


def _fields(required, optional="", **special):
    props = {}
    for key in (required + " " + optional).split():
        props[key] = deepcopy(special.get(key, _ID))
    return _object(props, required.split())


_REFERENCE = _fields("price price_kind observed_at available_at source feed max_age_seconds",
    price=_DECIMAL, price_kind=_enum("mid", "bid", "ask", "close", "trade"), observed_at=_TIME,
    available_at=_TIME, max_age_seconds={"type": "integer", "minimum": 0, "maximum": 31536000})
_SOURCE_TIME = _fields("source feed observed_at available_at", observed_at=_TIME, available_at=_TIME)
_PREDICTION = _fields("label horizon_end", "confidence", horizon_end=_TIME, confidence=_DECIMAL)
_COMPONENT = _object({"applicable": {"type": ["boolean", "null"]}, "evidence_ref": _ID})
_SIMULATION_ACCOUNT = _fields(
    "baseline_source_alias candidate_source_alias initial_cash currency symbol asset_class "
    "valuation_source valuation_feed price_kind initial_at terminal_at expected_decisions "
    "cost_model_id execution_policy_id timestamp_policy acknowledge_assumptions",
    initial_cash=_DECIMAL, currency=_enum("USD"), asset_class=_enum("us_equity"),
    price_kind=_REFERENCE["properties"]["price_kind"], initial_at=_TIME, terminal_at=_TIME,
    expected_decisions={"type":"integer", "minimum":1, "maximum":1000000},
    timestamp_policy=_enum("declared_historical_ordering"), acknowledge_assumptions={"type":"boolean"})
SCHEMAS = {
    "decision": _fields("decision_id agent_id agent_version opportunity_id symbol asset_class currency action quantity_delta decision_at horizon_end input_hash reference",
        "reason source_times episode_id prediction input_snapshot", currency=_CURRENCY,
        action=_enum("buy", "sell", "hold", "skip"), quantity_delta=_DECIMAL, decision_at=_TIME,
        horizon_end=_TIME, input_hash={"type": "string", "pattern": r"^[a-f0-9]{64}$"}, reference=_REFERENCE,
        reason=_TEXT, source_times={"type": "array", "items": _SOURCE_TIME}, prediction=_PREDICTION,
        input_snapshot={"type": "object"}),
    "order_binding": _fields("decision_id source_alias order_id", "client_order_id replaces_order_id"),
    "inventory": _fields("source_alias symbol asset_class currency quantity observed_at capture_started_at capture_completed_at open_order_ids origin",
        currency=_CURRENCY, quantity=_DECIMAL, observed_at=_TIME, capture_started_at=_TIME, capture_completed_at=_TIME,
        open_order_ids={"type": "array", "items": _ID}, origin=_enum("synthetic_fixture", "broker", "imported")),
    "order": _fields("source_alias order_id symbol asset_class currency side quantity filled_quantity status submitted_at",
        "client_order_id replaces_order_id replaced_by_order_id parent_order_id source_updated_at", currency=_CURRENCY,
        side=_enum("buy", "sell"), quantity=_DECIMAL, filled_quantity=_DECIMAL, submitted_at=_TIME, source_updated_at=_TIME),
    "fill": _fields("source_alias fill_id order_id symbol asset_class currency quantity_delta price occurred_at",
        "source_created_at", currency=_CURRENCY, quantity_delta=_DECIMAL, price=_DECIMAL, occurred_at=_TIME, source_created_at=_TIME),
    "cost": _fields("cost_id source_alias component amount currency evidence_kind applies_at",
        "fill_id order_id episode_id corrects_cost_id", component=_enum(*COMPONENTS), amount=_DECIMAL,
        currency=_CURRENCY, evidence_kind=_enum("observed", "modeled"), applies_at=_TIME),
    "cost_scope": _fields("episode_id components evidence_kind", "supersedes_scope_hash",
        supersedes_scope_hash={"type": "string", "pattern": r"^[a-f0-9]{64}$"}, evidence_kind=_enum("observed", "modeled"),
        components=_object({name: _COMPONENT for name in COMPONENTS})),
    "mark": _fields("mark_id symbol currency price price_kind source feed observed_at available_at", currency=_CURRENCY,
        price=_DECIMAL, price_kind=_REFERENCE["properties"]["price_kind"], observed_at=_TIME, available_at=_TIME),
    "comparison_plan": _fields("plan_id baseline_version candidate_version window_start window_end metric horizon_policy reference_policy cost_policy match_policy minimum_pairs",
        "supersedes_plan_id simulation", window_start=_TIME, window_end=_TIME,
        metric=_enum("episode_net_return_bps", "simulated_account_return_bps"),
        horizon_policy=_enum("decision_at_declared_end"), reference_policy=_enum("exact_reference"),
        cost_policy=_enum("complete_observed", "complete_modeled"),
        match_policy=_enum("exact_opportunity", "same_market_calendar"), simulation=_SIMULATION_ACCOUNT,
        minimum_pairs={"type": "integer", "minimum": 1, "maximum": 10000}),
    "source_note": _fields("source_alias note_id code interval_start interval_end", "symbol metadata",
        interval_start=_TIME, interval_end=_TIME, metadata=_object({"activity_type": _ID, "economic_at": _TIME, "source_created_at": _TIME}, [])),
}


def schema_for(kind) -> JsonObject:
    if kind not in SCHEMAS:
        invalid()
    return deepcopy(SCHEMAS[kind])


def validate_schema(value, schema):
    """Validate our deliberately small JSON-schema vocabulary and normalize."""
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    type_ok = {"null": value is None, "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool), "string": isinstance(value, str),
        "object": isinstance(value, dict), "array": isinstance(value, list)}
    if schema.get("x-feedback") == "decimal":
        return normalize_decimal(value)
    if types and not any(type_ok.get(t, False) for t in types):
        invalid()
    if "enum" in schema and value not in schema["enum"]:
        invalid()
    if schema.get("x-feedback") == "time":
        return utc_time(value)
    if isinstance(value, dict):
        props = schema.get("properties")
        if props is None:
            return deepcopy(value)
        if any(k not in value for k in schema.get("required", [])):
            invalid()
        if schema.get("additionalProperties") is False and any(k not in props for k in value):
            invalid()
        return {k: validate_schema(v, props[k]) for k, v in value.items()}
    if isinstance(value, list):
        return [validate_schema(v, schema["items"]) for v in value]
    if isinstance(value, str):
        if len(value) > schema.get("maxLength", 4096) or ("pattern" in schema and not re.fullmatch(schema["pattern"], value)):
            invalid()
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            invalid()
    return value


def validate_payload(kind, payload) -> JsonObject:
    canonical_json(payload)
    try:
        reject_sensitive_data(payload)
    except ValueError:
        raise FeedbackError("SENSITIVE_DATA", "Remove private fields and recognized sensitive data") from None
    item = validate_schema(payload, schema_for(kind))
    if kind == "decision":
        qty = Decimal(item["quantity_delta"])
        action = item["action"]
        if ((action == "buy" and qty <= 0) or (action == "sell" and qty >= 0)
                or (action in {"hold", "skip"} and qty != 0)):
            invalid()
        if item["decision_at"] >= item["horizon_end"]:
            invalid()
        if "prediction" in item and "confidence" in item["prediction"]:
            if not 0 <= Decimal(item["prediction"]["confidence"]) <= 1:
                invalid()
        if "input_snapshot" in item and hashlib.sha256(canonical_json(item["input_snapshot"]).encode()).hexdigest() != item["input_hash"]:
            invalid()
    if kind in {"fill", "mark"} and Decimal(item["price"]) <= 0:
        invalid()
    if kind == "fill" and Decimal(item["quantity_delta"]) == 0:
        invalid()
    if kind == "order" and not 0 <= Decimal(item["filled_quantity"]) <= Decimal(item["quantity"]):
        invalid()
    if kind == "cost" and sum(k in item for k in ("fill_id", "order_id", "episode_id")) != 1:
        invalid()
    if kind == "comparison_plan":
        if item["window_start"] >= item["window_end"]:
            invalid()
        if item["metric"] == "simulated_account_return_bps":
            sim = item.get("simulation")
            if (sim is None or item["cost_policy"] != "complete_modeled"
                    or item["match_policy"] != "same_market_calendar"):
                invalid()
            if (Decimal(sim["initial_cash"]) <= 0 or not sim["acknowledge_assumptions"]
                    or sim["baseline_source_alias"] == sim["candidate_source_alias"]
                    or not item["window_start"] <= sim["initial_at"] < sim["terminal_at"] <= item["window_end"]
                    or item["minimum_pairs"] > sim["expected_decisions"]):
                invalid()
        elif ("simulation" in item or item["cost_policy"] != "complete_observed"
                or item["match_policy"] != "exact_opportunity"):
            invalid()
    if kind == "inventory" and not item["capture_started_at"] <= item["observed_at"] <= item["capture_completed_at"]:
        invalid()
    return item
