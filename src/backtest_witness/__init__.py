"""Compatibility imports for projects created before the Tradeoff rename.

Aliases share canonical module objects so saved callbacks, exception classes
and local diagnostics keep working across both names. Optional trading engines
remain lazy; pinned third-party sources are never imported by this shim.
"""

from importlib import import_module as _import_module
import sys as _sys

import tradeoff as _tradeoff

__version__ = _tradeoff.__version__

_MODULES = (
    "adapters", "adapters._shared", "adapters.backtesting",
    "adapters.backtrader", "adapters.signals", "audit", "cases",
    "cases._loader", "cases.coinglass", "cases.riskkit", "cli", "data",
    "demos", "diagnostics", "economics", "execution", "failure_cli",
    "failure_lab", "failure_reproduce", "integration", "mutations",
    "preview", "privacy", "report", "report.failure_renderer",
    "report.renderer", "reproduce", "sizing", "strategy_onboarding", "validation",
)

for _name in _MODULES:
    _sys.modules[f"{__name__}.{_name}"] = _import_module(f"tradeoff.{_name}")


def __getattr__(name):
    return getattr(_tradeoff, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_tradeoff)))
