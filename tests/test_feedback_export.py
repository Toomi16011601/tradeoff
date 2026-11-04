import hashlib
import json

import pytest

from feedback_helpers import AFTER_HORIZON, episode_records, make_snapshot, mark


def export_fixture(tmp_path, *, records=None):
    from tradeoff.feedback.api import FeedbackApp
    records = episode_records() if records is None else records
    records.append(dict(event_id="mark", kind="mark", payload=mark()))
    make_snapshot(tmp_path, records)
    return FeedbackApp(tmp_path).export_feedback({"output": "feedback-output", "as_of": AFTER_HORIZON})


def test_export_omits_private_store_and_pseudonymizes_broker_ids(tmp_path):
    result = export_fixture(tmp_path)
    folder = tmp_path / "feedback-output"
    report = json.loads((folder / result["report"]).read_text())
    raw = "".join(p.read_text() for p in folder.iterdir())
    for private in ("order-entry", "fill-entry", "source_state", "private.key", "events.sqlite3", str(tmp_path)):
        assert private not in raw
    assert report["evaluation"]["episodes"][0]["observed_net"] == "0.95"
    receipt = json.loads((folder / "feedback-receipt.json").read_text())
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    assert "not a signature" in receipt["scope"]


def test_export_is_fresh_and_cannot_follow_symlinks(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError
    export_fixture(tmp_path)
    app = FeedbackApp(tmp_path)
    with pytest.raises(FeedbackError):
        app.export_feedback({"output": "feedback-output", "as_of": AFTER_HORIZON})
    (tmp_path / "linked").symlink_to(tmp_path / "feedback-output")
    with pytest.raises(FeedbackError):
        app.export_feedback({"output": "linked/nested", "as_of": AFTER_HORIZON})


def test_snapshot_content_is_not_exported_without_opt_in(tmp_path):
    from tradeoff.feedback.contracts import canonical_json
    from tradeoff.feedback.api import FeedbackApp
    records = episode_records()
    snapshot = {"private_strategy_setting": "SYNTHETIC_PROPRIETARY_SIGNAL"}
    records[1]["payload"].update(input_snapshot=snapshot, input_hash=hashlib.sha256(canonical_json(snapshot).encode()).hexdigest())
    export_fixture(tmp_path, records=records)
    assert "SYNTHETIC_PROPRIETARY_SIGNAL" not in (tmp_path / "feedback-output/feedback-evidence.json").read_text()
    result = FeedbackApp(tmp_path).export_feedback({"output": "feedback-opted", "as_of": AFTER_HORIZON, "include_snapshots": True})
    assert "SYNTHETIC_PROPRIETARY_SIGNAL" in (tmp_path / "feedback-opted/feedback-evidence.json").read_text()
