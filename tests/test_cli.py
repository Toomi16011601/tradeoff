"""Exercise public commands and their actual files, rather than argparse internals."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    return subprocess.run([sys.executable, "-m", "tradeoff", *map(str, args)],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_demo_produces_three_distinct_honest_states(tmp_path):
    result = invoke("demo", "--output", tmp_path / "demo")
    assert result.returncode == 0, result.stderr
    expected = {"leaky": "FOUND", "causal": "NO_DEPENDENCY_OBSERVED", "unstable": "INCONCLUSIVE"}
    for name, state in expected.items():
        folder = tmp_path / "demo" / name
        assert json.loads((folder / "report.json").read_text())["status"] == state
        assert (folder / "index.html").stat().st_size > 5000
    assert (tmp_path / "demo" / "leaky" / "test_future_invariance.py").exists()
    assert not (tmp_path / "demo" / "causal" / "test_future_invariance.py").exists()
    assert (tmp_path / "demo" / "index.html").exists()


def test_invalid_data_is_a_friendly_error(tmp_path):
    data = tmp_path / "bad.json"
    data.write_text('[{"timestamp":"wrong"}]')
    result = invoke("audit", "--adapter", "tradeoff.demos:causal_run", "--data", data,
                    "--output", tmp_path / "audit")
    assert result.returncode == 2
    assert "Error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_avoid_overwriting_unrelated_files(tmp_path):
    folder = tmp_path / "existing"
    folder.mkdir()
    keep = folder / "keep.txt"
    keep.write_text("mine")
    result = invoke("demo", "--output", folder)
    assert result.returncode == 2
    assert keep.read_text() == "mine"


def test_csv_callback_audit_and_fixture_replay(tmp_path):
    from tradeoff.demos import synthetic_rows
    import csv
    rows = synthetic_rows()
    data = tmp_path / "bars.csv"
    with data.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    folder = tmp_path / "audit"
    result = invoke("audit", "--adapter", "tradeoff.demos:leaky_run", "--data", data,
                    "--output", folder)
    assert result.returncode == 1, result.stderr
    report = json.loads((folder / "report.json").read_text())
    assert report["status"] == "FOUND"
    assert report["economics"]["original"]["final_equity"] > 0
    failed = invoke("reproduce", folder / "reproducer.json")
    assert failed.returncode == 1, failed.stderr
    passed = invoke("reproduce", folder / "reproducer.json", "--adapter", "tradeoff.demos:causal_run")
    assert passed.returncode == 0, passed.stderr


def test_help_describes_audit_command():
    result = invoke("--help")
    assert result.returncode == 0
    assert "audit" in result.stdout and "reproduce" in result.stdout


def test_projection_precision_does_not_discard_a_verified_witness(tmp_path):
    from tradeoff.demos import synthetic_rows
    data = tmp_path / "bars.json"
    data.write_text(json.dumps(synthetic_rows()))
    folder = tmp_path / "audit"
    result = invoke("audit", "--adapter", "tradeoff.demos:leaky_run", "--data", data,
                    "--output", folder, "--initial-cash", "1e16", "--fee-fixed", "0",
                    "--spread-bps", "0", "--slippage-bps", "0")
    assert result.returncode == 1, result.stderr
    report = json.loads((folder / "report.json").read_text())
    assert report["status"] == "FOUND" and report["witness"]
    assert report["economics"] is None
    assert "precision" in report["economics_error"]
    assert (folder / "reproducer.json").exists()


def test_negative_cost_is_a_friendly_configuration_error(tmp_path):
    result = invoke("demo", "--output", tmp_path / "demo", "--fee-fixed", "-1")
    assert result.returncode == 2
    assert "fee_fixed" in result.stderr and "Traceback" not in result.stderr


def local_invoke(folder, *args):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(folder)]))
    return subprocess.run([sys.executable, "-m", "tradeoff", *map(str, args)],
                          cwd=folder, env=env, capture_output=True, text=True)


def test_numeric_signal_function_needs_no_trace_wrapper_and_replays(tmp_path):
    from tradeoff.demos import synthetic_rows
    data = tmp_path / "bars.json"
    data.write_text(json.dumps(synthetic_rows()))
    source = tmp_path / "signals.py"
    source.write_text('def positions(rows, config, seed):\n    return [int(rows[-1]["close"] > 110)] * len(rows)\n')
    folder = tmp_path / "audit"
    result = local_invoke(tmp_path, "audit", "--adapter", "signals:positions", "--engine", "targets",
                          "--data", data, "--output", folder)
    assert result.returncode == 1, result.stderr
    fixture = json.loads((folder / "reproducer.json").read_text())
    assert fixture["runner_spec"] == {"engine": "targets", "engine_settings": {}}
    assert local_invoke(tmp_path, "reproduce", folder / "reproducer.json").returncode == 1
    source.write_text('def positions(rows, config, seed):\n    return [int(row["close"] > 110) for row in rows]\n\n# causal per-bar implementation\n')
    passed = local_invoke(tmp_path, "reproduce", folder / "reproducer.json")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_direct_backtesting_class_fixture_reconstructs_engine_settings(tmp_path):
    pytest.importorskip("backtesting")
    from tradeoff.demos import synthetic_rows
    data = tmp_path / "bars.json"
    data.write_text(json.dumps(synthetic_rows()))
    source = tmp_path / "strategy.py"
    source.write_text('from backtesting import Strategy\nclass PublicStyle(Strategy):\n'
                      '    def init(self):\n        self.leaked = self.data.Close[-1] > 110\n'
                      '    def next(self):\n        if self.leaked and not self.position:\n            self.buy(size=3)\n')
    folder = tmp_path / "audit"
    settings = '{"cash": 5000, "margin": 0.5}'
    result = local_invoke(tmp_path, "audit", "--adapter", "strategy:PublicStyle", "--engine", "backtesting",
                          "--engine-settings", settings, "--data", data, "--output", folder)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((folder / "report.json").read_text())
    assert report["trace_kind"] == "observed_position"
    paired = report["baseline"]["trace"] + report["witness"]["mutated_trace"]
    assert max(row["target"] for row in paired) == 3
    fixture = json.loads((folder / "reproducer.json").read_text())
    assert fixture["runner_spec"]["engine_settings"]["margin"] == 0.5
    replay = local_invoke(tmp_path, "reproduce", folder / "reproducer.json")
    assert replay.returncode == 1, replay.stdout + replay.stderr
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(tmp_path)]))
    generated = subprocess.run([sys.executable, "-m", "pytest", "-q", folder / "test_future_invariance.py"],
                               cwd=tmp_path, env=env, capture_output=True, text=True)
    assert generated.returncode == 1 and "InvarianceError" in generated.stdout
    source.write_text('from backtesting import Strategy\nclass PublicStyle(Strategy):\n'
                      '    def init(self):\n        pass\n'
                      '    def next(self):\n        if self.data.Close[-1] > 110 and not self.position:\n            self.buy(size=3)\n\n# repair\n')
    fixed = local_invoke(tmp_path, "reproduce", folder / "reproducer.json")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr


def test_cli_declares_leverage_and_short_borrow_in_report(tmp_path):
    result = invoke("demo", "--output", tmp_path / "demo", "--max-leverage", "2",
                    "--short-borrow-bps-annual", "75")
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "demo" / "leaky" / "report.json").read_text())
    assert report["economics"]["assumptions"]["max_leverage"] == 2
    assert report["economics"]["assumptions"]["short_borrow_bps_annual"] == 75


def test_pandas_signals_load_directly_and_export_replayable_descriptor(tmp_path):
    pytest.importorskip("pandas")
    from tradeoff.demos import synthetic_rows
    data = tmp_path / "bars.json"
    data.write_text(json.dumps(synthetic_rows()))
    source = tmp_path / "pandas_signals.py"
    source.write_text('def signals(frame, units=5):\n    return ((frame.close > frame.close.mean()) * units).rename("position").to_frame()\n')
    config = tmp_path / "config.json"
    config.write_text('{"units": 5}')
    folder = tmp_path / "audit"
    result = local_invoke(tmp_path, "audit", "--adapter", "pandas_signals:signals", "--engine", "pandas",
                          "--engine-settings", '{"target_column":"position"}', "--config", config,
                          "--data", data, "--output", folder)
    assert result.returncode == 1, result.stdout + result.stderr
    fixture = json.loads((folder / "reproducer.json").read_text())
    assert fixture["config"] == {"units": 5}
    assert fixture["runner_spec"]["engine_settings"] == {"target_column": "position"}
    assert local_invoke(tmp_path, "reproduce", folder / "reproducer.json").returncode == 1


def test_public_case_command_exports_original_and_checks_same_fixture_repair(tmp_path):
    pytest.importorskip("backtesting")
    folder = tmp_path / "public"
    result = invoke("cases", "--case", "riskkit", "--output", folder, "--max-calls", "48")
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((folder / "case-results.json").read_text())
    assert summary["cases"][0]["original_status"] == "FOUND"
    assert summary["cases"][0]["repair_replay"] == "PASS"
    original = json.loads((folder / "riskkit-original" / "report.json").read_text())
    assert original["provenance"]["commit"] == "99d1d167dc55c8a564526ef42d87e298f3e74fad"
    assert (folder / "riskkit-original" / "reproducer.json").exists()
    assert json.loads((folder / "riskkit-fixed" / "report.json").read_text())["status"] == "NO_DEPENDENCY_OBSERVED"


def test_unrepresentable_signed_reversal_preserves_dependency_artifacts(tmp_path):
    rows = [dict(timestamp=f"2026-01-0{i + 1}T00:00:00+00:00", symbol="TINY",
                 open=1e-300, high=1e-300, low=1e-300, close=1e-300, volume=100)
            for i in range(5)]
    data = tmp_path / "bars.json"
    data.write_text(json.dumps(rows))
    (tmp_path / "huge_positions.py").write_text('def positions(rows, config, seed):\n'
        '    later = 1e308 if rows[-1]["close"] > 1e-300 else -1e308\n'
        '    return [-1e308] + [later] * (len(rows) - 1)\n')
    folder = tmp_path / "audit"
    result = local_invoke(tmp_path, "audit", "--adapter", "huge_positions:positions", "--engine", "targets",
        "--data", data, "--output", folder, "--initial-cash", "1e9", "--fee-fixed", "0",
        "--spread-bps", "0", "--slippage-bps", "0")
    assert result.returncode == 1 and "Traceback" not in result.stderr, result.stdout + result.stderr
    report = json.loads((folder / "report.json").read_text())
    assert report["status"] == "FOUND" and report["economics"] is None
    assert "finite" in report["economics_error"] or "overflow" in report["economics_error"]
    assert (folder / "reproducer.json").exists()
