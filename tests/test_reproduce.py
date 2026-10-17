import copy
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import pytest
from test_validation import tape
from test_audit import clean, future_last


def test_hashed_fixture_fails_leak_and_passes_after_causal_fix(tmp_path):
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer, load_fixture, assert_future_invariance, InvarianceError
    report = audit(future_last, tape(), {"lookback": 2}, min_history=1)
    artifacts = export_reproducer(report, tmp_path, "adapter:run")
    assert artifacts == {"fixture": "reproducer.json", "test": "test_future_invariance.py", "receipt": "receipt.json"}
    fixture = load_fixture(tmp_path / artifacts["fixture"])
    assert fixture["config"] == {"lookback": 2}
    assert fixture["seed"] == 7
    assert len(fixture["original_rows"]) == 4
    assert len(fixture["mutated_rows"]) == 4
    with pytest.raises(InvarianceError, match="future"):
        assert_future_invariance(future_last, fixture)
    assert_future_invariance(clean, fixture)
    receipt = json.loads((tmp_path / artifacts["receipt"]).read_text())
    assert receipt["fixture_hash"] == fixture["fixture_hash"]
    assert set(fixture["content_hashes"]) == {"original_rows", "mutated_rows", "config"}


@pytest.mark.parametrize("field", ["original_rows", "mutated_rows", "config", "cutoff", "expected_prefix_hashes"])
def test_tampered_fixture_is_rejected(tmp_path, field):
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer, load_fixture
    export_reproducer(audit(future_last, tape(), min_history=1), tmp_path, "adapter:run")
    path = tmp_path / "reproducer.json"
    data = json.loads(path.read_text())
    if field.endswith("rows"):
        data[field][0]["volume"] += 1
    elif field == "config":
        data[field]["tampered"] = True
    elif field == "cutoff":
        data[field] = "2026-01-01T01:00:00+00:00"
    else:
        data[field]["original"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash"):
        load_fixture(path)


def test_generated_pytest_executes_adapter_and_switches_fail_to_pass(tmp_path):
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer
    export_reproducer(audit(future_last, tape(), min_history=1), tmp_path, "adapter:run")
    adapter = tmp_path / "adapter.py"
    adapter.write_text('def run(rows, config, seed):\n    return [{"timestamp": r["timestamp"], "target": int(rows[-1]["close"] > 20)} for r in rows]\n')
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(Path(__file__).resolve().parents[1] / "src")])
    command = [sys.executable, "-m", "pytest", "-q", "test_future_invariance.py"]
    failed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "InvarianceError" in failed.stdout
    adapter.write_text('def run(rows, config, seed):\n    return [{"timestamp": r["timestamp"], "target": int(r["close"] > r["open"])} for r in rows]\n\n# repaired causal callback\n')
    passed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_replay_rejects_stateful_or_failed_callback(tmp_path):
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer, load_fixture, assert_future_invariance, UnstableRunError
    export_reproducer(audit(future_last, tape(), min_history=1), tmp_path, "adapter:run")
    fixture = load_fixture(tmp_path / "reproducer.json")
    counter = 0
    def unstable(rows, config, seed):
        nonlocal counter
        counter += 1
        return [{"timestamp": row["timestamp"], "target": counter % 2} for row in rows]
    with pytest.raises(UnstableRunError):
        assert_future_invariance(unstable, fixture)
    def short(rows, config, seed):
        return []
    with pytest.raises(ValueError, match="trace"):
        assert_future_invariance(short, fixture)


def test_reproducer_requires_actual_verified_witness(tmp_path):
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer
    with pytest.raises(ValueError, match="FOUND"):
        export_reproducer(audit(clean, tape(), min_history=1), tmp_path, "adapter:run")


def test_receipt_records_runtime_and_observed_audit_scope(tmp_path):
    from tradeoff import __version__
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer
    report = audit(future_last, tape(), min_history=1, max_calls=8,
                   trace_kind="observed_positions")
    export_reproducer(report, tmp_path, "adapter:run")
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["runtime"]["python_version"] == platform.python_version()
    assert receipt["runtime"]["backtest_witness_version"] == __version__
    assert receipt["runtime"]["edgelab_version"] == __version__  # Existing receipt wire key.
    assert receipt["scope"]["trace_kind"] == "observed_positions"
    assert receipt["scope"]["settings"]["max_calls"] == 8
    assert receipt["scope"]["coverage"]["runs"] == 8
    assert not receipt["scope"]["coverage"]["complete"]


def test_export_keeps_hashed_runner_descriptor_and_receipt(tmp_path):
    from tradeoff.audit import audit
    from tradeoff.reproduce import export_reproducer, load_fixture
    from tradeoff.validation import canonical_hash
    report = audit(future_last, tape(), min_history=1)
    report["runner_spec"] = {"engine": "backtesting", "engine_settings": {"cash": 5000, "margin": 0.5}}
    export_reproducer(report, tmp_path, "strategy:Example")
    fixture = load_fixture(tmp_path / "reproducer.json")
    assert fixture["runner_spec"] == report["runner_spec"]
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["runner_spec"] == report["runner_spec"]
    damaged = dict(fixture)
    damaged["runner_spec"] = {"engine": "unknown", "engine_settings": {}}
    body = {key: value for key, value in damaged.items() if key != "fixture_hash"}
    damaged["fixture_hash"] = canonical_hash(body)
    (tmp_path / "reproducer.json").write_text(json.dumps(damaged))
    with pytest.raises(ValueError, match="runner"):
        load_fixture(tmp_path / "reproducer.json")
