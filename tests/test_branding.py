"""Tradeoff branding keeps existing callback references and regressions usable."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _python(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True)


@pytest.mark.parametrize("module", ["tradeoff", "backtest_witness"])
def test_public_and_legacy_module_commands_show_tradeoff(module):
    result = _python("-m", module, "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: tradeoff" in result.stdout
    assert "cases" in result.stdout and "reproduce" in result.stdout


def test_legacy_exceptions_can_be_caught_by_canonical_callers():
    for suffix, name in [("failure_reproduce", "ResilienceError"),
                         ("reproduce", "InvarianceError"),
                         ("privacy", "ExecutionUnavailable")]:
        old = importlib.import_module("backtest_witness." + suffix)
        new = importlib.import_module("tradeoff." + suffix)
        assert getattr(old, name) is getattr(new, name)
        with pytest.raises(getattr(new, name)):
            raise getattr(old, name)("expected compatibility check")


def test_legacy_recording_joins_the_canonical_diagnostics_context(tmp_path):
    old = importlib.import_module("backtest_witness.diagnostics")
    new = importlib.import_module("tradeoff.diagnostics")
    destination = tmp_path / "diagnostics.log"
    with new.local_diagnostics(destination):
        old.record_exception(ValueError("recorded across package names"))
    assert "recorded across package names" in destination.read_text()


def test_all_existing_first_party_import_paths_share_canonical_modules():
    package = ROOT / "src" / "tradeoff"
    assert package.is_dir(), "Canonical Tradeoff package is missing"
    for path in package.rglob("*.py"):
        if "sources" in path.parts or path.name == "__main__.py":
            continue
        parts = list(path.relative_to(package).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        suffix = ".".join(parts)
        assert importlib.import_module("backtest_witness." + suffix) is importlib.import_module("tradeoff." + suffix)


def test_saved_legacy_callback_fixture_replays_without_rewriting(tmp_path):
    from tradeoff.adapters import resolve_runner
    from tradeoff.audit import audit
    from tradeoff.demos import synthetic_rows
    from tradeoff.reproduce import export_reproducer, load_fixture, assert_future_invariance, InvarianceError

    reference = "backtest_witness.demos:leaky_run"
    run = resolve_runner(reference)
    report = audit(run, synthetic_rows(12), strategy_ref=reference)
    assert report["status"] == "FOUND"
    export_reproducer(report, tmp_path, reference)
    path = tmp_path / "reproducer.json"
    saved = path.read_bytes()
    fixture = load_fixture(path)
    assert fixture["strategy_ref"] == reference
    replay = resolve_runner(fixture["strategy_ref"], **fixture["runner_spec"])
    with pytest.raises(InvarianceError):
        assert_future_invariance(replay, fixture)
    assert path.read_bytes() == saved


def test_legacy_import_does_not_import_optional_frameworks():
    result = _python("-c", "import backtest_witness, sys, json; "
        "print(json.dumps(sorted(set(sys.modules) & "
        "{'numpy', 'pandas', 'backtesting', 'backtrader'})))")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
