"""Execute pinned public code; do not replace upstream order sizing with booleans."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def cases_api():
    assert importlib.util.find_spec("tradeoff.cases") is not None, "Pinned public strategy cases are missing"
    return importlib.import_module("tradeoff.cases")


def engine_case(name):
    pytest.importorskip("backtesting")
    pytest.importorskip("pandas")
    pytest.importorskip("numpy")
    return cases_api().get_case(name)


def test_public_cases_are_importable_without_loading_optional_engines():
    cases_api()
    code = """import sys
from tradeoff.cases import CASES, get_case
assert set(CASES) == {'riskkit', 'coinglass'}
get_case('riskkit')
get_case('coinglass')
assert not any(name in sys.modules for name in ('backtesting', 'pandas', 'numpy'))
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["riskkit", "coinglass"])
def test_original_public_strategy_produces_a_reproducible_bug_and_fixed_variant_passes(name, tmp_path):
    case = engine_case(name)
    from tradeoff.audit import audit
    from tradeoff.reproduce import InvarianceError, assert_future_invariance, export_reproducer, load_fixture
    report = audit(case["original"], case["rows"](), case["config"],
                   strategy_ref=case["original_ref"], trace_kind="observed_position",
                   **case["audit_settings"])
    assert report["status"] == "FOUND", report["reason"]
    assert report["witness"]["before_decision"]["target"] != report["witness"]["after_decision"]["target"]
    export_reproducer(report, tmp_path, case["original_ref"])
    fixture = load_fixture(tmp_path / "reproducer.json")
    with pytest.raises(InvarianceError):
        assert_future_invariance(case["original"], fixture)
    assert_future_invariance(case["fixed"], fixture)
    clean = audit(case["fixed"], case["rows"](), case["config"],
                  strategy_ref=case["fixed_ref"], trace_kind="observed_position",
                  **case["audit_settings"])
    assert clean["status"] == "NO_DEPENDENCY_OBSERVED", clean["reason"]


def test_riskkit_case_preserves_actual_position_sizer_and_nonbinary_positions():
    case = engine_case("riskkit")
    rows = case["rows"]()
    changed = json.loads(json.dumps(rows))
    for row in changed[46:]:
        for field in ("open", "high", "low", "close", "volume"):
            row[field] *= 0.4
    before = case["original"](rows, {}, 7)
    after = case["original"](changed, {}, 7)
    # Independent exploratory engine probe, using unmodified upstream class/sizer.
    assert before[42]["target"] == 29
    assert after[42]["target"] == 31
    assert case["original"].trace_kind == "observed_position"


def test_coinglass_case_recalculates_original_preprocessing_from_each_raw_tape():
    case = engine_case("coinglass")
    rows = case["rows"]()
    changed = json.loads(json.dumps(rows))
    for row in changed[-3:]:
        row["volume"] *= 0.05
    before = case["original"](rows, {}, 7)
    after = case["original"](changed, {}, 7)
    assert before[236]["target"] == 67
    assert after[236]["target"] == 0
    assert case["fixed"](rows, {}, 7)[:253] == case["fixed"](changed, {}, 7)[:253]


def test_public_case_source_integrity_rejects_tampering(tmp_path):
    cases_api()
    from tradeoff.cases._loader import load_source
    source = tmp_path / "source.py"
    source.write_text("def harmless(): return 1\n")
    with pytest.raises(ValueError, match="hash"):
        load_source(source, "0" * 64)


def test_unknown_case_name_has_actionable_error():
    api = cases_api()
    with pytest.raises(ValueError, match="riskkit.*coinglass|coinglass.*riskkit"):
        api.get_case("missing")
