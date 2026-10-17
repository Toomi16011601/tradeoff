"""Importable strategy adapters; optional packages are loaded only when used."""

from copy import deepcopy
from functools import wraps
import importlib
from pathlib import Path
import re
import sys

from ..validation import validate_config
from ._shared import settings_dict
from .backtrader import make_backtrader_runner
from .backtesting import make_backtesting_runner
from .signals import make_dataframe_runner, make_targets_runner


def _import_callable(reference):
    pattern = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    if not isinstance(reference, str) or re.fullmatch(pattern, reference) is None:
        raise ValueError("strategy reference must be an importable module:attribute")
    module_name, attribute_name = reference.split(":")
    project_directory = str(Path.cwd())
    if project_directory not in sys.path:
        sys.path.insert(0, project_directory)
    try:
        result = importlib.import_module(module_name)
        for name in attribute_name.split("."):
            result = getattr(result, name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"cannot load strategy {reference!r}: {exc}") from exc
    if not callable(result):
        raise ValueError("strategy reference must resolve to a callable")
    return result


def resolve_runner(reference, *, engine="callback", engine_settings=None):
    """Load a project callable/class and return a replayable adapter boundary."""
    if engine not in ("callback", "targets", "pandas", "backtrader", "backtesting"):
        raise ValueError(f"unsupported engine: {engine!r}")
    settings = validate_config(engine_settings)
    if engine in ("callback", "targets"):
        settings_dict(settings, {})
    elif engine == "pandas":
        settings = settings_dict(settings, {"target_column": "target"})
    fn = _import_callable(reference)
    if engine == "callback":
        @wraps(fn)
        def run(rows, config, seed):
            return fn(rows, config, seed)
        for name in ("trace_kind", "adapter_info"):
            if hasattr(fn, name):
                setattr(run, name, deepcopy(getattr(fn, name)))
    elif engine == "targets":
        run = make_targets_runner(fn)
    elif engine == "pandas":
        run = make_dataframe_runner(fn, **settings)
    elif engine == "backtrader":
        run = make_backtrader_runner(fn, engine_settings=settings)
        settings = deepcopy(run.adapter_info["engine_settings"])
    else:
        run = make_backtesting_runner(fn, engine_settings=settings)
        settings = deepcopy(run.adapter_info["engine_settings"])
    run.runner_spec = {"engine": engine, "engine_settings": deepcopy(settings)}
    return run


__all__ = ["resolve_runner", "make_targets_runner", "make_dataframe_runner",
           "make_backtrader_runner", "make_backtesting_runner"]
