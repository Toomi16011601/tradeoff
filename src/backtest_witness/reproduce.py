"""Portable paired tapes and executable future-invariance regression tests."""

from copy import deepcopy
from .privacy import callback_error, reject_sensitive_data
import json
from pathlib import Path
import platform
import re
from . import __version__
from .validation import canonical_hash, parse_timestamp, prefix_trace, validate_config, validate_rows, validate_trace


class InvarianceError(AssertionError):
    """Comparable reruns observed a changed target under a future intervention."""


class UnstableRunError(RuntimeError):
    """Identical inputs did not produce repeatable target decisions."""


def _strategy_reference(reference):
    reject_sensitive_data(reference)
    pattern = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
    if not isinstance(reference, str) or re.fullmatch(pattern, reference) is None:
        raise ValueError("strategy_ref must be an importable module:callable reference")
    return reference


def _validated_fixture(fixture):
    if not isinstance(fixture, dict) or fixture.get("schema_version") != "edgelab.fixture.v1":
        raise ValueError("Unsupported reproducer fixture schema")
    reject_sensitive_data(fixture)
    data = deepcopy(fixture)
    claimed_hash = data.pop("fixture_hash", None)
    if claimed_hash != canonical_hash(data):
        raise ValueError("Fixture hash mismatch: reproducer content has changed")
    data["fixture_hash"] = claimed_hash
    if "runner_spec" in data:
        _validated_runner_spec(data["runner_spec"])
    for key in ("original_rows", "mutated_rows", "config"):
        if key not in data or data.get("content_hashes", {}).get(key) != canonical_hash(data[key]):
            raise ValueError(f"Fixture content hash mismatch for {key}")
    original = validate_rows(data["original_rows"])
    mutated = validate_rows(data["mutated_rows"])
    validate_config(data["config"])
    cutoff = parse_timestamp(data.get("cutoff"), "fixture cutoff")
    if data.get("cutoff") not in {row["timestamp"] for row in original[:-1]}:
        raise ValueError("Fixture cutoff must match a bar with a future suffix")
    if type(data.get("seed")) is not int:
        raise ValueError("Fixture seed must be an integer")
    _strategy_reference(data.get("strategy_ref"))
    if len(original) != len(mutated):
        raise ValueError("Fixture must retain equal full-tape history")
    fields = {"open", "high", "low", "close", "volume"}
    changed = False
    for before, after in zip(original, mutated):
        if before == after:
            continue
        changed = True
        if parse_timestamp(before["available_at"]) <= cutoff:
            raise ValueError("Fixture intervention changed a row available at the cutoff")
        if {key: value for key, value in before.items() if key not in fields} != {key: value for key, value in after.items() if key not in fields}:
            raise ValueError("Fixture intervention changed timestamp, availability, symbol or unsupported fields")
    if not changed:
        raise ValueError("Fixture must contain a changed unavailable row")
    hashes = data.get("expected_prefix_hashes")
    if not isinstance(hashes, dict) or set(hashes) != {"original", "intervention"} or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in hashes.values()):
        raise ValueError("Fixture expected prefix hashes must be SHA-256 hashes")
    if hashes["original"] == hashes["intervention"]:
        raise ValueError("Fixture must record different observed prefix hashes")
    return data


def _validated_runner_spec(spec):
    """Validate the persisted adapter boundary without importing user code."""
    engines = {"callback", "targets", "pandas", "backtrader", "backtesting"}
    if (not isinstance(spec, dict) or set(spec) != {"engine", "engine_settings"}
            or not isinstance(spec.get("engine"), str) or spec["engine"] not in engines
            or not isinstance(spec.get("engine_settings"), dict)):
        raise ValueError("Invalid runner descriptor: expected engine and engine_settings")
    validate_config(spec["engine_settings"])
    return deepcopy(spec)


