"""Small, dependency-lazy helpers shared by optional integrations."""

from contextlib import contextmanager
from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from numbers import Integral, Real
import random

from ..validation import normalize_target


def settings_dict(settings, defaults):
    if settings is None:
        return deepcopy(defaults)
    if not isinstance(settings, dict):
        raise ValueError("engine_settings must be a dictionary")
    unknown = set(settings) - set(defaults)
    if unknown:
        raise ValueError(f"unsupported engine settings: {', '.join(sorted(unknown))}")
    return {**defaults, **deepcopy(settings)}


def position_target(size):
    """Convert real engine/array scalars without accepting strings or booleans."""
    if isinstance(size, bool) or not isinstance(size, Real):
        raise ValueError("target must be a finite numeric quantity")
    native = int(size) if isinstance(size, Integral) else float(size)
    return normalize_target(native)


def numeric_setting(value, label, *, minimum=0, maximum=None, exclusive_minimum=False):
    """Reject coercions before passing quantitative settings to an engine."""
    value = normalize_target(value, label)
    if value < minimum or (exclusive_minimum and value == minimum) or (maximum is not None and value > maximum):
        raise ValueError(f"{label} is outside its supported range")
    return value


def engine_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def frame_from_rows(rows):
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError("Optional adapters require pandas; install with pip install '.[adapters]'") from exc
    frame = pd.DataFrame({name.title(): [row[name] for row in rows]
                          for name in ("open", "high", "low", "close", "volume")})
    frame.index = pd.to_datetime([row["timestamp"] for row in rows], utc=True).tz_localize(None)
    return frame


@contextmanager
def seeded(seed):
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    try:
        import numpy as np
    except ImportError:
        np = None

    python_state = random.getstate()
    numpy_state = np.random.get_state() if np is not None else None
    random.seed(seed)
    if np is not None:
        np.random.seed(seed % (2 ** 32))
    try:
        yield
    finally:
        random.setstate(python_state)
        if np is not None:
            np.random.set_state(numpy_state)
