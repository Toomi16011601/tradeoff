"""Lazy compatibility alias; imports the optional engine only when requested."""
from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module('tradeoff.historical_strategy')
