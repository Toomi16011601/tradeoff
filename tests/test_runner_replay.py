"""The Python audit API preserves the same replay boundary as the CLI."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_python_api_audit_exports_actual_engine_replay_with_saved_settings(tmp_path):
    pytest.importorskip("backtesting")
    from backtest_witness.adapters import resolve_runner
    from backtest_witness.audit import audit
    from backtest_witness.demos import synthetic_rows
    from backtest_witness.reproduce import export_reproducer, load_fixture

    reference = "examples.backtesting_demo:LeakyStrategy"
    runner = resolve_runner(reference, engine="backtesting", engine_settings={"cash": 5000, "margin": 0.5})
    report = audit(runner, synthetic_rows(), strategy_ref=reference)
    assert report["status"] == "FOUND"
    export_reproducer(report, tmp_path, reference)
    repository = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(repository / "src"), str(repository)])}
    replay = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", "test_future_invariance.py"],
                            cwd=tmp_path, env=environment, capture_output=True, text=True)
    output = replay.stdout + replay.stderr
    assert replay.returncode == 1, output
    assert "InvarianceError" in output, output
    assert "Reproducer callback or trace failed" not in output, output
    assert report["trace_kind"] == "observed_position"
    fixture = load_fixture(tmp_path / "reproducer.json")
    assert report["runner_spec"] == runner.runner_spec
    assert fixture["runner_spec"] == runner.runner_spec
    assert fixture["runner_spec"]["engine_settings"] == {
        "cash": 5000, "commission": 0, "spread": 0, "trade_on_close": False,
        "margin": 0.5, "exclusive_orders": False,
    }
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["runner_spec"] == runner.runner_spec
    assert receipt["scope"]["trace_kind"] == "observed_position"
