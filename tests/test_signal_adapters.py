"""Signal wrappers preserve quantities, time alignment and fresh strategy inputs."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random
import sys

import pytest


def rows():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(days=i)).isoformat(), "symbol": "SYN",
             "open": 10, "high": 12, "low": 8, "close": 11, "volume": 100,
             "feature": {"nested": [1]}} for i in range(4)]


def test_targets_runner_accepts_native_and_numpy_signed_fractional_arrays():
    from tradeoff.adapters import make_targets_runner
    np = pytest.importorskip("numpy")
    for values in ([-2, 1.5, -0.0, 3.0], (-2, 1.5, -0.0, 3.0), np.array([-2, 1.5, -0.0, 3.0])):
        trace = make_targets_runner(lambda rows, config, seed: values)(rows(), {}, 7)
        assert [record["target"] for record in trace] == [-2, 1.5, 0, 3]
        assert [record["timestamp"] for record in trace] == [row["timestamp"] for row in rows()]
        assert type(trace[-1]["target"]) is int


@pytest.mark.parametrize("values", [
    [0, 0], [0, True, 0, 0], [0, "1", 0, 0], [0, float("nan"), 0, 0],
    [0, float("inf"), 0, 0], [[0], [0], [0], [0]], "0000", {0: 0, 1: 0, 2: 0, 3: 0},
])
def test_targets_runner_rejects_invalid_quantity_sequences(values):
    from tradeoff.adapters import make_targets_runner
    with pytest.raises(ValueError, match="target|sequence|length"):
        make_targets_runner(lambda rows, config, seed: values)(rows(), {}, 7)


def test_targets_runner_rebuilds_inputs_and_preserves_seeded_random_state():
    from tradeoff.adapters import make_targets_runner
    data = rows()
    config = {"nested": [2]}
    before = deepcopy((data, config))

    def signals(frame, config, seed):
        frame[0]["feature"]["nested"].append(99)
        config["nested"].append(99)
        return [random.random(), 0, 0, 0]

    run = make_targets_runner(signals)
    state = random.getstate()
    first = run(data, config, 7)
    assert random.getstate() == state
    assert run(data, config, 7) == first
    assert (data, config) == before
    assert run.trace_kind == "target_units"


def test_targets_runner_works_without_optional_numpy_dependency():
    from tradeoff.adapters import make_targets_runner
    # Simulate a core-only installation; the stdlib sequence path needs no array library.
    original = sys.modules.pop("numpy", None)
    sys.modules["numpy"] = None
    try:
        trace = make_targets_runner(lambda rows, config, seed: [-2, 0, 1.25, 0])(rows(), {}, 7)
        assert trace[0]["target"] == -2
    finally:
        sys.modules.pop("numpy", None)
        if original is not None:
            sys.modules["numpy"] = original


def test_targets_runner_keeps_original_alignment_when_strategy_mutates_input_rows():
    from tradeoff.adapters import make_targets_runner

    def signals(data, config, seed):
        data.pop()
        data[0]["timestamp"] = "2030-01-01T00:00:00+00:00"
        return [-2, 0, 3, 0]

    trace = make_targets_runner(signals)(rows(), {}, 7)
    assert len(trace) == 4
    assert trace[0]["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_dataframe_runner_passes_complete_fresh_utc_frame_and_strategy_parameters():
    pd = pytest.importorskip("pandas")
    from tradeoff.adapters import make_dataframe_runner
    data = rows()
    config = {"size": 2.5}
    before = deepcopy(data)

    def signals(frame, size):
        assert str(frame.index.tz) == "UTC"
        assert {"open", "high", "low", "close", "volume", "timestamp", "available_at", "symbol", "feature"} <= set(frame)
        frame.iloc[0]["feature"]["nested"].append(99)
        return pd.Series([-size, 0, size, 0], index=frame.index)

    run = make_dataframe_runner(signals)
    trace = run(data, config, 7)
    assert [record["target"] for record in trace] == [-2.5, 0, 2.5, 0]
    assert data == before
    assert run(data, config, 7) == trace
    assert run.trace_kind == "target_units"


def test_dataframe_runner_reads_selected_target_column_without_positional_reindexing():
    pd = pytest.importorskip("pandas")
    from tradeoff.adapters import make_dataframe_runner

    def signals(frame):
        return pd.DataFrame({"quantity": [-3, 0, 2, 0], "score": [0.1] * 4}, index=frame.index)

    trace = make_dataframe_runner(signals, target_column="quantity")(rows(), {}, 7)
    assert [record["target"] for record in trace] == [-3, 0, 2, 0]


@pytest.mark.parametrize("mode", ["reversed", "missing", "duplicate", "positional", "timezone", "nonnumeric", "boolean", "nan", "missing_column", "array"])
def test_dataframe_runner_rejects_ambiguous_or_invalid_output(mode):
    pd = pytest.importorskip("pandas")
    from tradeoff.adapters import make_dataframe_runner

    def signals(frame):
        result = pd.Series([0, 1, -2, 0], index=frame.index)
        if mode == "reversed":
            return result.iloc[::-1]
        if mode == "missing":
            return result.iloc[:-1]
        if mode == "duplicate":
            result.index = [frame.index[0]] * len(frame)
        if mode == "positional":
            result.index = range(len(frame))
        if mode == "timezone":
            result.index = result.index.tz_convert("America/New_York")
        if mode == "nonnumeric":
            return pd.Series(["0", "1", "-2", "0"], index=frame.index)
        if mode == "boolean":
            return pd.Series([False, True, False, False], index=frame.index)
        if mode == "nan":
            return pd.Series([0, float("nan"), 0, 0], index=frame.index)
        if mode == "missing_column":
            return pd.DataFrame({"wrong": result})
        if mode == "array":
            return result.to_numpy()
        return result

    with pytest.raises(ValueError, match="index|target|column|Series|DataFrame|quantity"):
        make_dataframe_runner(signals)(rows(), {}, 7)


def test_resolve_runner_imports_project_function_and_preserves_metadata(tmp_path, monkeypatch):
    from tradeoff.adapters import resolve_runner
    (tmp_path / "local_signals.py").write_text(
        "def target_sequence(rows, config, seed):\n    return [-2, 0, 3, 0]\n"
        "def callback(rows, config, seed):\n    return [{'timestamp': row['timestamp'], 'target': -2} for row in rows]\n"
        "callback.trace_kind = 'observed_position'\ncallback.adapter_info = {'engine': 'custom'}\n"
    )
    monkeypatch.chdir(tmp_path)
    targets = resolve_runner("local_signals:target_sequence", engine="targets")
    assert targets(rows(), {}, 7)[0]["target"] == -2
    assert targets.runner_spec == {"engine": "targets", "engine_settings": {}}
    callback = resolve_runner("local_signals:callback")
    assert callback.trace_kind == "observed_position"
    assert callback.adapter_info == {"engine": "custom"}
    assert callback.runner_spec == {"engine": "callback", "engine_settings": {}}
    import local_signals
    assert not hasattr(local_signals.callback, "runner_spec")


@pytest.mark.parametrize("reference,engine,settings", [
    ("../x:run", "callback", None), ("x:run()", "callback", None),
    ("x:run:other", "callback", None), ("tradeoff.demos:causal_run", "other", None),
    ("tradeoff.demos:causal_run", "callback", {"cash": 10}),
    ("tradeoff.demos:causal_run", "targets", {"cash": 10}),
    ("tradeoff.demos:causal_run", "pandas", {"cash": 10}),
])
def test_resolve_runner_rejects_malformed_references_and_unsupported_settings(reference, engine, settings):
    from tradeoff.adapters import resolve_runner
    with pytest.raises(ValueError):
        resolve_runner(reference, engine=engine, engine_settings=settings)


def test_resolve_runner_reconstructs_pandas_column_settings(tmp_path, monkeypatch):
    pytest.importorskip("pandas")
    from tradeoff.adapters import resolve_runner
    (tmp_path / "frame_signals.py").write_text(
        "def signals(frame, size=2):\n    frame['quantity'] = -size\n    return frame\n"
    )
    monkeypatch.chdir(tmp_path)
    runner = resolve_runner("frame_signals:signals", engine="pandas", engine_settings={"target_column": "quantity"})
    assert runner(rows(), {"size": 3.5}, 7)[0]["target"] == -3.5
    assert runner.runner_spec == {"engine": "pandas", "engine_settings": {"target_column": "quantity"}}


@pytest.mark.parametrize("reference", ["missing_tradeoff_strategy_module:run", "tradeoff.demos:missing_strategy"])
def test_resolve_runner_missing_module_or_attribute_is_a_friendly_reference_error(reference):
    from tradeoff.adapters import resolve_runner
    with pytest.raises(ValueError, match=reference):
        resolve_runner(reference)
