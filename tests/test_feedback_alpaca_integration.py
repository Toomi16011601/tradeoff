"""Opt-in, read-only account integration; never place/cancel orders."""
import os
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.skipif(os.environ.get("TRADEOFF_RUN_PAPER_TESTS") != "1", reason="NOT_RUN: explicit paper-account opt-in required")
def test_actual_paper_account_read_only_sync(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.store import FeedbackStore
    if not os.environ.get("APCA_API_KEY_ID") or not os.environ.get("APCA_API_SECRET_KEY"):
        pytest.skip("NOT_RUN: local paper credentials not configured")
    with FeedbackStore(tmp_path, create=True):
        pass
    end = datetime.now(timezone.utc)
    args = {"source_alias": "paper", "start": (end - timedelta(days=1)).isoformat(), "end": end.isoformat()}
    app = FeedbackApp(tmp_path)
    assert app.sync_paper_evidence(args)["status"] in {"SYNCED", "PARTIAL_SYNC"}
    assert app.sync_paper_evidence(args)["status"] in {"SYNCED", "PARTIAL_SYNC"}
