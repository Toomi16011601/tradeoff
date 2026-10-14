"""The public name must be importable and usable from a fresh command line."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def test_new_public_module_and_cli_name_work():
    assert importlib.util.find_spec("backtest_witness") is not None, "Public module is missing"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "backtest_witness", "--help"],
        cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "backtest-witness" in result.stdout
    assert "cases" in result.stdout and "reproduce" in result.stdout
