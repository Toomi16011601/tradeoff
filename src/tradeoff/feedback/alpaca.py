"""Bounded GET-only Alpaca paper evidence. No order mutation or live host."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

from .contracts import FeedbackError, ID_PATTERN, canonical_json, parse_json, utc_time, validate_payload

HOST = "https://paper-api.alpaca.markets"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class SyncBatch:
    records: list
    checkpoint: dict
    coverage: dict
    source_fingerprint: str


def _http(request, *, timeout, max_bytes):
    opener = urllib.request.build_opener(RejectRedirects(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise FeedbackError("BROKER_RESPONSE_TOO_LARGE", "Paper evidence response exceeded the supported bound")
    return parse_json(body)


def _record(alias, kind, payload, *, identity=None):
    payload = validate_payload(kind, {**payload, **({"source_alias": alias} if "source_alias" in payload else {})})
    stable = identity or canonical_json(payload)
    source_id = alias + ":" + kind + ":" + hashlib.sha256(stable.encode()).hexdigest()
    return {"event_id": "broker-" + hashlib.sha256(source_id.encode()).hexdigest(), "kind": kind,
            "payload": payload, "origin": "broker", "environment": "paper", "source_event_id": source_id}


class PaperReader:
    def __init__(self, *, key_id, secret_key, fingerprint, transport=None, overlap_seconds=172800):
        if not all(isinstance(x, str) and 0 < len(x) <= 4096 for x in (key_id, secret_key)):
            raise FeedbackError("BROKER_NOT_CONFIGURED", "Local paper credentials are required")
        if isinstance(overlap_seconds, bool) or not isinstance(overlap_seconds, int) or not 0 <= overlap_seconds <= 604800:
            raise FeedbackError("INVALID_SYNC_POLICY", "Paper overlap must be between zero and seven days")
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
        self._fingerprint, self._transport, self.overlap_seconds = fingerprint, transport or _http, overlap_seconds

    def _get(self, path, query, budget):
        remaining = budget["deadline"] - time.monotonic()
        if remaining <= 0 or budget["requests"] >= 100:
            raise FeedbackError("SYNC_BUDGET_EXHAUSTED", "Paper sync budget was exhausted; coverage is partial")
        if not re.fullmatch(r"/v2/(?:account|positions|orders|account/activities|orders/[A-Za-z0-9._:-]{1,128})", path):
            raise FeedbackError("UNSUPPORTED_ENDPOINT", "Unsupported paper evidence endpoint")
        url = HOST + path + ("?" + urllib.parse.urlencode(query) if query else "")
        request = urllib.request.Request(url, headers=self._headers, method="GET")
        budget["requests"] += 1
        try:
            result = self._transport(request, timeout=min(10, remaining), max_bytes=MAX_RESPONSE_BYTES)
            canonical_json(result)
            return result
        except FeedbackError:
            raise
        except Exception:
            raise FeedbackError("BROKER_READ_FAILED", "Paper evidence request failed; raw broker diagnostics are omitted") from None

    @staticmethod
    def _order(alias, p):
        item = {"source_alias": alias, "order_id": p["id"], "symbol": p["symbol"],
            "asset_class": p.get("asset_class", "us_equity"), "currency": "USD", "side": p["side"],
            "quantity": p["qty"], "filled_quantity": p["filled_qty"], "status": p["status"], "submitted_at": p["submitted_at"]}
        for incoming, key in (("client_order_id", "client_order_id"), ("replaces", "replaces_order_id"),
            ("replaced_by", "replaced_by_order_id"), ("parent_order_id", "parent_order_id"), ("updated_at", "source_updated_at")):
            if p.get(incoming) is not None:
                item[key] = p[incoming]
        return _record(alias, "order", item)

    def read_interval(self, source_state, *, start, end, budget):
        alias = source_state["source_alias"]
        start, end = utc_time(start), utc_time(end)
        account = self._get("/v2/account", {}, budget)
        if not isinstance(account, dict) or not isinstance(account.get("id"), str):
            raise FeedbackError("INVALID_BROKER_IDENTITY", "Paper source identity could not be established")
        fingerprint = self._fingerprint(account["id"])
        previous = source_state.get("fingerprint")
        if previous is not None and previous != fingerprint:
            raise FeedbackError("SOURCE_CHANGED", "This local alias belongs to a different paper source")
        records, codes, activity_complete, cursor = [], [], False, None

        def note(code, *, identity, activity_type="UNSUPPORTED", economic_at=None, source_created_at=None):
            interval_start = source_state.get("earliest_economic_at", start)
            interval_end = end
            metadata = {"activity_type": activity_type if re.fullmatch(ID_PATTERN, activity_type) else "UNSUPPORTED"}
            if economic_at:
                try:
                    is_date = bool(isinstance(economic_at, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", economic_at))
                    economic = utc_time(economic_at + "T00:00:00Z" if is_date else economic_at)
                    interval_start = economic
                    interval_end = utc_time(datetime.fromisoformat(economic) + timedelta(days=1) - timedelta(microseconds=1)) if is_date else economic
                    metadata["economic_at"] = economic
                except (FeedbackError, ValueError, TypeError, OverflowError):
                    codes.append("ACTIVITY_TIME_UNKNOWN")
            if source_created_at:
                try:
                    metadata["source_created_at"] = utc_time(source_created_at)
                except FeedbackError:
                    codes.append("ACTIVITY_TIME_UNKNOWN")
            payload = {"source_alias": alias, "note_id": "note-" + hashlib.sha256(identity.encode()).hexdigest(),
                "code": code, "interval_start": interval_start, "interval_end": interval_end, "metadata": metadata}
            records.append(_record(alias, "source_note", payload))

        try:
            captured_start = utc_time(datetime.now(timezone.utc))
            positions = self._get("/v2/positions", {}, budget)
            open_orders = self._get("/v2/orders", {"status": "open", "limit": 500, "nested": "false"}, budget)
            captured_end = utc_time(datetime.now(timezone.utc))
            if not isinstance(positions, list) or not isinstance(open_orders, list):
                raise FeedbackError("INVALID_BROKER_RESPONSE", "Paper inventory response has an unsupported shape")
            if len(open_orders) >= 500:
                codes.append("OPEN_ORDERS_CAPPED")
            position_map = {p["symbol"]: p for p in positions}
            symbols = set(source_state.get("symbols", [])) | set(position_map)
            for symbol in sorted(symbols):
                if len(open_orders) >= 500:
                    continue
                p = position_map.get(symbol, {})
                inv = {"source_alias": alias, "symbol": symbol, "asset_class": p.get("asset_class", "us_equity"),
                    "currency": "USD", "quantity": p.get("qty", "0"), "observed_at": captured_start,
                    "capture_started_at": captured_start, "capture_completed_at": captured_end,
                    "open_order_ids": [o["id"] for o in open_orders if o["symbol"] == symbol], "origin": "broker"}
                try:
                    records.append(_record(alias, "inventory", inv))
                except FeedbackError:
                    note("UNSUPPORTED_INVENTORY", identity="inventory:" + symbol)
                    codes.append("UNSUPPORTED_INVENTORY")
            for p in open_orders:
                records.append(self._order(alias, p))
            pending, fetched = list(source_state.get("order_ids", [])), set()
            while pending:
                oid = pending.pop(0)
                if oid in fetched:
                    continue
                if not isinstance(oid, str) or not re.fullmatch(ID_PATTERN, oid):
                    raise FeedbackError("INVALID_ORDER_ID", "A bound paper order ID is invalid")
                fetched.add(oid)
                p = self._get("/v2/orders/" + oid, {}, budget)
                if p.get("id") != oid:
                    raise FeedbackError("ORDER_ID_CONFLICT", "Paper order identity does not match its binding")
                records.append(self._order(alias, p))
                pending.extend(p[k] for k in ("replaces", "replaced_by") if p.get(k) and p[k] not in fetched)
            tokens = set()
            query_start = utc_time(datetime.fromisoformat(start) - timedelta(seconds=self.overlap_seconds))
            for _ in range(20):
                query = {"after": query_start, "until": end, "direction": "asc", "page_size": 100}
                if cursor:
                    query["page_token"] = cursor
                page = self._get("/v2/account/activities", query, budget)
                if not isinstance(page, list) or len(page) > 100:
                    raise FeedbackError("INVALID_BROKER_RESPONSE", "Paper activity page has an unsupported shape")
                for p in page:
                    identity = str(p.get("id", ""))
                    if p.get("activity_type") == "FILL":
                        payload = {"source_alias": alias, "fill_id": p["id"], "order_id": p["order_id"],
                            "symbol": p["symbol"], "asset_class": "us_equity", "currency": "USD",
                            "quantity_delta": ("-" if p["side"] == "sell" else "") + str(p["qty"]),
                            "price": p["price"], "occurred_at": p["transaction_time"]}
                        if p["side"] not in {"buy", "sell"}:
                            raise FeedbackError("UNSUPPORTED_FILL_SIDE", "Paper fill side is unsupported")
                        records.append(_record(alias, "fill", payload, identity=identity))
                    else:
                        note("UNSUPPORTED_SOURCE_ACTIVITY", identity=identity or "unknown-activity",
                             activity_type=str(p.get("activity_type", "UNSUPPORTED")),
                             economic_at=p.get("date") or p.get("transaction_time"), source_created_at=p.get("created_at"))
                if len(page) < 100:
                    activity_complete = True
                    break
                next_token = page[-1].get("id")
                if not isinstance(next_token, str) or next_token in tokens:
                    codes.append("REPEATED_PAGE_TOKEN")
                    break
                tokens.add(next_token)
                cursor = next_token
            else:
                codes.append("PAGE_BUDGET_EXHAUSTED")
        except FeedbackError as exc:
            codes.append(exc.code)
        except (KeyError, TypeError, ValueError, AttributeError):
            codes.append("UNSUPPORTED_BROKER_RECORD")
        complete = activity_complete and not codes
        coverage = {"fetch_complete": complete, "economic_history_complete": False,
            "codes": sorted(set(codes)), "activity_pages_completed": activity_complete,
            "paper_limitations": "Simulated fills omit live impact and latency effects; no missing fee is assumed zero"}
        checkpoint = {"source_alias": alias, "requested_start": start, "requested_end": end,
            "overlap_seconds": self.overlap_seconds, "cursor": cursor, **coverage}
        return SyncBatch(records, checkpoint, coverage, fingerprint)


def sync_paper(store, reader, *, source_alias, start, end):
    if not isinstance(source_alias, str) or not re.fullmatch(ID_PATTERN, source_alias):
        raise FeedbackError("INVALID_SOURCE", "Use a valid local paper source alias")
    start, end = utc_time(start), utc_time(end)
    if start >= end:
        raise FeedbackError("INVALID_INTERVAL", "Sync start must precede its end")
    snapshot = store.snapshot()
    state = {"source_alias": source_alias, "fingerprint": snapshot["source_state"].get(source_alias),
        "symbols": sorted({e["payload"]["symbol"] for e in snapshot["events"] if e["kind"] == "decision"}),
        "order_ids": sorted({e["payload"]["order_id"] for e in snapshot["events"] if e["kind"] == "order_binding" and e["payload"]["source_alias"] == source_alias})}
    state["earliest_economic_at"] = min([start, *[e["payload"]["occurred_at"] for e in snapshot["events"]
        if e["kind"] == "fill" and e["payload"]["source_alias"] == source_alias]])
    batch = reader.read_interval(state, start=start, end=end, budget={"deadline": time.monotonic() + 30, "requests": 0})
    # One bounded sync is committed atomically; any immutable-ID conflict aborts its checkpoint.
    with store.transaction():
        store.register_source(source_alias, batch.source_fingerprint)
        receipts = store.append_batch(batch.records, checkpoint=batch.checkpoint)
    return {"status": "SYNCED" if batch.coverage["fetch_complete"] else "PARTIAL_SYNC",
            "source_alias": source_alias, "record_count": len(receipts), "coverage": batch.coverage}
