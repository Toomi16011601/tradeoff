"""Synthetic scale regression: many valid records, never enlarged input limits."""
import asyncio
from datetime import datetime
import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from feedback_helpers import AFTER_HORIZON, decision

COUNT = 1400


@pytest.fixture(scope="module")
def large_history(tmp_path_factory):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.store import FeedbackStore
    project = tmp_path_factory.mktemp("synthetic-scale")
    with FeedbackStore(project, create=True, environment="simulated"):
        pass
    app = FeedbackApp(project, clock=lambda: datetime.fromisoformat(AFTER_HORIZON))
    for offset in range(0, COUNT, 100):
        app.import_evidence({"records": [dict(event_id=f"history-{i}", kind="decision", environment="simulated",
            payload=decision(decision_id=f"decision-{i}", opportunity_id=f"opportunity-{i}",
                action="hold", quantity_delta="0")) for i in range(offset, min(offset + 100, COUNT))]})
    (project / "prices.csv").write_text("timestamp,price,available_at\n2026-01-05T15:30:00Z,12,2026-01-05T15:30:01Z\n")
    app.configure_price_source(dict(data_file="prices.csv", symbol="SYNTH", currency="USD", source="fixture",
        feed="fixture-feed", price_kind="mid", available_at_column="available_at"))
    return project


@pytest.fixture
def large_project(large_history, tmp_path):
    project = tmp_path / "workspace"
    shutil.copytree(large_history, project)
    return project


def assert_large_evaluation(report, *, available):
    assert len(json.dumps(report).encode()) > 1024 * 1024
    assert report["evaluation"]["coverage"]["decision_count"] == COUNT
    decisions = report["evaluation"]["decisions"]
    assert len(decisions) == COUNT
    assert {d["outcome_status"] for d in decisions} == {"AVAILABLE" if available else "UNAVAILABLE"}
    assert all(d["realized_decision_pnl"] is None for d in decisions)


def test_evaluate_valid_history_larger_than_one_input_envelope(large_project):
    from tradeoff.feedback.api import FeedbackApp
    report = FeedbackApp(large_project).evaluate_decisions({"as_of": AFTER_HORIZON})
    assert_large_evaluation(report, available=False)
    assert report["report_id"] == FeedbackApp(large_project).evaluate_decisions({"as_of": AFTER_HORIZON})["report_id"]


def test_collect_large_history_completes_and_retries_without_duplicate_marks(large_project):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.store import FeedbackStore
    app = FeedbackApp(large_project, clock=lambda: datetime.fromisoformat(AFTER_HORIZON))
    result = app.collect_outcomes({"as_of": AFTER_HORIZON})
    assert result["status"] == "COLLECTED"
    assert result["collection"]["new_marks"] == 1
    assert result["collection"]["newly_available_outcomes"] == COUNT
    assert_large_evaluation(result["feedback"], available=True)
    again = app.collect_outcomes({"as_of": AFTER_HORIZON})
    assert again["collection"]["new_marks"] == 0
    assert again["collection"]["newly_available_outcomes"] == 0
    assert again["feedback"]["report_id"] == result["feedback"]["report_id"]
    with FeedbackStore(large_project, readonly=True) as store:
        assert sum(e["kind"] == "mark" for e in store.snapshot()["events"]) == 1


def test_export_large_history_preserves_all_records_and_receipt_bytes(large_project):
    from tradeoff.feedback.api import FeedbackApp
    result = FeedbackApp(large_project).export_feedback({"output": "feedback-output", "as_of": AFTER_HORIZON})
    output = large_project / "feedback-output"
    assert_large_evaluation(json.loads((output / result["report"]).read_text()), available=False)
    evidence = output / result["evidence"]
    assert evidence.stat().st_size > 1024 * 1024
    assert len(json.loads(evidence.read_text())["events"]) == COUNT
    receipt = json.loads((output / result["receipt"]).read_text())
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert not list(large_project.glob(".feedback-export-*"))


