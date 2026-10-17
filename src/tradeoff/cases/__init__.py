"""Pinned public strategies with runnable originals and disclosed causal patches.

Importing this registry does not load engine, dataframe, or numerical libraries.
"""

from importlib import import_module

CASES = ("riskkit", "coinglass")


def get_case(name):
    """Return a fresh case descriptor; execution dependencies remain lazy."""
    if name not in CASES:
        raise ValueError(f"Unknown public case {name!r}; choose {', '.join(CASES)}")
    module = import_module(f"tradeoff.cases.{name}")
    return {"name": name, "description": module.DESCRIPTION,
            "original": module.original_run, "fixed": module.fixed_run,
            "original_ref": f"tradeoff.cases.{name}:original_run",
            "fixed_ref": f"tradeoff.cases.{name}:fixed_run",
            "rows": module.rows, "config": {},
            "execution_rows": getattr(module, 'execution_rows', module.rows),
            "execution_input": getattr(module, 'EXECUTION_INPUT', module.PROVENANCE['input']),
            "original_execution": module.original_execution, "fixed_execution": module.fixed_execution,
            "original_execution_ref": f"tradeoff.cases.{name}:original_execution",
            "fixed_execution_ref": f"tradeoff.cases.{name}:fixed_execution",
            "audit_settings": dict(module.AUDIT_SETTINGS),
            "provenance": dict(module.PROVENANCE)}
