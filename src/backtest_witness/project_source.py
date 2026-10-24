"""Compatibility alias for current project source resolution."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module('tradeoff.project_source')