def test_installed_cli_evaluates_large_history(large_project, tmp_path):
    entry = Path(sys.executable).with_name("tradeoff")
    if not entry.is_file():
        pytest.skip("Installed Tradeoff entry point is unavailable in this interpreter")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run([str(entry), "feedback", "evaluate", "--project", str(large_project),
        "--as-of", AFTER_HORIZON, "--json"], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert_large_evaluation(json.loads(result.stdout), available=False)


@pytest.mark.skipif(find_spec("mcp") is None, reason="Optional MCP SDK not installed")
def test_real_mcp_serializes_large_evaluation_and_collection(large_project, tmp_path):
    from mcp import StdioServerParameters
    from mcp.client import ClientSession
    from mcp.client.stdio import stdio_client

    async def check():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "tradeoff", "feedback", "mcp", "--project", str(large_project)],
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        with (tmp_path / "mcp-stderr.log").open("w") as log:
            async with stdio_client(params, errlog=log) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    evaluated = await session.call_tool("tradeoff_evaluate_decisions", {"as_of": AFTER_HORIZON})
                    assert not evaluated.is_error, evaluated
                    assert_large_evaluation(evaluated.structured_content, available=False)
                    assert json.loads(evaluated.content[0].text) == evaluated.structured_content
                    collected = await session.call_tool("tradeoff_collect_outcomes", {"as_of": AFTER_HORIZON})
                    assert not collected.is_error, collected
                    assert collected.structured_content["collection"]["new_marks"] == 1
                    assert_large_evaluation(collected.structured_content["feedback"], available=True)
                    assert json.loads(collected.content[0].text) == collected.structured_content
    asyncio.run(check())


