"""Load inspected, pinned case-study code without executing network/main paths."""

import ast
import hashlib
import json
from pathlib import Path
import sys
import types

SOURCE_DIR = Path(__file__).with_name("sources")


def load_source(path, expected_hash):
    """Verify vendored bytes before any upstream code is executed."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError(f"Public case source hash mismatch: {Path(path).name}")
    return raw.decode("utf-8")


def patch_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError("Pinned causal patch no longer matches the inspected source")
    return source.replace(before, after, 1)


def load_rows(name):
    return json.loads((SOURCE_DIR / f"{name}_rows.json").read_text(encoding="utf-8"))


def strategy_namespace(source, filename, *, extra=None, prepare_sentiment=False):
    """Retain original functions/classes; omit imports and data-fetch/main code.

    The CoinGlass prepare function executes the exact pure preprocessing
    statements from get_simple_data on a supplied DataFrame. Network setup and
    print statements are outside the audited trading computation.
    """
    try:
        import numpy as np
        import pandas as pd
        from backtesting import Strategy
        from backtesting.lib import crossover
        from backtesting.test import SMA
    except ImportError as exc:
        raise ImportError("Public cases require pip install '.[cases]'") from exc
    namespace = {"__name__": "backtest_witness.cases._loaded_strategy", "np": np,
                 "pd": pd, "Strategy": Strategy, "crossover": crossover, "SMA": SMA}
    namespace.update(extra or {})
    tree = ast.parse(source, filename)
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    if prepare_sentiment:
        function = next(node for node in tree.body
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_simple_data")
        start = next(index for index, node in enumerate(function.body)
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id == "close_prices")
        finish = next(index for index, node in enumerate(function.body)
                      if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript)
                      and isinstance(node.targets[0].value, ast.Name) and node.targets[0].value.id == "data")
        prepare = ast.FunctionDef(name="prepare", args=ast.arguments(posonlyargs=[],
                                  args=[ast.arg(arg="data")], kwonlyargs=[], kw_defaults=[], defaults=[]),
                                  body=function.body[start:finish + 1] + [ast.Return(value=ast.Name(id="data", ctx=ast.Load()))],
                                  decorator_list=[])
        selected.append(prepare)
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, filename, "exec"), namespace)
    return namespace


def riskkit_sizing(source, filename):
    """Execute the exact dependency-free upstream sizing module, including dataclasses."""
    name = "backtest_witness.cases._loaded_riskkit_sizing"
    module = types.ModuleType(name)
    module.__file__ = filename
    sys.modules[name] = module
    exec(compile(source, filename, "exec"), module.__dict__)
    return module
