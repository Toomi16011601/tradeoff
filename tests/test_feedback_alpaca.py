"""Protocol-shaped responses; only the HTTP boundary is replaced."""
from datetime import datetime, timezone
import json
from urllib.parse import urlparse, parse_qs

import pytest

from feedback_helpers import START, END, decision, feedback_project


class PaperTransport:
    def __init__(self, *, activities=None, repeat_page=False, fail=False, identity="synthetic-account"):
        self.calls, self.activities = [], activities or []
        self.repeat_page, self.fail, self.identity = repeat_page, fail, identity

    def __call__(self, request, *, timeout, max_bytes):
        assert request.get_method() == "GET"
        assert urlparse(request.full_url).netloc == "paper-api.alpaca.markets"
        assert 0 < timeout <= 10
        self.calls.append(request)
        path = urlparse(request.full_url).path
        if self.fail:
            raise RuntimeError("SYNTHETIC_SECRET private raw HTTP body")
        if path == "/v2/account":
            return {"id": self.identity, "account_number": "PRIVATE_ACCOUNT_SENTINEL", "status": "ACTIVE"}
        if path in {"/v2/positions", "/v2/orders"}:
            return []
        if path in {"/v2/orders/order-entry", "/v2/orders/order-exit"}:
            entry = path.endswith("order-entry")
            return {"id": "order-entry" if entry else "order-exit", "symbol": "SYNTH", "asset_class": "us_equity",
                "side": "buy" if entry else "sell", "qty": "1.25" if entry else "0.5", "filled_qty": "0.5",
                "status": "canceled" if entry else "filled", "submitted_at": "2026-01-05T14:30:02Z" if entry else "2026-01-05T14:31:01Z",
                "updated_at": "2026-01-05T14:31:03Z"}
        if path == "/v2/account/activities":
            if self.repeat_page:
                return [self.activity(str(i)) for i in range(100)]
            return self.activities
        raise AssertionError("unexpected endpoint")

    @staticmethod
    def activity(activity_id="activity-1"):
        return {"id": activity_id, "activity_type": "FILL", "type": "partial_fill", "order_id": "order-entry",
            "symbol": "SYNTH", "side": "buy", "qty": "0.5", "price": "10", "cum_qty": "0.5",
            "leaves_qty": "0.75", "transaction_time": "2026-01-05T14:30:03Z"}


def test_paper_sync_get_only_private_and_repeatable(feedback_project):
    from tradeoff.feedback.alpaca import PaperReader, sync_paper
    from tradeoff.feedback.store import FeedbackStore
    fake = PaperTransport(activities=[PaperTransport.activity()])
    with FeedbackStore(feedback_project) as store:
        store.append("d1", "decision", decision())
        reader = PaperReader(key_id="SYNTHETIC_KEY", secret_key="SYNTHETIC_SECRET", fingerprint=store.fingerprint, transport=fake)
        first = sync_paper(store, reader, source_alias="paper_a", start=START, end=END)
        sync_paper(store, reader, source_alias="paper_a", start=START, end=END)
        snapshot = store.snapshot()
    assert first["status"] == "SYNCED"
    assert len([e for e in snapshot["events"] if e["kind"] == "fill"]) == 1
    serialized = json.dumps(snapshot) + json.dumps(first)
    assert all(s not in serialized for s in ("SYNTHETIC_SECRET", "PRIVATE_ACCOUNT_SENTINEL", "synthetic-account"))
    # Current flat holdings are explicitly timestamped now, never at historical START.
    inventory = next(e["payload"] for e in snapshot["events"] if e["kind"] == "inventory")
    assert inventory["observed_at"] > END


def test_repeated_tokens_and_source_change_do_not_claim_complete(feedback_project):
    from tradeoff.feedback.alpaca import PaperReader, sync_paper
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    with FeedbackStore(feedback_project) as store:
        reader = PaperReader(key_id="k", secret_key="s", fingerprint=store.fingerprint, transport=PaperTransport(repeat_page=True))
        result = sync_paper(store, reader, source_alias="paper_a", start=START, end=END)
        assert result["status"] == "PARTIAL_SYNC"
        assert not result["coverage"]["fetch_complete"]
        before = store.snapshot()
        other = PaperReader(key_id="k", secret_key="s", fingerprint=store.fingerprint, transport=PaperTransport(identity="another-account"))
        with pytest.raises(FeedbackError):
            sync_paper(store, other, source_alias="paper_a", start=START, end=END)
        assert store.snapshot() == before


def test_http_failure_has_no_raw_exception(feedback_project):
    from tradeoff.feedback.alpaca import PaperReader, sync_paper
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    with FeedbackStore(feedback_project) as store:
        reader = PaperReader(key_id="k", secret_key="s", fingerprint=store.fingerprint, transport=PaperTransport(fail=True))
        with pytest.raises(FeedbackError) as caught:
            sync_paper(store, reader, source_alias="paper_a", start=START, end=END)
    assert "SYNTHETIC_SECRET" not in str(caught.value)


def test_late_fee_activity_is_retained_as_unresolved_source_evidence(feedback_project):
    from tradeoff.feedback.alpaca import PaperReader, sync_paper
    from tradeoff.feedback.store import FeedbackStore
    activity = {"id": "fee-1", "activity_type": "FEE", "date": "2026-01-05", "net_amount": "-0.01"}
    with FeedbackStore(feedback_project) as store:
        reader = PaperReader(key_id="k", secret_key="s", fingerprint=store.fingerprint, transport=PaperTransport(activities=[activity]))
        result = sync_paper(store, reader, source_alias="paper_a", start=START, end=END)
        assert any(e["kind"] == "source_note" for e in store.snapshot()["events"])
        assert not result["coverage"]["economic_history_complete"]


def test_real_transport_blocks_redirects_without_contacting_a_server():
    from tradeoff.feedback.alpaca import RejectRedirects
    handler = RejectRedirects()
    assert handler.redirect_request(None, None, 302, "redirect", {}, "https://example.invalid") is None