def test_collection_export_failure_reports_saved_marks_and_allows_retry(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(tmp_path, create=True):
        pass
    app = FeedbackApp(tmp_path, clock=lambda: datetime.fromisoformat(AFTER_HORIZON))
    app.record_decision({"event_id": "hold", "decision": decision(action="hold", quantity_delta="0")})
    (tmp_path / "prices.csv").write_text("timestamp,price,available_at\n2026-01-05T15:30:00Z,12,2026-01-05T15:30:01Z\n")
    app.configure_price_source(dict(data_file="prices.csv", symbol="SYNTH", currency="USD", source="fixture",
        feed="fixture-feed", price_kind="mid", available_at_column="available_at"))
    (tmp_path / "blocked").write_text("parent is a file")
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({"as_of": AFTER_HORIZON, "output": "blocked/report"})
    assert caught.value.code == "COLLECTED_EXPORT_FAILED"
    assert "saved" in caught.value.message.lower()
    assert str(tmp_path) not in caught.value.message
    retried = app.collect_outcomes({"as_of": AFTER_HORIZON, "output": "retry-report"})
    assert retried["collection"]["new_marks"] == 0
    assert (tmp_path / "retry-report" / retried["interface"]).is_file()


def test_large_outputs_do_not_weaken_ingestion_limits(large_project):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError, canonical_json, parse_json
    oversized = {"records": [{"kind": "decision", "payload": decision(reason="x" * 4096),
        "event_id": f"new-{i}"} for i in range(300)]}
    assert len(json.dumps(oversized).encode()) > 1024 * 1024
    for operation in (lambda: canonical_json(oversized), lambda: parse_json(json.dumps(oversized)),
                      lambda: FeedbackApp(large_project).import_evidence(oversized)):
        with pytest.raises(FeedbackError):
            operation()


def test_output_hash_preserves_existing_canonical_bytes_and_small_report_ids(tmp_path):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import canonical_json
    from tradeoff.feedback.serialization import output_hash, output_json
    from tradeoff.feedback.store import FeedbackStore
    from decimal import Decimal
    sample = {"unicode": "\u03a3", "decimal": Decimal("1.250"), "nested": [True, None, {"b": 2, "a": 1}]}
    assert output_json(sample) == '{"decimal":"1.25","nested":[true,null,{"a":1,"b":2}],"unicode":"\\u03a3"}'
    assert output_hash(sample) == hashlib.sha256(canonical_json(sample).encode()).hexdigest()
    with FeedbackStore(tmp_path, create=True):
        pass
    report = FeedbackApp(tmp_path).evaluate_decisions({"as_of": AFTER_HORIZON})
    identity = report.pop("report_id")
    assert identity == hashlib.sha256(canonical_json(report).encode()).hexdigest()[:24]


@pytest.mark.parametrize("value", [
    {"evaluation": {"decisions": [{"text": "x" * 4097}]}},
    {"evaluation": {"decisions": [{"text": float("nan")}]}},
    {"evaluation": {"decisions": [{"text": float("inf")}]}},
    {"evaluation": {"decisions": [{"api_key": "SYNTHETIC_SENTINEL"}]}},
    {"evaluation": {"decisions": [{"text": "person@example.com"}]}},
    {"evaluation": {"decisions": [{"input_snapshot": {str(i): "x" * 4096 for i in range(300)}}]}},
    {"unknown": [str(i) for i in range(10001)]},
])
def test_output_validation_still_rejects_unsafe_individual_records(value):
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.serialization import output_json
    with pytest.raises(FeedbackError):
        output_json(value)


def test_output_validation_preserves_depth_and_cycle_bounds():
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.serialization import output_json
    deep = 0
    for _ in range(33):
        deep = [deep]
    cyclic = []
    cyclic.append(cyclic)
    for value in (deep, cyclic):
        with pytest.raises(FeedbackError):
            output_json({"evaluation": {"decisions": [value]}})


def test_output_allows_long_history_but_bounds_each_record():
    from tradeoff.feedback.serialization import output_json
    text = output_json({"events": [{"kind": "synthetic", "seq": i} for i in range(10001)]})
    assert len(json.loads(text)["events"]) == 10001


def test_unexpected_export_failure_still_discloses_committed_collection(large_project, monkeypatch):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.store import FeedbackStore

    def failed_render(report):
        raise RuntimeError("SYNTHETIC_PRIVATE_DIAGNOSTIC")

    monkeypatch.setattr("tradeoff.report.feedback_renderer.render_feedback_report", failed_render)
    app = FeedbackApp(large_project, clock=lambda: datetime.fromisoformat(AFTER_HORIZON))
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({"as_of": AFTER_HORIZON, "output": "failed-report"})
    assert caught.value.code == "COLLECTED_EXPORT_FAILED"
    assert "saved" in caught.value.message.lower()
    assert "SYNTHETIC_PRIVATE_DIAGNOSTIC" not in caught.value.message
    with FeedbackStore(large_project, readonly=True) as store:
        assert sum(e["kind"] == "mark" for e in store.snapshot()["events"]) == 1
    assert not (large_project / "failed-report").exists()
    assert not list(large_project.glob(".feedback-export-*"))


def test_report_validation_failure_does_not_commit_new_price_marks(large_project, monkeypatch):
    from tradeoff.feedback.api import FeedbackApp
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.store import FeedbackStore

    def failed_hash(value):
        raise FeedbackError("INVALID_EVIDENCE", "Synthetic report validation failure")

    app = FeedbackApp(large_project, clock=lambda: datetime.fromisoformat(AFTER_HORIZON))
    with monkeypatch.context() as patch:
        patch.setattr("tradeoff.feedback.api.output_hash", failed_hash)
        with pytest.raises(FeedbackError):
            app.collect_outcomes({"as_of": AFTER_HORIZON})
    with FeedbackStore(large_project, readonly=True) as store:
        assert store.snapshot()["as_of_seq"] == COUNT
        assert all(e["kind"] != "mark" for e in store.snapshot()["events"])
    retried = app.collect_outcomes({"as_of": AFTER_HORIZON})
    assert retried["collection"]["new_marks"] == 1
    assert retried["collection"]["newly_available_outcomes"] == COUNT
