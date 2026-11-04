"""Store retries, integrity, rollback and project boundaries."""
import json
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from feedback_helpers import decision, fixed_clock


def test_restart_and_concurrent_retries_have_one_receipt(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(tmp_path, create=True, clock=fixed_clock) as store:
        first = store.append("event-d1", "decision", decision())
    def retry(_):
        with FeedbackStore(tmp_path, clock=fixed_clock) as store:
            return store.append("event-d1", "decision", decision())
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(retry, range(8))) == [first] * 8
    with FeedbackStore(tmp_path) as store:
        assert len(store.snapshot()["events"]) == 1
        assert store.verify_chain()["status"] == "VERIFIED"


def test_conflicts_and_failed_batch_do_not_advance_head(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    with FeedbackStore(tmp_path, create=True) as store:
        before = store.snapshot()
        with pytest.raises(FeedbackError):
            store.append_batch([dict(event_id="e1", kind="decision", payload=decision()),
                dict(event_id="e1", kind="decision", payload=decision(quantity_delta="2"))],
                checkpoint={"source_alias": "paper_a", "fetch_complete": True})
        assert store.snapshot() == before


def test_historical_snapshot_retains_old_sync_state(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(tmp_path, create=True) as store:
        store.append_batch([dict(event_id="e1", kind="decision", payload=decision())],
                           checkpoint={"source_alias": "paper_a", "fetch_complete": False})
        old = store.snapshot()
        store.append_batch([dict(event_id="e2", kind="decision", payload=decision(decision_id="d2"))],
                           checkpoint={"source_alias": "paper_a", "fetch_complete": True})
        assert store.snapshot(as_of_seq=old["as_of_seq"]) == old


def test_source_change_and_tampering_are_detected(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    with FeedbackStore(tmp_path, create=True) as store:
        digest = store.fingerprint("synthetic-account")
        store.register_source("paper_a", digest)
        with pytest.raises(FeedbackError):
            store.register_source("paper_a", store.fingerprint("another-account"))
        store.append("e1", "decision", decision())
        assert "synthetic-account" not in json.dumps(store.snapshot())
    path = tmp_path / ".tradeoff/feedback/events.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE events SET payload_json='{}'")
    with FeedbackStore(tmp_path) as store:
        with pytest.raises(FeedbackError):
            store.snapshot()


def test_private_files_are_ignored_and_foreign_folder_refused(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with FeedbackStore(tmp_path, create=True):
        pass
    result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout == ""
    assert (tmp_path / ".tradeoff/feedback/events.sqlite3").stat().st_mode & 0o077 == 0
    other = tmp_path / "foreign"
    (other / ".tradeoff/feedback").mkdir(parents=True)
    (other / ".tradeoff/feedback/untouched").write_text("keep")
    with pytest.raises(FeedbackError):
        FeedbackStore(other, create=True)
    assert (other / ".tradeoff/feedback/untouched").read_text() == "keep"


def test_symlink_and_schema_conflicts_refused(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.contracts import FeedbackError
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target)
    with pytest.raises(FeedbackError):
        FeedbackStore(linked, create=True)
    with FeedbackStore(target, create=True):
        pass
    metadata = target / ".tradeoff/feedback/project.json"
    data = json.loads(metadata.read_text())
    data["schema_version"] = "unsupported"
    metadata.write_text(json.dumps(data))
    with pytest.raises(FeedbackError):
        FeedbackStore(target)