def load_fixture(path):
    """Load a fixture and verify both tape/config hashes and its full receipt."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read reproducer fixture: {exc}") from exc
    return _validated_fixture(raw)


def assert_future_invariance(run, fixture):
    """Repeat each tape, then require equal target decisions through the cutoff.

    Stored prefix hashes describe the original defect; repaired callbacks need
    not match those historical hashes. Only current paired decisions must match.
    """
    data = _validated_fixture(fixture)
    if not callable(run):
        raise ValueError("run must be callable")
    def repeated(rows):
        rows = validate_rows(rows)
        traces = []
        for _ in range(2):
            try:
                output = run(deepcopy(rows), deepcopy(data["config"]), data["seed"])
            except Exception as exc:
                raise ValueError('Reproducer: ' + callback_error(exc)) from None
            try:
                traces.append(validate_trace(output, rows))
            except Exception:
                raise ValueError('Reproducer trace validation failed; invalid or sensitive observations omitted') from None
        if prefix_trace(traces[0]) != prefix_trace(traces[1]):
            raise UnstableRunError("Unstable targets on identical reproducer inputs; future invariance is not comparable")
        return prefix_trace(traces[0], data["cutoff"])
    original = repeated(data["original_rows"])
    intervention = repeated(data["mutated_rows"])
    if original != intervention:
        index = next(index for index, (before, after) in enumerate(zip(original, intervention)) if before != after)
        before, after = original[index], intervention[index]
        raise InvarianceError(f"future invariance failed at {before['timestamp']}: target {before['target']} became {after['target']} under unavailable data intervention (cutoff {data['cutoff']})")


def export_reproducer(report, output_dir, strategy_ref):
    """Write a hashed paired fixture, a receipt, and an adapter-importing pytest."""
    reject_sensitive_data(report)
    reference = _strategy_reference(strategy_ref)
    if report.get("status") != "FOUND" or not report.get("witness"):
        raise ValueError("A FOUND report with a verified witness is required for reproducer export")
    witness = report["witness"]
    original = validate_rows(witness["original_rows"])
    mutated = validate_rows(witness["mutated_rows"])
    baseline = validate_trace(report["baseline"]["trace"], original)
    intervention = validate_trace(witness["mutated_trace"], mutated)
    config = validate_config(report.get("config", {}))
    fixture = {
        "schema_version": "edgelab.fixture.v1", "strategy_ref": reference,
        "cutoff": witness["cutoff"], "config": config, "seed": report["settings"]["seed"],
        "original_rows": original, "mutated_rows": mutated,
        "expected_prefix_hashes": {"original": canonical_hash(prefix_trace(baseline, witness["cutoff"])),
                                   "intervention": canonical_hash(prefix_trace(intervention, witness["cutoff"]))},
        "content_hashes": {"original_rows": canonical_hash(original), "mutated_rows": canonical_hash(mutated), "config": canonical_hash(config)},
    }
    if "runner_spec" in report:
        fixture["runner_spec"] = _validated_runner_spec(report["runner_spec"])
    if "provenance" in report:
        fixture["provenance"] = validate_config(report["provenance"])
    fixture["fixture_hash"] = canonical_hash(fixture)
    _validated_fixture(fixture)
    receipt = {"schema_version": "edgelab.receipt.v1", "report_id": report["report_id"], "strategy_ref": reference,
               "fixture_hash": fixture["fixture_hash"], "content_hashes": fixture["content_hashes"],
               "expected_prefix_hashes": fixture["expected_prefix_hashes"],
               "runtime": {"python_version": platform.python_version(), "python_implementation": platform.python_implementation(), "edgelab_version": __version__, "backtest_witness_version": __version__},
               "scope": {"settings": deepcopy(report["settings"]), "coverage": deepcopy(report["coverage"]), "trace_kind": report["trace_kind"]},
               "explanation": "Content hashes are reproducibility receipts, not signed attestations. The full tapes, configuration, cutoff and seed are bound by fixture_hash. Runtime metadata records the exporter and does not attest to a complete dependency environment."}
    if "runner_spec" in fixture:
        receipt["runner_spec"] = deepcopy(fixture["runner_spec"])
    if "provenance" in fixture:
        receipt["provenance"] = deepcopy(fixture["provenance"])
    generated = '''"""Regression test exported by BacktestWitness. Keep the fixture beside this file."""
from pathlib import Path
from backtest_witness.adapters import resolve_runner
from backtest_witness.reproduce import load_fixture, assert_future_invariance


def test_future_invariance():
    fixture = load_fixture(Path(__file__).with_name("reproducer.json"))
    spec = fixture.get("runner_spec", {"engine": "callback", "engine_settings": {}})
    run = resolve_runner(fixture["strategy_ref"], **spec)
    assert_future_invariance(run, fixture)
'''
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "reproducer.json").write_text(json.dumps(fixture, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    (output / "test_future_invariance.py").write_text(generated, encoding="utf-8")
    return {"fixture": "reproducer.json", "test": "test_future_invariance.py", "receipt": "receipt.json"}
