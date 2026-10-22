"""Lazy compatibility alias for the Tradeoff historical demo."""
from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module('tradeoff.historical_demo')
