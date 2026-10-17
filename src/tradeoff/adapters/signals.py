"""Small wrappers for existing numeric and pandas signal functions."""

from array import array
from copy import deepcopy

from ..validation import validate_config, validate_rows, validate_trace
from ._shared import position_target, seeded


def _sequence_trace(values, rows):
    if len(values) != len(rows):
        raise ValueError("target sequence length must match the input rows")
    trace = [{"timestamp": row["timestamp"], "target": position_target(value)}
             for row, value in zip(rows, values)]
    return validate_trace(trace, rows)


def make_targets_runner(fn):
    """Wrap fn(rows, config, seed) returning a list, tuple or one-dimensional array."""
    if not callable(fn):
        raise ValueError("signal function must be callable")

    def run(rows, config, seed):
        rows = validate_rows(rows)
        config = validate_config(config)
        with seeded(seed):
            values = fn(deepcopy(rows), config, seed)
        if not isinstance(values, (list, tuple, array)):
            try:
                import numpy as np
            except ImportError:
                np = None
            if np is None or not isinstance(values, np.ndarray) or values.ndim != 1:
                raise ValueError("targets must be a numeric list, tuple or one-dimensional array")
        return _sequence_trace(values, rows)

    run.trace_kind = "target_units"
    run.adapter_info = {"engine": "targets", "timing": "Absolute signed target units aligned to each bar close."}
    return run


def make_dataframe_runner(fn, *, target_column="target"):
    """Wrap fn(frame, **config) returning an exactly aligned Series/DataFrame.

    The fresh frame contains all row fields, lower-case OHLCV and a UTC-aware
    DatetimeIndex. The strategy remains responsible for causal preprocessing.
    """
    if not callable(fn):
        raise ValueError("signal function must be callable")
    if not isinstance(target_column, str) or not target_column:
        raise ValueError("target_column must be a nonempty string")

    def run(rows, config, seed):
        rows = validate_rows(rows)
        config = validate_config(config)
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("Pandas signal adapter requires pip install '.[adapters]'") from exc
        frame = pd.DataFrame(rows)
        frame.index = pd.to_datetime([row["timestamp"] for row in rows], utc=True)
        expected_index = frame.index.copy()
        with seeded(seed):
            result = fn(frame, **config)
        if isinstance(result, pd.DataFrame):
            if target_column not in result.columns or result.columns.tolist().count(target_column) != 1:
                raise ValueError(f"result must contain exactly one {target_column!r} target column")
            result = result[target_column]
        if not isinstance(result, pd.Series):
            raise ValueError("pandas strategy must return a Series or DataFrame")
        if not result.index.equals(expected_index):
            raise ValueError("target index must exactly match the input UTC index, in order")
        return _sequence_trace(result.to_numpy(), rows)

    run.trace_kind = "target_units"
    run.adapter_info = {"engine": "pandas", "engine_settings": {"target_column": target_column},
                        "timing": "Absolute signed target units; exact UTC index alignment is required."}
    return run
